"""Read-only local API and web interface. The independent worker captures prices."""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from scanner.config import TICKERS
from scanner.pattern_score import apply_pattern_score
from scanner.store import Store
from scanner.calendar import calendar_status
from scanner.charts import cutoff_chart

ROOT = Path(__file__).resolve().parent


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "EfectoImanScanner/1.0"

    def send(self, body, status=200, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)) or body is None:
            body = json.dumps(clean(body), ensure_ascii=False, default=str, allow_nan=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self.route()
        except (ValueError, KeyError) as exc:
            self.send({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Request failed")
            self.send({"error": "No se pudo leer el diagnóstico. Consulta logs/web.log."}, 500)

    def route(self):
        request = urlsplit(self.path)
        query = parse_qs(request.query)
        path = request.path
        store = self.server.store
        if path == "/api/health":
            return self.send({"ok": True, "app": "EfectoImanScanner"})
        if path == "/api/status":
            now = datetime.now(ZoneInfo("America/New_York"))
            sessions = store.list_sessions()
            latest = ({"date": sessions[0]["date"], "seconds": sessions[0]["latest_seconds"]}
                      if sessions else None)
            return self.send({"now_ny": now.isoformat(),
                              "now_hermosillo": now.astimezone(ZoneInfo("America/Hermosillo")).isoformat(),
                              "universe_count": len(TICKERS), "worker": store.get_status(),
                              "latest": latest, "schedule": calendar_status(now)})
        if path == "/api/sessions":
            return self.send(store.list_sessions())
        if path in ("/api/snapshot", "/api/export", "/api/chart"):
            day = query.get("date", [None])[0]
            if day:
                datetime.strptime(day, "%Y-%m-%d")
            seconds = query.get("seconds", [None])[0]
            seconds = int(seconds) if seconds else None
            if seconds is not None and seconds not in (10, 30, 60, 90):
                raise ValueError("Corte no válido")
            snapshot = store.get_snapshot(day, seconds)
            if snapshot is None:
                return self.send({"error": "No hay un corte guardado para esta selección."}, 404)
            if path == "/api/chart":
                ticker = query.get("ticker", [""])[0]
                row = next((r for r in snapshot["rows"] if r.get("ticker") == ticker), None)
                if not row:
                    raise ValueError("Empresa no presente en el diagnóstico")
                return self.send(cutoff_chart(snapshot, row, store.get_bars(snapshot["date"], ticker)))
            snapshot = apply_pattern_score(snapshot,
                store.get_quotes(snapshot["date"], deadline=snapshot["cutoff_at"]),
                store.get_prior_widths(snapshot["date"]))
            if path == "/api/snapshot":
                return self.send(snapshot)
            rows = snapshot["rows"]
            columns = list(dict.fromkeys(k for row in rows for k in row))
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
            name = f"efecto_iman_{snapshot['date']}_{snapshot['seconds']}s_{snapshot['score_version']}.csv"
            return self.send("\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8",
                             extra={"Content-Disposition": f'attachment; filename="{name}"'})
        if path == "/vendor/plotly.min.js":
            import plotly
            script = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
            return self.send(script.read_bytes(), content_type="text/javascript; charset=utf-8")
        static_files = {"/": ("index.html", "text/html"),
                        "/index.html": ("index.html", "text/html"),
                        "/app.js": ("app.js", "text/javascript"),
                        "/styles.css": ("styles.css", "text/css")}
        if path in static_files:
            name, mime = static_files[path]
            return self.send((ROOT / "static" / name).read_bytes(), content_type=mime + "; charset=utf-8")
        return self.send({"error": "No encontrado"}, 404)

    def log_message(self, format, *args):
        logging.info("%s %s", self.address_string(), format % args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8601)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.store = Store()
    print(f"Efecto Imán Scanner: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
