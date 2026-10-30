"""Offline tests for the lotto analysis."""
import unittest

from analysis import lotto_games


class Odds(unittest.TestCase):
    def test_division_one_odds_match_the_published_figures(self):
        published = {"TattsLotto": 8_145_060, "OzLotto": 62_891_499, "Powerball": 134_490_400,
                     "SetForLife744": 38_320_568}
        for product, n in published.items():
            self.assertAlmostEqual(1 / lotto_games.odds(product)[1], n, delta=1)

    def test_divisions_are_disjoint_and_shares_sum_to_one(self):
        for product, g in lotto_games.GAMES.items():
            self.assertLess(sum(lotto_games.odds(product).values()), 1)
            self.assertAlmostEqual(sum(g["share"].values()), 1.0)
            self.assertEqual(set(g["share"]), set(g["divisions"]))

    def test_saturday_lotto_division_six_is_one_in_144(self):
        self.assertAlmostEqual(1 / lotto_games.odds("TattsLotto")[6], 144, delta=1)


if __name__ == "__main__":
    unittest.main()
