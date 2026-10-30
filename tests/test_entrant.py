"""Offline tests for the auto-entry queue and entrant (no network, no personal details)."""
import datetime as dt
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from workers import comps, entry_queue

TODAY = dt.date(2026, 10, 30)
FORM = "**How do I enter the competition?** Complete the online entry form. **How is the winner selected?** Random draw."


def rec(i, desc=FORM, **kw):
    base = {"id": i, "title": f"Win {i}", "brand": "Shop", "prize_pool": 500.0, "closes": "2026-12-01T23:59:59+10:00",
            "open_to_vic": True, "entry_url": f"https://shop.example/{i}", "url": f"u{i}", "description": desc}
    return {**base, **kw}


class Limits(unittest.TestCase):
    def test_entry_limits(self):
        now = dt.datetime(2026, 10, 30, 3, 0, tzinfo=dt.timezone.utc)            # 2pm in Melbourne
        earlier_today = now - dt.timedelta(hours=3)
        yesterday = now - dt.timedelta(days=1)
        may = entry_queue.may_enter
        self.assertTrue(may("once", [], now))
        self.assertFalse(may("once", [yesterday], now))
        self.assertTrue(may("daily", [yesterday], now))
        self.assertFalse(may("daily", [earlier_today], now))
        self.assertTrue(may("daily", [earlier_today], now, n=3))
        self.assertFalse(may("weekly", [yesterday], now))
        self.assertTrue(may("capped", [yesterday], now, n=2))
        self.assertFalse(may("capped", [yesterday, earlier_today], now, n=2))
        burst = now.replace(minute=30)                           # 03:30 UTC: window 03:00-05:59 UTC
        mins = lambda m: burst - dt.timedelta(minutes=m)
        for limit in ("unlimited", "unknown"):                    # no limit: bursts of 5 per 3-hour window, 5 min apart
            self.assertTrue(may(limit, [mins(5), mins(10), mins(15), mins(20)], burst))
            self.assertFalse(may(limit, [mins(5), mins(10), mins(15), mins(20), mins(25)], burst))
            self.assertFalse(may(limit, [mins(3)], burst))
            self.assertTrue(may(limit, [mins(181), mins(186), mins(191), mins(196), mins(201)], burst))
            self.assertTrue(may(limit, [mins(31), mins(36), mins(41), mins(46), mins(51)], burst))   # last window
        hrs = lambda h: now - dt.timedelta(hours=h)
        self.assertTrue(may("unknown", [hrs(5)], now, excessive=True))     # excessive clause: 4 a day, 5 h apart
        self.assertFalse(may("unknown", [hrs(2)], now, excessive=True))
        many = [now.replace(hour=0) - dt.timedelta(hours=10) + dt.timedelta(minutes=k) for k in range(4)]
        self.assertTrue(all(t.astimezone(entry_queue.MELB).date() == now.astimezone(entry_queue.MELB).date()
                            for t in many))
        self.assertFalse(may("unknown", many, now, excessive=True))

    def test_excessive_wording(self):
        from workers import comp_odds
        ex = lambda t: bool(comp_odds.re.search(comp_odds.EXCESSIVE, t))
        self.assertTrue(ex("The Promoter may, in its discretion, disqualify excessive entries."))
        self.assertTrue(ex("Multiple entries deemed excessive by the Promoter will be removed."))
        self.assertTrue(ex("The Promoter reserves the right to exclude bulk entries."))
        self.assertFalse(ex("You may enter as many times as you like."))


