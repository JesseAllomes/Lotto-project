"""Offline tests for the owner's competition page and the re-entry queue."""
import csv
import datetime as dt
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workers import reenter, site


def write_manual(e, rows):
    with open(e / "manual.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


class Page(unittest.TestCase):
    def test_lists_open_manual_comps_with_categories_and_no_personal_details(self):
        with tempfile.TemporaryDirectory() as d:
            e = Path(d)
            write_manual(e, [
                {"id": "1", "title": "Win a 4 Seater Sofa", "brand": "Eva", "prize_pool": "3790",
                 "closes": "2026-11-03T23:59", "draw_type": "chance", "reason": "entrant blocked: captcha",
                 "entry_platform": "web", "entry_url": "https://eva.example/pages/giveaway"},
                {"id": "2", "title": "Win VIP Festival Tickets", "brand": "Shop", "prize_pool": "100",
                 "closes": "2026-11-01T23:59", "draw_type": "chance", "reason": "entry route manual",
                 "entry_platform": "instagram", "entry_url": "https://www.instagram.com/p/x/"},
                {"id": "3", "title": "Closed one", "brand": "Old", "prize_pool": "9", "closes": "2026-10-01T23:59",
                 "draw_type": "chance", "reason": "entry route manual", "entry_platform": "web",
                 "entry_url": "https://old.example/"}])
            (e / "answers.json").write_text(json.dumps({"1": "Comfy, deep and built for movie nights."}))
            (e / "log.jsonl").write_text(json.dumps({"id": 9, "mode": "live", "result": "entered",
                                                     "time_utc": "2026-10-30T01:00:00Z"}) + "\n")
            (e / "log_reenter.jsonl").write_text(json.dumps({"id": 9, "mode": "live", "result": "entered",
                                                             "time_utc": "2026-10-30T02:00:00Z"}) + "\n")
            it = {x["id"]: x for x in site.items(e, dt.date(2026, 10, 31), recs={})}
            self.assertEqual(sorted(it), ["1", "2"])
            self.assertEqual((it["1"]["g"], it["1"]["k"], it["1"]["a"]), ("web", "Home & garden",
                                                                          "Comfy, deep and built for movie nights."))
            self.assertEqual((it["2"]["g"], it["2"]["k"]), ("social", "Tickets & experiences"))
            self.assertEqual(site.stats(e), {"entries": 2, "comps": 1})
            html = site.page(e, dt.date(2026, 10, 31), built="t")
            data = json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1))
            self.assertEqual(len(data["todo"]), 2)
            self.assertNotIn("@example", html)

    def test_categories(self):
        self.assertEqual(site.category("Win a $3.4M Mooloolaba Prize Home"), "Prize homes & lotteries")
        self.assertEqual(site.category("Win a Custom Toyota Landcruiser"), "Cars & vehicles")
        self.assertEqual(site.category("Win $5,000 Cash"), "Cash & vouchers")
        self.assertEqual(site.category("Win something", "travel-competitions"), "Travel")
        # fixes from the 31 Oct review
        self.assertEqual(site.category("Win 1 of 2 $55 Spring Cleaning Kits"), "Home & garden")         # not "ring"
        self.assertEqual(site.category("Win a Sheet Set Worth $158"), "Home & garden")                  # "$158" is not cash
        self.assertEqual(site.category("Win 1 X 5 Double Passes to the Piano Symphony Australian Tour"),
                         "Tickets & experiences")
        self.assertEqual(site.category("Switch – Win 1/5 of La Bola Negra DPs (9:30am close, M/R)"), "Tickets & experiences")
        self.assertEqual(site.category("Win a Crime Book Pack"), "Books & media")
        self.assertEqual(site.category("Trade to Win a Porsche 911 GTS"), "Cars & vehicles")
        self.assertEqual(site.category("Win $3K for your Summer Fund Every Week"), "Cash & vouchers")
        self.assertEqual(site.category("Win a $20,000 Cruise Voucher"), "Travel")


def build_page():
    with tempfile.TemporaryDirectory() as d:
        return site.page(Path(d), dt.date(2026, 10, 31), built="t")


