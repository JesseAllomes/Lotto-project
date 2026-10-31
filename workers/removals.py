"""Competitions the owner removed, and the pattern of what they keep and what they remove.

    python3 -m workers.removals "remove: 75870 76058"   # record removals (workers/actions.py does this for the site)
    python3 -m workers.removals "broken: 75870"         # the site's Doesn't work button: removed, not a dislike
    python3 -m workers.removals                         # rebuild data/entries/PREFERENCES.md only

The site's Remove button sends {"kind": "remove", "ids": [...]} to the site API; the actions job (workers/actions.py)
records each id in data/entries/log_removed.jsonl with what the listing was (category, brand, prize, entry route,
draw type, source), so the queue never enters it again and both lists drop it. PREFERENCES.md compares removed
competitions with the ones still listed: removal rate by category, entry route, prize band, source and brand, and
the title words that turn up most in removals. No personal details.
"""
import collections
import datetime as dt
import json
import re
import sys

from workers import comp_odds, comps, entry_queue, site

ENTRIES = entry_queue.ENTRIES
LOG = ENTRIES / "log_removed.jsonl"
REPORT = ENTRIES / "PREFERENCES.md"
STOP = {"win", "a", "an", "the", "of", "to", "and", "for", "with", "your", "you", "1", "2", "or", "in", "on", "at", "x",
        "worth", "from", "plus", "+", "&"}


def removed_ids(entries=ENTRIES):
    return {r["id"] for r in entry_queue.read_jsonl(entries / "log_removed.jsonl") if r.get("result") == "removed"}


def band(p):
    p = p or 0
    return "under $500" if p < 500 else "$500-$1,999" if p < 2000 else "$2,000-$9,999" if p < 10000 else "$10,000+"


def describe(r):
    a = comp_odds.assess(r)
    return {"title": r.get("title", ""), "brand": r.get("brand") or "", "category": site.category(r.get("title"),
            r.get("category_slug")), "prize_pool": r.get("prize_pool"), "prize_band": band(r.get("prize_pool")),
            "entry_route": a["entry_route"], "draw_type": a["draw_type"], "platform": comps.platform(r.get("entry_url")),
            "source": r.get("source_site") or "competitions.com.au"}


def record(text, store=comps.STORE, entries=ENTRIES, now=None):
    """Append a removal for each listing id in text; returns the ids recorded (ids already removed are skipped).
    "broken: <ids>" (the site's Doesn't work button) records why = "doesn't work": removed the same way, but kept out
    of the likes-and-dislikes pattern and listed on its own."""
    why = "doesn't work" if re.match(r"(?i)\s*broken", text or "") else "not for me"
    now = now or dt.datetime.now(dt.timezone.utc)
    recs = {json.loads(l)["comp"]["id"]: json.loads(l)["comp"] for l in comps.stored(store).values()}
    done, out = removed_ids(entries), []
    entries.mkdir(parents=True, exist_ok=True)
    with open(entries / "log_removed.jsonl", "a") as fh:
        for i in dict.fromkeys(int(x) for x in re.findall(r"\b(\d{5,9})\b", text or "")):
            if i in done or i not in recs:
                continue
            fh.write(json.dumps({"time_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "id": i, "mode": "owner",
                                 "result": "removed", "why": why, **describe(recs[i])}) + "\n")
            out.append(i)
    return out


def report(store=comps.STORE, entries=ENTRIES, today=None):
    """PREFERENCES.md: removed vs still-listed open competitions a Victorian can enter for free."""
    today = (today or dt.date.today()).isoformat()
    rows = [r for r in entry_queue.read_jsonl(entries / "log_removed.jsonl") if r.get("result") == "removed"]
    gone = {r["id"] for r in rows}
    removed = [r for r in rows if r.get("why") != "doesn't work"]          # dislikes; broken ones are listed below
    broken = [r for r in rows if r.get("why") == "doesn't work"]
    kept = [describe(r) for r in (json.loads(l)["comp"] for l in comps.stored(store).values())
            if r.get("open_to_vic") and (entry_queue.close_date(r) or "9") >= today and r["id"] not in gone
            and comp_odds.assess(r)["purchase"] != "yes"]
    lines = ["# What the owner removes", "",
             f"{len(removed)} competitions removed, {len(kept)} open free ones still listed (built {today}).", ""]
    if broken:
        lines += [f"## Marked \"doesn't work\" ({len(broken)}; not counted as dislikes)", ""] + \
                 [f"- {r['id']} {r['title'][:70]} ({r['platform']}, {r['entry_route']})" for r in broken] + [""]
    if not removed:
        lines += ["Nothing removed yet. Use the Remove button on the site; the pattern shows here after a few."]
    for key, name in (("category", "Category"), ("entry_route", "Entry route"), ("prize_band", "Prize"),
                      ("draw_type", "Draw type"), ("source", "Source")):
        if not removed:
            break
        r_c, k_c = collections.Counter(x[key] for x in removed), collections.Counter(x[key] for x in kept)
        lines += [f"## {name}", "", "| | removed | still listed | removal rate |", "|---|---:|---:|---:|"]
        for v in sorted(set(r_c) | set(k_c), key=lambda v: -r_c[v] / (r_c[v] + k_c[v])):
            if r_c[v]:
                lines.append(f"| {v} | {r_c[v]} | {k_c[v]} | {100 * r_c[v] / (r_c[v] + k_c[v]):.0f}% |")
        lines.append("")
    if removed:
        brands = collections.Counter(x["brand"] for x in removed if x["brand"])
        words = collections.Counter(w for x in removed for w in set(re.findall(r"[a-z][a-z'-]+", x["title"].lower()))
                                    if w not in STOP)
        lines += ["## Brands removed more than once", ""] + \
                 ([f"- {b} ({n})" for b, n in brands.most_common() if n > 1] or ["None yet."]) + \
                 ["", "## Title words in removals", ""] + \
                 [", ".join(f"{w} ({n})" for w, n in words.most_common(20))]
    entries.mkdir(parents=True, exist_ok=True)
    (entries / "PREFERENCES.md").write_text("\n".join(lines) + "\n")
    return removed


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        ids = record(" ".join(args))
        print(f"removals: recorded {len(ids)}: {' '.join(map(str, ids)) or 'none (unknown or already removed)'}")
    print(f"removals: {len(report())} removed in total", flush=True)


if __name__ == "__main__":
    sys.exit(main())
