"""Correction to EXHAUSTIVE.md test 1: the right standard error for the top 1,000 lines.

    python3 -m analysis.lotto_exhaustive_check     # appends a correction section to data/analysis/EXHAUSTIVE.md

Post-hoc and disclosed: the pre-registered z in analysis/lotto_exhaustive.py treated the top 1,000 lines as 1,000
independent bets. They are not: they are built from nearly the same few numbers, so on any one draw they mostly
hit or miss together. That makes the z far too large in both directions (Oz Lotto came out at z = -6.87, which
fair draws do not produce either). The draws are what is independent, so this check takes, for each blind draw,
the share of the top 1,000 lines that hit, and tests the mean of those shares against the chance rate with the
standard error measured across draws (a one-sample t-test; the selection of lines is unchanged).
"""
import math
import sys

import numpy as np

from analysis import lotto_blind as lb
from analysis import lotto_exhaustive as ex


def check(games=None):
    lines = ["", "## Correction: draw-level test of the top 1,000 lines (post-hoc, see "
             "`analysis/lotto_exhaustive_check.py`)", "",
             "The registered z above treated the 1,000 overlapping lines as independent. Here each blind draw is one "
             "observation: the share of the 1,000 lines that hit on that draw.", "",
             "| Game | Blind draws | Chance hit rate | Top 1,000 blind hit rate | Edge | t | p | Beats chance |",
             "|---|---|---|---|---|---|---|---|"]
    out = []
    for label, products, pool, main, pick, since in lb.GAMES:
        if games and label not in games:
            continue
        rows = lb.load_game(products, pool, main, since)
        cut, dev, blind = lb.split(rows)
        dm, bm = ex.masks_of([r[3] for r in dev]), ex.masks_of([r[3] for r in blind])
        top_m, *_ = ex.search(pool, pick, dm, np.zeros(0, dtype=np.uint64))
        p = ex.p_hit(pool, main, pick)
        share = np.array([(np.bitwise_count(top_m & d) >= ex.MIN_HIT).mean() for d in bm])
        se = share.std(ddof=1) / math.sqrt(len(share))
        t = (share.mean() - p) / se if se > 0 else 0.0
        pv = math.erfc(abs(t) / math.sqrt(2))
        win = t > 0 and pv < 0.05
        out.append((label, share.mean(), p, t, pv, win))
        lines.append(f"| {label} | {len(bm)} | {p:.2%} | {share.mean():.2%} | {(share.mean() - p) / p:+.1%} | "
                     f"{t:+.2f} | {pv:.3f} | {'yes' if win else 'no'} |")
        print(f"{label}: blind {share.mean():.2%} vs chance {p:.2%}, t={t:+.2f}, p={pv:.3f}", flush=True)
    return lines, out


def main(argv=None):
    lines, _ = check()
    path = ex.OUT / "EXHAUSTIVE.md"
    path.write_text(path.read_text() + "\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
