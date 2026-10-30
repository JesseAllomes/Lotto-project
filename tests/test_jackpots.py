"""Offline tests for the Lucky Lotteries jackpot tracker (no network)."""
import json
import tempfile
import unittest
from pathlib import Path

from workers import draws, jackpots


def draw(n, amount, winners=0, product="LuckyLotteries5"):
    return {"ProductId": product, "DrawNumber": n, "DrawDate": f"2019-08-{n % 28 + 1:02d}T00:00:00",
            "PrimaryNumbers": [1], "SecondaryNumbers": [2, 3, 4],
            "Dividends": [{"Division": 1, "BlocDividend": 200000.0, "BlocNumberOfWinners": 1},
                          {"Division": 11, "BlocDividend": amount, "BlocNumberOfWinners": winners}]}


class Jackpot(unittest.TestCase):
    def test_jackpot_is_division_eleven(self):
        self.assertEqual(jackpots.jackpot(draw(1447, 96_040_000.0, 1)), (96_040_000.0, 1))
        r = jackpots.row(draw(1447, 96_040_000.0, 1))
        self.assertEqual((r["game"], r["jackpot_winners"], r["pct_of_break_even"]), ("Mega Jackpot", 1, 274.4))

    def test_cycle_restarts_after_a_win(self):
        recs = [draw(10, 5e6), draw(11, 5.24e6, 1), draw(12, 1e6), draw(13, 1.24e6), draw(14, 1.48e6)]
        self.assertEqual(jackpots.cycle(recs), (12, 3, 240000.0))


class Alerts(unittest.TestCase):
    def test_no_alert_below_the_alert_level(self):
        s = jackpots.assess("LuckyLotteries5", [draw(1, 1e6)], (2, 29_999_999.0))
        self.assertEqual(s["alerts"], [])

    def test_alert_and_break_even_have_stable_keys_per_cycle(self):
        recs = [draw(5, 9e6, 1), draw(6, 1e6)]
        s = jackpots.assess("LuckyLotteries2", recs, (7, 27_500_000.0))
        keys = [a["key"] for a in s["alerts"]]
        self.assertEqual(keys, ["Super Jackpot cycle 6 alert level", "Super Jackpot cycle 6 break-even"])
        later = jackpots.assess("LuckyLotteries2", recs + [draw(7, 27_500_000.0, product="LuckyLotteries2")],
                                (8, 27_630_000.0))
        self.assertEqual([a["key"] for a in later["alerts"]], keys)   # same cycle, same issues, no duplicates
        self.assertTrue(all(a["key"] in a["title"] for a in s["alerts"]))


class Store(unittest.TestCase):
    def test_open_jackpot_log_appends_only_changes(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            self.assertTrue(jackpots.record_open(store, "LuckyLotteries5", 1791, 1960004.0, "t1"))
            self.assertFalse(jackpots.record_open(store, "LuckyLotteries5", 1791, 1960004.0, "t2"))
            self.assertTrue(jackpots.record_open(store, "LuckyLotteries5", 1791, 2200004.0, "t3"))
            lines = [json.loads(l) for l in (store / "open.jsonl").read_text().splitlines()]
            self.assertEqual([l["fetched_utc"] for l in lines], ["t1", "t3"])

    def test_csv_and_status_are_written(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            draws.append(store, "LuckyLotteries5", [draw(2, 1.24e6), draw(1, 1e6)], fetched="t", source="test")
            self.assertEqual(jackpots.write_csv(store, "LuckyLotteries5"), 2)
            rows = (store / "LuckyLotteries5.csv").read_text().splitlines()
            self.assertEqual([r.split(",")[2] for r in rows[1:]], ["1", "2"])
            s = jackpots.assess("LuckyLotteries5", jackpots.history(store, "LuckyLotteries5"), (3, 1.48e6))
            md = jackpots.status_md([s], "t")
            self.assertIn("| Mega Jackpot | 3 | $1,480,000 | $30,000,000 | $35,000,000 | 4% | 2 | $240,000 | 140 |", md)


if __name__ == "__main__":
    unittest.main()
