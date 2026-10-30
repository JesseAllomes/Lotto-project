"""Every possible line, scored against every draw: do the lines that did best in the past keep doing best?

    python3 -m analysis.lotto_exhaustive --prereg   # data/analysis/EXHAUSTIVE_PREREG.md (commit before scoring)
    python3 -m analysis.lotto_exhaustive --score    # data/analysis/EXHAUSTIVE.md

For each game, every combination of `pick` numbers from the pool (8,145,060 lines for 6 from 45; 38 million for
Set for Life; 62.9 million for Oz Lotto; 6.7 million for Powerball) is scored on every draw: a hit is a draw in
which the line matches 3 or more of the winning main numbers (supplementaries and the Powerball are ignored).
Development draws are the first 75% of each game's draws, blind draws the last 25% (as BLIND_PREREG.md).

Tests, fixed before scoring:
  1. top_1000   the 1,000 lines with the most development hits (ties: more matched numbers, then lowest line)
                are played on the blind draws. Their blind hit rate against the exact chance rate: z and p.
  2. top_10     the ten best development lines, each scored on the blind draws (binomial p).
  3. carry_over correlation, across every line, between development hits and blind hits. If past form carries
                forward it is clearly positive; with fair draws it is about zero.
  4. luck       Saturday Lotto only: the same search over the same number of fair simulated draws, to show how
                many hits the best of 8 million lines gets by luck alone.
Verdict: a pattern exists only if test 1 is positive with p < 0.05.
"""
import argparse
import hashlib
import itertools
import math
import random
import sys
import time
from pathlib import Path

import numpy as np

from analysis import lotto_blind as lb

OUT = lb.OUT
PREREG = OUT / "EXHAUSTIVE_PREREG.md"
TOP = 1000
MIN_HIT = 3


def script_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def p_hit(pool, main, pick, k=MIN_HIT):
    """Chance that one line matches at least k of the `main` winning numbers."""
    total = math.comb(pool, pick)
    return sum(math.comb(main, m) * math.comb(pool - main, pick - m) for m in range(k, min(main, pick) + 1)) / total


def masks_of(draws):
    return np.array([sum(1 << x for x in d) for d in draws], dtype=np.uint64)


def chunks(pool, pick):
    """Line masks in blocks, one block per (first, second) number."""
    for a in range(1, pool + 1):
        for b in range(a + 1, pool + 1):
            rest = range(b + 1, pool + 1)
            if len(rest) < pick - 2:
                continue
            tails = np.array(list(itertools.combinations(rest, pick - 2)), dtype=np.uint64).reshape(-1, pick - 2)
            if not len(tails):
                continue
            m = np.left_shift(np.uint64(1), tails).sum(axis=1, dtype=np.uint64)
            yield m | np.uint64((1 << a) | (1 << b))


def hits(lines, draw_masks):
    """(hits, matched numbers) per line over the draws."""
    h = np.zeros(len(lines), dtype=np.int32)
    t = np.zeros(len(lines), dtype=np.int32)
    for d in draw_masks:
        c = np.bitwise_count(lines & d)
        h += c >= MIN_HIT
        t += c
    return h, t


def search(pool, pick, dev, blind, top=TOP, log=None):
    """Score every line; keep the top lines by development hits and the carry-over sums."""
    best_m = np.zeros(0, dtype=np.uint64)
    best_key = np.zeros(0, dtype=np.int64)
    s = np.zeros(5)                                   # n, sum x, sum y, sum x^2, sum y^2 ... and xy below
    sxy = 0.0
    n_lines = 0
    t0 = time.time()
    for i, lines in enumerate(chunks(pool, pick)):
        hd, td = hits(lines, dev)
        hb, _ = hits(lines, blind) if len(blind) else (np.zeros(len(lines), dtype=np.int32), None)
        x, y = hd.astype(np.float64), hb.astype(np.float64)
        s += [len(x), x.sum(), y.sum(), (x * x).sum(), (y * y).sum()]
        sxy += (x * y).sum()
        n_lines += len(lines)
        key = hd.astype(np.int64) * 1_000_000 + td
        cand_m = np.concatenate([best_m, lines])
        cand_k = np.concatenate([best_key, key])
        if len(cand_k) > top:
            idx = np.lexsort((cand_m, -cand_k))[:top]
            best_m, best_key = cand_m[idx], cand_k[idx]
        else:
            best_m, best_key = cand_m, cand_k
        if log and i % 200 == 0:
            log(f"  block {i}, {n_lines:,} lines, {time.time() - t0:.0f}s")
    n, sx, sy, sxx, syy = s
    corr = (n * sxy - sx * sy) / math.sqrt(max((n * sxx - sx * sx) * (n * syy - sy * sy), 1e-12))
    order = np.lexsort((best_m, -best_key))
    return best_m[order], best_key[order], corr, n_lines, sx / n


def numbers(mask):
    m = int(mask)
    return [x for x in range(1, 64) if m >> x & 1]


