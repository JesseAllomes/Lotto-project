"""What each listing's entry link actually opens: a dead page, the site's home page, a social post (cannot be checked
without logging in), an entry form, or only the terms (and then how to enter).

    python3 -m workers.entry_pages              # check every open listing a Victorian can enter for free, once
    python3 -m workers.entry_pages --max 100

Some listings link to the promoter's terms page instead of the entry page (ING "Celebrating you": opt in from a
customer email; White Fox: the terms name the entry page). For each listing this fetches the entry link once and
records whether the page has a form, or reads as terms only; for a terms page it keeps the "To enter ..." sentence and,
when the page names or links an entry page on the same site, that page. The site shows the sentence on the card and
opens the better page. Static HTML only: a form drawn by JavaScript can look like "no form", so a page counts as
terms only when it reads like terms (several terms phrases) and has no form or email box at all.
Every link is checked again after RECHECK_DAYS (links die while competitions run), 12 at a time.
Appends to data/comps/entry_pages.jsonl (the latest record per listing counts); nothing personal.
"""
import argparse
import concurrent.futures
import datetime as dt
import html
import json
import re
import sys
import urllib.error
import urllib.parse

from workers import comp_odds, comp_terms, comps, entry_queue

STORE = comps.STORE
TERMS_WORDS = [r"\bthe promoter\b", r"promotion period|entry period|competition period", r"these terms",
               r"terms and conditions|conditions of entry", r"\beligib", r"prize draw|draw will take place|winners? will be",
               r"\bclause\b|\b\d{1,2}\.\s+[A-Z]"]
HOW = (r"(?:\bTo enter\b[^.]{0,40}?(?:,|:|\byou\b|\bvisit\b|\bcomplete\b|\bgo to\b)|\b[Hh]ow to [Ee]nter\b:?|"
       r"\b[Ee]ntrants? (?:must|need to|should)\b|\bTo be eligible to enter\b|\bTo participate\b)[^.]{12,400}?\.")
ENTER_LINK = r"""(?is)<a\b[^>]*href=["']([^"'#]+)["'][^>]*>((?:(?!</a>).){0,200}?)</a>"""
ENTER_TEXT = r"(?i)\b(?:enter|entry form|enter now|win|giveaway|competition|sign ?up|register|join)\b"


BAD = {"dead": "the entry link is dead (page not found)", "moved": "the entry link now goes to the shop's home page",
       "home": "the entry link is the shop's home page, not the competition"}


def done_ids(store=STORE):
    path = store / "entry_pages.jsonl"
    return {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()} if path.exists() else set()


def latest(store=STORE):
    path = store / "entry_pages.jsonl"
    out = {}
    if path.exists():
        for l in path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                out[r["id"]] = r
    return out


def check(url, raw, prose, fetch_url=None):
    """{kind: form|terms|page, how, better_url} for one fetched page."""
    body = re.sub(r"(?is)<footer\b.*?</footer>", " ", raw)             # footer newsletter boxes are not entry forms
    forms = [f for f in re.findall(r"(?is)<form\b.*?</form>", body)
             if not re.search(r"(?i)newsletter|subscribe|search|login|/account|/cart", f[:600])]
    has_form = any(re.search(r"(?i)type=[\"']email|name=[\"'][^\"']*e-?mail", f) for f in forms) or \
        bool(re.search(r"(?i)klaviyo-form|gleam\.io|woobox|viralsweep|wishpond|shortstack|komo\.|typeform|jotform|"
                       r"hsforms|gravityforms|wpforms|forms\.office|docs\.google\.com/forms", raw))
    hits = sum(bool(re.search(p, prose, re.I if "[A-Z]" not in p else 0)) for p in TERMS_WORDS)
    terms_url = bool(re.search(r"(?i)terms|conditions|t-?(?:and|&)-?c|[-_/]tcs?\b|/rules|\.pdf(?:$|\?)", url))
    kind = "terms" if (terms_url and hits >= 2) or (hits >= 4 and not has_form) else "form" if has_form else "page"
    rec = {"kind": kind, "how": None, "better_url": None}
    if kind != "terms":
        return rec
    m = re.search(HOW, prose)
    rec["how"] = re.sub(r"\s+", " ", m.group(0)).strip()[:300] if m else None
    host = urllib.parse.urlparse(url).hostname
    named = re.search(r"(?i)(?:to enter|enter (?:the|this) (?:promotion|competition|giveaway)|visit)[^.]{0,200}?"
                      r"(https?://[^\s)\"',]+)", prose)
    cands = [named.group(1).rstrip(".")] if named else []
    for href, text in re.findall(ENTER_LINK, raw):
        t = html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()
        if re.search(ENTER_TEXT, t) and not re.search(r"(?i)terms|conditions|privacy|login|log in|account", t):
            cands.append(urllib.parse.urljoin(url, html.unescape(href)))
    for c in cands:
        p = urllib.parse.urlparse(c)
        if p.scheme in ("http", "https") and p.hostname == host and p.path.rstrip("/") != \
                urllib.parse.urlparse(url).path.rstrip("/") and not re.search(r"(?i)terms|conditions|privacy", c):
            rec["better_url"] = c
            break
    return rec


