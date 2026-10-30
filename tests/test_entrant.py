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
        d = TODAY - dt.timedelta(days=1)
        self.assertTrue(entry_queue.may_enter("once", [], TODAY))
        self.assertFalse(entry_queue.may_enter("once", [d], TODAY))
        self.assertFalse(entry_queue.may_enter("unknown", [d], TODAY))
        self.assertTrue(entry_queue.may_enter("daily", [d], TODAY))
        self.assertFalse(entry_queue.may_enter("daily", [TODAY], TODAY))
        self.assertFalse(entry_queue.may_enter("weekly", [d], TODAY))


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
                rec(6),                                                                   # already entered once
                rec(7),                                                                   # terms not read yet
                rec(8),                                                                   # entrant hit a captcha
            ], "t")
            (store / "terms.jsonl").write_text("".join(json.dumps({"id": i, "tried": ["x"], "terms_read": True}) + "\n"
                                                       for i in (1, 2, 3, 4, 6, 8)))
            entries.mkdir()
            (entries / "log.jsonl").write_text(
                json.dumps({"id": 6, "time_utc": "2026-10-20T01:00:00Z", "mode": "live", "result": "entered"}) + "\n" +
                json.dumps({"id": 8, "time_utc": "2026-10-29T01:00:00Z", "mode": "dry", "result": "skipped",
                            "reason": "captcha"}) + "\n")
            queue, manual = entry_queue.build(store, entries, TODAY)
            self.assertEqual([(q["id"], q["needs_answer"]) for q in queue], [(1, False), (4, True)])
            self.assertEqual({m["id"]: m["reason"] for m in manual},
                             {2: "entry route manual", 3: "terms ban automated entry", 8: "entrant blocked: captcha"})
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
