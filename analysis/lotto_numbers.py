"""Two number sets per game from the draw register: the numbers players pick least, and the numbers drawn most.

    python3 -m analysis.lotto_numbers    # writes data/analysis/numbers_<game>.csv and data/analysis/NUMBERS.md

Least picked (popularity). Every division below a fixed or jackpot Division One is pari-mutuel: its share of the
prize fund is split among its winners. For each draw the prize fund F is recovered from the dividends
(winners x dividend / share, median over divisions), so the expected winners in division d are F x c x P(d) for a
constant c. When the drawn numbers are popular picks, more people hold them and actual winners exceed that. A
weighted regression of log(winners / (F x P(d))) on the drawn numbers, over every current-format draw and the
divisions that depend only on the main numbers, gives each number's popularity (0 = average; +0.10 = about 10%
more players hold it). Choosing unpopular numbers does not change the chance of winning; it lowers the number of
people a prize is shared with, so each win pays more. The uplift column estimates that for the set.
A holdout check (fit on the earlier half of draws, test on the later half) shows whether the pattern is stable.

Most drawn (frequency). Counts of each main number over the current format, with a chi-square test of whether the
draws are consistent with every number being equally likely. If they are, past frequency says nothing about the
next draw: the set is what was asked for, not an edge.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

from analysis import lotto_games

ROOT = Path(__file__).resolve().parent.parent
DRAWS = ROOT / "data" / "draws"
OUT = ROOT / "data" / "analysis"
GAMES = ["TattsLotto", "MondayWednesdayFridayLotto", "OzLotto", "Powerball", "SetForLife744"]
# Frequency can use older draws when the number pool and count drawn were the same (Saturday Lotto: 6 from 45
# throughout the register; only its prize divisions changed in 2011).
FREQ_SINCE = {"TattsLotto": 0}


def load(product, store=DRAWS, since=None):
    since = lotto_games.GAMES[product]["since"] if since is None else since
    recs = [json.loads(l)["draw"] for l in (store / f"{product}.jsonl").read_text().splitlines() if l.strip()]
    return sorted((d for d in recs if d["DrawNumber"] >= since), key=lambda d: d["DrawNumber"])


def prize_fund(d, share):
    """Prize fund of one draw from its pari-mutuel divisions (median of winners x dividend / share)."""
    est = [x["BlocNumberOfWinners"] * x["BlocDividend"] / share[x["Division"]]
           for x in d["Dividends"] if share.get(x["Division"]) and x["Division"] > 1
           and x["BlocNumberOfWinners"] and x["BlocDividend"]]
    return float(np.median(est)) if est else None


def main_only_divisions(product):
    g = lotto_games.GAMES[product]
    return [d for d, (m, srule, pb) in g["divisions"].items()
            if d > 1 and srule in (None, 0) and pb in (None, False) and g["share"][d] > 0]


def observations(product, draws):
    """Rows (draw index, division, y, weight) for the popularity regression."""
    g = lotto_games.GAMES[product]
    p = lotto_games.odds(product)
    divs = main_only_divisions(product)
    rows = []
    for t, d in enumerate(draws):
        f = prize_fund(d, g["share"])
        if not f:
            continue
        for x in d["Dividends"]:
            w = x["BlocNumberOfWinners"]
            if x["Division"] in divs and w and w >= 5:
                rows.append((t, x["Division"], math.log(w / (f * p[x["Division"]])), math.sqrt(w)))
    return rows


def fit(product, draws, rows):
    """Per-number popularity (mean zero) by weighted least squares with a fixed effect per division."""
    n = lotto_games.GAMES[product]["pool"]
    divs = sorted({r[1] for r in rows})
    x = np.zeros((len(rows), n + len(divs)))
    y = np.zeros(len(rows))
    w = np.zeros(len(rows))
    for i, (t, dv, yy, ww) in enumerate(rows):
        for num in draws[t]["PrimaryNumbers"]:
            x[i, num - 1] = 1.0
        x[i, n + divs.index(dv)] = 1.0
        y[i], w[i] = yy, ww
    coef, *_ = np.linalg.lstsq(x * w[:, None], y * w, rcond=None)
    beta = coef[:n] - coef[:n].mean()
    return beta, x, y, w, coef


def holdout_r(product, draws):
    """Correlation between predicted and actual popularity residuals on the later half, fit on the earlier half."""
    rows = observations(product, draws)
    half = len(draws) // 2
    train = [r for r in rows if r[0] < half]
    test = [r for r in rows if r[0] >= half]
    if len(train) < 50 or len(test) < 50:
        return None
    beta, *_ = fit(product, draws, train)
    pred, actual = [], []
    by_div = {}
    for t, dv, yy, _ in test:
        by_div.setdefault(dv, []).append(yy)
    means = {dv: float(np.mean(v)) for dv, v in by_div.items()}
    for t, dv, yy, _ in test:
        pred.append(sum(beta[num - 1] for num in draws[t]["PrimaryNumbers"]))
        actual.append(yy - means[dv])
    return float(np.corrcoef(pred, actual)[0, 1])


def chi2_sf(x, k):
    """Upper tail of the chi-square distribution (regularised gamma Q(k/2, x/2))."""
    a, z = k / 2.0, x / 2.0
    if z <= 0:
        return 1.0
    if z < a + 1:
        term = total = 1.0 / a
        for i in range(1, 500):
            term *= z / (a + i)
            total += term
        return max(0.0, 1.0 - total * math.exp(-z + a * math.log(z) - math.lgamma(a)))
    b, c, d = z + 1 - a, 1e300, 1 / (z + 1 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = b + an / c
        c = c if abs(c) > 1e-300 else 1e-300
        h *= d * c
    return h * math.exp(-z + a * math.log(z) - math.lgamma(a))


def frequency(product, draws):
    n = lotto_games.GAMES[product]["pool"]
    counts = np.zeros(n)
    for d in draws:
        for num in d["PrimaryNumbers"]:
            counts[num - 1] += 1
    expected = counts.sum() / n
    chi2 = float(((counts - expected) ** 2 / expected).sum())
    return counts, expected, chi2, chi2_sf(chi2, n - 1)


def analyse(product, store=DRAWS):
    g = lotto_games.GAMES[product]
    draws = load(product, store)
    rows = observations(product, draws)
    beta, *_ = fit(product, draws, rows)
    freq_draws = load(product, store, FREQ_SINCE[product]) if product in FREQ_SINCE else draws
    counts, expected, chi2, p = frequency(product, freq_draws)
    pick = g["pick"]
    least = sorted(range(1, g["pool"] + 1), key=lambda i: beta[i - 1])[:pick]
    most = sorted(range(1, g["pool"] + 1), key=lambda i: (-counts[i - 1], i))[:pick]
    # A winning entry in a division matched on m main numbers shares with people holding those m numbers;
    # with the least-popular set the expected co-winners fall by about exp(m x mean popularity of the set).
    m = max(lotto_games.GAMES[product]["divisions"][d][0] if not isinstance(
        lotto_games.GAMES[product]["divisions"][d][0], tuple) else 2 for d in main_only_divisions(product)[-1:])
    uplift = math.exp(-m * float(np.mean([beta[i - 1] for i in least]))) - 1
    return {"product": product, "name": g["name"], "draws": len(draws), "observations": len(rows),
            "first_draw": draws[0]["DrawNumber"], "first_date": draws[0]["DrawDate"][:10],
            "freq_draws": len(freq_draws), "freq_from": freq_draws[0]["DrawDate"][:10],
            "beta": beta, "counts": counts, "expected": expected, "chi2": chi2, "p": p, "least": sorted(least),
            "most": sorted(most), "uplift": uplift, "uplift_matches": m, "holdout_r": holdout_r(product, draws)}


def write(results, out=OUT):
    out.mkdir(parents=True, exist_ok=True)
    md = ["# Lotto number sets", "",
          "From `analysis/lotto_numbers.py` over each game's current-format draws (see that file for the method).", "",
          "- **Least picked**: the numbers fewest players choose. Same chance of winning; fewer people to share a",
          "  prize with, so each win pays more. *Uplift* is the estimated extra paid on a division win.",
          "- **Most drawn**: the numbers drawn most often. *p* tests whether the counts fit equally likely numbers;",
          "  p above 0.05 means they do, and past frequency says nothing about the next draw.",
          "- *Holdout r*: how well popularity fitted on the earlier half of draws predicts the later half (0 = not",
          "  at all, 1 = perfectly). Positive and clear of zero means the popularity pattern is stable.", "",
          "| Game | Draws (from) | Least picked | Uplift | Holdout r | Most drawn (draws counted) | Chi-square p |",
          "|---|---|---|---|---|---|---|"]
    for r in results:
        hr = "n/a" if r["holdout_r"] is None else f"{r['holdout_r']:.2f}"
        md.append(f"| {r['name']} | {r['draws']} ({r['first_date']}) | {' '.join(map(str, r['least']))} | "
                  f"{r['uplift']:+.0%} | {hr} | {' '.join(map(str, r['most']))} ({r['freq_draws']} from {r['freq_from'][:4]}) | "
                  f"{r['p']:.2f} |")
        with open(out / f"numbers_{r['product']}.csv", "w") as fh:
            fh.write("number,popularity,popularity_rank,times_drawn,expected,z\n")
            order = {num: i + 1 for i, num in enumerate(sorted(range(1, len(r['beta']) + 1),
                                                             key=lambda k: r['beta'][k - 1]))}
            sd = math.sqrt(r["expected"])
            for k in range(1, len(r["beta"]) + 1):
                c = r["counts"][k - 1]
                fh.write(f"{k},{r['beta'][k - 1]:.4f},{order[k]},{int(c)},{r['expected']:.1f},"
                         f"{(c - r['expected']) / sd:.2f}\n")
    md += ["", "Popularity rank 1 = least picked. Powerball's Powerball number is not modelled here.", ""]
    (out / "NUMBERS.md").write_text("\n".join(md))


def run(store=DRAWS, out=OUT):
    results = [analyse(p, store) for p in GAMES]
    write(results, out)
    for r in results:
        print(f"{r['name']}: least {r['least']} uplift {r['uplift']:+.0%} holdout r {r['holdout_r']}; "
              f"most {r['most']} p={r['p']:.2f}", flush=True)
    return results


def main(argv=None):
    run()


if __name__ == "__main__":
    sys.exit(main())
