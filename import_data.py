"""Read-only import from diagnostic CSVs and the old application's local history."""
import argparse
from contextlib import closing
from pathlib import Path
import re
import sqlite3

import pandas as pd

from scanner.legacy.trial_variants import historical_home_b_score, read_live_cut_observations
from scanner.scoring import _decorate, rescore_export, score_cut
from scanner.store import Store


def import_csv(path, store):
    result = rescore_export(pd.read_csv(path))
    day, seconds = str(result.date.iloc[0]), int(result.window_seconds.iloc[0])
    source = ", ".join(sorted(result.source.dropna().astype(str).unique()))
    saved = store.save_snapshot(day, seconds, result, source, imported=True)
    print(f"{Path(path).name}: {day} {seconds}s · {len(result)} símbolos · "
          f"{int(result.home_b_candidate.sum())} candidatos · {'importado' if saved else 'ya existía'}")
    return int(saved)


def import_legacy(root, store):
    root = Path(root).resolve()
    if root == Path(__file__).resolve().parent:
        raise ValueError("La carpeta antigua y la nueva deben ser distintas")
    database = root / "data" / "efecto_iman.db"
    folder = root / "data" / "snapshots"
    bars_by_day = {}
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            bars = pd.read_sql_query("SELECT session_date,ticker,bar_index,session,time,open,high,low,close "
                                     "FROM daily_candles WHERE source='real' ORDER BY session_date,ticker,bar_index", db)
        for day, rows in bars.groupby("session_date"):
            candles = rows.drop(columns="session_date")
            store.save_bars(str(day), candles)
            bars_by_day[str(day)] = candles
        print(f"Velas copiadas de {len(bars_by_day)} sesiones; origen abierto sólo para lectura.")
    imported = 0
    # Actual live captures take precedence over historical reconstructions.
    for path in sorted(folder.glob("apertura_flujo_*s_*.csv"), reverse=True):
        match = re.fullmatch(r"apertura_flujo_(10|30|60|90)s_(\d{4}-\d{2}-\d{2})", path.stem)
        if not match:
            continue
        maximum, day = int(match[1]), match[2]
        quotes = pd.read_csv(path).to_dict("records")
        store.append_quotes(day, quotes)
        if day not in bars_by_day:
            continue
        for seconds in (10, 30, 60, 90):
            if seconds > maximum or store.get_snapshot(day, seconds):
                continue
            result = score_cut(bars_by_day[day], quotes, day, seconds)
            if result.price_at_cutoff.notna().any():
                imported += store.save_snapshot(day, seconds, result, "yahoo_websocket_local", imported=True)
    # Historical trades retain their provenance. No reception timestamps are fabricated.
    for path in sorted(folder.glob("apertura_historica_*s_*.csv"), reverse=True):
        match = re.fullmatch(r"apertura_historica_(10|30|60)s_(\d{4}-\d{2}-\d{2})", path.stem)
        if not match or match[2] not in bars_by_day:
            continue
        day = match[2]
        frame = pd.read_csv(path)
        if "price_first_10s" in frame:
            frame = frame.rename(columns={"price_first_10s": "first_price", "price_at_10s": "price"})
            frame["window_seconds"] = 10
        else:
            frame = frame.rename(columns={"price_first": "first_price", "price_at_cutoff": "price"})
        frame = frame.rename(columns={"first_trade_at_et": "first_time", "last_trade_at_et": "last_time", "trade_count": "event_count"})
        if not {"first_price", "price", "window_seconds", "first_time", "last_time", "source", "event_count"}.issubset(frame):
            continue
        for seconds in (10, 30, 60):
            if store.get_snapshot(day, seconds) or frame.loc[frame.window_seconds.eq(seconds)].empty:
                continue
            _, result = historical_home_b_score(bars_by_day[day], frame, seconds, 1.0)
            result = _decorate(result, day, seconds)
            imported += store.save_snapshot(day, seconds, result, "alpaca_sip_historical_trades", imported=True)
    print(f"Cortes históricos agregados: {imported}")
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, action="append", default=[])
    parser.add_argument("--legacy", type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if not args.csv and not args.legacy:
        parser.error("Indica --csv ARCHIVO o --legacy CARPETA")
    store = Store(args.database)
    for path in args.csv:
        import_csv(path, store)
    if args.legacy:
        import_legacy(args.legacy, store)


if __name__ == "__main__":
    main()
