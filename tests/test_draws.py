"""Offline tests for the winning-numbers register worker (no network)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from workers import draws
from workers.lott import windows

SAMPLE = {
    "ProductId": "Powerball", "DrawNumber": 719, "DrawDate": "2010-02-25T00:00:00",
    "PrimaryNumbers": [32, 1, 24, 37, 33], "SecondaryNumbers": [37], "TicketNumbers": None,
    "Dividends": [{"Division": 1, "BlocNumberOfWinners": 0, "BlocDividend": 0.0, "CompanyId": "Tattersalls",
                   "CompanyNumberOfWinners": 0, "CompanyDividend": 0.0, "PoolTransferType": "None",
                   "PoolTransferredTo": 0}],
}


class Windows(unittest.TestCase):
    def test_windows_cover_the_range_within_the_90_day_limit(self):
        w = list(windows(dt.date(2010, 1, 1), dt.date(2010, 12, 31), days=89))
        self.assertEqual(w[0][0], dt.date(2010, 1, 1))
        self.assertEqual(w[-1][1], dt.date(2010, 12, 31))
        for (a, b), (c, _) in zip(w, w[1:]):
            self.assertLessEqual((b - a).days, 89)
            self.assertEqual(c, b + dt.timedelta(days=1))   # no gaps, no overlaps


class Register(unittest.TestCase):
    def test_row_keeps_numbers_in_drawn_order_and_division_one(self):
        row = draws.row(SAMPLE)
        self.assertEqual(row["product"], "Powerball")
        self.assertEqual(row["draw_number"], 719)
        self.assertEqual(row["draw_date"], "2010-02-25")
        self.assertEqual(row["primary"], "32 1 24 37 33")
        self.assertEqual(row["secondary"], "37")
        self.assertEqual(row["div1_winners"], 0)

    def test_append_is_idempotent_by_draw_number(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            n1 = draws.append(store, "Powerball", [SAMPLE], fetched="2026-10-30T00:00:00Z", source="test")
            n2 = draws.append(store, "Powerball", [SAMPLE], fetched="2026-10-31T00:00:00Z", source="test")
            self.assertEqual((n1, n2), (1, 0))
            lines = (store / "Powerball.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["fetched_utc"], "2026-10-30T00:00:00Z")   # first sighting is kept, never overwritten
            self.assertEqual(rec["draw"]["DrawNumber"], 719)

    def test_csv_register_is_rebuilt_in_draw_order(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            later = dict(SAMPLE, DrawNumber=720, DrawDate="2010-03-04T00:00:00")
            draws.append(store, "Powerball", [later, SAMPLE], fetched="t", source="test")
            draws.write_csv(store, "Powerball")
            rows = (store / "Powerball.csv").read_text().splitlines()
            self.assertTrue(rows[0].startswith("product,draw_number,draw_date,primary,secondary"))
            self.assertEqual([r.split(",")[1] for r in rows[1:]], ["719", "720"])


if __name__ == "__main__":
    unittest.main()