def binom_p_upper(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    return min(1.0, sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1)))


def prereg(path=PREREG):
    path.write_text("\n".join([
        "# Every line against every draw: pre-registration", "",
        f"Script: `analysis/lotto_exhaustive.py`, sha256 prefix `{script_hash()}`; uses `analysis/lotto_blind.py` "
        f"(prefix `{lb.script_hash()}`) for the games and the development/blind split. Scoring refuses to run if "
        "either changes after this file is committed.", "",
        f"Hit: a draw where the line matches {MIN_HIT}+ winning main numbers. Tests 1-4 and the verdict are as "
        "documented in the script; the verdict rests on test 1 (top 1,000 development lines on the blind draws).",
        ""]) + "\n")
    return path


def score(out=OUT, games=None):
    reg = PREREG.read_text() if PREREG.exists() else ""
    if f"`{script_hash()}`" not in reg or f"`{lb.script_hash()}`" not in reg:
        raise SystemExit("pre-registration missing or a script changed since it was written: no scoring")
    md = ["# Every line against every draw: results", "",
          f"Every possible line scored on every draw (hit = {MIN_HIT}+ winning main numbers). The top {TOP:,} lines "
          "by development draws were then played on the blind draws they never saw (see EXHAUSTIVE_PREREG.md).", "",
          "| Game | Lines | Dev draws | Blind draws | Chance hit rate | Top 1,000: dev hit rate | Top 1,000: blind "
          "hit rate | z | p | Carry-over r |", "|---|---|---|---|---|---|---|---|---|---|"]
    detail, verdicts = [], []
    for label, products, pool, main, pick, since in lb.GAMES:
        if games and label not in games:
            continue
        rows = lb.load_game(products, pool, main, since)
        cut, dev, blind = lb.split(rows)
        dm, bm = masks_of([r[3] for r in dev]), masks_of([r[3] for r in blind])
        print(f"{label}: {math.comb(pool, pick):,} lines x {len(rows)} draws", flush=True)
        top_m, top_k, corr, n_lines, _ = search(pool, pick, dm, bm, log=lambda s: print(s, flush=True))
        p = p_hit(pool, main, pick)
        hb, _ = hits(top_m, bm)
        hd = top_k // 1_000_000
        n_obs = TOP * len(bm)
        exp = n_obs * p
        z = (hb.sum() - exp) / math.sqrt(n_obs * p * (1 - p))      # treats the 1,000 lines as independent (generous)
        pv = math.erfc(abs(z) / math.sqrt(2))
        verdicts.append((label, z > 0 and pv < 0.05))
        md.append(f"| {label} | {n_lines:,} | {len(dm)} | {len(bm)} | {p:.2%} | {hd.mean() / len(dm):.2%} | "
                  f"{hb.mean() / len(bm):.2%} | {z:+.2f} | {pv:.3f} | {corr:+.4f} |")
        detail += ["", f"### {label}: the ten best development lines", "",
                   "| Line | Dev hits | Dev rate | Blind hits | Blind rate | Blind p (one-sided) |", "|---|---|---|---|---|---|"]
        for m, k in zip(top_m[:10], hd[:10]):
            b = int(hits(np.array([m], dtype=np.uint64), bm)[0][0])
            detail.append(f"| {' '.join(map(str, numbers(m)))} | {k} | {k / len(dm):.2%} | {b} | {b / len(bm):.2%} | "
                          f"{binom_p_upper(b, len(bm), p):.3f} |")
        if label == "Saturday Lotto":
            rng = random.Random(2026)
            fake = masks_of([rng.sample(range(1, pool + 1), main) for _ in range(len(rows))])
            print("Saturday Lotto: luck check on simulated fair draws", flush=True)
            f_m, f_k, *_ = search(pool, pick, fake, np.zeros(0, dtype=np.uint64))
            real_all, _ = hits(top_m[:1], masks_of([r[3] for r in rows]))
            best_real = search(pool, pick, masks_of([r[3] for r in rows]), np.zeros(0, dtype=np.uint64))[1][0] // 1_000_000
            detail += ["", "### Luck check (Saturday Lotto)", "",
                       f"Over all {len(rows)} real draws the best of {n_lines:,} lines has {best_real} hits "
                       f"({best_real / len(rows):.2%}; chance rate {p:.2%}). Over {len(rows)} simulated fair draws the "
                       f"best line has {f_k[0] // 1_000_000} hits ({f_k[0] // 1_000_000 / len(rows):.2%}). The best line "
                       "always looks well above chance in hindsight, real draws or fake."]
    found = [l for l, v in verdicts if v]
    verdict = ("Past form did not carry forward in any game: the best past lines hit at the chance rate on the "
               "blind draws." if not found else "Past form carried forward in: " + ", ".join(found) + ".")
    md[2:2] = [f"**Verdict: {verdict}**", ""]
    (out / "EXHAUSTIVE.md").write_text("\n".join(md + detail) + "\n")
    print(verdict, flush=True)
    return verdicts


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
