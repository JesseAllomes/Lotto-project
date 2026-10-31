"""Offline tests for the relative chance-of-winning estimate."""
import datetime as dt
import unittest

from workers import chance

FORM = "**How do I enter the competition?** Complete the online entry form. **How is the winner selected?** Random draw."
TODAY = dt.date(2026, 10, 31)


def rec(title, prize, desc=FORM, closes="2026-11-30T23:59:59+10:00"):
    return {"id": 1, "title": title, "brand": "Shop", "prize_pool": prize, "closes": closes, "open_to_vic": True,
            "entry_url": "https://shop.example/1", "url": "u1", "description": desc}


class Chance(unittest.TestCase):
    def test_more_prizes_and_smaller_prizes_rank_higher(self):
        many = chance.estimate(rec("Win 1 of 20 $100 Visa Cards", 2000), today=TODAY)
        one = chance.estimate(rec("Win a $2,000 Visa Card", 2000), today=TODAY)
        huge = chance.estimate(rec("Win $100,000 Cash", 100000), today=TODAY)
        self.assertEqual((many[2], one[2]), (20, 1))
        self.assertGreater(many[0], one[0])
        self.assertGreater(one[0], huge[0])

    def test_prize_amounts_are_not_prize_counts(self):
        self.assertEqual(chance.winners({"title": "Win up to $2K of Gear"}, prizes=2000), 1)
        self.assertEqual(chance.winners({"title": "Win 5 x $100 vouchers"}), 5)
        self.assertEqual(chance.winners({"title": "Switch – Win 1/5 of La Bola Negra DPs"}), 5)

    def test_bands_by_fifths(self):
        b = chance.bands({i: i for i in range(10)})
        self.assertEqual([b[i] for i in (9, 8, 7, 4, 3, 0)], ["high", "high", "medium", "medium", "low", "low"])


if __name__ == "__main__":
    unittest.main()
