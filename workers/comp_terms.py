"""Ticket and entry caps from promoters' own pages and terms (charity lotteries, art unions, raffles first).

    python3 -m workers.comp_terms             # look up every open, purchase-entry listing a Victorian can enter
    python3 -m workers.comp_terms --max 20    # at most 20 listings this run

For each listing it fetches the promoter's draw page; if that names no cap it follows the page's terms links
(HTML or PDF, PDFs read with pdftotext when installed). It records the cap ("permitted to sell up to N
tickets", "Maximum number of tickets N", "Limited to N tickets" ...; the cap on entries in the draw, bonus tickets
included), the cap on paid tickets where stated, the ticket prices it can see, the Victorian permit number, and
the sentence the cap came from, so every number can be checked against its source.
Prices: per_ticket holds the "$X per ticket" figures shown on the draw page (single ticket and book discounts);
prices holds every (tickets, dollars) offer seen, which on shared lottery sites can include other draws.

A cap is an upper bound on tickets sold: value per ticket at a full sell-out is the floor of what a ticket is
worth; fewer tickets sold means better odds. Promoters rarely publish tickets sold.

Appends to data/comps/terms.jsonl, one record per attempt. A listing with a cap is not looked up again; one
without is retried on later runs, at most MAX_TRIES times.
"""
import argparse
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
from pathlib import Path

from workers import comp_odds, comps

STORE = comps.STORE
MAX_TRIES = 3
MAX_TERMS_PAGES = 3
MIN_CAP = 1000            # smaller numbers are book sizes and bonus-draw prizes, not caps
PAID_CAP = r"up to (?P<n>\d[\d,]{2,}) paid tickets"
CAP_PATTERNS = [
    r"permitted to (?:sell|issue) (?:up to |a maximum of )?(?P<n>\d[\d,]{2,}) tickets",
    r"number of tickets available will range from \d[\d,]* (?:\([^)]*\) )?to (?P<n>\d[\d,]{2,})",
    r"maximum (?:number of |saleable quantity of )?(?:tickets|entries)(?: (?:is|of|available|offered|to be sold|"
    r"for sale|in this (?:draw|lottery|raffle)))?[:\s]+(?P<n>\d[\d,]{2,})",
    r"maximum of (?P<n>\d[\d,]{2,}) (?:tickets|entries)",
    r"limited to (?P<n>\d[\d,]{2,}) (?:tickets|entries)",
    r"(?:total (?:number of )?tickets|tickets (?:available|on sale|offered|printed))[:\s]+(?P<n>\d[\d,]{2,})",
    r"(?P<n>\d[\d,]{2,}) tickets (?:will be|are|have been) (?:printed|offered|available|issued|on sale|for sale)",
]
PRICE_PATTERNS = [
    r"(?P<n>\d+) tickets? (?:for|-|=) \$(?P<p>\d[\d,]*(?:\.\d\d)?)",
    r"\$(?P<p>\d[\d,]*(?:\.\d\d)?) (?:for|-) (?P<n>\d+) tickets?",
    r"\$(?P<p>\d[\d,]*(?:\.\d\d)?) (?:per|each|a) ticket",
    r"tickets? (?:are |cost |from |priced at )+\$(?P<p>\d[\d,]*(?:\.\d\d)?)",
]
PER_TICKET = r"\$(?P<p>\d[\d,]*(?:\.\d\d)?) (?:per|each|a|/) ?ticket"
JSON_PRICE = r'"numTickets":(?P<n>\d+),"price":\{[^}]*?"amount":"(?P<p>\d+(?:\.\d+)?)"'
PERMIT = r"(?:VIC|Vic\.?|Victorian?) (?:Permit|Licence|License)(?: No\.?| Number)?:? ?(?P<v>[A-Z0-9][A-Z0-9/.-]{3,})"
TERMS_LINK = r"""(?:href=["']|["'])(?P<u>(?:https?://[^"'\s]+|/[^"'\s]*)(?:terms|conditions|rules)[^"'\s]*)["']"""


def text_of(body, content_type=""):
    """Plain text of an HTML page (embedded JSON strings included) or a PDF (via pdftotext)."""
    if body[:5] == b"%PDF-" or "pdf" in content_type:
        if not shutil.which("pdftotext"):
            return ""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
            fh.write(body)
            fh.flush()
            out = subprocess.run(["pdftotext", "-layout", fh.name, "-"], capture_output=True, timeout=120)
        return re.sub(r"\s+", " ", out.stdout.decode("utf-8", "replace"))
    t = body.decode("utf-8", "replace")
    t = re.sub(r"(?s)<style.*?</style>", " ", t)
    t = re.sub(r"\\[nrt]", " ", t)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def find_cap(text):
    """(cap, evidence) for the first cap stated in the text, else (None, None)."""
    for pat in CAP_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            n = int(m.group("n").replace(",", ""))
            if n >= MIN_CAP:
                return n, text[max(0, m.start() - 160):m.end() + 80].strip()
    return None, None


def find_prices(raw, text):
    """Sorted unique (tickets, dollars) offers, from embedded shop data and from the wording."""
    out = set()
    for m in re.finditer(JSON_PRICE, raw):
        out.add((int(m.group("n")), float(m.group("p"))))
    for pat in PRICE_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            n = int(m.groupdict().get("n") or 1)
            p = float(m.group("p").replace(",", ""))
            if 0 < p <= 10_000 and 0 < n <= 10_000:
                out.add((n, p))
    return sorted(out)


