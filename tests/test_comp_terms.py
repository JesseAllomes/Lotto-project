"""Offline tests for ticket caps from promoters' pages and terms (saved pages, no network)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from workers import comp_terms, comps

FIX = Path(__file__).resolve().parent / "fixtures"
DH_DRAW = "https://www.dreamhomeartunion.com.au/prize-home"
DH_TERMS = "https://www.dreamhomeartunion.com.au/about/terms-and-conditions/prize-home"
YT_DRAW = "https://www.yourtownprizehomes.com.au/win-a-home/prize-draw-buderim/"


def saved(name):
    return (FIX / name).read_bytes()


class Extract(unittest.TestCase):
    def test_cap_wordings(self):
        cap = lambda t: comp_terms.find_cap(t)[0]
        self.assertEqual(cap("We are permitted to sell up to 10,763,970 tickets in Draw AU435L."), 10_763_970)
        self.assertEqual(cap("Maximum number of tickets 500,000. Tickets are numbered"), 500_000)
        self.assertEqual(cap("Limited to 500,000 tickets! Get yours today."), 500_000)
        self.assertEqual(cap("A maximum of 250,000 tickets will be sold."), 250_000)
        self.assertEqual(cap("120,000 tickets will be printed for this raffle."), 120_000)
        self.assertEqual(cap("Total tickets: 45,000"), 45_000)
        self.assertIsNone(cap("Maximum value is $4,999, purchase caps may apply."))
        self.assertIsNone(cap("Book value: $100 | Paid tickets: 100 | Bonus tickets: 100 | Total tickets: 200"))
        self.assertEqual(cap("Mater Foundation is permitted to issue up to 1,000,000 tickets in this lottery"), 1_000_000)
        self.assertEqual(cap("The number of tickets available will range from 600,000 (single-ticket purchases) to "
                             "1,350,000 (if bundle purchases occur)."), 1_350_000)

    def test_prices_from_shop_data_and_wording(self):
        raw = saved("terms_dreamhome_draw.html").decode()
        self.assertEqual(comp_terms.find_prices(raw, comp_terms.text_of(raw.encode()))[:2], [(1, 10.0), (2, 20.0)])
        self.assertEqual(comp_terms.find_prices("", "Tickets are $5 each or 3 tickets for $12"), [(1, 5.0), (3, 12.0)])

    def test_per_ticket_prices_from_the_buy_box(self):
        page = b"<p>$30 1 Ticket $30.00 per Ticket</p><p>$90 3 Tickets $30.00 per Ticket</p><p>$5 each ticket</p>"
        rec = comp_terms.look_up("https://x.org/d", fetch=lambda u: (page, "text/html", u), delay=0)
        self.assertEqual(rec["per_ticket"], [5.0, 30.0])

    def test_terms_links_prefer_the_draws_own_terms(self):
        raw = saved("terms_dreamhome_draw.html").decode()
        self.assertEqual(comp_terms.terms_links(raw, DH_DRAW)[0], DH_TERMS)


class LookUp(unittest.TestCase):
    def test_cap_on_the_draw_page(self):
        pages = {YT_DRAW: saved("terms_yourtown_draw.html")}
        rec = comp_terms.look_up(YT_DRAW, fetch=lambda u: (pages[u], "text/html", u), delay=0)
        self.assertEqual((rec["cap"], rec["source"]), (500_000, YT_DRAW))
        self.assertEqual(rec["per_ticket"], [])
        self.assertIn("tickets 500,000", rec["cap_text"])

    def test_cap_from_the_linked_terms_with_permit(self):
        pages = {DH_DRAW: saved("terms_dreamhome_draw.html"), DH_TERMS: saved("terms_dreamhome.html")}

        def fetch(u):
            if u not in pages:
                raise OSError("404")
            return pages[u], "text/html", u

        rec = comp_terms.look_up(DH_DRAW, fetch=fetch, delay=0)
        self.assertEqual((rec["cap"], rec["source"], rec["permit_vic"]), (10_763_970, DH_TERMS, "MG-R26346261/1"))
        self.assertIn([15, 50.0], rec["prices"])


class Run(unittest.TestCase):
    def test_paid_listings_get_caps_free_ones_get_one_terms_read(self):
        listing = {"id": 9, "title": "Win a Prize Home", "brand": "yourtown", "prize_pool": 2_970_000.0,
                   "closes": "2026-11-18T23:59:59+10:00", "open_to_vic": True, "entry_url": YT_DRAW, "url": "u",
                   "description": "**How do I enter the competition?** Buy a ticket. **How is the winner selected?** "
                                  "Random draw."}
        free = dict(listing, id=10, brand="Shop", entry_url="https://shop.example/win",
                    description="**How do I enter the competition?** Complete the online entry form. No purchase "
                                "necessary.")
        pages = {YT_DRAW: saved("terms_yourtown_draw.html"),
                 "https://shop.example/win": b'<a href="/terms">Terms</a> Fill in the form.',
                 "https://shop.example/terms": b"Entries made using automated software or bots are invalid."}
        fetch = lambda u: (pages[u], "text/html", u)
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            comps.append(store, [listing, free], "t")
            today = dt.date(2026, 10, 30)
            self.assertEqual(comp_terms.run(store, fetch=fetch, delay=0, today=today), 1)
            self.assertEqual(comp_terms.run(store, fetch=fetch, delay=0, today=today), 0)
            lines = [json.loads(l) for l in (store / "terms.jsonl").read_text().splitlines()]
            self.assertEqual([(l["id"], l["cap"], l["automation_banned"], l["terms_read"]) for l in lines],
                             [(10, None, True, True), (9, 500_000, False, False)])    # free (auto-entry) listings first


if __name__ == "__main__":
    unittest.main()
