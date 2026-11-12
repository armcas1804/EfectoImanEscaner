from datetime import datetime, timedelta
from pathlib import Path
import unittest

import pandas as pd

from scanner.pattern_score import apply_pattern_score
from scanner.scoring import rescore_export


HISTORICAL_FIXTURE = Path(__file__).parent / "fixtures" / "approved_b_90s.csv"


@unittest.skipUnless(HISTORICAL_FIXTURE.exists(), "CSV histórico disponible sólo en la instalación local")
class PatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = dict(date="2026-11-11", seconds=90, cutoff_at="2026-11-11T09:31:30-05:00",
                            score_version="original", rows=rescore_export(pd.read_csv(HISTORICAL_FIXTURE)).to_dict("records"))

    def test_rescore_preserves_original_and_eligibility(self):
        original = {row["ticker"]: row for row in self.snapshot["rows"]}
        view = apply_pattern_score(self.snapshot)
        rows = {row["ticker"]: row for row in view["rows"]}
        self.assertEqual(original["V"]["score_home_b"], 78.1)
        self.assertEqual(rows["V"]["score_home_b_previous"], 78.1)
        self.assertEqual(rows["V"]["pattern_coverage"], "endpoints")
        self.assertEqual(view["stored_score_version"], "original")
        self.assertNotEqual(rows["V"]["score_home_b"], 78.1)
        self.assertLess(rows["MU"]["score_home_b"], rows["V"]["score_home_b"])
        self.assertIsNone(rows["AAPL"]["score_home_b"])
        self.assertEqual({k for k, v in rows.items() if v["home_b_candidate"]},
                         {k for k, v in original.items() if v["home_b_candidate"]})

    def test_intermediate_excursion_counts_but_late_quotes_do_not(self):
        row = dict(next(row for row in self.snapshot["rows"] if row["ticker"] == "V"), event_count=3)
        snapshot = dict(self.snapshot, rows=[row])
        first = datetime.fromisoformat(row["first_time"])
        last = datetime.fromisoformat(row["last_time"])
        middle = first + (last - first) / 2

        def quote(event, price, received=None):
            return dict(ticker="V", event_time=event.isoformat(), price=price,
                        received_at=(received or event).isoformat())

        endpoints = [quote(first, row["first_price"]), quote(last, row["price_at_cutoff"])]
        excursion = quote(middle, row["first_price"] * .95)
        with_path = apply_pattern_score(snapshot, [*endpoints, excursion])["rows"][0]
        without_path = apply_pattern_score(snapshot, endpoints)["rows"][0]
        self.assertEqual(with_path["pattern_coverage"], "observations")
        self.assertLess(with_path["score_home_b"], without_path["score_home_b"])

        late = datetime.fromisoformat(snapshot["cutoff_at"]) + timedelta(seconds=1)
        self.assertEqual(apply_pattern_score(snapshot, [*endpoints,
                         quote(middle, excursion["price"], late)])["rows"][0], without_path)
