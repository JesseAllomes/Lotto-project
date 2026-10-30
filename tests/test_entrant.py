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


class LastDay(unittest.TestCase):
    def test_stated_closing_time_beats_the_listing_default(self):
        r = rec(1, desc="**When does the competition close?** The competition closes at 6:00 PM AEDT on Saturday, "
                        "31 October 2026.", closes="2026-10-31T23:59:59+10:00")
        self.assertEqual(entry_queue.closes_at(r), dt.datetime(2026, 10, 31, 7, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(entry_queue.closes_at(rec(2, closes="2026-10-31T23:59:59+10:00")),
                         dt.datetime(2026, 10, 31, 13, 59, 59, tzinfo=dt.timezone.utc))
        now = dt.datetime(2026, 10, 30, 22, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(entry_queue.last_day(r, now))
        self.assertFalse(entry_queue.last_day(rec(3), now))

    def test_last_day_pace(self):
        may = entry_queue.may_enter
        now = dt.datetime(2026, 10, 31, 4, 40, tzinfo=dt.timezone.utc)          # 04:00-04:59 UTC hour, 03:00 window
        five = [now - dt.timedelta(minutes=m) for m in (35, 30, 25)] + [now - dt.timedelta(minutes=m) for m in (100, 95)]
        self.assertFalse(may("unknown", five, now))                    # 5 in the 3-hour window already
        self.assertTrue(may("unknown", five, now, final=True))         # last day: 5 an hour
        self.assertFalse(may("once", five[:1], now, final=True))       # stated limits never change
        self.assertFalse(may("daily", five[:1], now, final=True))
        three_h = [now - dt.timedelta(hours=3, minutes=5)]
        self.assertFalse(may("unknown", three_h, now, excessive=True))
        self.assertTrue(may("unknown", three_h, now, excessive=True, final=True))

    def test_last_day_queue_retry_and_pace_file(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            soon = "2026-11-01T06:00:00+11:00"                                 # 19:00 UTC on 31 Oct
            comps.append(store, [rec(1, closes=soon), rec(2, closes=soon), rec(3, closes=soon), rec(4)], "t")
            (store / "terms.jsonl").write_text("".join(json.dumps({"id": i, "tried": ["x"], "terms_read": True}) + "\n"
                                                       for i in (1, 4)))          # 2 and 3: terms not read yet
            entries.mkdir()
            log = [{"id": 3, "time_utc": "2026-10-30T17:05:00Z", "mode": "live", "result": "failed", "reason": "x"},
                   {"id": 3, "time_utc": "2026-10-30T17:10:00Z", "mode": "live", "result": "failed", "reason": "x"}]
            (entries / "log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in log))
            now = dt.datetime(2026, 10, 30, 22, 0, tzinfo=dt.timezone.utc)
            queue, manual = entry_queue.build(store, entries, now - dt.timedelta(hours=4))
            self.assertEqual([m["id"] for m in manual], [3])                 # before its last day: still blocked
            queue, manual = entry_queue.build(store, entries, now)
            self.assertEqual(sorted(q["id"] for q in queue), [1, 2, 3, 4])   # 2 unread terms, 3 one more try
            self.assertEqual({q["id"]: q["last_day"] for q in queue}, {1: True, 2: True, 3: True, 4: False})
            self.assertEqual(json.loads((entries / "pace.json").read_text())["next_run_minutes"], 60)
            log.append({"id": 3, "time_utc": "2026-10-30T22:05:00Z", "mode": "live", "result": "failed", "reason": "x"})
            (entries / "log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in log))
            queue, manual = entry_queue.build(store, entries, now + dt.timedelta(minutes=10))
            self.assertEqual([m["id"] for m in manual], [3])                 # failed again today: back on the list

    def test_unknown_result_counts_against_stated_limits_only(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(1, desc=FORM + " Only one entry per person."), rec(2)], "t")
            (store / "terms.jsonl").write_text("".join(json.dumps({"id": i, "tried": ["x"], "terms_read": True}) + "\n"
                                                       for i in (1, 2)))
            entries.mkdir()
            (entries / "log.jsonl").write_text("".join(json.dumps({"id": i, "time_utc": "2026-10-30T17:00:00Z",
                                                                   "mode": "live", "result": "unknown"}) + "\n"
                                                       for i in (1, 2)))
            queue, _ = entry_queue.build(store, entries, dt.datetime(2026, 10, 30, 22, tzinfo=dt.timezone.utc))
            self.assertEqual([q["id"] for q in queue], [2])               # once: maybe entered, so not again
            self.assertEqual((entries / "register.csv").read_text().count("\n"), 1)   # header only

    def test_allowed_one_entry_wording(self):
        from workers import comp_odds
        self.assertEqual(comp_odds.entry_limit({}, "Each individual is allowed one entry unless otherwise specified."),
                         ("once", None))
        self.assertEqual(comp_odds.terms_limit("Entrants are permitted only one entry."), ("once", None))


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
                json.dumps({"id": 8, "time_utc": "2026-10-30T23:00:00Z", "mode": "dry", "result": "skipped",
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
