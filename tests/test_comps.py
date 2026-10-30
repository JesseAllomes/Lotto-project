"""Offline tests for the competition register worker (saved pages, no network)."""
import json
import tempfile
import unittest
from pathlib import Path

from workers import comps

FIX = Path(__file__).resolve().parent / "fixtures"
RAFFLE_URL = "https://www.competitions.com.au/win-this-3-3m-sunshine-coast-prize-home/76171/"
CASH_URL = "https://www.competitions.com.au/win-1k-sportscraft-gift-card/76174/"


def page(name):
    return (FIX / name).read_text()


class Parse(unittest.TestCase):
    def test_sitemap_gives_listing_ids_and_skips_the_home_page(self):
        got = comps.listing_urls(page("comps_sitemap.xml"))
        self.assertEqual([i for i, _ in got], [76174, 76171, 76170])
        self.assertEqual(got[1][1], RAFFLE_URL)

    def test_charity_prize_home_listing(self):
        r = comps.parse(page("comp_76171.html"), 76171, RAFFLE_URL)
        self.assertEqual(r["title"], "Win this $3.3M Sunshine Coast Prize Home")
        self.assertEqual((r["category"], r["category_slug"]), ("Charity Raffles", "charity-competitions"))
        self.assertEqual(r["brand"], "Endeavour Lotteries")
        self.assertEqual(r["prize_pool"], 3_300_000.0)
        self.assertEqual(r["states"], "NSW, VIC, QLD, SA, WA, TAS, NT, ACT")
        self.assertTrue(r["open_to_vic"])
        self.assertEqual(r["closes"], "2027-02-11T23:59:59+10:00")
        self.assertEqual(r["entry_url"], "https://www.endeavourlotteries.com.au/endeavour-foundation/draw/471")
        self.assertIn("$3,329,295", r["description"])

    def test_cash_listing(self):
        r = comps.parse(page("comp_76174.html"), 76174, CASH_URL)
        self.assertEqual((r["category"], r["prize_pool"], r["open_to_vic"]), ("Win Cash", 1000.0, True))

    def test_states_without_victoria_are_flagged(self):
        html = page("comp_76174.html").replace("NSW, VIC, QLD, SA, WA, TAS, NT, ACT", "NSW, QLD")
        self.assertFalse(comps.parse(html, 76174, CASH_URL)["open_to_vic"])


class Platform(unittest.TestCase):
    def test_entry_platform_comes_from_the_entry_host(self):
        self.assertEqual(comps.platform("https://www.facebook.com/ReviewBrisbane/posts/x"), "facebook")
        self.assertEqual(comps.platform("https://m.facebook.com/x"), "facebook")
        self.assertEqual(comps.platform("https://www.instagram.com/p/x/"), "instagram")
        self.assertEqual(comps.platform("https://notfacebook.com/x"), "web")
        self.assertEqual(comps.platform("https://www.yarn.com.au/pages/win"), "web")
        self.assertIsNone(comps.platform(None))


class Store(unittest.TestCase):
    def test_run_adds_only_new_listings_and_keeps_the_first_fetch(self):
        pages = {comps.SITEMAP: page("comps_sitemap.xml"), RAFFLE_URL: page("comp_76171.html"),
                 CASH_URL: page("comp_76174.html")}

        def fetch(url):
            if url not in pages:
                raise ValueError("not saved")      # 76170 fails: skipped, retried next run
            return pages[url]

        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            self.assertEqual(comps.run(store, fetch=fetch, delay=0), 2)
            self.assertEqual(comps.run(store, fetch=fetch, delay=0), 0)
            lines = [json.loads(l) for l in (store / "comps.jsonl").read_text().splitlines()]
            self.assertEqual(sorted(l["comp"]["id"] for l in lines), [76171, 76174])
            rows = (store / "comps.csv").read_text().splitlines()
            self.assertTrue(rows[0].startswith("id,title,category,brand,prize_pool,states,open_to_vic"))
            self.assertNotIn("description", rows[0])
            self.assertIn("entry_platform", rows[0])
            self.assertEqual(comps.run(store, max_new=0, fetch=fetch, delay=0), 0)



class AusComps(unittest.TestCase):
    def test_page_becomes_a_register_record(self):
        from workers import comp_odds, source_auscomps
        r = source_auscomps.parse(page("auscomps_page.html"), "https://auscomps.au/competition/x/")
        self.assertEqual((r["id"], r["prize_pool"], r["open_to_vic"]), (10_007_590, 500.0, True))
        self.assertEqual((r["closes"][:10], r["entry_url"], r["brand"]), ("2026-12-09", "https://wn.nr/HCX5mHn", "Charlesworth Nuts"))
        a = comp_odds.assess(r)
        self.assertEqual((a["purchase"], a["entry_limit"], a["entry_route"]), ("no", "once", "agent_ok"))

    def test_duplicates_of_stored_listings_are_skipped(self):
        from workers import source_auscomps
        r = {"title": "Win the Grand Majestic Gift Hamper valued at $500 from Charlesworth Nuts",
             "entry_url": "https://wn.nr/HCX5mHn", "closes": "2026-12-09T23:59:59+11:00"}
        same_url = [{"title": "Something else", "entry_url": "https://wn.nr/hcx5mhn/", "closes": None}]
        same_title = [{"title": "Win a Grand Majestic Gift Hamper from Charlesworth Nuts", "entry_url": "https://x.example/",
                       "closes": "2026-12-08T23:59:59+10:00"}]
        other = [{"title": "Win a car", "entry_url": "https://y.example/", "closes": "2026-12-09T00:00:00+10:00"}]
        self.assertTrue(source_auscomps.duplicate(r, same_url))
        self.assertTrue(source_auscomps.duplicate(r, same_title))
        self.assertFalse(source_auscomps.duplicate(r, other))


if __name__ == "__main__":
    unittest.main()
