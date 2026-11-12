"""Durable local snapshots, quotes and worker status, independent from the UI."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .config import DATABASE_PATH, SCORE_VERSION


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clean(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json(value):
    return json.dumps(_clean(value), ensure_ascii=False, allow_nan=False)


def _utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("Quote timestamps must include their timezone")
    return stamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DATABASE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                  day TEXT NOT NULL, seconds INTEGER NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(day, seconds));
                CREATE TABLE IF NOT EXISTS bars (
                  day TEXT NOT NULL, ticker TEXT NOT NULL, bar_index INTEGER NOT NULL,
                  payload TEXT NOT NULL, PRIMARY KEY(day,ticker,bar_index));
                CREATE TABLE IF NOT EXISTS quotes (
                  day TEXT NOT NULL, ticker TEXT NOT NULL, price REAL NOT NULL,
                  event_time TEXT NOT NULL, received_at TEXT NOT NULL,
                  UNIQUE(day,ticker,price,event_time,received_at));
                CREATE INDEX IF NOT EXISTS quotes_day_received ON quotes(day,received_at);
                CREATE TABLE IF NOT EXISTS status (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        return db

    def save_snapshot(self, day, seconds, rows, source, captured_at=None, imported=False):
        date.fromisoformat(day)
        if int(seconds) not in (10, 30, 60, 90):
            raise ValueError("Unsupported opening cutoff")
        records = json.loads(rows.to_json(orient="records")) if hasattr(rows, "to_json") else _clean(rows)
        now = datetime.now(timezone.utc).isoformat()
        opening = datetime.fromisoformat(day + "T09:30:00").replace(tzinfo=ZoneInfo("America/New_York"))
        payload = dict(date=day, seconds=int(seconds), rows=records, source=source,
                       imported=bool(imported), captured_at=(captured_at or (None if imported else now)),
                       saved_at=now, cutoff_at=(opening + timedelta(seconds=int(seconds))).isoformat(),
                       score_version=SCORE_VERSION,
                       coverage=sum(row.get("price_at_cutoff") is not None for row in records),
                       candidates=sum(row.get("home_b_candidate") is True for row in records),
                       scored=sum(row.get("score_home_b") is not None for row in records))
        with closing(self._connect()) as db, db:
            result = db.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,?)",
                                (day, int(seconds), _json(payload)))
            return bool(result.rowcount)

    def get_snapshot(self, day=None, seconds=None):
        filters, values = [], []
        if day is not None:
            filters.append("day=?"); values.append(day)
        if seconds is not None:
            filters.append("seconds=?"); values.append(int(seconds))
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with closing(self._connect()) as db:
            row = db.execute("SELECT payload FROM snapshots" + where +
                             " ORDER BY day DESC,seconds DESC LIMIT 1", values).fetchone()
        return json.loads(row[0]) if row else None

    def list_sessions(self):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT day,seconds,payload FROM snapshots ORDER BY day DESC,seconds DESC").fetchall()
        sessions = {}
        for row in rows:
            payload = json.loads(row["payload"])
            item = sessions.setdefault(row["day"], dict(date=row["day"], cuts=[],
                latest_seconds=row["seconds"], source=payload["source"], imported=payload.get("imported", False)))
            item["cuts"].append(row["seconds"])
        for item in sessions.values():
            item["cuts"].sort()
        return list(sessions.values())

    def get_prior_widths(self, day, limit=20):
        """One pre-open width per symbol and earlier stored session."""
        with closing(self._connect()) as db:
            snapshots = db.execute("""
                WITH previous AS (
                    SELECT day, max(seconds) AS seconds FROM snapshots WHERE day < ?
                    GROUP BY day ORDER BY day DESC LIMIT ?
                ) SELECT snapshots.payload FROM snapshots JOIN previous USING (day, seconds)
                """, (day, limit)).fetchall()
        widths = {}
        for snapshot in snapshots:
            for row in json.loads(snapshot[0])["rows"]:
                width = row.get("prior_bb_width_pct")
                if isinstance(width, (int, float)) and math.isfinite(width) and width > 0:
                    widths.setdefault(row["ticker"], []).append(width)
        return {ticker: sorted(series) for ticker, series in widths.items()}

    def save_bars(self, day, records):
        date.fromisoformat(day)
        if hasattr(records, "to_json"):
            records = json.loads(records.to_json(orient="records"))
        with closing(self._connect()) as db, db:
            db.executemany("INSERT INTO bars VALUES (?,?,?,?) ON CONFLICT(day,ticker,bar_index) "
                           "DO UPDATE SET payload=excluded.payload",
                           [(day, r["ticker"], int(r["bar_index"]), _json(r)) for r in records])

    def get_bars(self, day, ticker=None):
        query, args = "SELECT payload FROM bars WHERE day=?", [day]
        if ticker is not None:
            query += " AND ticker=?"; args.append(ticker)
        with closing(self._connect()) as db:
            rows = db.execute(query + " ORDER BY ticker,bar_index", args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def append_quote(self, day, quote=None, **values):
        q = {**(quote or {}), **values}
        price = float(q["price"])
        if not math.isfinite(price) or price <= 0:
            return False
        event = _utc(q.get("quote_event_time", q.get("event_time")))
        received = _utc(q.get("quote_received_at", q.get("received_at")))
        with closing(self._connect()) as db, db:
            cursor = db.execute("INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?)",
                                (day, q["ticker"], price, event, received))
            return bool(cursor.rowcount)

    def append_quotes(self, day, quotes):
        records = []
        for q in quotes:
            price = float(q["price"])
            if not math.isfinite(price) or price <= 0:
                continue
            records.append((day, q["ticker"], price,
                _utc(q.get("quote_event_time", q.get("event_time"))),
                _utc(q.get("quote_received_at", q.get("received_at")))))
        with closing(self._connect()) as db, db:
            before = db.total_changes
            db.executemany("INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?)", records)
            return db.total_changes - before

    def get_quotes(self, day, deadline=None):
        query, args = "SELECT * FROM quotes WHERE day=?", [day]
        if deadline is not None:
            query += " AND received_at<=?"; args.append(_utc(deadline))
        with closing(self._connect()) as db:
            rows = db.execute(query + " ORDER BY received_at,event_time,ticker", args).fetchall()
        return [{**dict(row), "quote_event_time": row["event_time"],
                 "quote_received_at": row["received_at"]} for row in rows]

    def set_status(self, values=None, **kwargs):
        with closing(self._connect()) as db, db:
            current = db.execute("SELECT payload FROM status WHERE id=1").fetchone()
            payload = json.loads(current[0]) if current else {}
            payload.update(values or {}); payload.update(kwargs)
            db.execute("INSERT INTO status VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                       (_json(payload),))

    def get_status(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT payload FROM status WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}
