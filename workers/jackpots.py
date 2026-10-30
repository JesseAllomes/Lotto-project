"""Lucky Lotteries jackpot tracker: every Mega and Super Jackpot draw, the open jackpot, and alerts.

    python3 -m workers.jackpots                    # update from the last stored draw; snapshot the open jackpots
    python3 -m workers.jackpots --backfill         # walk each game's whole history (from 2000)
    python3 -m workers.jackpots --alerts out.json  # also write the alerts that are due (the workflow opens issues)

Stores, in data/jackpots/:
  <product>.jsonl  one raw API draw per line (first fetch time and source); never rewritten
  <product>.csv    draw number, date, jackpot on offer (division 11), jackpot winners, % of break-even
  open.jsonl       each new open-draw jackpot seen (product, draw, amount, fetch time); append-only
  STATUS.md        the current jackpots against the alert and break-even levels

The jackpot is division 11 of each draw. It is never shared and does not shrink as sales grow, so once it
passes break-even every ticket has positive expected value (SURVEY.md section 2.1).
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

from workers import draws, lott

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "jackpots"
SOURCE = draws.SOURCE
OPEN_SOURCE = lott.BASE + "opendraws"
JACKPOT_DIVISION = 11
# Alert at the subscription break-even; break-even at the retail price (SURVEY.md 2.1, work/scripts/ev_models.py).
GAMES = {
    "LuckyLotteries5": {"name": "Mega Jackpot", "price": 5.50, "first_year": 2000,
                        "alert": 30_000_000, "break_even": 35_000_000},
    "LuckyLotteries2": {"name": "Super Jackpot", "price": 2.20, "first_year": 2000,
                        "alert": 23_000_000, "break_even": 27_200_000},
}
FIELDS = ["product", "game", "draw_number", "draw_date", "jackpot", "jackpot_winners", "pct_of_break_even"]


def jackpot(d):
    """(amount on offer, number of winners) for one draw, from division 11."""
    div = next((x for x in d.get("Dividends") or [] if x.get("Division") == JACKPOT_DIVISION), {})
    return div.get("BlocDividend"), div.get("BlocNumberOfWinners")


def row(d):
    g = GAMES[d["ProductId"]]
    amount, winners = jackpot(d)
    return {
        "product": d["ProductId"],
        "game": g["name"],
        "draw_number": d["DrawNumber"],
        "draw_date": d["DrawDate"][:10],
        "jackpot": amount,
        "jackpot_winners": winners,
        "pct_of_break_even": None if amount is None else round(100 * amount / g["break_even"], 1),
    }


def history(store, product):
    return sorted((json.loads(l)["draw"] for l in draws._stored(store, product).values()),
                  key=lambda d: d["DrawNumber"])


def write_csv(store, product):
    recs = history(store, product)
    with open(store / f"{product}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        for d in recs:
            w.writerow(row(d))
    return len(recs)


def open_jackpot(product):
    """The next draw on sale: (draw number, jackpot amount). The API also lists the placeholder after it."""
    body = {"CompanyId": lott.COMPANY, "MaxDrawCount": 2, "OptionalProductFilter": [product]}
    found = [d for d in lott.post("opendraws", body).get("Draws") or [] if d.get("ProductId") == product]
    if not found:
        return None
    d = min(found, key=lambda d: d["DrawNumber"])
    return d["DrawNumber"], d["Div1Amount"]


def record_open(store, product, draw_number, amount, fetched):
    """Append the open jackpot if this (draw, amount) has not been seen. Returns True when appended."""
    path = store / "open.jsonl"
    seen = set()
    if path.exists():
        for l in path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                seen.add((r["product"], r["draw_number"], r["jackpot"]))
    if (product, draw_number, amount) in seen:
        return False
    with open(path, "a") as fh:
        fh.write(json.dumps({"fetched_utc": fetched, "source": OPEN_SOURCE, "product": product,
                             "draw_number": draw_number, "jackpot": amount}, separators=(",", ":")) + "\n")
    return True


def cycle(recs):
    """Draws since the jackpot was last won: (first draw number of the cycle, draws so far, growth per draw)."""
    start = recs[0]["DrawNumber"] if recs else None
    for d in recs:
        if (jackpot(d)[1] or 0) > 0:
            start = d["DrawNumber"] + 1
    run = [d for d in recs if start is not None and d["DrawNumber"] >= start]
    amounts = [jackpot(d)[0] for d in run if jackpot(d)[0] is not None]
    growth = (amounts[-1] - amounts[-2]) if len(amounts) >= 2 else None
    return start, len(run), growth


def assess(product, recs, open_draw):
    """State of one game: open jackpot against its levels, plus the alerts now due (keys are stable per cycle)."""
    g = GAMES[product]
    start, n, growth = cycle(recs)
    draw_number, amount = open_draw if open_draw else (None, None)
    if amount is None and recs:
        amount = jackpot(recs[-1])[0]
    s = {"product": product, "game": g["name"], "open_draw": draw_number, "jackpot": amount,
         "cycle_start": start, "draws_in_cycle": n, "growth_per_draw": growth,
         "alert": g["alert"], "break_even": g["break_even"], "alerts": []}
    if amount is None:
        return s
    for level, label in ((g["alert"], "alert level"), (g["break_even"], "break-even")):
        if amount >= level:
            key = f"{g['name']} cycle {start} {label}"
            s["alerts"].append({
                "key": key,
                "title": f"[jackpot] {key}: ${amount:,.0f}",
                "body": (f"{g['name']} is ${amount:,.0f} for draw {draw_number}, at or above the {label} "
                         f"(${level:,.0f}). Break-even at the ${g['price']:.2f} ticket price is "
                         f"${g['break_even']:,.0f}; above it every ticket has positive expected value, but the "
                         f"chance of winning stays about 1 in 9-18 million per ticket. Buy before the draw sells "
                         f"out. See SURVEY.md section 2.1."),
            })
    return s


def _money(x):
    return "n/a" if x is None else f"${x:,.0f}"


def status_md(states, fetched):
    lines = ["# Lucky Lotteries jackpots", "", f"Updated {fetched} by workers/jackpots.py.", "",
             "| Game | Open draw | Jackpot | Alert at | Break-even | % of break-even | Draws this cycle | Growth per draw | Draws to break-even |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in states:
        j, be, gr = s["jackpot"], s["break_even"], s["growth_per_draw"]
        pct = "n/a" if j is None else f"{100 * j / be:.0f}%"
        to_be = "reached" if j is not None and j >= be else (
            f"{-(-(be - j) // gr):.0f}" if j is not None and gr else "n/a")
        lines.append(f"| {s['game']} | {s['open_draw'] or 'n/a'} | {_money(j)} | {_money(s['alert'])} | {_money(be)} "
                     f"| {pct} | {s['draws_in_cycle']} | {_money(gr)} | {to_be} |")
    lines += ["", "An alert opens a GitHub issue once per jackpot cycle at each level. Break-even comes from "
              "SURVEY.md section 2.1.", ""]
    return "\n".join(lines)


def run(products, backfill, store=STORE, today=None, alerts_path=None, opener=open_jackpot):
    today = today or dt.date.today()
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    store.mkdir(parents=True, exist_ok=True)
    states = []
    for p in products:
        last = None if backfill else draws.last_date(store, p)
        start = (last - dt.timedelta(days=14)) if last else dt.date(GAMES[p]["first_year"], 1, 1)
        found = []
        for a, b in lott.windows(start, today):
            found += lott.draws_between(p, a, b)
        n = draws.append(store, p, found, fetched, source=SOURCE)
        total = write_csv(store, p)
        od = opener(p)
        if od:
            record_open(store, p, od[0], od[1], fetched)
        s = assess(p, history(store, p), od)
        states.append(s)
        print(f"{p}: {n} new draws, {total} in register; open jackpot {_money(s['jackpot'])}, "
              f"{len(s['alerts'])} alert(s)", flush=True)
    (store / "STATUS.md").write_text(status_md(states, fetched))
    if alerts_path:
        Path(alerts_path).write_text(json.dumps([a for s in states for a in s["alerts"]], indent=1))
    return states


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--product", choices=sorted(GAMES))
    ap.add_argument("--alerts", help="write due alerts to this JSON file")
    a = ap.parse_args(argv)
    run([a.product] if a.product else list(GAMES), a.backfill, alerts_path=a.alerts)


if __name__ == "__main__":
    sys.exit(main())
