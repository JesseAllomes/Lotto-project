"""Competition register: open Australian competitions, flagged for whether a Victorian can enter.

    python3 -m workers.comps            # add every listing not yet stored (about one page a second)
    python3 -m workers.comps --max 50   # at most 50 new listings this run

Source: competitions.com.au, which lists trade promotions, charity raffles and prize homes, free and skill
competitions, with the prize pool, the states each is open to and the closing date. Its sitemap names every
open listing; each listing page carries schema.org Event data and a short facts block.

Stores, in data/comps/:
  comps.jsonl  one listing per line (first fetch time, source page, parsed fields, promoter's description);
               never rewritten, de-duplicated by listing id
  comps.csv    the register rebuilt from the JSONL, without the long description
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "comps"
SITEMAP = "https://www.competitions.com.au/sitemap_files.cfm?part=competitions&start=1"
UA = "lotto-project-register/1.0 (+https://github.com/JesseAllomes/Lotto-project)"
DELAY_S = 1.0
FIELDS = ["id", "title", "category", "brand", "prize_pool", "states", "open_to_vic", "opens", "closes",
          "entry_url", "url"]


def get(url, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def listing_urls(sitemap_xml):
    """(id, url) for every competition listing in the sitemap."""
    out = []
    for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", sitemap_xml):
        m = re.search(r"/(\d+)/$", html.unescape(loc))
        if m:
            out.append((int(m.group(1)), html.unescape(loc)))
    return out


def _event(page):
    for block in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', page):
        if '"Event"' not in block:
            continue
        try:
            d = json.loads(block)
        except json.JSONDecodeError:
            continue
        if d.get("@type") == "Event":
            return d
    return {}


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _entry_url(url):
    """The promoter's own page: affiliate links carry it in a Url= parameter."""
    if not url:
        return None
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return q.get("Url", q.get("url", [url]))[0]


def parse(page, comp_id, url):
    ev = _event(page)
    cat = re.search(r'<a href="/([a-z0-9-]+)/"[^>]*>\s*<i class="fas fa-tag[^"]*"></i>(.*?)</a>', page, re.S)
    pool = re.search(r'Prize pool</span>\s*<span[^>]*>(.*?)</span>', page, re.S)
    states = re.search(r'<i class="fas fa-map-marker-alt[^"]*"></i>(.*?)</span>', page, re.S)
    amount = None
    if pool:
        digits = re.sub(r"[^\d.]", "", _text(pool.group(1)))
        amount = float(digits) if digits else None
    st = _text(states.group(1)) if states else None
    loc = ev.get("location") or {}
    return {
        "id": comp_id,
        "title": _text(ev.get("name")) or _text((re.search(r"(?s)<h1[^>]*>(.*?)</h1>", page) or [None, ""])[1]),
        "category": _text(cat.group(2)) if cat else None,
        "category_slug": cat.group(1) if cat else None,
        "brand": (ev.get("organizer") or {}).get("name"),
        "prize_pool": amount,
        "states": st,
        "open_to_vic": None if not st else bool(re.search(r"\b(VIC|Victoria|all states|Australia[- ]wide|national)",
                                                          st, re.I)),
        "opens": ev.get("startDate"),
        "closes": ev.get("endDate"),
        "entry_url": _entry_url(loc.get("url") if isinstance(loc, dict) else None),
        "url": url,
        "description": ev.get("description"),
    }


def stored(store):
    path = store / "comps.jsonl"
    if not path.exists():
        return {}
    return {json.loads(l)["comp"]["id"]: l for l in path.read_text().splitlines() if l.strip()}


def append(store, recs, fetched):
    """Append listings not yet stored. Returns how many were new. Existing lines are never touched."""
    store.mkdir(parents=True, exist_ok=True)
    have = set(stored(store))
    n = 0
    with open(store / "comps.jsonl", "a") as fh:
        for r in recs:
            if r["id"] in have:
                continue
            have.add(r["id"])
            fh.write(json.dumps({"fetched_utc": fetched, "source": r["url"], "comp": r}, separators=(",", ":")) + "\n")
            n += 1
    return n


def write_csv(store):
    recs = sorted((json.loads(l)["comp"] for l in stored(store).values()), key=lambda r: r["id"])
    with open(store / "comps.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in recs:
            w.writerow(r)
    return len(recs)


def run(store=STORE, max_new=None, fetch=get, delay=DELAY_S):
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    have = set(stored(store))
    todo = [(i, u) for i, u in listing_urls(fetch(SITEMAP)) if i not in have]
    if max_new is not None:
        todo = todo[:max_new]
    recs, failed = [], 0
    for i, u in todo:
        try:
            recs.append(parse(fetch(u), i, u))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            failed += 1                       # retried on the next run, since nothing was stored for it
            print(f"skip {u}: {exc}", flush=True)
        time.sleep(delay)
    n = append(store, recs, fetched)
    total = write_csv(store)
    vic = sum(1 for r in recs if r["open_to_vic"])
    print(f"comps: {n} new listings ({vic} open to Victoria), {failed} failed, {total} in register", flush=True)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, dest="max_new")
    a = ap.parse_args(argv)
    run(max_new=a.max_new)


if __name__ == "__main__":
    sys.exit(main())
