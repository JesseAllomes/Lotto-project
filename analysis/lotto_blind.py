"""Blind test of pattern-based number picks against real, held-out draws.

    python3 -m analysis.lotto_blind --prereg   # write data/analysis/BLIND_PREREG.md (commit it before scoring)
    python3 -m analysis.lotto_blind --score    # score the held-out draws; writes data/analysis/BLIND.md

Methods (each ranks every number using only draws before the one being predicted):
  hot_50, hot_200, hot_all  most drawn in the last 50 / 200 / all earlier draws
  cold_all                  least drawn in all earlier draws
  overdue                   longest since last drawn
  repeat_last               last draw's numbers first, then hot_50
  pairs                     most often drawn together with the last draw's numbers
  momentum                  last 50 draws' frequency above its long-run rate
  least_picked              least popular with players (payout reference; fitted on the development draws only)
Two entries per method per draw:
  games_24   24 standard games, each a seeded random selection from the method's top numbers (12 for 6-number
             games, 14 for 7-number games). Score: winning main numbers matched, summed over the 24 games.
  system_24  one System 24: the method's top 24 numbers. Score: winning main numbers inside the 24.
Under fair draws the expected score and its exact variance follow from the hypergeometric distribution, so no
random baseline is needed: z = (observed - expected) / sd over the blind draws, two-sided p, Bonferroni across
every game x method x entry. Blind draws are the last 25% of each game; the rest are development draws.
"""
import argparse
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

from analysis import lotto_games, lotto_numbers

ROOT = Path(__file__).resolve().parent.parent
DRAWS = ROOT / "data" / "draws"
OUT = ROOT / "data" / "analysis"
PREREG = OUT / "BLIND_PREREG.md"
HOLDOUT = 0.25
ALPHA = 0.05
# (label, products in date order, pool, main numbers drawn, numbers per game, first draw used per product)
GAMES = [
    ("Saturday Lotto", ["TattsLotto"], 45, 6, 6, {"TattsLotto": 0}),
    ("Weekday Lotto", ["MonWedLotto", "MondayWednesdayFridayLotto"], 45, 6, 6, {}),
    ("Set for Life", ["SetForLife744"], 44, 7, 7, {}),
    ("Oz Lotto", ["OzLotto"], 47, 7, 7, {"OzLotto": 1474}),
    ("Powerball", ["Powerball"], 35, 7, 7, {"Powerball": 1144}),
]
METHODS = ["hot_50", "hot_200", "hot_all", "cold_all", "overdue", "repeat_last", "pairs", "momentum", "least_picked"]
ENTRIES = ["games_24", "system_24"]


def script_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def load_game(products, pool, main, since, store=DRAWS):
    rows = []
    for p in products:
        for l in (store / f"{p}.jsonl").read_text().splitlines():
            if not l.strip():
                continue
            d = json.loads(l)["draw"]
            nums = d.get("PrimaryNumbers") or []
            if d["DrawNumber"] >= since.get(p, 0) and len(nums) == main and max(nums) <= pool:
                rows.append((d["DrawDate"][:10], p, d["DrawNumber"], sorted(nums)))
    rows.sort()
    return rows


def ranking(method, history, pool, beta=None):
    """Numbers 1..pool ordered best first by the method, from earlier draws only. Ties go to the lower number."""
    n = np.zeros(pool + 1)
    if method in ("hot_50", "hot_200", "hot_all", "cold_all"):
        window = {"hot_50": 50, "hot_200": 200}.get(method)
        for nums in (history[-window:] if window else history):
            for x in nums:
                n[x] += 1
        if method == "cold_all":
            n = -n
    elif method == "momentum":
        allf, last = np.zeros(pool + 1), np.zeros(pool + 1)
        for nums in history:
            for x in nums:
                allf[x] += 1
        for nums in history[-50:]:
            for x in nums:
                last[x] += 1
        n = last / max(min(50, len(history)), 1) - allf / max(len(history), 1)
    elif method == "overdue":
        for i, nums in enumerate(history):
            for x in nums:
                n[x] = i + 1
        n = -n
    elif method == "repeat_last":
        for nums in history[-50:]:
            for x in nums:
                n[x] += 1
        for x in (history[-1] if history else []):
            n[x] += 1000
    elif method == "pairs":
        last = set(history[-1]) if history else set()
        for nums in history[:-1]:
            hit = len(last & set(nums))
            if hit:
                for x in nums:
                    n[x] += hit
        for x in last:
            n[x] -= 0.5                     # prefer partners of the last draw over its own numbers
    elif method == "least_picked":
        n[1:] = -beta[:pool]
    return sorted(range(1, pool + 1), key=lambda x: (-n[x], x))


def games_24(order, pick, draw_no):
    top = order[:12 if pick == 6 else 14]
    rng = random.Random(draw_no)
    return [rng.sample(top, pick) for _ in range(24)]


def score_games(lines, drawn, pool, main):
    """(observed matches, expected, variance) for fixed lines against a fair draw of `main` from `pool`."""
    c = np.zeros(pool + 1)
    for line in lines:
        for x in line:
            c[x] += 1
    p = main / pool
    cov = main * (main - 1) / (pool * (pool - 1)) - p * p
    s1, s2 = c.sum(), (c * c).sum()
    var = s2 * p * (1 - p) + (s1 * s1 - s2) * cov
    obs = sum(len(set(line) & drawn) for line in lines)
    return obs, s1 * p, var


