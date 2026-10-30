"""Offline tests for the lotto analysis."""
import unittest
from pathlib import Path

import math
import random

import numpy as np

from analysis import lotto_blind, lotto_games, lotto_numbers


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



class Blind(unittest.TestCase):
    def test_exact_expectation_and_variance_match_simulation(self):
        rng = random.Random(3)
        lines = [rng.sample(range(1, 13), 6) for _ in range(24)]
        sims = [lotto_blind.score_games(lines, set(rng.sample(range(1, 46), 6)), 45, 6)[0] for _ in range(20000)]
        _, mean, var = lotto_blind.score_games(lines, set(), 45, 6)
        self.assertAlmostEqual(np.mean(sims), mean, delta=4 * math.sqrt(var / len(sims)))
        self.assertAlmostEqual(np.var(sims), var, delta=var * 0.05)
        sims = [lotto_blind.score_system(list(range(1, 25)), set(rng.sample(range(1, 46), 6)), 45, 6)[0]
                for _ in range(20000)]
        _, mean, var = lotto_blind.score_system(list(range(1, 25)), set(), 45, 6)
        self.assertAlmostEqual(np.mean(sims), mean, delta=4 * math.sqrt(var / len(sims)))
        self.assertAlmostEqual(np.var(sims), var, delta=var * 0.05)

    def test_rankings_use_only_the_history_given(self):
        history = [[1, 2, 3, 4, 5, 6], [1, 2, 3, 7, 8, 9], [1, 10, 11, 12, 13, 14]]
        self.assertEqual(lotto_blind.ranking("hot_all", history, 45)[:3], [1, 2, 3])
        self.assertEqual(lotto_blind.ranking("cold_all", history, 45)[0], 15)
        self.assertEqual(lotto_blind.ranking("overdue", history, 45)[0], 15)
        self.assertEqual(set(lotto_blind.ranking("repeat_last", history, 45)[:6]), {1, 10, 11, 12, 13, 14})
        for m in lotto_blind.METHODS:
            order = lotto_blind.ranking(m, history, 45, np.zeros(45))
            self.assertEqual(sorted(order), list(range(1, 46)))

    def test_scoring_refuses_without_a_matching_preregistration(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            old = lotto_blind.PREREG
            try:
                lotto_blind.PREREG = Path(d) / "none.md"
                with self.assertRaises(SystemExit):
                    lotto_blind.score(Path(d))
            finally:
                lotto_blind.PREREG = old


if __name__ == "__main__":
    unittest.main()
