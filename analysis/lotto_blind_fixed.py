"""Blind test, second variant: one fixed number set played on every held-out draw.

    python3 -m analysis.lotto_blind_fixed --prereg   # write data/analysis/BLIND_FIXED_PREREG.md (commit before scoring)
    python3 -m analysis.lotto_blind_fixed --score    # writes data/analysis/BLIND_FIXED.md

Same games, split and scoring as analysis/lotto_blind.py, but each set is chosen once, from the development draws
only, and then played unchanged on every blind draw:
  fixed_hot           most drawn over the development draws
  fixed_cold          least drawn over the development draws
  fixed_least_picked  least popular with players over the development draws (current-format games only)
  fixed_dev_best      the System 24 that matched the most winning numbers over the development draws
                      (this is fixed_hot by construction for a System entry; kept separate for the 24 games, where
                      it is the 24 games, from the hot top numbers, that scored best over the development draws)
Entries: games_24 (24 fixed games from the set's top numbers, seed 0) and system_24 (the set's top 24 numbers).
A set picked by looking at all draws, blind ones included, would look good in hindsight; this avoids that.
"""
import argparse
import hashlib
import random
import sys
from pathlib import Path

import numpy as np

from analysis import lotto_blind as lb

OUT = lb.OUT
PREREG = OUT / "BLIND_FIXED_PREREG.md"
METHODS = ["fixed_hot", "fixed_cold", "fixed_least_picked", "fixed_dev_best"]
CANDIDATES = 200          # fixed_dev_best: seeded 24-game sets tried on the development draws


def script_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def choose(method, dev, pool, pick, main, beta):
    """(System 24 numbers, 24 fixed games) for one method, from development draws only."""
    history = [r[3] for r in dev]
    base = {"fixed_hot": "hot_all", "fixed_cold": "cold_all", "fixed_least_picked": "least_picked",
            "fixed_dev_best": "hot_all"}[method]
    order = lb.ranking(base, history, pool, beta)
    top = order[:12 if pick == 6 else 14]
    games = [random.Random(0).sample(top, pick) for _ in range(24)]
    if method == "fixed_dev_best":
        best, best_score = None, -1
        for seed in range(CANDIDATES):
            rng = random.Random(seed)
            cand = [rng.sample(top, pick) for _ in range(24)]
            s = sum(lb.score_games(cand, set(d), pool, main)[0] for d in history)
            if s > best_score:
                best, best_score = cand, s
        games = best
    return order[:24], games


def evaluate(rows, cut, pool, main, pick, beta):
    dev, blind = rows[:cut], rows[cut:]
    out = {}
    for m in METHODS:
        system, games = choose(m, dev, pool, pick, main, beta)
        for e in lb.ENTRIES:
            acc = [0.0, 0.0, 0.0, 0]
            for r in blind:
                drawn = set(r[3])
                o, x, v = (lb.score_games(games, drawn, pool, main) if e == "games_24"
                           else lb.score_system(system, drawn, pool, main))
                acc[0] += o
                acc[1] += x
                acc[2] += v
                acc[3] += 1
            out[(m, e)] = (*acc, system)
    return out


def prereg(path=PREREG):
    tests = len(lb.GAMES) * len(METHODS) * len(lb.ENTRIES)
    path.write_text("\n".join([
        "# Blind lotto test, fixed sets: pre-registration", "",
        f"Script: `analysis/lotto_blind_fixed.py`, sha256 prefix `{script_hash()}`; uses `analysis/lotto_blind.py` "
        f"(prefix `{lb.script_hash()}`). Scoring refuses to run if either script changes after this file is committed.",
        "", "Same games and blind draws as BLIND_PREREG.md. Each set is chosen once from the development draws and "
        f"played on every blind draw. Verdict: beats chance only if p < {lb.ALPHA} after Bonferroni across {tests} "
        "tests, in the direction of more matches.", ""]) + "\n")
    return path


def score(out=OUT):
    reg = PREREG.read_text() if PREREG.exists() else ""
    if f"`{script_hash()}`" not in reg or f"`{lb.script_hash()}`" not in reg:
        raise SystemExit("pre-registration missing or a script changed since it was written: no scoring")
    tests = len(lb.GAMES) * len(METHODS) * len(lb.ENTRIES)
    md = ["# Blind lotto test, fixed sets: results", "",
          "One set per method, chosen from the development draws only, played unchanged on every blind draw "
          f"(see BLIND_FIXED_PREREG.md). Bonferroni threshold: p < {lb.ALPHA / tests:.5f} ({tests} tests).", "",
          "| Game | Method | Entry | Blind draws | Matches | Expected | Edge | z | p | Beats chance | System 24 set |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    winners = []
    for label, products, pool, main, pick, since in lb.GAMES:
        rows = lb.load_game(products, pool, main, since)
        cut, dev, _ = lb.split(rows)
        beta = lb.popularity_beta(products, dev, pool)
        for (m, e), (o, x, v, n, system) in evaluate(rows, cut, pool, main, pick, beta).items():
            z, p = lb.z_p(o, x, v)
            win = z > 0 and p < lb.ALPHA / tests
            winners += [(label, m, e)] if win else []
            md.append(f"| {label} | {m} | {e} | {n} | {o:.0f} | {x:.1f} | {(o - x) / x:+.1%} | {z:+.2f} | {p:.3f} | "
                      f"{'yes' if win else 'no'} | {' '.join(map(str, sorted(system))) if e == 'system_24' else ''} |")
    verdict = ("No fixed set beat chance on the blind draws." if not winners else
               "Beat chance on the blind draws: " + "; ".join(f"{a} {b} {c}" for a, b, c in winners) + ".")
    md[2:2] = [f"**Verdict: {verdict}**", ""]
    (out / "BLIND_FIXED.md").write_text("\n".join(md) + "\n")
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
