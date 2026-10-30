"""Offline test for the owner's competition page."""
import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from workers import site


class Page(unittest.TestCase):
    def test_lists_open_manual_comps_grouped_and_holds_no_personal_details(self):
        with tempfile.TemporaryDirectory() as d:
            e = Path(d)
            rows = [
                {"id": "1", "title": "Win a sofa", "brand": "Eva", "prize_pool": "3790", "closes": "2026-11-03T23:59",
                 "draw_type": "chance", "reason": "entrant blocked: captcha", "entry_platform": "web",
                 "entry_url": "https://eva.example/pages/giveaway"},
                {"id": "2", "title": "Win merch", "brand": "Shop", "prize_pool": "100", "closes": "2026-11-01T23:59",
                 "draw_type": "chance", "reason": "entry route manual", "entry_platform": "instagram",
                 "entry_url": "https://www.instagram.com/p/x/"},
                {"id": "3", "title": "Closed one", "brand": "Old", "prize_pool": "9", "closes": "2026-10-01T23:59",
                 "draw_type": "chance", "reason": "entry route manual", "entry_platform": "web",
                 "entry_url": "https://old.example/"},
            ]
            with open(e / "manual.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            (e / "log.jsonl").write_text(json.dumps({"id": 9, "mode": "live", "result": "entered",
                                                     "time_utc": "2026-10-30T01:00:00Z"}) + "\n")
            it = site.items(e, dt.date(2026, 10, 31))
            self.assertEqual([(x["id"], x["group"]) for x in it], [("2", "social"), ("1", "web")])
            html = site.page(e, dt.date(2026, 10, 31), built="t")
            self.assertIn("Win a sofa", html)
            self.assertNotIn("Closed one", html)
            self.assertIn("made\n1 entries in 1 competitions", html)
            self.assertNotIn("@", html.split("<script>")[0].replace("@media", ""))


if __name__ == "__main__":
    unittest.main()