def score_system(numbers, drawn, pool, main):
    k = len(numbers)
    mean = main * k / pool
    var = main * (k / pool) * (1 - k / pool) * (pool - main) / (pool - 1)
    return len(set(numbers) & drawn), mean, var


def split(rows):
    cut = int(len(rows) * (1 - HOLDOUT))
    return cut, rows[:cut], rows[cut:]


def popularity_beta(products, rows_dev, pool):
    """Least-picked reference: player popularity fitted on development draws of the game's current format."""
    product = products[-1]
    if product not in lotto_numbers.GAMES:
        return np.zeros(pool)
    dev_numbers = {(p, n) for _, p, n, _ in rows_dev}
    draws = [d for d in lotto_numbers.load(product) if (product, d["DrawNumber"]) in dev_numbers]
    if len(draws) < 30:
        return np.zeros(pool)
    beta, *_ = lotto_numbers.fit(product, draws, lotto_numbers.observations(product, draws))
    return beta


def evaluate(rows, start, pool, main, pick, beta):
    """{(method, entry): (obs, exp, var, draws)} over rows[start:], predicting each from all earlier rows."""
    history = [r[3] for r in rows]
    out = {(m, e): [0.0, 0.0, 0.0, 0] for m in METHODS for e in ENTRIES}
    for t in range(max(start, 30), len(rows)):
        drawn = set(history[t])
        for m in METHODS:
            order = ranking(m, history[:t], pool, beta)
            for e, (o, x, v) in (("games_24", score_games(games_24(order, pick, rows[t][2]), drawn, pool, main)),
                                 ("system_24", score_system(order[:24], drawn, pool, main))):
                acc = out[(m, e)]
                acc[0] += o
                acc[1] += x
                acc[2] += v
                acc[3] += 1
    return out


def z_p(obs, exp, var):
    z = (obs - exp) / math.sqrt(var) if var > 0 else 0.0
    return z, math.erfc(abs(z) / math.sqrt(2))


def prereg(path=PREREG):
    lines = ["# Blind lotto test: pre-registration", "",
             f"Script: `analysis/lotto_blind.py`, sha256 prefix `{script_hash()}`. Scoring refuses to run if the "
             "script changes after this file is committed.", "",
             f"Blind draws: the last {HOLDOUT:.0%} of each game's draws, in date order. Methods, entries and metric "
             "are as documented in the script. Verdict: a method beats chance only if its blind-draw p-value is "
             f"below {ALPHA} after Bonferroni correction across all {len(GAMES) * len(METHODS) * len(ENTRIES)} "
             "tests, in the direction of more matches.", "",
             "| Game | Draws | Development draws | Blind draws (from) |", "|---|---|---|---|"]
    for label, products, pool, main, pick, since in GAMES:
        rows = load_game(products, pool, main, since)
        cut, dev, blind = split(rows)
        lines.append(f"| {label} | {len(rows)} | {len(dev)} | {len(blind)} ({blind[0][0]}) |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def score(out=OUT):
    reg = PREREG.read_text() if PREREG.exists() else ""
    if f"`{script_hash()}`" not in reg:
        raise SystemExit("pre-registration missing or the script changed since it was written: no scoring")
    tests = len(GAMES) * len(METHODS) * len(ENTRIES)
    md = ["# Blind lotto test: results", "",
          "Each method picked numbers using only earlier draws, and was scored only on blind draws it never saw "
          f"(see BLIND_PREREG.md). Bonferroni threshold: p < {ALPHA / tests:.5f} ({tests} tests). "
          "*Edge* = matches above (or below) the exact random expectation, as a percentage.", "",
          "| Game | Method | Entry | Blind draws | Matches | Expected | Edge | z | p | Beats chance |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    picks = ["", "## Current picks (for the next draw, by method)", ""]
    winners = []
    for label, products, pool, main, pick, since in GAMES:
        rows = load_game(products, pool, main, since)
        cut, dev, blind = split(rows)
        beta = popularity_beta(products, dev, pool)
        res = evaluate(rows, cut, pool, main, pick, beta)
        for (m, e), (o, x, v, n) in res.items():
            z, p = z_p(o, x, v)
            win = z > 0 and p < ALPHA / tests
            winners += [(label, m, e)] if win else []
            md.append(f"| {label} | {m} | {e} | {n} | {o:.0f} | {x:.1f} | {(o - x) / x:+.1%} | {z:+.2f} | {p:.3f} | "
                      f"{'yes' if win else 'no'} |")
        history = [r[3] for r in rows]
        for m in ("hot_all", "hot_50", "overdue", "least_picked"):
            order = ranking(m, history, pool, beta)
            picks.append(f"- {label}, {m}: System 24 = {' '.join(map(str, sorted(order[:24])))}")
    verdict = ("No method beat chance on the blind draws." if not winners else
               "Beat chance on the blind draws: " + "; ".join(f"{a} {b} {c}" for a, b, c in winners) + ".")
    md[2:2] = [f"**Verdict: {verdict}**", ""]
    (out / "BLIND.md").write_text("\n".join(md + picks) + "\n")
    print(verdict, flush=True)
    return winners


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prereg", action="store_true")
    g.add_argument("--score", action="store_true")
    a = ap.parse_args(argv)
    if a.prereg:
        print(f"wrote {prereg()}")
    else:
        score()


if __name__ == "__main__":
    sys.exit(main())
