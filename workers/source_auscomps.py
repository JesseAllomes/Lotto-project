"""Second competition source: AusComps (auscomps.au), added to the same register as competitions.com.au.

    python3 -m workers.source_auscomps            # add every AusComps listing not yet stored (about one page a second)
    python3 -m workers.source_auscomps --max 50

Its sitemaps (competition-sitemap1.xml, 2, ...) name every listing; each page carries the closing date, eligible
states, brand, prize value, the "Enter Competition" link and a Q&A (schema.org FAQPage) including how often one may
enter. Each listing becomes a record shaped like workers/comps.py's, with id 10,000,000 + the WordPress post id, and
a description in the same "**Question?** answer" form so workers/comp_odds.py reads it unchanged. AusComps'
"Frequency" is written as an explicit entry limit. Listings that match one already stored from competitions.com.au
(same entry page, or nearly the same title closing within three days) are skipped, so nothing is entered twice.
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error

from workers import comps

STORE = comps.STORE
INDEX = "https://auscomps.au/sitemap_index.xml"
ID_BASE = 10_000_000
FREQUENCY = {"once": "Only one entry per person.", "daily": "You may enter once per day.",
             "weekly": "You may enter once per week.", "unlimited": "Multiple entries are permitted.",
             "multiple": "Multiple entries are permitted."}
STOP = {"win", "a", "an", "the", "of", "to", "from", "and", "for", "with", "worth", "valued", "at", "1", "in", "your"}


def sitemap_urls(index_xml, fetch, since=None):
    """Competition page URLs from the sitemaps, newest first; with since (a UTC datetime), only pages modified since
    then. The sitemaps hold every competition AusComps ever listed (6,500 on 31 Oct 2026, most long closed)."""
    out = []
    for sm in re.findall(r"<loc>\s*(https://auscomps\.au/competition-sitemap\d*\.xml)\s*</loc>", index_xml):
        for u, lastmod in re.findall(r"<loc>\s*(https://auscomps\.au/competition/[^<\s]+/)\s*</loc>"
                                     r"(?:\s*<lastmod>\s*([^<\s]+)\s*</lastmod>)?", fetch(sm)):
            when = None
            try:
                when = dt.datetime.fromisoformat(lastmod.replace("Z", "+00:00")) if lastmod else None
            except ValueError:
                pass
            if since is None or when is None or when >= since:
                out.append((when or dt.datetime.max.replace(tzinfo=dt.timezone.utc), u))
    out.sort(reverse=True)
    return list(dict.fromkeys(u for _, u in out))


def _detail(page, label):
    m = re.search(r'sc-detail-label">\s*' + label + r'\s*</div>\s*<div class="sc-detail-value">(.*?)</div>', page, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None


def parse(page, url):
    post = re.search(r"rel=['\"]shortlink['\"] href=['\"]https://auscomps\.au/\?p=(\d+)['\"]", page)
    title = re.search(r'<h1 class="sc-title">(.*?)</h1>', page, re.S)
    if not (post and title):
        raise ValueError("not a competition page")
    enter = re.search(r'<a href="([^"]+)"[^>]*id="enter-btn"', page)
    value = re.search(r'sc-prize-value">\s*\$?([\d,.]+)', page)
    cd = re.search(r'data-cd="(\d{8})"', page)
    closes = None
    if cd:
        closes = f"{cd.group(1)[:4]}-{cd.group(1)[4:6]}-{cd.group(1)[6:]}T23:59:59+11:00"
    else:
        c = _detail(page, "Closes")
        if c:
            try:
                closes = dt.datetime.strptime(c, "%d %b %Y").strftime("%Y-%m-%dT23:59:59+11:00")
            except ValueError:
                pass
    states = _detail(page, "Eligible States")
    qa = []
    for block in re.findall(r'(?s)<script type="application/ld\+json">(\{"@context":"https://schema.org","@type":"FAQPage".*?)</script>', page):
        try:
            for q in json.loads(block).get("mainEntity", []):
                a = q.get("acceptedAnswer", {}).get("text", "")
                f = re.search(r"Frequency:\s*([A-Za-z]+)", a)
                if f and f.group(1).lower() in FREQUENCY:
                    a = re.sub(r"Frequency:\s*[A-Za-z]+\.?", FREQUENCY[f.group(1).lower()], a)
                qa.append(f"**{q.get('name', '').strip()}**  \n{a.strip()}")
        except json.JSONDecodeError:
            continue
    return {
        "id": ID_BASE + int(post.group(1)),
        "title": html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip(),
        "category": None, "category_slug": None,
        "brand": _detail(page, "Brand"),
        "prize_pool": float(value.group(1).replace(",", "")) if value and value.group(1).replace(",", "").replace(".", "").isdigit() else None,
        "states": states,
        "open_to_vic": None if not states else bool(re.search(r"(?i)all states|\bVIC\b|victoria|australia", states)),
        "opens": None, "closes": closes,
        "entry_url": html.unescape(enter.group(1)) if enter else None,
        "url": url,
        "description": "\n".join(qa),
        "source_site": "auscomps.au",
    }


def _words(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP}


def duplicate(rec, existing):
    """True when rec is a competition already stored (same entry page, or near-identical title closing within 3 days)."""
    u = (rec.get("entry_url") or "").rstrip("/").lower()
    w = _words(rec["title"])
    c = (rec.get("closes") or "")[:10]
    for e in existing:
        if u and u == (e.get("entry_url") or "").rstrip("/").lower():
            return True
        ew = _words(e.get("title") or "")
        if w and ew and len(w & ew) / len(w | ew) >= 0.7:
            ec = (e.get("closes") or "")[:10]
            if not c or not ec or abs((dt.date.fromisoformat(c) - dt.date.fromisoformat(ec)).days) <= 3:
                return True
    return False


RECENT_DAYS = 60       # pages not modified for this long are closed competitions
BATCH = 50             # listings are saved every BATCH pages, so a timed-out run keeps its work


def run(store=STORE, max_new=None, fetch=comps.get, delay=comps.DELAY_S, now=None):
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    stored = {json.loads(l)["comp"]["id"]: json.loads(l) for l in comps.stored(store).values()}
    skip_path = store / "auscomps_skipped.txt"
    seen_urls = {r["source"] for r in stored.values()} | (
        set(skip_path.read_text().split()) if skip_path.exists() else set())
    existing = [r["comp"] for r in stored.values() if r["comp"].get("source_site") != "auscomps.au"]
    since = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=RECENT_DAYS)
    todo = [u for u in sitemap_urls(fetch(INDEX), fetch, since) if u not in seen_urls]
    if max_new is not None:
        todo = todo[:max_new]
    recs, failed, dupes, skipped, n = [], 0, 0, [], 0

    def save():
        nonlocal recs, skipped, n
        n += comps.append(store, recs, fetched)
        if skipped:
            with open(skip_path, "a") as fh:
                fh.write("".join(u + "\n" for u in skipped))
        recs, skipped = [], []

    for k, u in enumerate(todo, 1):
        try:
            r = parse(fetch(u), u)
            if duplicate(r, existing):
                dupes += 1
                skipped.append(u)
            else:
                recs.append(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            failed += 1
            print(f"skip {u}: {exc}", flush=True)
        time.sleep(delay)
        if k % BATCH == 0:
            save()
    save()
    total = comps.write_csv(store)
    print(f"auscomps: {len(todo)} pages read, {n} new listings, {dupes} already listed, {failed} failed; "
          f"{total} in register", flush=True)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, dest="max_new")
    a = ap.parse_args(argv)
    run(max_new=a.max_new)


if __name__ == "__main__":
    sys.exit(main())
