import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scanner.scoring import rescore_export, score_cut
from scanner.store import Store


HISTORICAL_FIXTURE = Path(__file__).parent / "fixtures" / "approved_b_90s.csv"


class CoreTests(unittest.TestCase):
    @unittest.skipUnless(HISTORICAL_FIXTURE.exists(), "CSV histórico disponible sólo en la instalación local")
    def test_approved_real_examples_keep_exact_scores(self):
        result = rescore_export(pd.read_csv(HISTORICAL_FIXTURE)).set_index("ticker")
        self.assertEqual(len(result), 72)
        self.assertEqual(result.loc["V", "score_home_b"], 78.1)
        self.assertEqual(result.loc["MA", "score_home_b"], 74.6)
        self.assertEqual(result.loc["SLV", "score_home_b"], 63.4)
        self.assertEqual(result.loc["MU", "score_home_b"], 47.1)
        self.assertTrue(pd.isna(result.loc["AAPL", "score_home_b"]))

    def test_snapshot_survives_restart_and_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scanner.db"
            original = Store(path)
            self.assertTrue(original.save_snapshot("2026-11-11", 30,
                [{"ticker": "V", "score_home_b": 77.6, "home_b_candidate": True,
                  "price_at_cutoff": 100.0}], "test", imported=True))
            restarted = Store(path)
            self.assertFalse(restarted.save_snapshot("2026-11-11", 30,
                [{"ticker": "V", "score_home_b": 99.0}], "test"))
            saved = restarted.get_snapshot("2026-11-11", 30)
            self.assertEqual(saved["rows"][0]["score_home_b"], 77.6)
            self.assertTrue(saved["imported"])
            self.assertIsNone(saved["captured_at"])

    def test_later_prices_and_late_reception_do_not_change_cut(self):
        prior = pd.DataFrame([{
            "ticker": "V", "bar_index": i, "session": "PREVIA",
            "time": f"{9 + i//4:02d}:{i%4*15:02d}",
            "open": 100 + (i % 2) * .1, "high": 100.2, "low": 99.9,
            "close": 100 + (i % 2) * .1,
        } for i in range(26)])
        quotes = [dict(ticker="V", price=price,
            event_time=f"2026-11-11T09:30:{event:02d}-05:00",
            received_at=f"2026-11-11T09:30:{received:02d}-05:00")
            for price,event,received in [(104.,1,2),(103.8,20,21)]]
        first = score_cut(prior, quotes, "2026-11-11", 30).set_index("ticker")
        quotes.extend([
            dict(ticker="V",price=95,event_time="2026-11-11T09:30:29-05:00",
                 received_at="2026-11-11T09:30:31-05:00"),
            dict(ticker="V",price=110,event_time="2026-11-11T09:30:31-05:00",
                 received_at="2026-11-11T09:30:29-05:00")])
        future = dict(ticker="V",bar_index=26,session="ACTUAL",time="09:30",
                      open=200,high=200,low=200,close=200)
        later = score_cut(pd.concat([prior,pd.DataFrame([future])]), quotes,
                         "2026-11-11", 30).set_index("ticker")
        self.assertEqual(first.loc["V", "score_home_b"], later.loc["V", "score_home_b"])
        self.assertEqual(later.loc["V", "event_count"], 2)
        self.assertEqual(later.loc["V", "price_at_cutoff"], 103.8)

    def test_quotes_preserve_both_clocks_and_filter_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "scanner.db")
            quote = dict(ticker="V",price=100,event_time="2026-11-11T09:30:05-05:00",
                         received_at="2026-11-11T09:30:25-05:00")
            self.assertEqual(store.append_quotes("2026-11-11",[quote,quote]), 1)
            self.assertEqual(store.get_quotes("2026-11-11","2026-11-11T09:30:10-05:00"), [])
            rows = store.get_quotes("2026-11-11","2026-11-11T09:30:30-05:00")
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0]["event_time"], rows[0]["received_at"])


if __name__ == "__main__":
    unittest.main()