def targets(store=STORE, today=None):
    today = (today or dt.date.today()).isoformat()
    out = []
    for r in (json.loads(l)["comp"] for l in comps.stored(store).values()):
        if r.get("open_to_vic") and r.get("entry_url") and (entry_queue.close_date(r) or "9") >= today and \
                comp_odds.assess(r)["purchase"] != "yes":
            out.append(r)
    out.sort(key=lambda r: entry_queue.close_date(r) or "9")
    return out


COMP_WORDS = r"(?i)\b(?:win|winner|competition|giveaway|give-away|prize|enter|entries|entry|promotion|sweepstake|draw)\b"
RECHECK_DAYS = 3           # links go dead while a competition runs: check again after this long


def inspect(r, fetch=comp_terms.fetch_bytes):
    """One check of one listing's entry link: dead (404/410), moved (the competition page now redirects to the home
    page), home (the link is a home page with nothing about a competition), social, or form / terms / page as check()
    decides."""
    rec = {"id": r["id"], "checked_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "url": r["entry_url"]}
    try:
        body, ctype, final = fetch(r["entry_url"])
    except urllib.error.HTTPError as exc:
        rec.update(kind="dead" if exc.code in (404, 410) else "error", status=exc.code)
        return rec
    except (OSError, ValueError) as exc:
        rec.update(kind="error", error=type(exc).__name__)
        return rec
    raw = body.decode("utf-8", "replace") if not body.startswith(b"%PDF-") else ""
    prose = comp_terms.prose_of(body, ctype)
    rec.update(check(final, raw, prose), final=final, status=200)
    was, now = urllib.parse.urlparse(r["entry_url"]), urllib.parse.urlparse(final)
    if was.path.strip("/") and not now.path.strip("/") and not now.query:
        rec["kind"] = "moved"                                  # the competition page now redirects to the home page
    elif re.search(r"(?i)(?:^|\.)(?:facebook|instagram|tiktok|twitter|x|youtube|threads)\.(?:com|net)$", now.hostname or ""):
        rec["kind"] = "social"                                 # a login wall hides the post: cannot be checked
    elif rec["kind"] == "page" and not now.path.strip("/") and len(re.findall(COMP_WORDS, prose)) < 3 and \
            not re.match(r"(?i)(?:win|comp|comps|competition|giveaway|promo|promotion)s?\.", now.hostname or ""):
        # the link is the shop's home page, which says nothing about a competition (a page that draws its content
        # with JavaScript can look empty too, so only a bare home page counts)
        rec["kind"] = "home"
    return rec


def due(r, last, now):
    if not last or "status" not in last:      # never checked, or checked before dead/moved/unrelated existed
        return True
    if last.get("kind") == "unrelated":
        return True                               # checked under an older, looser rule
    try:
        when = dt.datetime.fromisoformat(last["checked_utc"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return True
    return now - when >= dt.timedelta(days=RECHECK_DAYS) or last.get("kind") == "error"


def run(store=STORE, max_new=None, fetch=comp_terms.fetch_bytes, workers=12, now=None):
    """Checks every open listing whose link is unchecked or was checked RECHECK_DAYS ago (12 at a time)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    last = latest(store)
    todo = [r for r in targets(store) if due(r, last.get(r["id"]), now)]
    if max_new is not None:
        todo = todo[:max_new]
    kinds = {}
    with open(store / "entry_pages.jsonl", "a") as fh, \
            concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for rec in pool.map(lambda r: inspect(r, fetch), todo):
            kinds[rec["kind"]] = kinds.get(rec["kind"], 0) + 1
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
    print(f"entry_pages: {len(todo)} checked: " + ", ".join(f"{v} {k}" for k, v in kinds.items()), flush=True)
    return kinds


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, dest="max_new")
    a = ap.parse_args(argv)
    run(max_new=a.max_new)


if __name__ == "__main__":
    sys.exit(main())
