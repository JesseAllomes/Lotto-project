"""The Lott draw games: number pools, prize divisions and their odds, and each division's share of the prize fund.

Division rules and fund shares are from the Tattersall's Rules of Authorised Lotteries (work/data/tatts_rules_azure.txt,
Schedules A, C, D, E, H). Every division except a fixed or guaranteed Division One is pari-mutuel: its share of
the prize fund is split among its winners, so how many other people hold the drawn numbers sets the payout.

Odds are exact: a standard entry picks `pick` numbers; `main` winning and `supp` supplementary numbers are drawn
from the same pool of `pool` (Powerball draws its Powerball from a separate pool of `pb_pool`). `since` is the first
draw number of the current format (Oz Lotto went to 47 numbers and 3 supplementaries at draw 1474, May 2022;
Powerball to 7 from 35 at draw 1144, April 2018; the lotto games to six divisions in 2011-12); older draws follow
other rules and are left out of the analysis.
"""
from math import comb

# Division rule: (main numbers matched, supplementary rule, powerball rule). Supplementary rule: None (any),
# 0 (none), ">=1", "1", "2". Powerball rule: None (not a Powerball game), True (must match), False (must not).
GAMES = {
    "TattsLotto": {
        "name": "Saturday Lotto", "pool": 45, "pick": 6, "main": 6, "supp": 2, "since": 3081,
        "divisions": {1: (6, None, None), 2: (5, ">=1", None), 3: (5, 0, None), 4: (4, None, None),
                      5: (3, ">=1", None), 6: ((1, 2), "2", None)},
        "share": {1: 0.3275, 2: 0.037, 3: 0.056, 4: 0.083, 5: 0.1225, 6: 0.374},
    },
    "MondayWednesdayFridayLotto": {
        "name": "Mon/Wed/Fri Lotto", "pool": 45, "pick": 6, "main": 6, "supp": 2, "since": 4392,
        "divisions": {1: (6, None, None), 2: (5, ">=1", None), 3: (5, 0, None), 4: (4, None, None),
                      5: (3, ">=1", None), 6: ((1, 2), "2", None)},
        "share": {1: 0.0, 2: 0.042, 3: 0.065, 4: 0.185, 5: 0.263, 6: 0.445},
    },
    "MonWedLotto": {
        "name": "Mon/Wed Lotto", "pool": 45, "pick": 6, "main": 6, "supp": 2, "since": 3116,
        "divisions": {1: (6, None, None), 2: (5, ">=1", None), 3: (5, 0, None), 4: (4, None, None),
                      5: (3, ">=1", None), 6: ((1, 2), "2", None)},
        "share": {1: 0.0, 2: 0.042, 3: 0.065, 4: 0.185, 5: 0.263, 6: 0.445},
    },
    "OzLotto": {
        "name": "Oz Lotto", "pool": 47, "pick": 7, "main": 7, "supp": 3, "since": 1474,
        "divisions": {1: (7, None, None), 2: (6, ">=1", None), 3: (6, 0, None), 4: (5, ">=1", None),
                      5: (5, 0, None), 6: (4, None, None), 7: (3, ">=1", None)},
        "share": {1: 0.40, 2: 0.022, 3: 0.026, 4: 0.02, 5: 0.016, 6: 0.198, 7: 0.318},
    },
    "Powerball": {
        "name": "Powerball", "pool": 35, "pick": 7, "main": 7, "supp": 0, "pb_pool": 20, "since": 1144,
        "divisions": {1: (7, None, True), 2: (7, None, False), 3: (6, None, True), 4: (6, None, False),
                      5: (5, None, True), 6: (4, None, True), 7: (5, None, False), 8: (3, None, True),
                      9: (2, None, True)},
        "share": {1: 0.35, 2: 0.018, 3: 0.011, 4: 0.02, 5: 0.015, 6: 0.097, 7: 0.076, 8: 0.15, 9: 0.263},
    },
    "SetForLife744": {
        "name": "Set for Life", "pool": 44, "pick": 7, "main": 7, "supp": 2, "since": 1691,
        "divisions": {1: (7, None, None), 2: (6, "1", None), 3: (6, 0, None), 4: (5, ">=1", None),
                      5: (5, 0, None), 6: (4, ">=1", None), 7: (4, 0, None), 8: (3, ">=1", None)},
        "share": {1: 0.0, 2: 0.0, 3: 0.022, 4: 0.02, 5: 0.046, 6: 0.106, 7: 0.282, 8: 0.524},
    },
}


def _supp_ok(rule, j):
    return rule is None or (rule == 0 and j == 0) or (rule == ">=1" and j >= 1) or (rule == "1" and j == 1) \
        or (rule == "2" and j == 2)


def odds(product):
    """{division: probability} for one standard entry."""
    g = GAMES[product]
    n, k, s, pick = g["pool"], g["main"], g["supp"], g["pick"]
    total = comb(n, pick)
    out = {}
    for d, (m, srule, pb) in g["divisions"].items():
        mains = m if isinstance(m, tuple) else (m,)
        p = 0.0
        for mm in mains:
            for j in range(0, s + 1):
                if not _supp_ok(srule, j):
                    continue
                rest = pick - mm - j
                if rest < 0:
                    continue
                p += comb(k, mm) * comb(s, j) * comb(n - k - s, rest) / total
        if pb is not None:
            p *= (1 / g["pb_pool"]) if pb else (1 - 1 / g["pb_pool"])
        out[d] = p
    return out
