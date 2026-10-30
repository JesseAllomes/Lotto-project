"""Winning-numbers register: every draw of The Lott's draw games, kept append-only.

    python3 -m workers.draws                      # update every game from its last stored draw
    python3 -m workers.draws --backfill           # walk each game's whole history from its first year
    python3 -m workers.draws --product Powerball  # one game

Stores, per game, in data/draws/:
  <product>.jsonl  one raw API draw per line, with the time it was first fetched and its source; never rewritten
  <product>.csv    the register rebuilt from the JSONL: draw number, date, numbers in drawn order, division 1
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

from workers import lott

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "draws"
SOURCE = lott.BASE + "results/search/daterange"
# First year to search for each game (a little before its known launch; empty windows cost one request).
# Product ids are The Lott's own: Monday/Wednesday Lotto became MondayWednesdayFridayLotto in May 2024,
# and Set for Life is SetForLife744. The API's history starts around 1997 for the older games.
PRODUCTS = {"TattsLotto": 1972, "MonWedLotto": 1978, "MondayWednesdayFridayLotto": 2024, "OzLotto": 1994,
            "Powerball": 1996, "SetForLife744": 2015}
FIELDS = ["product", "draw_number", "draw_date", "primary", "secondary", "div1_winners", "div1_dividend"]


def row(d):
    div1 = next((x for x in d.get("Dividends") or [] if x.get("Division") == 1), {})
    return {
        "product": d["ProductId"],
        "draw_number": d["DrawNumber"],
        "draw_date": d["DrawDate"][:10],
        "primary": " ".join(str(n) for n in d.get("PrimaryNumbers") or []),
        "secondary": " ".join(str(n) for n in d.get("SecondaryNumbers") or []),
        "div1_winners": div1.get("BlocNumberOfWinners"),
        "div1_dividend": div1.get("BlocDividend"),
    }


def _stored(store, product):
    path = store / f"{product}.jsonl"
    if not path.exists():
        return {}
    return {json.loads(l)["draw"]["DrawNumber"]: l for l in path.read_text().splitlines() if l.strip()}


def append(store, product, found, fetched, source=SOURCE):
    """Append draws not yet stored. Returns how many were new. Existing lines are never touched."""
    store.mkdir(parents=True, exist_ok=True)
    have = _stored(store, product)
    new = [d for d in sorted(found, key=lambda d: d["DrawNumber"]) if d["DrawNumber"] not in have]
    seen = set()
    with open(store / f"{product}.jsonl", "a") as fh:
        for d in new:
            if d["DrawNumber"] in seen:
                continue
            seen.add(d["DrawNumber"])
            fh.write(json.dumps({"fetched_utc": fetched, "source": source, "draw": d}, separators=(",", ":")) + "\n")
    return len(seen)


def write_csv(store, product):
    recs = sorted((json.loads(l)["draw"] for l in _stored(store, product).values()), key=lambda d: d["DrawNumber"])
    with open(store / f"{product}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        for d in recs:
            w.writerow(row(d))
    return len(recs)


def last_date(store, product):
    have = _stored(store, product)
    if not have:
        return None
    return max(dt.date.fromisoformat(json.loads(l)["draw"]["DrawDate"][:10]) for l in have.values())


def run(products, backfill, store=STORE, today=None):
    today = today or dt.date.today()
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for p in products:
        last = None if backfill else last_date(store, p)
        start = (last - dt.timedelta(days=14)) if last else dt.date(PRODUCTS[p], 1, 1)
        found = []
        for a, b in lott.windows(start, today):
            found += lott.draws_between(p, a, b)
        n = append(store, p, found, fetched)
        total = write_csv(store, p)
        print(f"{p}: {n} new draws, {total} in register", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--product", choices=sorted(PRODUCTS))
    a = ap.parse_args(argv)
    run([a.product] if a.product else list(PRODUCTS), a.backfill)


if __name__ == "__main__":
    sys.exit(main())