class Buttons(unittest.TestCase):
    """Every button posts to the site API; nothing opens a GitHub issue."""

    def test_no_github_issue_links_remain(self):
        html = build_page()
        for text in ("issues/new", "github.com", "rmIssue", "brokenIssue", "answerIssue", "D.repo"):
            self.assertNotIn(text, html, text)
        self.assertNotIn("repo", json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1)))
        self.assertNotIn("JesseAllomes", html)

    def test_actions_go_through_the_api_with_the_login_redirect(self):
        html = build_page()
        self.assertIn('fetch("/api/action", { method: "POST"', html)
        self.assertIn('redirect: "manual"', html)                                       # the edge's 302 login redirect is detected, not followed
        self.assertIn("/.auth/login/github?post_login_redirect_uri=", html)
        self.assertIn("r.status === 401 || r.status === 403", html)
        self.assertIn("/.auth/me", html)                                                # read-only page when not signed in
        for kind in ("remove", "broken", "reenter", "answer", "done", "undone"):
            self.assertIn(f'"{kind}"', html, kind)

    def test_buttons_are_buttons_with_data_actions(self):
        html = build_page()
        for act in ('data-act="remove"', 'data-act="broken"', 'data-act="reenter"', 'data-act="rmsel"', 'data-act="resel"',
                    'data-act="edit-answer"', 'data-act="save-answer"'):
            self.assertIn(act, html, act)
        self.assertIn('id="toast"', html)
        self.assertIn("Sign in", html)

    def test_done_ticks_are_kept_locally_and_synced(self):
        html = build_page()
        self.assertIn('store.set("comps-done", d)', html)                               # localStorage stays
        self.assertIn('syncDone(on ? "done" : "undone", id)', html)                     # and the tick is posted
        with tempfile.TemporaryDirectory() as d:
            e = Path(d)
            (e / "done.json").write_text(json.dumps({"75870": 1760000000000, "bad": "x"}))
            data = json.loads(re.search(r"const D = (\{.*?\});\n", site.page(e, dt.date(2026, 10, 31), built="t")).group(1))
        self.assertEqual(data["done"], {"75870": 1760000000000})
        self.assertEqual(site.load_done(Path("/nonexistent")), {})

    def test_the_page_script_is_valid_javascript(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        script = re.search(r"<script>(.*)</script>", build_page(), re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "page.js"
            path.write_text(script)
            done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)


class StaticWebAppConfig(unittest.TestCase):
    def test_api_needs_the_owner_role_and_pages_stay_public(self):
        cfg = site.SWA_CONFIG
        routes = {r["route"]: r for r in cfg["routes"]}
        self.assertEqual(routes["/api/*"]["allowedRoles"], ["owner"])
        self.assertNotIn("methods", routes["/api/*"])                                   # every method, not just POST
        for route in routes:
            if route != "/api/*" and not route.startswith("/.auth/"):
                self.fail(f"unexpected route {route}")                                  # no page route restricts the public site
        for provider in ("aad", "google", "twitter", "facebook", "apple"):
            self.assertEqual(routes[f"/.auth/login/{provider}"]["statusCode"], 404)
        self.assertNotIn("/.auth/login/github", routes)
        self.assertEqual(cfg["responseOverrides"]["401"]["redirect"], "/.auth/login/github?post_login_redirect_uri=.referrer")
        self.assertEqual(cfg["responseOverrides"]["401"]["statusCode"], 302)
        self.assertEqual(cfg["platform"]["apiRuntime"], "python:3.11")
        self.assertNotIn("anonymous", json.dumps(cfg["routes"]))

    def test_main_writes_the_config_next_to_the_page(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(site, "page", return_value="<html></html>"):
            site.main(["--out", d])
            self.assertEqual(json.loads((Path(d) / "staticwebapp.config.json").read_text()), site.SWA_CONFIG)
            self.assertTrue((Path(d) / "index.html").is_file())


class Freebies(unittest.TestCase):
    def test_keeps_national_and_victorian_freebies_only(self):
        from workers import freebies
        rows = freebies.parse((Path(__file__).resolve().parent / "fixtures" / "ozbargain_freebies.html").read_text())
        titles = [r["title"] for r in rows]
        self.assertTrue(any("[VIC]" in t for t in titles))
        self.assertFalse(any(t.startswith("[NSW]") or "Today [NSW]" in t for t in titles))
        self.assertTrue(all(r["url"].startswith("https://www.ozbargain.com.au/node/") for r in rows))


class Reenter(unittest.TestCase):
    def test_ids_are_read_from_the_issue_title_and_only_open_listings_queued(self):
        from workers import comps
        with tempfile.TemporaryDirectory() as d:
            store, e = Path(d) / "comps", Path(d) / "entries"
            e.mkdir()
            comps.append(store, [
                {"id": 75870, "title": "A", "entry_url": "https://a.example/", "closes": "2026-11-30T23:59", "url": "u1"},
                {"id": 76000, "title": "B", "entry_url": "https://b.example/", "closes": "2026-10-01T23:59", "url": "u2"}],
                "t")
            (e / "answers.json").write_text(json.dumps({"75870": "Because."}))
            q = reenter.build("reenter: 75870 76000 12345", store, e, dt.date(2026, 10, 31))
            self.assertEqual(q, [{"id": 75870, "entry_url": "https://a.example/", "answer": "Because."}])


if __name__ == "__main__":
    unittest.main()
