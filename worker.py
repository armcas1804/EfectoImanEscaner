"""Independent opening capture. The web page never starts or owns this process."""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import queue
import signal
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from scanner.calendar import CUTS, NY, calendar_status, session_for_day
from scanner.config import DATA_DIR, PROVIDER_SYMBOLS, TICKERS
from scanner.scoring import score_cut
from scanner.store import Store

LOG = logging.getLogger("scanner.worker")
UTC = timezone.utc


class WorkerLock:
    """OS-held lock, automatically released on crash; never guess stale PIDs."""
    def __init__(self, path):
        self.path, self.file = Path(path), None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("Ya existe un capturador activo para esta carpeta de datos") from exc
        return self

    def __exit__(self, *_):
        if self.file:
            self.file.close()


def parse_quote(message: dict, received_at: datetime, session, symbols: dict) -> dict | None:
    """Accept only information available in the session's real receipt window."""
    ticker = symbols.get(str(message.get("id", "")))
    if ticker is None or received_at.tzinfo is None:
        return None
    try:
        price, epoch = float(message["price"]), float(message["time"])
        event = datetime.fromtimestamp(epoch / 1000 if epoch > 100_000_000_000 else epoch, UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None
    if (not math.isfinite(price) or price <= 0 or
            not session.opens <= received_at <= session.deadline(max(CUTS)) or
            event < session.opens or event > received_at + timedelta(seconds=3)):
        return None
    return {"ticker": ticker, "price": price, "quote_event_time": event.isoformat(),
            "quote_received_at": received_at.astimezone(UTC).isoformat()}


def download_prior_bars(day: str, tickers=TICKERS) -> list[dict]:
    """Regular-session 15m bars strictly before the requested session, never today."""
    records = []
    cutoff_date = datetime.fromisoformat(day).date()
    for offset in range(0, len(tickers), 12):
        batch = tickers[offset:offset + 12]
        providers = [PROVIDER_SYMBOLS.get(t, t) for t in batch]
        raw = yf.download(providers, period="10d", interval="15m", group_by="ticker",
                          auto_adjust=False, prepost=False, progress=False, threads=True,
                          timeout=15)
        if raw.empty:
            continue
        for ticker, provider in zip(batch, providers):
            try:
                frame = raw[provider] if isinstance(raw.columns, pd.MultiIndex) else raw
                frame = frame[["Open", "High", "Low", "Close"]].dropna().sort_index()
            except KeyError:
                continue
            index = pd.DatetimeIndex(frame.index)
            index = index.tz_localize("UTC") if index.tz is None else index
            frame.index = index.tz_convert(NY)
            frame = frame.loc[~frame.index.duplicated(keep="last")]
            accepted = []
            for stamp, row in frame.iterrows():
                if stamp.date() >= cutoff_date:
                    continue
                trading = session_for_day(stamp.date())
                if trading and trading.opens <= stamp and stamp + timedelta(minutes=15) <= trading.closes:
                    accepted.append((stamp, row))
            # Includes earlier sessions after a shortened day: BB still needs 20+ bars.
            for index, (stamp, row) in enumerate(accepted[-26:]):
                records.append({"ticker": ticker, "bar_index": index, "session": "PREVIA",
                                "time": stamp.isoformat(), "timestamp": stamp.isoformat(),
                                "open": float(row.Open), "high": float(row.High),
                                "low": float(row.Low), "close": float(row.Close)})
    if not records:
        raise RuntimeError("Yahoo no devolvió velas previas válidas")
    return records


class OpeningWorker:
    def __init__(self, store=None, clock=None):
        self.store = store or Store()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.session = None
        self.socket = None
        self.listener = None
        self.preparer = None
        self.prior = []
        self.connected = False
        self.last_error = None
        self.next_prepare = datetime.min.replace(tzinfo=UTC)
        self.capture_started_at = None
        self.capture_interrupted = False
        self.started_at = self.clock()
        self.symbol_map = {PROVIDER_SYMBOLS.get(t, t): t for t in TICKERS}
        self.last_heartbeat = datetime.min.replace(tzinfo=UTC)

    def accept_message(self, message):
        received = self.clock()
        if self.session:
            quote = parse_quote(message, received, self.session, self.symbol_map)
            if quote:
                self.events.put((self.session.day.isoformat(), quote))

    def flush_events(self):
        batches = {}
        while True:
            try:
                day, quote = self.events.get_nowait()
                batches.setdefault(day, []).append(quote)
            except queue.Empty:
                break
        for day, quotes in batches.items():
            if hasattr(self.store, "append_quotes"):
                self.store.append_quotes(day, quotes)
            else:
                for quote in quotes:
                    self.store.append_quote(day, quote)

    def _prepare(self, day):
        try:
            bars = download_prior_bars(day)
            self.store.save_bars(day, bars)
            self.prior = bars
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Bandas previas: {exc}"
            LOG.exception("No se prepararon las velas de %s", day)
        finally:
            self.next_prepare = self.clock() + timedelta(seconds=30)

    def _listen(self, session):
        while not self.stop.is_set() and self.clock() < session.deadline(max(CUTS)):
            socket = None
            try:
                socket = yf.WebSocket(verbose=False)
                self.socket = socket
                socket.subscribe(list(self.symbol_map))
                self.connected = True
                self.capture_started_at = self.capture_started_at or self.clock()
                socket.listen(self.accept_message)
            except Exception as exc:
                self.last_error = f"Flujo Yahoo: {exc}"
                if session.opens <= self.clock() < session.deadline(max(CUTS)):
                    self.capture_interrupted = True
                LOG.warning("Reconectando flujo: %s", exc)
            finally:
                self.connected = False
                if socket:
                    try:
                        socket.close()
                    except Exception:
                        LOG.debug("No se pudo cerrar socket", exc_info=True)
                self.socket = None
            self.stop.wait(2)

    def _close_stream(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                LOG.debug("Cierre del flujo", exc_info=True)

    def _finalize(self, now) -> dict:
        day = self.session.day.isoformat()
        states = {}
        for seconds in CUTS:
            existing = self.store.get_snapshot(day, seconds)
            if existing:
                states[str(seconds)] = "importado" if existing.get("imported") else "guardado"
                continue
            deadline = self.session.deadline(seconds)
            if now < deadline + timedelta(milliseconds=250):
                states[str(seconds)] = "pendiente"
                continue
            quotes = self.store.get_quotes(day, deadline=deadline.isoformat())
            if not quotes:
                states[str(seconds)] = "sin_cotizaciones" if self.capture_started_at else "no_capturado"
                continue
            if not self.prior:
                states[str(seconds)] = "sin_bandas_previas"
                continue
            result = score_cut(pd.DataFrame(self.prior), quotes, day, seconds)
            if not result.price_at_cutoff.notna().any():
                states[str(seconds)] = "sin_cotizaciones_validas"
                continue
            partial = (self.started_at > self.session.opens or self.capture_interrupted or
                       bool(self.capture_started_at and self.capture_started_at > self.session.opens))
            result["capture_status"] = "captura_parcial_o_reanudada" if partial else "captura_en_vivo"
            result["capture_started_at"] = (self.capture_started_at or self.started_at).isoformat()
            self.store.save_snapshot(day, seconds, result.to_dict("records"),
                                     source="yahoo_websocket_local", captured_at=now.isoformat())
            states[str(seconds)] = "guardado_parcial" if partial else "guardado"
            LOG.info("Corte %s %ss guardado: %s empresas", day, seconds, len(result))
        return states

    def step(self, now=None):
        now = now or self.clock()
        self.flush_events()
        today = session_for_day(now.astimezone(NY).date())
        schedule = calendar_status(now)
        if today is None:
            self._publish(now, "cerrado", "Sin sesión bursátil hoy", schedule, {})
            return
        if self.session is None or self.session.day != today.day:
            self._close_stream()
            self.session = today
            self.prior = self.store.get_bars(today.day.isoformat())
            self.prior = [row for row in self.prior if row.get("session") == "PREVIA"]
            self.capture_started_at = None
            self.capture_interrupted = False
        end = today.deadline(max(CUTS))
        if now >= today.prepare_at and now < end:
            if not self.prior and now >= self.next_prepare and (not self.preparer or not self.preparer.is_alive()):
                self.preparer = threading.Thread(target=self._prepare, args=(today.day.isoformat(),), daemon=True)
                self.preparer.start()
            if not self.listener or not self.listener.is_alive():
                self.listener = threading.Thread(target=self._listen, args=(today,), daemon=True)
                self.listener.start()
        elif now >= end:
            self._close_stream()
            # After a restart, only recorded receipts can recover an unfinished cut.
            if (not self.prior and self.store.get_quotes(today.day.isoformat()) and
                    now >= self.next_prepare and (not self.preparer or not self.preparer.is_alive())):
                self.preparer = threading.Thread(target=self._prepare, args=(today.day.isoformat(),), daemon=True)
                self.preparer.start()
        states = self._finalize(now)
        if now < today.prepare_at:
            state, message = "programado", "Captura preparada para el horario de mercado"
        elif now < today.opens:
            state, message = "preparando", "Preparando bandas previas y conexión de cotizaciones"
        elif now <= end:
            state, message = "capturando", "Recibiendo apertura y guardando cortes independientes"
        elif any(value.startswith("guardado") for value in states.values()):
            state, message = "listo", "Cortes disponibles; el capturador sigue esperando la próxima sesión"
        elif any(value == "importado" for value in states.values()):
            state, message = "importado", "Hay cortes importados; no son una captura nueva de este proceso"
        else:
            state, message = "sin_captura", "No hay cortes completos de hoy; consulta el historial guardado"
        self._publish(now, state, message, schedule, states)

    def _publish(self, now, state, message, schedule, states):
        if (now - self.last_heartbeat).total_seconds() < 2:
            return
        self.last_heartbeat = now
        self.store.set_status(state=state, message=message, heartbeat=now.isoformat(),
                              pid=os.getpid(), session_date=schedule["date"],
                              source="yahoo_websocket_local", stream_connected=self.connected,
                              prepared_symbols=len({row["ticker"] for row in self.prior}),
                              universe_count=len(TICKERS), cuts=states, schedule=schedule,
                              last_error=self.last_error,
                              capture_started_at=self.capture_started_at.isoformat() if self.capture_started_at else None)

    def run(self):
        with WorkerLock(DATA_DIR / "worker.lock"):
            LOG.info("Capturador iniciado, independiente de la página (%d símbolos)", len(TICKERS))
            try:
                while not self.stop.is_set():
                    try:
                        self.step()
                    except Exception as exc:
                        LOG.exception("Fallo recuperable del capturador")
                        self.store.set_status(state="error", message=str(exc), heartbeat=self.clock().isoformat())
                        self.stop.wait(3)
                    now = self.clock()
                    active = self.session and self.session.prepare_at <= now < self.session.deadline(max(CUTS)) + timedelta(seconds=1)
                    self.stop.wait(.25 if active else 2)
            finally:
                self._close_stream()
                self.flush_events()
                self.store.set_status(state="detenido", message="Capturador detenido",
                                      heartbeat=self.clock().isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Mostrar calendario y estado sin conectarse a Yahoo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.check:
        print(json.dumps({"schedule": calendar_status(datetime.now(UTC)), "worker": Store().get_status()}, ensure_ascii=False, indent=2))
        return
    worker = OpeningWorker()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run()


if __name__ == "__main__":
    main()
