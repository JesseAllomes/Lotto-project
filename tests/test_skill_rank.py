"""Offline tests for the skill-competition ranking."""
import datetime as dt
import unittest

from analysis import skill_rank

TODAY = dt.date(2026, 10, 30)


def row(**kw):
    base = {"task": "25 words or less", "prizes": "", "prize_pool": "500", "purchase": "no", "entry_limit": "once",
            "question": "", "closes": "2026-11-09T23:59:59+10:00"}
    return dict(base, **kw)


class Score(unittest.TestCase):
    def test_quick_answer_with_many_small_prizes_ranks_high(self):
        s = skill_rank.score(row(prizes="10", prize_pool="1000"), "", TODAY)
        self.assertEqual((s["effort"], s["skill"], s["chance"]), (2, 3, 5.0))
        self.assertEqual((s["overall"], s["prize_per_winner"], s["days_left"]), (8.5, 100, 10))

    def test_video_for_a_big_prize_decided_by_public_vote_ranks_low(self):
        desc = "**How is the winner selected?** Five finalists go to a public vote; most votes wins."
        s = skill_rank.score(row(task="video", prize_pool="150000"), desc, TODAY)
        self.assertEqual((s["effort"], s["skill"], s["public_vote"]), (5, 2, True))
        self.assertLess(s["chance"], 3)
        self.assertIn("public vote decides", s["why"])

    def test_purchase_and_long_word_limit_add_effort(self):
        desc = "**How do I enter?** Buy a pack and tell us in 150 words or less why you love it."
        s = skill_rank.score(row(purchase="yes"), desc, TODAY)
        self.assertEqual((s["effort"], s["word_limit"]), (4, 150))

    def test_scores_stay_in_range(self):
        for task in list(skill_rank.TASK_EFFORT) + ["unseen"]:
            for prizes in ("", "1", "200"):
                s = skill_rank.score(row(task=task, prizes=prizes, prize_pool="9000000", purchase="yes",
                                         entry_limit="unlimited"), "", TODAY)
                self.assertTrue(1 <= s["chance"] <= 5 and 1 <= s["effort"] <= 5 and 1 <= s["skill"] <= 5)
                self.assertTrue(0 <= s["overall"] <= 10)


if __name__ == "__main__":
    unittest.main()
