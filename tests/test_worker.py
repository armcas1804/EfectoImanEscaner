import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scanner.calendar import NY, calendar_status, session_for_day
from scanner.store import Store
from worker import OpeningWorker, WorkerLock, parse_quote


class CalendarTests(unittest.TestCase):
    def test_holiday_and_early_close(self):
        self.assertIsNone(session_for_day("2026-12-25"))
        session = session_for_day("2026-11-27")
        self.assertEqual(session.closes.hour, 13)
        self.assertEqual(session.opens.hour, 9)

    def test_dst_market_open_is_fixed_new_york(self):
        summer = session_for_day("2026-07-06")
        winter = session_for_day("2026-11-02")
        self.assertEqual(summer.opens.astimezone(timezone.utc).hour, 13)
        self.assertEqual(winter.opens.astimezone(timezone.utc).hour, 14)
        self.assertEqual((winter.opens.hour, winter.opens.minute), (9, 30))

    def test_future_event_and_late_receipt_are_not_quotes(self):
        session = session_for_day("2026-11-11")
        received = datetime(2026, 11, 11, 9, 30, 10, tzinfo=NY)
        message = {"id": "AAA", "price": 102, "time": received.timestamp() * 1000}
        self.assertIsNotNone(parse_quote(message, received, session, {"AAA": "AAA"}))
        message["time"] += 4000
        self.assertIsNone(parse_quote(message, received, session, {"AAA": "AAA"}))
        self.assertIsNone(parse_quote(message, datetime(2026, 11, 11, 9, 32, tzinfo=NY), session, {"AAA": "AAA"}))

    def test_os_lock_prevents_duplicate_workers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "worker.lock"
            with WorkerLock(path):
                with self.assertRaises(RuntimeError):
                    with WorkerLock(path):
                        pass
            with WorkerLock(path):
                pass

    def test_start_after_open_marks_missing_cuts_without_connecting(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "scanner.db")
            now = datetime(2026, 11, 11, 12, tzinfo=NY)
            worker = OpeningWorker(store, clock=lambda: now)
            worker.step()
            self.assertIsNone(worker.listener)
            self.assertIsNone(worker.preparer)
            self.assertEqual(store.get_status()["state"], "sin_captura")
            self.assertEqual(set(store.get_status()["cuts"].values()), {"no_capturado"})
            self.assertIsNone(store.get_snapshot())

    def test_restart_recovers_only_previously_received_quotes_and_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "scanner.db")
            day = "2026-11-11"
            store.save_bars(day, [{
                "ticker": "AAPL", "bar_index": i, "session": "PREVIA",
                "time": f"{9 + (30 + 15*i)//60:02d}:{(30 + 15*i)%60:02d}",
                "open": 100 + (i%2)*.1, "high": 100.2, "low": 99.9,
                "close": 100 + (i%2)*.1,
            } for i in range(26)])
            for second, price in ((1, 103), (8, 102.5)):
                stamp = datetime(2026, 11, 11, 9, 30, second, tzinfo=NY).isoformat()
                store.append_quote(day, ticker="AAPL", price=price, event_time=stamp, received_at=stamp)
            now = datetime(2026, 11, 11, 9, 32, tzinfo=NY)
            worker = OpeningWorker(store, clock=lambda: now)
            worker.step()
            recovered = store.get_snapshot(day, 10)
            self.assertEqual(recovered["coverage"], 1)
            self.assertFalse(recovered["imported"])
            self.assertTrue(any(r.get("capture_status") == "captura_parcial_o_reanudada" for r in recovered["rows"]))
            OpeningWorker(store, clock=lambda: datetime(2026, 11, 11, 10, tzinfo=NY)).step()
            self.assertEqual(recovered, store.get_snapshot(day, 10))


if __name__ == "__main__":
    unittest.main()
