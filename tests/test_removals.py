"""Offline tests for owner removals and the preferences report (no network, no personal details)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from workers import comps, entry_queue, removals

FORM = "**How do I enter the competition?** Complete the online entry form. **How is the winner selected?** Random draw."


def rec(i, title, **kw):
    return {"id": i, "title": title, "brand": kw.get("brand", "Shop"), "prize_pool": kw.get("prize", 500.0),
            "closes": "2026-12-01T23:59:59+10:00", "open_to_vic": True, "entry_url": f"https://shop.example/{i}",
            "url": f"u{i}", "description": FORM}


class Removals(unittest.TestCase):
    def test_removed_comps_are_never_queued_and_feed_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(10001, "Win a Wine Hamper", brand="Cellar"), rec(10002, "Win a Wine Tasting Trip"),
                                 rec(10003, "Win a $500 Bunnings Voucher")], "t")
            (store / "terms.jsonl").write_text("".join(json.dumps({"id": i, "tried": ["x"], "terms_read": True}) + "\n"
                                                       for i in (10001, 10002, 10003)))
            now = dt.datetime(2026, 10, 31, 4, tzinfo=dt.timezone.utc)
            self.assertEqual(removals.record("remove: 10001 99999 10001", store, entries, now), [10001])   # unknown and repeat ids skipped
            self.assertEqual(removals.record("remove: 10001", store, entries, now), [])
            queue, manual = entry_queue.build(store, entries, now)
            self.assertEqual(sorted(q["id"] for q in queue), [10002, 10003])
            self.assertNotIn(10001, [m["id"] for m in manual])
            row = json.loads((entries / "log_removed.jsonl").read_text())
            self.assertEqual((row["category"], row["brand"], row["prize_band"]), ("Food & drink", "Cellar", "$500-$1,999"))
            removals.report(store, entries, dt.date(2026, 10, 31))
            text = (entries / "PREFERENCES.md").read_text()
            self.assertIn("1 competitions removed, 2 open free ones still listed", text)
            self.assertIn("| Food & drink | 1 | 0 | 100% |", text)
            self.assertIn("hamper (1)", text)


    def test_doesnt_work_is_removed_but_not_a_dislike(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(10001, "Win a Wine Hamper"), rec(10002, "Win a $500 Bunnings Voucher")], "t")
            now = dt.datetime(2026, 10, 31, 4, tzinfo=dt.timezone.utc)
            removals.record("broken: 10001", store, entries, now)
            self.assertEqual(json.loads((entries / "log_removed.jsonl").read_text())["why"], "doesn't work")
            self.assertEqual(removals.removed_ids(entries), {10001})
            removals.report(store, entries, dt.date(2026, 10, 31))
            text = (entries / "PREFERENCES.md").read_text()
            self.assertIn("0 competitions removed", text)
            self.assertIn("Marked \"doesn't work\" (1; not counted as dislikes)", text)


if __name__ == "__main__":
    unittest.main()