class Retries(unittest.TestCase):
    def test_two_failures_block_and_already_entered_stops_repeats(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(1, desc=FORM + " Multiple entries are permitted."), rec(2), rec(3)], "t")
            (store / "terms.jsonl").write_text("".join(json.dumps({"id": i, "tried": ["x"], "terms_read": True}) + "\n"
                                                       for i in (1, 2, 3)))
            entries.mkdir()
            log = [{"id": 1, "time_utc": "2026-10-30T00:05:00Z", "mode": "live", "result": "entered",
                    "reason": "already entered"},
                   {"id": 2, "time_utc": "2026-10-30T17:05:00Z", "mode": "live", "result": "failed", "reason": "x"},
                   {"id": 2, "time_utc": "2026-10-30T17:10:00Z", "mode": "live", "result": "failed", "reason": "x"},
                   {"id": 3, "time_utc": "2026-10-30T17:05:00Z", "mode": "live", "result": "failed", "reason": "x"}]
            (entries / "log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in log))
            queue, manual = entry_queue.build(store, entries, dt.datetime(2026, 10, 30, 18, 30, tzinfo=dt.timezone.utc))
            self.assertEqual([q["id"] for q in queue], [3])                 # one failure: try again
            self.assertEqual({m["id"]: m["reason"] for m in manual}, {2: "entrant blocked: failing (x)"})


class TermsLimit(unittest.TestCase):
    def test_explicit_wording_only(self):
        from workers import comp_odds
        lim = comp_odds.terms_limit
        self.assertEqual(lim("Entrants are limited to one entry per person."), ("once", None))
        self.assertEqual(lim("Only one (1) entry per person is permitted."), ("once", None))
        self.assertEqual(lim("Entrants may enter once per day during the promotional period."), ("daily", None))
        self.assertEqual(lim("A maximum of 3 entries per day."), ("daily", 3))
        self.assertEqual(lim("Maximum of 5 entries per person."), ("capped", 5))
        self.assertEqual(lim("Multiple entries are permitted."), ("unlimited", None))
        self.assertEqual(lim("Prizes are drawn daily at 10am. Winners notified each day."), (None, None))


class Queue(unittest.TestCase):
    def test_queue_and_manual_list(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [
                rec(1),                                                                   # ready
                rec(2, desc=FORM.replace("Complete the online entry form.", "Comment on our Facebook post.")),
                rec(3, desc=FORM + " Entries made using automated software or bots are invalid."),
                rec(4, desc=FORM.replace("Random draw.", "Judged on creativity and merit.")),  # needs an answer
                rec(5, desc=FORM.replace("Complete the online entry form.", "Buy a ticket online.")),  # paid
                rec(6),                                                                   # terms: once, entered
                rec(7),                                                                   # terms not read yet
                rec(8),                                                                   # entrant hit a captcha
            ], "t")
            (store / "terms.jsonl").write_text("".join(json.dumps(
                {"id": i, "tried": ["x"], "terms_read": True, "entry_limit_terms": "once" if i == 6 else None}) + "\n"
                for i in (1, 2, 3, 4, 6, 8)))
            entries.mkdir()
            (entries / "log.jsonl").write_text(
                json.dumps({"id": 6, "time_utc": "2026-10-20T01:00:00Z", "mode": "live", "result": "entered"}) + "\n" +
                json.dumps({"id": 8, "time_utc": "2026-10-29T01:00:00Z", "mode": "dry", "result": "skipped",
                            "reason": "captcha"}) + "\n")
            queue, manual = entry_queue.build(store, entries, dt.datetime(2026, 10, 30, 3, tzinfo=dt.timezone.utc))
            self.assertEqual([(q["id"], q["needs_answer"]) for q in queue], [(1, False), (3, False), (4, True)])
            self.assertEqual({m["id"]: m["reason"] for m in manual},
                             {2: "entry route manual", 8: "entrant blocked: captcha"})
            entry_queue.ENTER_BANNED = False                          # owner's off switch
            try:
                queue, manual = entry_queue.build(store, entries, dt.datetime(2026, 10, 30, 3, tzinfo=dt.timezone.utc))
            finally:
                entry_queue.ENTER_BANNED = True
            self.assertEqual(manual[0]["reason"] if manual[0]["id"] == 3 else
                             {m["id"]: m["reason"] for m in manual}[3], "terms ban automated entry")
            text = (entries / "queue.csv").read_text() + (entries / "manual.csv").read_text()
            self.assertNotIn("@", text)

            ready = json.loads((entries / "queue.json").read_text())
            self.assertEqual(ready, [{"id": 1, "entry_url": "https://shop.example/1", "answer": None}])


@unittest.skipUnless(shutil.which("node") and subprocess.run(["node", "-e", "require('playwright')"],
                                                             capture_output=True).returncode == 0,
                     "node and playwright not installed")
class Browser(unittest.TestCase):
    def test_entrant_on_local_forms(self):
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(["node", "--test", "tests/entrant.test.mjs"], cwd=root, capture_output=True, text=True,
                             timeout=600)
        self.assertEqual(out.returncode, 0, out.stdout[-2000:] + out.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