def terms_links(raw, base):
    """Candidate terms URLs on the page, those sharing words with the draw's own path first."""
    words = set(re.findall(r"[a-z]{4,}", urllib.parse.urlparse(base).path.lower())) - {"draw", "html"}
    host = urllib.parse.urlparse(base).hostname
    found = []
    for m in re.finditer(TERMS_LINK, raw, re.I):
        u = urllib.parse.urljoin(base, html.unescape(m.group("u")).replace("\\/", "/"))
        if urllib.parse.urlparse(u).hostname != host or u in found:
            continue
        found.append(u)
    return sorted(found, key=lambda u: (-len(words & set(re.findall(r"[a-z]{4,}", u.lower()))), found.index(u)))


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": comps.UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(), resp.headers.get("Content-Type", ""), resp.geturl()


def look_up(entry_url, fetch=fetch_bytes, delay=comps.DELAY_S):
    """Fetch the draw page, then up to MAX_TERMS_PAGES terms pages, until a cap is found."""
    rec = {"cap": None, "cap_paid": None, "cap_text": None, "source": None, "per_ticket": [], "prices": [],
           "permit_vic": None, "automation_banned": False, "terms_read": False, "entry_limit_terms": None,
           "entry_limit_terms_n": None, "excessive_clause": False, "tried": []}
    queue, seen = [entry_url], set()
    while queue and len(rec["tried"]) < 1 + MAX_TERMS_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            body, ctype, final = fetch(url)
        except (OSError, ValueError) as exc:
            rec["tried"].append(f"{url} ({exc})")
            continue
        finally:
            time.sleep(delay)
        rec["tried"].append(url)
        if url != entry_url:
            rec["terms_read"] = True
        raw = body.decode("utf-8", "replace") if not body.startswith(b"%PDF-") else ""
        text = text_of(body, ctype)
        rec["prices"] = sorted(set(map(tuple, rec["prices"])) | set(find_prices(raw, text)))
        if url == entry_url:
            rec["per_ticket"] = sorted({float(m.group("p").replace(",", "")) for m in re.finditer(PER_TICKET, text, re.I)})
        if re.search(comp_odds.BANNED, text):
            rec["automation_banned"] = True
        if re.search(comp_odds.EXCESSIVE, text):
            rec["excessive_clause"] = True
        if not rec["entry_limit_terms"]:
            rec["entry_limit_terms"], rec["entry_limit_terms_n"] = comp_odds.terms_limit(text)
        permit = re.search(PERMIT, text)
        if permit and not rec["permit_vic"]:
            rec["permit_vic"] = permit.group("v").rstrip(".,")
        cap, evidence = find_cap(text)
        if cap:
            paid = re.search(PAID_CAP, text, re.I)
            rec.update(cap=cap, cap_text=evidence, source=final,
                       cap_paid=int(paid.group("n").replace(",", "")) if paid else None)
            break
        if url == entry_url:
            queue += terms_links(raw, final)
    rec["prices"] = [list(p) for p in rec["prices"]]
    return rec


def history(store):
    out = {}
    path = store / "terms.jsonl"
    if path.exists():
        for l in path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                out.setdefault(r["id"], []).append(r)
    return out


def targets(store, today):
    """Open listings a Victorian can enter: paid ones (for caps; raffles and lotteries first), then free web-form
    ones (auto-entry candidates, read for an automation ban)."""
    paid, free = [], []
    for r in (json.loads(l)["comp"] for l in comps.stored(store).values()):
        if not (r.get("open_to_vic") and r.get("entry_url") and (r.get("closes") or "9")[:10] >= today):
            continue
        a = comp_odds.assess(r)
        if a["purchase"] == "yes":
            paid.append(r)
        elif a["purchase"] == "no" and a["entry_route"] == "agent_ok":
            free.append(dict(r, _free=True))
    paid.sort(key=lambda r: (not comp_odds.RAFFLE_BRAND.search(r.get("brand") or ""), -(r.get("prize_pool") or 0)))
    return paid + free


def done(r, hist):
    """Paid listings are retried until a cap is found (MAX_TRIES); a free listing needs one successful read."""
    h = hist.get(r["id"], [])
    if any(x.get("cap") for x in h) or len(h) >= MAX_TRIES:
        return True
    return bool(r.get("_free")) and any(len(x.get("tried") or []) and "excessive_clause" in x for x in h)


def run(store=STORE, max_new=None, fetch=fetch_bytes, delay=comps.DELAY_S, today=None):
    today = (today or dt.date.today()).isoformat()
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    hist = history(store)
    todo = [r for r in targets(store, today) if not done(r, hist)]
    if max_new is not None:
        todo = todo[:max_new]
    store.mkdir(parents=True, exist_ok=True)
    found = 0
    with open(store / "terms.jsonl", "a") as fh:
        for r in todo:
            rec = look_up(r["entry_url"], fetch=fetch, delay=delay)
            found += bool(rec["cap"])
            fh.write(json.dumps({"fetched_utc": fetched, "id": r["id"], "entry_url": r["entry_url"], **rec},
                                separators=(",", ":")) + "\n")
            fh.flush()
    print(f"comp_terms: {len(todo)} listings looked up, {found} caps found", flush=True)
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, dest="max_new")
    a = ap.parse_args(argv)
    run(max_new=a.max_new)


if __name__ == "__main__":
    sys.exit(main())
