"""Offline tests for the winners tracker (no network; a fake surname)."""
import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from workers import comps, winners

DESC = ("**When does the competition close?** The competition closes at 6:00 PM AEDT on Saturday, 31 October 2026. "
        "**How is the winner selected?** Winners are selected randomly during a draw held at 10:00 AM AEDT on Sunday, "
        "1 November 2026, in Bondi, NSW. "
        "**How will the winner be notified?** Winners will be notified by email and phone within two business days. "
        "Winners will be announced on www.Example.com.au/winners within 7 days. "
        "**What happens if the prize is unclaimed?** If a prize is unclaimed within 14 days, it will be redrawn.")


def rec(i, desc=DESC, closes="2026-10-31T23:59:59+10:00"):
    return {"id": i, "title": f"Win {i}", "brand": "Shop", "prize_pool": 500.0, "closes": closes, "open_to_vic": True,
            "entry_url": f"https://shop.example/{i}", "url": f"u{i}", "description": desc}


class Info(unittest.TestCase):
    def test_reads_draw_notice_claim_and_page(self):
        i = winners.info(rec(1))
        self.assertEqual(i["draw_date"], dt.date(2026, 11, 1))
        self.assertFalse(i["draw_estimated"])
        self.assertEqual(i["notify"], "email, phone")
        self.assertEqual(i["notify_within_days"], 2)
        self.assertEqual(i["claim_within_days"], 14)
        self.assertEqual(i["winners_page"], "https://www.example.com.au/winners")

    def test_estimates_the_draw_when_not_stated(self):
        i = winners.info(rec(2, desc="**How do I enter?** Fill in the form."))
        self.assertEqual(i["draw_date"], dt.date(2026, 11, 7))
        self.assertTrue(i["draw_estimated"])
        self.assertEqual(i["notify"], "")

    def test_dates(self):
        self.assertEqual(winners.parse_date("on 2nd November 2026"), dt.date(2026, 11, 2))
        self.assertEqual(winners.parse_date("by November 15, 2026"), dt.date(2026, 11, 15))
        self.assertEqual(winners.parse_date("on 03/11/2026"), dt.date(2026, 11, 3))


class Statuses(unittest.TestCase):
    def test_status_and_surname_check(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(1), rec(2, closes="2026-12-01T23:59:59+10:00")], "t")
            entries.mkdir()
            rows = {r["id"]: r for r in winners.build(store, entries, today=dt.date(2026, 11, 3))}
            self.assertEqual(rows[1]["status"], "drawn: watch email/phone")
            self.assertEqual(rows[2]["status"], "open")
            later = {r["id"]: r for r in winners.build(store, entries, today=dt.date(2026, 12, 1))}
            self.assertEqual(later[1]["status"], "claim window passed")
            pages = []
            fake = lambda url: pages.append(url) or "Congratulations to J. Testperson (VIC) and others"
            now = dt.datetime(2026, 11, 3, 1, 0, tzinfo=dt.timezone.utc)
            n = winners.check(list(rows.values()), "Testperson", entries, fetch=fake, now=now, delay=0)
            self.assertEqual((n, pages), (1, ["https://www.example.com.au/winners"]))
            log = (entries / "winner_checks.jsonl").read_text()
            self.assertNotIn("Testperson", log)
            self.assertTrue(json.loads(log)["name_seen"])
            self.assertEqual(winners.check(list(rows.values()), "Testperson", entries, fetch=fake, now=now, delay=0), 0)
            rows = winners.build(store, entries, today=dt.date(2026, 11, 3))
            self.assertEqual((rows[0]["id"], rows[0]["name_seen"]), (1, "yes"))
            with open(entries / "winners.csv") as fh:
                self.assertEqual(next(csv.DictReader(fh))["name_seen"], "yes")


if __name__ == "__main__":
    unittest.main()
