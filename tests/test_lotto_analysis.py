"""Offline tests for the lotto analysis."""
import unittest

import math
import random

import numpy as np

from analysis import lotto_games, lotto_numbers


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



class Numbers(unittest.TestCase):
    def test_chi_square_tail(self):
        self.assertAlmostEqual(lotto_numbers.chi2_sf(3.841, 1), 0.05, places=3)
        self.assertAlmostEqual(lotto_numbers.chi2_sf(11.070, 5), 0.05, places=3)
        self.assertAlmostEqual(lotto_numbers.chi2_sf(61.66, 44), 0.04, delta=0.005)

    def test_prize_fund_is_recovered_from_the_shared_divisions(self):
        share = lotto_games.GAMES["TattsLotto"]["share"]
        d = {"Dividends": [{"Division": dv, "BlocNumberOfWinners": 10, "BlocDividend": 1_000_000 * share[dv] / 10}
                           for dv in range(1, 7)]}
        self.assertAlmostEqual(lotto_numbers.prize_fund(d, share), 1_000_000)

    def test_regression_recovers_planted_popularity(self):
        rng = random.Random(7)
        product = "TattsLotto"
        p = lotto_games.odds(product)
        true = np.array([0.15 if n <= 31 else -0.3 for n in range(1, 46)])
        true -= true.mean()
        draws = []
        for _ in range(400):
            nums = rng.sample(range(1, 46), 6)
            draws.append({"PrimaryNumbers": nums})
        rows = []
        for t, d in enumerate(draws):
            for dv in (3, 4):
                w = 2e7 * p[dv] * math.exp(sum(true[n - 1] for n in d["PrimaryNumbers"]))
                rows.append((t, dv, math.log(w / p[dv]), math.sqrt(w)))
        beta, *_ = lotto_numbers.fit(product, draws, rows)
        self.assertLess(np.abs(beta - true).max(), 1e-6)
        self.assertTrue(all(n > 31 for n in sorted(range(1, 46), key=lambda n: beta[n - 1])[:6]))


if __name__ == "__main__":
    unittest.main()
