"""Side crawl: free stuff a Victorian can get, from OzBargain's Freebies listing (free samples, free food, free games).

    python3 -m workers.freebies         # writes data/freebies/freebies.csv (the current list) for the site

Reads the first few pages of https://www.ozbargain.com.au/freebies (public pages; robots.txt allows them), one
request a second. Keeps freebies that are national or tagged [VIC] (drops ones tagged only for other states) and
not expired, and links to each deal's OzBargain page, where the store link and conditions are. Rebuilt every time
the site is built (.github/workflows/site.yml); no history is kept.
"""
import csv
import datetime as dt
import html
import re
import sys
import time

from workers import comps

STORE = comps.ROOT / "data" / "freebies"
PAGES = ["https://www.ozbargain.com.au/freebies", "https://www.ozbargain.com.au/freebies?page=1",
         "https://www.ozbargain.com.au/freebies?page=2"]
STATES = {"VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT"}
FIELDS = ["id", "title", "kind", "store", "posted", "expires", "votes", "summary", "url"]


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(page):
    out = []
    for nid, body in re.findall(r'(?s)<div class="node node-ozbdeal node-teaser" id="node(\d+)">(.*?)(?=<div class="node node-ozbdeal|\Z)', page):
        title = re.search(r'data-title="([^"]*)"', body)
        if not title:
            continue
        t = html.unescape(title.group(1)).strip()
        tags = [x.strip().upper() for x in re.findall(r"\[([^\]]+)\]", t[:60])]
        states = {s for tag in tags for s in re.split(r"[,/ ]+", tag) if s in STATES}
        if states and "VIC" not in states:
            continue
        expired = "expired" in body[:400].lower() or 'class="expired"' in body
        if expired:
            continue
        kind = re.search(r'<a href="/cat/[^"]+">([^<]+)</a>', body)
        store = re.search(r'<span class="via">.*?<a [^>]*>([^<]+)</a>', body, re.S)
        posted = re.search(r"</strong> on (\d\d/\d\d/\d{4})", body)
        expires = re.search(r'class="nodeexpiry">.*?</i>\s*([^<]+?)\s*<', body, re.S)
        votes = re.search(r'class="nvb voteup">.*?<span>(\d+)</span>', body, re.S)
        summary = re.search(r'(?s)<div class="content">(.*?)</div>', body)
        out.append({"id": int(nid), "title": t, "kind": _text(kind.group(1)) if kind else "Freebie",
                    "store": _text(store.group(1)) if store else "", "posted": posted.group(1) if posted else "",
                    "expires": _text(expires.group(1)) if expires else "", "votes": int(votes.group(1)) if votes else 0,
                    "summary": _text(summary.group(1))[:220] if summary else "",
                    "url": f"https://www.ozbargain.com.au/node/{nid}"})
    return out


def run(store=STORE, fetch=comps.get, delay=comps.DELAY_S):
    rows, seen = [], set()
    for u in PAGES:
        try:
            for r in parse(fetch(u)):
                if r["id"] not in seen:
                    seen.add(r["id"])
                    rows.append(r)
        except Exception as exc:                 # one page failing keeps the rest
            print(f"skip {u}: {exc}", flush=True)
        time.sleep(delay)
    rows.sort(key=lambda r: -r["id"])
    store.mkdir(parents=True, exist_ok=True)
    with open(store / "freebies.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"freebies: {len(rows)} current freebies for Victoria", flush=True)
    return rows


def main(argv=None):
    run()


if __name__ == "__main__":
    sys.exit(main())
