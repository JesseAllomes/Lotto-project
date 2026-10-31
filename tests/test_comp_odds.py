"""Offline tests for the competition odds variables and the skill list."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from workers import comp_odds, comps

FIX = Path(__file__).resolve().parent / "fixtures"


def desc(enter, select, prize=""):
    return (f"**What are the prizes?**  \r\n{prize}\r\n**How do I enter the competition?**  \r\n{enter}\r\n"
            f"**How is the winner selected?**  \r\n{select}\r\n**When does the competition close?**  \r\nSoon.")


def rec(i, title, d, brand="Promoter", closes="2026-12-01T23:59:59+10:00", vic=True):
    return {"id": i, "title": title, "brand": brand, "prize_pool": 100.0, "closes": closes, "open_to_vic": vic,
            "entry_url": "https://www.facebook.com/p/1", "url": f"https://www.competitions.com.au/x/{i}/",
            "description": d}


SKILL = desc('Answer, in 25 words or less, "Why do you love camping?" Limited to one entry per person.',
             "Entries are judged on creativity and literary merit. This is a game of skill and chance plays no part.")
CHANCE = desc("Like our page and comment. Additional entries can be earned by referring a friend.",
              "The winner will be randomly drawn on 2 December.", prize="There are 5 prizes of $20 vouchers.")


class Classify(unittest.TestCase):
    def test_sections_split_on_the_question_headings(self):
        s = comp_odds.sections(SKILL)
        self.assertIn("25 words or less", s["enter"])
        self.assertIn("judged", s["select"])

    def test_skill_competition(self):
        a = comp_odds.assess(rec(1, "Win a Tent", SKILL))
        self.assertEqual((a["draw_type"], a["entry_limit"], a["task"]), ("skill", "once", "25 words or less"))
        self.assertEqual(a["question"], "Why do you love camping?")

    def test_chance_competition_with_bonus_entries(self):
        a = comp_odds.assess(rec(2, "Win a Voucher", CHANCE))
        self.assertEqual((a["draw_type"], a["purchase"], a["bonus"], a["prizes"]), ("chance", "no", "yes", 5))
        self.assertEqual(a["entry_platform"], "facebook")

    def test_entry_route(self):
        route = lambda t, platform="web", buy="no": comp_odds.entry_route({"enter": t}, t, platform, buy)
        self.assertEqual(route("Complete the online entry form."), "agent_ok")
        self.assertEqual(route("Buy tickets online via the website.", buy="yes"), "agent_assist")
        self.assertEqual(route("Scan your receipt in store."), "manual")
        self.assertEqual(route("Complete the form.", platform="facebook"), "manual")
        self.assertEqual(route("Comment on the post and tag a friend."), "manual")
        self.assertEqual(route(""), "unknown")
        self.assertEqual(route("Complete the online form with your name, email and phone number."), "agent_ok")
        self.assertEqual(route("Complete the online form. Follow us on Instagram for a bonus entry."), "agent_ok")
        self.assertEqual(route("Call us on 13 13 13 to enter."), "manual")
        self.assertEqual(route("Enter by phone during the show."), "manual")

    def test_automation_ban_wording(self):
        ban = lambda t: bool(comp_odds.re.search(comp_odds.BANNED, t))
        self.assertTrue(ban("Entries made using automated software, scripts or bots are invalid."))
        self.assertTrue(ban("Entries submitted through third-party competition services will be disqualified."))
        self.assertFalse(ban("You will automatically be entered into the draw."))

    def test_entry_limits(self):
        lim = lambda t: comp_odds.entry_limit({"enter": t}, "")
        self.assertEqual(lim("You may enter once per day."), ("daily", None))
        self.assertEqual(lim("Maximum of 3 entries per person."), ("capped", 3))
        self.assertEqual(lim("One entry for every eligible purchase over $20."), ("per_purchase", None))
        self.assertEqual(lim("Multiple entries are allowed."), ("unlimited", None))
        self.assertEqual(lim("Fill in the form."), ("unknown", None))

    def test_raffle_brand_means_purchase_and_title_gives_prize_count(self):
        a = comp_odds.assess(rec(3, "Win 1 of 12 Cars", desc("Buy a ticket.", "Drawn at random."),
                                 brand="Mater Home Lottery"))
        self.assertEqual((a["purchase"], a["prizes"], a["draw_type"]), ("yes", 12, "chance"))

    def test_saved_listing_is_a_chance_raffle(self):
        r = comps.parse((FIX / "comp_76171.html").read_text(), 76171, "u")
        a = comp_odds.assess(r)
        self.assertEqual((a["draw_type"], a["purchase"]), ("chance", "yes"))


class Tags(unittest.TestCase):
    def test_crawl_walks_pages_until_nothing_new_and_never_repeats_a_tag(self):
        card = lambda *ids: "".join(f'<a data-comp-id="{i}">' for i in ids)
        pages = {comp_odds.TYPE_PAGE.format("daily-entry", 1): card(1, 2),
                 comp_odds.TYPE_PAGE.format("daily-entry", 2): card(3),
                 comp_odds.TYPE_PAGE.format("daily-entry", 3): card(3)}
        fetch = lambda url: pages.get(url, "")
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            self.assertEqual(comp_odds.crawl_tags(store, fetch=fetch, delay=0), 3)
            self.assertEqual(comp_odds.crawl_tags(store, fetch=fetch, delay=0), 0)
            self.assertEqual(comp_odds.tags(store), {1: ["daily-entry"], 2: ["daily-entry"], 3: ["daily-entry"]})


class Files(unittest.TestCase):
    def test_skill_list_holds_open_victorian_skill_competitions_only(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            recs = [rec(1, "Win a Tent", SKILL), rec(2, "Win a Voucher", CHANCE),
                    rec(3, "Closed", SKILL, closes="2026-01-01T00:00:00+10:00"), rec(4, "WA only", SKILL, vic=False)]
            comps.append(store, recs, "t")
            (store / "terms.jsonl").write_text(json.dumps({"id": 2, "cap": 5000, "source": "terms-url"}) + "\n")
            (store / "tags.jsonl").write_text(json.dumps({"id": 2, "entry_type": "daily-entry"}) + "\n")
            rows = comp_odds.run(store, today=dt.date(2026, 10, 30))
            self.assertEqual({r["id"]: r["cap"] for r in rows}[2], 5000)
            skill = (store / "skill.csv").read_text().splitlines()
            self.assertEqual([l.split(",")[0] for l in skill[1:]], ["1"])
            odds = (store / "odds.csv").read_text()
            self.assertIn("daily-entry", odds)


if __name__ == "__main__":
    unittest.main()


class BanWording(unittest.TestCase):
    def test_who_may_enter_is_not_an_automation_ban(self):
        import re
        from workers import comp_odds as c
        ban = lambda t: bool(re.search(c.BANNED, t))
        self.assertFalse(ban("Employees of the Promoter and its related bodies, agencies and agents are ineligible to enter."))
        self.assertTrue(ban("Entries made using automated entry software are invalid."))
        self.assertTrue(ban("Entries made by third party entry services will be deemed invalid."))
        self.assertTrue(ban("Entries lodged by agents are not accepted."))

