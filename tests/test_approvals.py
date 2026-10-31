"""Offline tests for answers written in issues, the Approvals list and the entry-page check (fake data only)."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from workers import answers, comps, entry_pages, site

SKILL = ("**How do I enter?** Complete the online entry form and tell us in 25 words or less why you love the beach. "
         "**How is the winner selected?** Judged on creativity.")


def rec(i, desc=SKILL):
    return {"id": i, "title": f"Win prize {i}", "brand": "Shop", "prize_pool": 500.0, "closes": "2026-12-01T23:59:59+10:00",
            "open_to_vic": True, "entry_url": f"https://shop.example/{i}", "url": f"u{i}", "description": desc}


class Answers(unittest.TestCase):
    def test_saved_within_the_limit_only(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(10001)], "t")
            entries.mkdir()
            body = "Win prize 10001\nQuestion: ...\nUp to 25 words.\n---\nThe salt air resets everything."
            ok, msg = answers.save("answer: 10001", body, store, entries)
            self.assertTrue(ok, msg)
            self.assertEqual(json.loads((entries / "answers.json").read_text()), {"10001": "The salt air resets everything."})
            ok, msg = answers.save("answer: 10001", "---\n" + "word " * 26, store, entries)
            self.assertFalse(ok)
            self.assertIn("26 words; the limit is 25", msg)
            self.assertFalse(answers.save("answer: 10001", "---\n  ", store, entries)[0])
            self.assertFalse(answers.save("answer: 99999", "---\nhi", store, entries)[0])
            self.assertEqual(answers.word_limit("Tell us in fifty words"), 50)

    def test_approvals_list(self):
        with tempfile.TemporaryDirectory() as d:
            store, entries = Path(d) / "comps", Path(d) / "entries"
            comps.append(store, [rec(10001), rec(10002), rec(10003)], "t")
            entries.mkdir()
            (entries / "answers.json").write_text(json.dumps({"10001": "Approved words.", "10003": "Entered already."}))
            (entries / "register.csv").write_text("id,title,entries\n10003,x,1\n")
            with open(entries / "queue.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, ["id", "needs_answer", "question"])
                w.writeheader()
                w.writerow({"id": "10002", "needs_answer": "True", "question": ""})
            recs = {str(r["id"]): r for r in (json.loads(l)["comp"] for l in comps.stored(store).values())}
            got = {x["id"]: (x["st"], x["a"], x["lim"]) for x in site.approvals(entries, None, recs)}
            self.assertEqual(got, {"10001": ("ok", "Approved words.", 25), "10002": ("need", None, 25)})
            self.assertIn("25 words or less", site.approvals(entries, None, recs)[1]["q"])


class EntryPages(unittest.TestCase):
    def test_terms_page_with_entry_link_and_how_to_enter(self):
        raw = ('<html><body><h1>Giveaway Terms and Conditions</h1><p>1. The Promoter is Shop Pty Ltd. 2. The promotion '
               'period runs to 30 November. 3. To enter the Promotion, you need to complete the entry form at the '
               'giveaway page. 4. Eligible entrants... 5. The prize draw will take place on 2 December.</p>'
               '<a href="/pages/giveaway">Enter now</a><footer><form action="/contact#newsletter">'
               '<input type="email" name="contact[email]"></form></footer></body></html>')
        prose = entry_pages.comp_terms.prose_of(raw.encode())
        r = entry_pages.check("https://shop.example/pages/giveaway-terms", raw, prose)
        self.assertEqual(r["kind"], "terms")
        self.assertEqual(r["better_url"], "https://shop.example/pages/giveaway")
        self.assertTrue(r["how"].startswith("To enter the Promotion, you need to complete the entry form"))
        form = '<html><form id="comp"><input type="email" name="email"><button>Enter</button></form></html>'
        self.assertEqual(entry_pages.check("https://shop.example/win", form, "Win a prize")["kind"], "form")


    def test_dead_home_and_social_links(self):
        import urllib.error
        r = {"id": 1, "entry_url": "https://shop.example/pages/win-a-bag"}

        def gone(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        self.assertEqual(entry_pages.inspect(r, gone)["kind"], "dead")
        home = lambda url: (b"<html><body>New season dresses. Free shipping.</body></html>", "text/html",
                            "https://shop.example/")
        self.assertEqual(entry_pages.inspect(r, home)["kind"], "moved")
        r2 = {"id": 2, "entry_url": "https://shop.example/"}
        self.assertEqual(entry_pages.inspect(r2, home)["kind"], "home")
        win = lambda url: (b"<html><body>Loading</body></html>", "text/html", "https://win.shop.example/")
        self.assertEqual(entry_pages.inspect({"id": 3, "entry_url": "https://win.shop.example/"}, win)["kind"], "page")
        fb = lambda url: (b"<html><body>Log in to Facebook</body></html>", "text/html",
                          "https://www.facebook.com/shop/posts/123")
        self.assertEqual(entry_pages.inspect({"id": 4, "entry_url": "https://www.facebook.com/shop/posts/123"}, fb)["kind"],
                         "social")


if __name__ == "__main__":
    unittest.main()
