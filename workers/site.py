"""The competition page: search, filter and tick off what to enter by hand; see and re-enter the auto-entries.

    python3 -m workers.site                 # writes site/index.html (published by .github/workflows/site.yml)
    python3 -m workers.site --out DIR       # somewhere else

One static page built from the registers after each run. All the data is embedded as JSON and the phone does the
searching, filtering and sorting (gamer-chic theme: purple fuzz, neon orange, paint splatter). Tabs:
  Social       the To enter list's Facebook / Instagram / TikTok competitions, on their own tab.
  Remove       (and Doesn't work, not counted as a dislike) on To enter and Auto-entered: stops entries, drops the comp
               from both lists and records it for the owner's pattern of likes and dislikes (workers/removals.py ->
               data/entries/PREFERENCES.md); hidden on the phone at once.
  To enter     open competitions a Victorian can enter that the auto-entrant cannot (bot-checked web forms,
               social media, everything else), each with its prize category, Open button, approved answer with a
               Copy button, and a Done tick kept in the phone's browser storage and synced (data/entries/done.json).
  Auto-entered the auto-entry register: every competition entered automatically, how many times, when last, with a
               Re-enter button and multi-select to re-enter several at once.
  Approvals    skill competitions: approved answers not entered yet (Submit now, or Submit all approved) and those
               waiting for the owner's answer (Write answer / Edit answer: an in-page editor, saved by
               workers/answers.py within the word limit).
Every button sends POST /api/action (azure/site-api, a Static Web Apps managed API); the API queues it and the
Container Apps job lotto-actions applies it (workers/actions.py).  There is no login anywhere on the site: every tab and
button always works, and the public API protects itself with strict validation, size limits and a per-client-IP cap
(429 when exceeded).  main() also writes staticwebapp.config.json (SWA_CONFIG), which 404s every /.auth/login/* provider.
  Winners      draw date, how winners are told, claim deadline and winners page for every auto-entered comp and every
               comp ticked Done (data/entries/winners.csv from workers/winners.py), with a flag when the owner's
               surname was seen on a published winners page.
  Freebies     free stuff for Victoria from OzBargain's Freebies listing (workers/freebies.py, rebuilt with the site).
Closing times are the promoter's stated time where the listing gives one (entry_queue.closes_at).
The repository is public, so the page holds no personal details.
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from workers import answers, chance, comp_odds, comps, entry_pages, entry_queue

ROOT = comps.ROOT
ENTRIES = ROOT / "data" / "entries"
FREEBIES = ROOT / "data" / "freebies" / "freebies.csv"
OUT = ROOT / "site"
DONE = "done.json"
# Written next to index.html as staticwebapp.config.json.  tools/cost_guard.py (C12) reads this literal: no login is
# offered (every /.auth/login/* provider 404s, GitHub included), and the runtime must match limits.json.  Pages and the
# API are public; the API's own abuse caps (azure/site-api/lotto_actions.py) are checked by the guard.
SWA_CONFIG = {
    "routes": [
        {"route": "/.auth/login/github", "statusCode": 404},
        {"route": "/.auth/login/aad", "statusCode": 404},
        {"route": "/.auth/login/google", "statusCode": 404},
        {"route": "/.auth/login/twitter", "statusCode": 404},
        {"route": "/.auth/login/facebook", "statusCode": 404},
        {"route": "/.auth/login/apple", "statusCode": 404},
    ],
    "platform": {"apiRuntime": "python:3.11"},
    "globalHeaders": {"X-Content-Type-Options": "nosniff"},
}
MELB = ZoneInfo("Australia/Melbourne")
CATEGORIES = [   # first match wins, on the title (AusComps notes stripped); then the aggregator's own category
    ("Prize homes & lotteries", r"prize home|\bhouse\b|apartment|penthouse|lottery|art union|raffle|dream home|"
                                r"\bhome lottery"),
    ("Cars & vehicles", r"\bcars?\b|\bute\b|4wd|4x4|e-?bike|\bbikes?\b|motorcycle|motorbike|caravan|camper|\bboat\b|"
                        r"scooter|vehicle|landcruiser|prado|rav4|harley|\branger\b|hilux|porsche|ferrari|lamborghini|"
                        r"\bbmw\b|tesla|mercedes|\baudi\b|toyota|mazda|hyundai|\bkia\b|volkswagen|\bjeep\b|jet ?ski"),
    # strong travel words first, so "a family trip to see The Wiggles" is travel ...
    ("Travel", r"\btrips?\b|holiday|getaway|cruise|flights?\b|resort|\bnights?\b|travel voucher|retreat|\bstay\b|"
               r"\bvacation"),
    # ... but "double passes to the ... Australian tour" is tickets
    ("Tickets & experiences", r"tickets?\b|passes\b|\bpass\b|\bdps?\b|concert|festival|experience|\bvip\b|screening|"
                              r"preview|premiere|movie|\bfilms?\b|cinema|\bshows?\b|musical|theatre|theater|symphony|"
                              r"opera|\bgig\b|grand final|\bmatch\b|courtside|race ?day|\brace\b|membership|"
                              r"\bseats?\b|meet (?:&|and) greet"),
    # a voucher, gift card or cash prize; a bare "$500" in "Products worth $500" is not cash
    ("Cash & vouchers", r"\bcash\b|gift ?cards?|e-?gift|vouchers?|eftpos|store credit|prepaid|\bvisa card|shopping spree|"
                        r"^(?:[^–-]*[–-]\s*)?win (?:a |an )?(?:share of )?\$\d[\d,.]*\s?(?:k|m|million)?\s*"
                        r"(?:$|every|each|a |per |for |drawn|\+|&|plus)"),
    ("Travel", r"\bescape\b|adventure|\btour\b|island|travel|suitcase|luggage"),
    ("Tech & gaming", r"\btvs?\b|laptop|\bphones?\b|iphone|samsung|playstation|ps5|xbox|nintendo|console|camera|"
                      r"headphones|earbuds|airpods|speaker|tablet|ipad|gaming|\bpc\b|drone|smart ?watch|blu-?ray|"
                      r"robot|intel\b|\bcpu\b|\bgpu\b|graphics card|monitor|keyboard|\bmouse\b|computer|macbook|"
                      r"apple watch|garmin|projector|soundbar"),
    ("Home & garden", r"sofa|\bbed\b|bedroom|bedding|kitchen|appliance|vacuum|fridge|freezer|bbq|garden|\bpool\b|"
                      r"furniture|mattress|cookware|air fryer|steamer|homewares|bathroom|renovat|playroom|\bdesk\b|"
                      r"\brug\b|lawn ?mower|cleaning|candle|diffuser|\btools?\b|power tools|coffee machine|blender|sheets?\b|"
                      r"linen|towels?\b|quilt|\bthrow\b|slush|mixers?\b|ev charger|solar|heater|\bfan\b"),
    ("Fashion & beauty", r"wardrobe|fashion|clothing|apparel|\bshoes?\b|sneakers|boots\b|jewellery|jewelry|"
                         r"\brings?\b|\bwatch\b|handbag|\bbags?\b|wallet|beauty|skin ?care|makeup|fragrance|perfume|"
                         r"\bhair\b|swimwear|merch|grooming|\bface\b|\bbody\b|serum|cosmetic|sunglasses|tee\b|"
                         r"t-?shirt|hoodie"),
    ("Kids & baby", r"\bbaby\b|\bkids?\b|toddler|infant|newborn|colic|\bpram\b|\btoys?\b|lego|plush|nursery|"
                    r"parenting|school|wiggles|bluey"),
    ("Food & drink", r"food|grocer|hamper|wine|\bbeer\b|whisky|whiskey|spirits|\bgin\b|coffee|chocolate|dinner|"
                     r"restaurant|snack|pantry|dining|\bchef\b|\bnuts\b|cheese|\btea\b|\bbbq sauce|meal"),
    ("Books & media", r"\bbooks?\b|novel|reading copy|\bcopy of\b|audiobook|vinyl|\balbum\b|\bdvds?\b|"
                      r"magazine|puzzler|box ?set|\bguitar\b|instrument"),
]
SLUG_CATEGORY = {"cash-competitions": "Cash & vouchers", "travel-competitions": "Travel",
                 "home-garden-competitions": "Home & garden", "home-appliances": "Home & garden",
                 "experience-competitions": "Tickets & experiences", "ticket-competitions": "Tickets & experiences",
                 "car-competitions": "Cars & vehicles", "electronics-competitions": "Tech & gaming",
                 "gaming-competitions": "Tech & gaming", "phone-competitions": "Tech & gaming",
                 "baby-competitions": "Kids & baby", "food-competitions": "Food & drink",
                 "fashion-competitions": "Fashion & beauty", "beauty-competitions": "Fashion & beauty",
                 "charity-competitions": "Prize homes & lotteries", "win-a-house": "Prize homes & lotteries"}
GROUP_NAMES = {"web": "Web form with a human check", "social": "Social media", "other": "Other entry"}


def category(title, slug=None):
    title = comps.clean_title(title)
    for name, pat in CATEGORIES:
        if re.search(pat, title or "", re.I):
            return name
    return SLUG_CATEGORY.get(slug or "", "Other")


def group_of(reason, platform, url):
    if platform in ("facebook", "instagram", "tiktok", "x", "youtube") or \
            re.search(r"(?i)//(?:[\w-]+\.)?(?:facebook|instagram|tiktok|threads)\.(?:com|net)/|//(?:www\.)?fb\.(?:com|me)/", url or ""):
        return "social"
    if any(k in reason for k in ("captcha", "human_check", "failing", "no_form", "unfillable", "login",
                                 "terms ban")) or "/pages/" in (url or ""):
        return "web"
    return "other"


def why(reason):
    r = reason.replace("entrant blocked: ", "")
    if r.startswith("entry link "):
        return {"dead": "entry link dead", "moved": "entry link goes to the home page",
                "home": "entry link is the shop's home page", "wrong": "entry page is not this competition"}.get(r.split()[2], r)
    return {"captcha": "human check (CAPTCHA)", "human_check": "the site's bot check", "no_form": "form not reachable",
            "unfillable": "a field only you can answer", "login": "needs a login",
            "blocked": "the site blocks automated browsers",
            "moved": "entry page moved or gone",
            "entry route manual": "manual entry", "entry route unknown": "entry method unclear",
            "terms ban automated entry": "terms ban automated entry"}.get(r, r if not r.startswith("failing") else
                                                                          "the auto-entrant failed here")


def melb(utc_text):
    """'2026-10-30 19:31' (UTC) as Melbourne time, e.g. 'Sat 31 Oct, 6:31am'."""
    t = dt.datetime.strptime(utc_text, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).astimezone(MELB)
    return t.strftime("%a %d %b, %I:%M%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")


ROLLING = r"(?i)drawn monthly|monthly draws?|draws? (?:each|every) (?:month|week)|ongoing (?:promotion|competition)|no end date"


def close_of(rec, fallback=""):
    """(Melbourne closing date, closing time) from the listing; the time only when the summary states one, and
    "ongoing" for rolling monthly/weekly draws that state no end date (audit 31 Oct: invented end dates)."""
    t = entry_queue.closes_at(rec) if rec else None
    if not t:
        return fallback[:10], ""
    desc = (rec or {}).get("description") or ""
    stated = re.search(entry_queue.STATED_CLOSE, desc)
    rolling = re.search(ROLLING, desc) and not re.search(entry_queue.CLOSE_DATE, desc)
    t = t.astimezone(MELB)
    return t.date().isoformat(), ("ongoing draws" if rolling else t.strftime("%I:%M%p").lstrip("0").lower() if stated else "")


def removed(entries=ENTRIES):
    """Ids the owner removed (data/entries/log_removed.jsonl, written by workers/removals.py)."""
    path = entries / "log_removed.jsonl"
    rows = (json.loads(l) for l in path.read_text().splitlines() if l.strip()) if path.exists() else ()
    return {str(r["id"]) for r in rows if r.get("result") == "removed"}


def load_answers(entries=ENTRIES):
    path = entries / "answers.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_done(entries=ENTRIES):
    """The synced Done ticks {id: epoch ms} (data/entries/done.json, written by workers/actions.py)."""
    path = entries / DONE
    try:
        doc = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}
    return {str(k): int(v) for k, v in doc.items() if isinstance(v, (int, float))} if isinstance(doc, dict) else {}


def _num(x):
    try:
        return float(x) if x not in (None, "") else 0.0
    except ValueError:
        return 0.0


def records():
    return {str(r["id"]): r for r in (json.loads(l)["comp"] for l in comps.stored(comps.STORE).values())}


def items(entries=ENTRIES, today=None, recs=None, pages=None):
    """The 'To enter' list. pages: workers/entry_pages.py results; a link that only opens the terms gets the "To enter"
    sentence on the card, and the entry page when one was found."""
    today = (today or dt.date.today()).isoformat()
    ans, recs = load_answers(entries), recs if recs is not None else records()
    pages = pages if pages is not None else entry_pages.latest()
    path = entries / "manual.csv"
    out = []
    for r in (csv.DictReader(open(path)) if path.exists() else []):
        rec = recs.get(r["id"], {})
        closes, at = close_of(rec, r.get("closes") or "")
        if closes and closes < today or not r.get("entry_url"):
            continue
        pv, est = comps.prize_value(rec or r)
        pg = pages.get(int(r["id"]), {}) if str(r["id"]).isdigit() else {}
        terms, bad = pg.get("kind") == "terms", entry_pages.BAD.get(pg.get("kind"))
        out.append({"id": r["id"], "t": comps.clean_title(r["title"]), "b": r.get("brand") or "", "p": pv or 0, "pe": est,
                    "c": closes, "ct": at,
                    "u": (rec.get("url") if bad else None) or (terms and pg.get("better_url")) or r["entry_url"],
                    "bad": bad or "", "orig": r["entry_url"] if bad else "",
                    "tu": r["entry_url"] if terms else "", "how": pg.get("how") if terms else "",
                    "w": why(r.get("reason") or ""),
                    "g": group_of(r.get("reason") or "", r.get("entry_platform") or "", r["entry_url"]),
                    "k": category(r["title"], rec.get("category_slug")), "a": ans.get(str(r["id"])),
                    "s": rec.get("source_site") or "competitions.com.au"})
    return out


def autos(entries=ENTRIES, today=None, recs=None):
    """The 'Auto-entered' list: the register (competitions the entrant has actually entered)."""
    today = (today or dt.date.today()).isoformat()
    ans, recs = load_answers(entries), recs if recs is not None else records()
    path = entries / "register.csv"
    out, seen = [], set()
    for r in (csv.DictReader(open(path)) if path.exists() else []):
        seen.add(r["id"])
        pv, est = comps.prize_value(recs.get(r["id"]) or r)
        out.append({"id": r["id"], "t": comps.clean_title(r["title"]), "b": r.get("brand") or "", "p": pv or 0, "pe": est,
                    "c": entry_queue.close_date(recs[r["id"]]) if r["id"] in recs else r.get("closes") or "",
                    "u": r.get("entry_url") or "", "n": int(r["entries"]),
                    "l": melb(r["last_entered_utc"]), "k": category(r["title"], recs.get(r["id"], {}).get("category_slug")),
                    "a": ans.get(r["id"]), "open": (r.get("closes") or "9") >= today})
    return out


def approvals(entries=ENTRIES, today=None, recs=None):
    """The 'Approvals' list: skill competitions with an approved answer not entered yet ("ok"), and those the
    auto-entrant could enter once the owner writes an answer ("need", from the queue)."""
    today = (today or dt.date.today()).isoformat()
    ans, recs = load_answers(entries), recs if recs is not None else records()
    reg = entries / "register.csv"
    entered = {r["id"] for r in csv.DictReader(open(reg))} if reg.exists() else set()
    queued = {}
    if (entries / "queue.csv").exists():
        queued = {r["id"]: r for r in csv.DictReader(open(entries / "queue.csv")) if r.get("needs_answer") == "True"}
    manual = {r["id"] for r in csv.DictReader(open(entries / "manual.csv"))} if (entries / "manual.csv").exists() else set()
    out = []
    for k in list(dict.fromkeys([*ans, *queued])):
        rec = recs.get(k)
        if not rec or k in entered or (entry_queue.close_date(rec) or "9") < today:
            continue
        q = answers.question(rec, (queued.get(k) or {}).get("question"))
        pv, est = comps.prize_value(rec)
        out.append({"id": k, "t": comps.clean_title(rec["title"]), "b": rec.get("brand") or "", "p": pv or 0, "pe": est,
                    "c": entry_queue.close_date(rec), "u": rec.get("entry_url") or "", "q": q,
                    "lim": answers.word_limit(q), "a": ans.get(k), "st": "ok" if k in ans else "need",
                    "hand": k in manual,
                    "k": category(rec["title"], rec.get("category_slug"))})
    return out


def winners(entries=ENTRIES, recs=None):
    """The 'Winners' list (all tracked comps; the page shows the auto-entered and the ones ticked Done)."""
    path = entries / "winners.csv"
    if not path.exists():
        return []
    recs = recs if recs is not None else records()
    value = lambda r: comps.prize_value(recs.get(r["id"]) or r)
    return [{"id": r["id"], "t": comps.clean_title(r["title"]), "b": r.get("brand") or "", "p": value(r)[0] or 0,
             "pe": value(r)[1],
             "c": r.get("draw_date") or r.get("closes") or "", "cl": r.get("closes") or "", "n": int(r.get("auto_entries") or 0),
             "st": r["status"], "est": r.get("draw_estimated") == "True", "h": r.get("notify") or "",
             "nw": r.get("notify_within_days") or "", "cw": r.get("claim_within_days") or "", "cb": r.get("claim_by") or "",
             "wp": r.get("winners_page") or "", "pn": r.get("published_note") or "", "seen": r.get("name_seen") or "",
             "u": r.get("url") or "", "k": category(r["title"])}
            for r in csv.DictReader(open(path))]


def freebies(path=FREEBIES):
    if not path.exists():
        return []
    return [{"t": r["title"], "u": r["url"], "c": r.get("posted") or "", "k": r.get("kind") or "Freebie",
             "d": " · ".join(x for x in (r.get("store"), ("ends " + r["expires"]) if r.get("expires") else "",
                                         f'{r.get("votes") or 0} votes', r.get("summary")) if x)}
            for r in csv.DictReader(open(path))]


def stats(entries=ENTRIES):
    ids, n = set(), 0
    for path in sorted(entries.glob("log*.jsonl")):
        for x in (json.loads(l) for l in path.read_text().splitlines() if l.strip()):
            if x.get("mode") == "live" and x.get("result") == "entered":
                n += 1
                ids.add(x["id"])
    return {"entries": n, "comps": len(ids)}


def add_chance(data, recs, today=None):
    """Chance-of-winning estimate on every competition card (workers/chance.py): "ch" the estimate, "cb" its band
    among the competitions on the page, "cw" the number of prizes."""
    scores, extra = {}, {}
    for key in ("todo", "auto", "appr"):
        for x in data[key]:
            rec = recs.get(str(x["id"]))
            if rec and x["id"] not in scores:
                s, kind, n = chance.estimate(rec, comp_odds.assess(rec), today)
                scores[x["id"]], extra[x["id"]] = s, n
    band = chance.bands(scores)
    for key in ("todo", "auto", "appr"):
        for x in data[key]:
            if x["id"] in scores:
                x.update(ch=scores[x["id"]], cb=band[x["id"]], cw=extra[x["id"]],
                         why=chance.reason(recs[str(x["id"])], today=today))


def page(entries=ENTRIES, today=None, built=None, freebie_path=FREEBIES):
    recs = records()
    gone = removed(entries)
    data = {"todo": [x for x in items(entries, today, recs) if x["id"] not in gone],
            "auto": [x for x in autos(entries, today, recs) if x["id"] not in gone], "free": freebies(freebie_path),
            "appr": [x for x in approvals(entries, today, recs) if x["id"] not in gone],
            "win": [x for x in winners(entries, recs) if x["id"] not in gone], "removed": len(gone),
            "done": load_done(entries),
            "stats": stats(entries), "groups": GROUP_NAMES, "categories": list(dict.fromkeys(c for c, _ in CATEGORIES)) + ["Other"],
            "built": built or dt.datetime.now(MELB).strftime("%a %d %b, %I:%M%p").replace(" 0", " ")}
    add_chance(data, recs)
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", blob)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comp Quest</title><meta name="theme-color" content="#1a0b2e">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bungee&family=Space+Grotesk:wght@400;500;700&family=VT323&display=swap" rel="stylesheet">
<style>
/* Gamer-chic retro: purple fuzz, neon orange, paint splatter. Dark by design. */
:root{--bg:#1a0b2e;--bg2:#2b1150;--card:#241042;--card2:#2f1658;--ink:#f6efff;--muted:#bba6d9;--line:#4a2a7a;
  --orange:#ff6b1a;--orange2:#ffa040;--purple:#b44dff;--pink:#ff3ea5;--lime:#c6ff3d;--accent:var(--orange);--chip:#341a5e;--warn:#ffb347}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;color:var(--ink);font:16px/1.5 "Space Grotesk",system-ui,sans-serif;min-height:100vh;
  background:
    radial-gradient(1200px 600px at 110% -10%,rgba(180,77,255,.35),transparent 60%),
    radial-gradient(900px 500px at -20% 30%,rgba(255,107,26,.18),transparent 60%),
    radial-gradient(700px 700px at 50% 120%,rgba(255,62,165,.18),transparent 60%),var(--bg)}
/* fuzz: fine grain over everything */
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.16;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
/* paint splatter */
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.55;
  background:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Cpath fill='%23ff6b1a' d='M100 30c18 0 22 22 40 26s34-8 36 10-22 20-20 38 26 30 12 44-30-6-46 2-18 32-36 28-8-30-24-38-40 2-42-16 24-20 22-38-24-30-10-42 30 8 44 0 6-14 24-14z'/%3E%3Ccircle cx='182' cy='34' r='7' fill='%23ff6b1a'/%3E%3Ccircle cx='24' cy='178' r='5' fill='%23ff6b1a'/%3E%3Ccircle cx='170' cy='176' r='3' fill='%23ff6b1a'/%3E%3C/svg%3E") -60px -50px/230px no-repeat,
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Cpath fill='%23b44dff' d='M96 22c14 6 8 30 26 34s30-16 40-2-12 26 0 40 34 6 30 26-30 10-38 26 8 36-10 40-20-24-38-22-30 26-44 14 8-30-6-42-40-4-38-22 30-12 30-30-24-36-6-44 26 18 40 12 14-36 34-28z'/%3E%3Ccircle cx='20' cy='30' r='6' fill='%23b44dff'/%3E%3Ccircle cx='186' cy='150' r='8' fill='%23b44dff'/%3E%3C/svg%3E") calc(100% + 70px) 38%/260px no-repeat,
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Cpath fill='%23ff3ea5' d='M104 40c12 4 6 24 22 28s28-10 32 4-18 18-10 32 30 14 22 28-28-2-38 10 0 32-16 30-12-26-26-26-28 20-38 8 10-24-2-36-34-14-26-28 30 0 34-14-14-30 0-36 22 12 34 6 0-10 12-6z'/%3E%3Ccircle cx='160' cy='30' r='5' fill='%23ff3ea5'/%3E%3C/svg%3E") -70px calc(100% + 60px)/240px no-repeat}
header,main,.bar{position:relative;z-index:1}
header{background:transparent;border-bottom:2px solid var(--purple)}
.wrap{max-width:820px;margin:0 auto;padding:14px 16px}
h1{font-family:Bungee,"Space Grotesk",sans-serif;font-weight:400;font-size:1.7rem;letter-spacing:.02em;margin:0;line-height:1.1;
  color:var(--orange);text-shadow:0 0 10px rgba(255,107,26,.7),3px 3px 0 var(--purple)}
.sub,.meta,.hint{color:var(--muted);font-size:.88rem}
.tabs{display:flex;gap:8px;margin:12px 0 10px;overflow-x:auto;scrollbar-width:none;padding:2px 2px 6px}
.tab{flex:1 0 auto;padding:9px 12px;border-radius:12px;border:2px solid var(--line);background:#241042;color:var(--ink);
  font:inherit;font-weight:700;letter-spacing:.02em;cursor:pointer;box-shadow:3px 3px 0 #0b0418}
.tab[aria-selected=true]{background:var(--orange);color:#1a0b2e;border-color:var(--orange2);box-shadow:3px 3px 0 var(--purple),0 0 16px rgba(255,107,26,.6)}
input[type=search],select{font:inherit;padding:10px 12px;border-radius:12px;border:2px solid var(--line);background:var(--bg2);color:var(--ink)}
input[type=search]:focus,select:focus{outline:none;border-color:var(--orange);box-shadow:0 0 0 3px rgba(255,107,26,.25)}
input[type=search]{width:100%}input::placeholder{color:var(--muted)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.row>*{flex:1 1 auto}
.chips{display:flex;gap:8px;overflow-x:auto;padding:10px 0 4px;scrollbar-width:none}
.chip{white-space:nowrap;padding:6px 12px;border-radius:999px;border:2px solid var(--purple);background:transparent;color:var(--ink);font:inherit;font-size:.85rem;cursor:pointer}
.chip[aria-pressed=true]{background:var(--purple);color:#fff;box-shadow:0 0 12px rgba(180,77,255,.7)}
ul{list-style:none;padding:0;margin:0}
.card{background:linear-gradient(160deg,var(--card2),var(--card));border:2px solid var(--line);border-radius:16px;padding:14px 16px;margin:14px 0;
  box-shadow:5px 5px 0 #0b0418,0 0 0 1px rgba(180,77,255,.15) inset;transition:transform .12s,box-shadow .12s}
.card:hover{transform:translate(-2px,-2px);box-shadow:7px 7px 0 var(--purple),0 0 22px rgba(255,107,26,.25)}
.top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.prize{font-family:Bungee,sans-serif;font-weight:400;font-size:1.15rem;color:var(--orange);text-shadow:0 0 8px rgba(255,107,26,.55)}
.soon{color:var(--lime);font-weight:700;text-shadow:0 0 8px rgba(198,255,61,.45)}
.title{display:block;font-weight:700;font-size:1.05rem;color:var(--ink);text-decoration:none;margin:6px 0}
.title:hover{color:var(--orange2)}
.tag{display:inline-block;font-size:.74rem;font-weight:700;padding:3px 9px;border-radius:999px;background:var(--chip);color:var(--muted);margin:2px 4px 2px 0;letter-spacing:.02em}
.tag.ch-high{background:var(--orange);color:#1a0b2e;box-shadow:0 0 10px rgba(255,107,26,.7)}
.tag.ch-medium{background:var(--purple);color:#fff}
.tag.ch-low{background:transparent;border:1px solid var(--line)}
.acts{display:flex;flex-wrap:wrap;justify-content:flex-start;align-items:center;gap:8px;margin-top:12px}.acts .done{margin-left:auto}
.go{background:var(--orange);color:#1a0b2e;text-decoration:none;padding:9px 14px;border-radius:10px;font:inherit;font-weight:700;border:0;
  box-shadow:3px 3px 0 var(--purple);cursor:pointer}
.go:active,.ghost:active{transform:translate(2px,2px);box-shadow:1px 1px 0 var(--purple)}
.ghost{background:transparent;color:var(--orange2);border:2px solid var(--orange);padding:7px 12px;border-radius:10px;font:inherit;font-weight:700;text-decoration:none;cursor:pointer}
a{color:var(--orange2)}
.done{display:flex;gap:6px;align-items:center}.done input{width:22px;height:22px;accent-color:var(--orange)}
.card.is-done{opacity:.45}.card.is-done .title{text-decoration:line-through}
.ans{background:rgba(11,4,24,.55);border:1px dashed var(--purple);border-radius:12px;padding:10px 12px;margin:10px 0}.ans p{margin:0 0 8px}
.bar{position:sticky;bottom:0;background:var(--bg2);border-top:2px solid var(--orange);padding:10px 16px;display:none;box-shadow:0 -6px 20px rgba(255,107,26,.25)}
.bar.show{display:flex;justify-content:space-between;align-items:center;gap:8px}
.empty{color:var(--muted);text-align:center;padding:30px 0}
#count .go{display:inline-block;margin:8px 0 2px}
/* tickets: stub (number, prize, chance meter and why) | perforation | body */
.t{display:grid;grid-template-columns:112px 1fr;margin:14px 0;filter:drop-shadow(5px 6px 0 #0b0418)}
.stub{background:var(--orange);color:#1a0b2e;padding:10px 9px;display:flex;flex-direction:column;justify-content:space-between;gap:8px;border-radius:12px 0 0 12px;
 -webkit-mask:radial-gradient(circle 9px at 100% 0,#0000 98%,#000) top/100% 51% no-repeat,radial-gradient(circle 9px at 100% 100%,#0000 98%,#000) bottom/100% 51% no-repeat;
 mask:radial-gradient(circle 9px at 100% 0,#0000 98%,#000) top/100% 51% no-repeat,radial-gradient(circle 9px at 100% 100%,#0000 98%,#000) bottom/100% 51% no-repeat}
.stub .no{font:400 16px VT323;opacity:.75}.stub .p{font:400 18px/1.05 Bungee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stub .l{font:700 10px "Space Grotesk";letter-spacing:.07em;text-transform:uppercase}
.why{display:block;font:500 11px/1.25 "Space Grotesk";letter-spacing:0;text-transform:none;margin-top:2px}
.mt{font:400 24px/1 VT323;letter-spacing:1px}.mt em{font-style:normal;opacity:.3}
.body{background:linear-gradient(160deg,var(--card2),var(--card));border-left:3px dashed var(--orange);border-radius:0 12px 12px 0;padding:10px 12px;min-width:0;
 -webkit-mask:radial-gradient(circle 9px at 0 0,#0000 98%,#000) top/100% 51% no-repeat,radial-gradient(circle 9px at 0 100%,#0000 98%,#000) bottom/100% 51% no-repeat;
 mask:radial-gradient(circle 9px at 0 0,#0000 98%,#000) top/100% 51% no-repeat,radial-gradient(circle 9px at 0 100%,#0000 98%,#000) bottom/100% 51% no-repeat}
.body .title{font-size:15px;margin:3px 0 4px}.body .when{font-size:12.5px;font-weight:700;color:var(--lime)}
.t.is-done{opacity:.45}.t.is-done .title{text-decoration:line-through}
.t .acts{margin-top:8px;gap:6px}.t .go{background:var(--purple);color:#fff;padding:7px 12px;box-shadow:3px 3px 0 #0b0418}
.ic{display:inline-grid;place-items:center;width:36px;height:34px;border-radius:9px;color:var(--orange2);font-size:18px;font-weight:700;text-decoration:none;cursor:pointer;border:2px solid transparent}
.ic:hover,.ic:focus-visible{border-color:var(--orange)}.ic input{position:absolute;opacity:0;pointer-events:none}
.ic:has(input:checked){background:var(--lime);color:#1a0b2e}
.t .acts .sel{margin-left:auto}
button.ic{background:transparent;font-family:inherit;padding:0}
button[disabled]{opacity:.5;cursor:default}
.editor{margin:10px 0}.editor textarea{width:100%;min-height:96px;font:inherit;padding:10px 12px;border-radius:12px;border:2px solid var(--line);background:var(--bg2);color:var(--ink)}
.editor textarea:focus{outline:none;border-color:var(--orange)}.editor .over{color:var(--pink);font-weight:700}
#toast{position:fixed;left:50%;bottom:78px;transform:translateX(-50%);max-width:92vw;background:var(--bg2);color:var(--ink);border:2px solid var(--orange);
  border-radius:12px;padding:10px 14px;z-index:5;box-shadow:4px 4px 0 var(--purple);display:none;font-size:.92rem}
#toast.show{display:block}
/* best shot today: the top pick as a paint splat */
.hero{margin:18px 0 8px;position:relative;padding:24px 20px 20px;color:#1a0b2e;isolation:isolate}
.hero::before{content:"";position:absolute;inset:-12px -6px;z-index:-1;background:var(--orange);
 clip-path:polygon(4% 9%,22% 0,41% 6%,63% 1%,86% 7%,100% 24%,96% 47%,100% 71%,90% 94%,66% 100%,44% 93%,20% 99%,3% 86%,0 60%,5% 38%,0 20%)}
.hero .kick{font:400 12px Bungee;letter-spacing:.06em}.hero h2{font:400 clamp(19px,4.6vw,26px)/1.1 Bungee;margin:8px 0}
.hero h2 a{color:inherit;text-decoration:none}.hero .info{font-weight:600}
.hero .bt{display:inline-block;background:#1a0b2e;color:var(--orange);font:400 14px Bungee;padding:9px 14px;border-radius:999px;margin-top:10px;text-decoration:none}
</style></head><body>
<header><div class="wrap">
<h1>Comp Quest</h1><div class="sub" id="summary"></div>
<div class="tabs" role="tablist"><button class="tab" data-tab="todo">To enter</button><button class="tab" data-tab="social">Social</button><button class="tab" data-tab="auto">Entered</button><button class="tab" data-tab="appr">Approvals</button><button class="tab" data-tab="win">Winners</button><button class="tab" data-tab="free">Freebies</button></div>
<input type="search" id="q" placeholder="Search prize, brand or title">
<div class="chips" id="cats"></div>
<div class="row" style="margin-top:6px">
<select id="grp"><option value="">All entry types</option></select>
<select id="close"><option value="">Any close date</option><option value="0">Closes today</option><option value="7">This week</option><option value="30">This month</option></select>
<select id="min"><option value="0">Any prize</option><option value="0-500">Under $500</option><option value="500-2000">$500 to $2K</option><option value="2000-10000">$2K to $10K</option><option value="10000-50000">$10K to $50K</option><option value="50000-1e12">$50K and up</option></select>
<select id="sort"><option value="chance">Best chance</option><option value="close">Closing soonest</option><option value="prize">Biggest prize</option><option value="az">A to Z</option></select>
</div>
<label class="done hint" style="margin-top:8px"><input type="checkbox" id="hide"> Hide done</label>
</div></header>
<main class="wrap"><div class="sub" id="count"></div><ul id="list"></ul></main>
<div class="bar" id="bar"><span id="selcount"></span><button type="button" class="ghost" id="rmselect" data-act="rmsel">Remove selected</button><button type="button" class="go" id="reselect" data-act="resel">Re-enter selected</button></div>
<div id="toast" role="status" aria-live="polite"></div>
<script>
const D = __DATA__;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
                 set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
let S = Object.assign({ tab: "todo", q: "", cats: [], grp: "", close: "", min: "0", sort: "chance", hide: false }, store.get("comps-ui", {}));
if (!/^(0|[\d.e]+-[\d.e]+)$/.test(S.min)) S.min = "0";   // the old "500+"-style choices are gone
// Done ticks: this phone's (comps-done, comps-undone = unticked at that time) merged with the synced ones (D.done); the latest wins.
const done = () => { const s = D.done || {}, l = store.get("comps-done", {}), u = store.get("comps-undone", {}), out = {};
  for (const id of new Set([...Object.keys(s), ...Object.keys(l)])) { const t = Math.max(s[id] || 0, l[id] || 0); if (t > (u[id] || 0)) out[id] = t; }
  return out; };
const sel = new Set();
const today = new Date(); today.setHours(0, 0, 0, 0);
const days = (c) => c ? Math.round((new Date(c.slice(0, 10) + "T00:00:00") - today) / 864e5) : 9999;
const chanceTag = (x) => x.cb ? `<span class="tag ch-${x.cb}" title="Estimated from the number of prizes, the prize size, how much effort entering takes and how long it runs. A ranking, not real odds.">${x.cb} chance${x.cw > 1 ? ` · ${x.cw} prizes` : ""}</span>` : "";
const nice = (c) => { const t = new Date(c.slice(0, 10) + "T00:00:00"); return isNaN(t) ? esc(c) : t.toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" }) + (t.getFullYear() !== new Date().getFullYear() ? " " + t.getFullYear() : ""); };
const money = (p, est) => p ? (est ? "~$" : "$") + Math.round(p).toLocaleString("en-AU") : "prize n/a";   // ~ = estimated from the title
const gone = () => store.get("comps-removed", {});
const pending = () => store.get("comps-pending", {});    // re-entries sent from this phone: id -> time
const isPending = (id) => Date.now() - (pending()[id] || 0) < 15 * 60 * 1000;
const BLOCKS = { high: 5, medium: 3, low: 1 };
const meter = (x) => { const k = BLOCKS[x.cb] || 0; return `<span class="mt" aria-label="${esc(x.cb || "unknown")} chance">${"▮".repeat(k)}<em>${"▯".repeat(5 - k)}</em></span>`; };
const stub = (x) => `<div class="stub"><div><div class="no">No. ${esc(String(x.id).slice(-5))}</div><div class="p">${money(x.p, x.pe)}</div></div>
  <div title="Estimated from the number of prizes, the prize size, how much effort entering takes and how long it runs. A ranking, not real odds.">${meter(x)}<div class="l">${esc(x.cb || "unrated")} chance<span class="why">${esc(x.why || "")}</span></div></div></div>`;
const icons = (x) => `<button type="button" class="ic rm" data-act="remove" data-ids="${esc(x.id)}" title="Remove: not for me" aria-label="Remove">✕</button>` +
  `<button type="button" class="ic rm" data-act="broken" data-ids="${esc(x.id)}" title="Doesn't work" aria-label="Doesn't work">⚠</button>`;
const enterBtn = (ids, label, cls = "go") => ids.every(isPending) ? `<span class="meta">Queued</span>` : `<button type="button" class="${cls}" data-act="reenter" data-ids="${esc(ids.join(" "))}">${label}</button>`;
const words = (t) => (String(t).match(/[\w'’-]+/g) || []).length;
const drafts = {}, editing = new Set();                  // answer text not sent yet, and the open editors
const editor = (x) => `<div class="editor"><textarea data-draft="${esc(x.id)}" maxlength="2000" aria-label="Your answer">${esc(drafts[x.id] ?? x.a ?? "")}</textarea>
  <div class="meta" data-count="${esc(x.id)}">${words(drafts[x.id] ?? x.a ?? "")} of ${x.lim} words</div>
  <div class="acts"><button type="button" class="go" data-act="save-answer" data-id="${esc(x.id)}">Save answer</button><button type="button" class="ghost" data-act="cancel-answer" data-id="${esc(x.id)}">Cancel</button></div></div>`;
const doneBox = (id, on) => `<label class="ic" title="Done" aria-label="Done"><input type="checkbox" class="tick" data-id="${esc(id)}" ${on ? "checked" : ""}>✓</label>`;
const hero = (x) => `<section class="hero"><div class="kick">Best shot today</div><h2><a href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a></h2>
  <div class="info">${money(x.p, x.pe)} · ${meter(x)} ${esc(x.cb || "")} chance${x.why ? " · " + esc(x.why) : ""}</div><a class="bt" href="${esc(x.u)}" target="_blank" rel="noopener">Enter now →</a></section>`;
$("#summary").textContent = `${D.todo.length} to enter by hand · ${D.stats.entries} auto-entries in ${D.stats.comps} comps` + (D.removed ? ` · ${D.removed} removed` : "") + ` · updated ${D.built}`;
for (const [k, v] of Object.entries(D.groups)) $("#grp").insertAdjacentHTML("beforeend", `<option value="${k}">${esc(v)}</option>`);
const pool = () => S.tab === "todo" ? D.todo.filter((x) => x.g !== "social") : S.tab === "social" ? D.todo.filter((x) => x.g === "social") : S.tab === "auto" ? D.auto : S.tab === "appr" ? D.appr : S.tab === "win" ? D.win.filter((x) => x.n || done()[x.id] || x.seen === "yes") : D.free;
function chips() {
  const src = S.tab === "free" ? [...new Set(D.free.map((x) => x.k))] : D.categories;
  $("#cats").innerHTML = src.map((c) => { const n = pool().filter((x) => x.k === c).length;
    return n ? `<button class="chip" data-cat="${esc(c)}" aria-pressed="${S.cats.includes(c)}">${esc(c)} ${n}</button>` : ""; }).join("");
}
function card(x) {
  const d = days(x.c), soon = d <= 2 ? "soon" : "";
  const ans = x.a ? `<div class="ans"><p>${esc(x.a)}</p><button class="ghost copy" data-copy="${esc(x.a)}">Copy answer</button></div>` : "";
  const at = x.ct ? " " + esc(x.ct) : "";
  const when = x.ct === "ongoing draws" ? `<span>ongoing draws</span>` : x.c ? `<span class="${soon}">${d === 0 ? "closes today" + at : d === 1 ? "closes tomorrow" + at : "closes " + nice(x.c)}</span>` : "";
  if (S.tab === "win") {
    const st = x.seen === "yes" ? `<span class="soon">Your surname is on the winners page</span>` : `<span class="${/watch/.test(x.st) ? "soon" : ""}">${esc(x.st)}</span>`;
    const draw = x.c ? `${x.est ? "drawn by about" : "drawn"} ${esc(x.c)}` : "draw date not stated";
    const claim = x.cb ? `claim by ${esc(x.cb)}` : x.cw ? `claim within ${esc(x.cw)} days` : "";
    return `<li class="card"><div class="top"><span class="prize">${money(x.p, x.pe)}</span><span class="meta">${st}</span></div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>
    <div class="meta"><span class="tag">${esc(x.k)}</span>${esc(x.b)} · ${x.st === "open" ? "closes" : "closed"} ${esc(x.cl)} · ${draw}</div>
    <div class="meta">Winners told by ${esc(x.h || "not stated")}${x.nw ? ` within ${esc(x.nw)} days` : ""}${claim ? " · " + claim : ""}${x.n ? ` · ${x.n} auto-entries` : " · entered by hand"}</div>
    ${x.pn ? `<div class="meta">${esc(x.pn)}</div>` : ""}
    <div class="acts">${x.wp ? `<a class="go" href="${esc(x.wp)}" target="_blank" rel="noopener">Winners page</a>` : `<span class="meta">Watch your email, phone and spam folder</span>`}<a class="ghost" href="${esc(x.u)}" target="_blank" rel="noopener">Listing</a></div></li>`;
  }
  if (S.tab === "appr") {
    const body = x.a ? `<div class="ans"><p>${esc(x.a)}</p><button class="ghost copy" data-copy="${esc(x.a)}">Copy answer</button></div>`
                     : `<div class="meta">${x.q ? "Question: " + esc(x.q) : "Open the entry page to see the question."}</div>`;
    return `<li class="t">${stub(x)}<div class="body"><div class="when">${when}</div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>
    <div class="meta"><span class="tag">${x.st === "ok" ? (x.hand ? "approved: enter by hand" : "approved, waiting to go in") : "needs your answer"}</span>${esc(x.b)} · up to ${x.lim} words</div>${body}
    ${editing.has(x.id) ? editor(x) : ""}<div class="acts"><button type="button" class="ghost" data-act="edit-answer" data-id="${esc(x.id)}">${x.a ? "Edit answer" : "Write answer"}</button>
    ${x.a && !x.hand ? enterBtn([x.id], "Submit now") : `<a class="go" href="${esc(x.u)}" target="_blank" rel="noopener">Open</a>`}${icons(x)}</div></div></li>`;
  }
  if (S.tab === "auto") return `<li class="t">${stub(x)}<div class="body"><div class="when">${when}</div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>
    <div class="meta"><span class="tag">${esc(x.k)}</span>${x.n ? `<b>${x.n}</b> ${x.n === 1 ? "entry" : "entries"} · last ${esc(x.l)}` : "waiting for the next burst"}</div>${ans}
    <div class="acts">${x.open ? enterBtn([x.id], "Re-enter") : `<span class="meta">closed</span>`}${icons(x)}
    ${x.open ? `<label class="ic sel" title="Select for Re-enter selected"><input type="checkbox" class="pick" data-id="${esc(x.id)}" ${sel.has(x.id) ? "checked" : ""}>☐</label>` : ""}</div></div></li>`;
  if (S.tab === "free") { const dn = !!done()["f:" + x.u];
    return `<li class="card ${dn ? "is-done" : ""}"><div class="top"><span class="tag">${esc(x.k)}</span><span class="meta">${esc(x.c)}</span></div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a><div class="meta">${esc(x.d)}</div>
    <div class="acts"><a class="go" href="${esc(x.u)}" target="_blank" rel="noopener">Get it</a><label class="done"><input type="checkbox" class="tick" data-id="f:${esc(x.u)}" ${dn ? "checked" : ""}> Done</label></div></li>`; }
  const isDone = !!done()[x.id];
  return `<li class="t ${isDone ? "is-done" : ""}">${stub(x)}<div class="body"><div class="when">${when}</div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>
    <div class="meta"><span class="tag">${esc(x.k)}</span>${esc(x.b)} · ${esc(x.w)}</div>
    ${x.bad ? `<div class="meta soon">Checked: ${esc(x.bad)}. The button opens the listing page instead; the competition may have ended early. <a href="${esc(x.orig)}" target="_blank" rel="noopener">Try link</a></div>` : ""}
    ${x.tu ? `<div class="meta">The listing links the terms${x.u !== x.tu ? "; the button opens the entry page they name" : ""}.${x.how ? " " + esc(x.how) : ""} <a href="${esc(x.tu)}" target="_blank" rel="noopener">Terms</a></div>` : ""}${ans}
    <div class="acts"><a class="go" href="${esc(x.u)}" target="_blank" rel="noopener">${x.bad ? "Listing" : "Enter"}</a>${doneBox(x.id, isDone)}${icons(x)}</div></div></li>`;
}
function inBand(p) {   // prize range "lo-hi"; old saved "500" style values mean any
  const m = /^([\d.e]+)-([\d.e]+)$/.exec(S.min || ""); return !m || (p >= +m[1] && p < +m[2]);
}
function render() {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", t.dataset.tab === S.tab));
  $("#q").value = S.q; $("#grp").value = S.grp; $("#close").value = S.close; $("#min").value = S.min; $("#sort").value = S.sort; $("#hide").checked = S.hide;
  $("#grp").style.display = S.tab === "todo" ? "" : "none";
  chips();
  const q = S.q.trim().toLowerCase(), dn = done(), rm = gone(), P = pool().filter((x) => !rm[x.id]);
  const list = P.filter((x) => (!q || (x.t + " " + (x.b || "") + " " + (x.d || "") + " " + x.k).toLowerCase().includes(q))
    && (!S.cats.length || S.cats.includes(x.k)) && (S.tab !== "todo" || !S.grp || x.g === S.grp)
    && (S.close === "" || days(x.c) <= +S.close) && (S.tab === "free" || inBand(x.p || 0))
    && !(S.hide && (S.tab === "todo" || S.tab === "social") && dn[x.id]) && !(S.hide && S.tab === "free" && dn["f:" + x.u]));
  const by = { chance: (a, b) => (b.ch || 0) - (a.ch || 0) || days(a.c) - days(b.c), close: (a, b) => days(a.c) - days(b.c) || (b.p || 0) - (a.p || 0), prize: (a, b) => (b.p || 0) - (a.p || 0), az: (a, b) => a.t.localeCompare(b.t) };
  list.sort(by[S.sort]);
  const total = list.reduce((s, x) => s + (x.p || 0), 0);
  $("#count").textContent = `${list.length} shown` + (S.tab !== "free" ? ` · ${money(total)} in prizes` : "") + (S.tab === "todo" || S.tab === "social" ? ` · ${P.filter((x) => !dn[x.id]).length} not done` : "") + (S.tab === "win" ? " · auto-entered and ticked Done; close-date filter uses the draw date" : "");
  const ok = S.tab === "appr" ? list.filter((x) => x.st === "ok" && !x.hand) : [];
  $("#count").innerHTML = esc($("#count").textContent) + (S.tab === "appr"
    ? ` · ${list.filter((x) => x.st === "ok").length} approved, ${list.filter((x) => x.st !== "ok").length} need an answer` + (ok.length ? " " + enterBtn(ok.map((x) => x.id), `Submit all approved (${ok.length})`) : "")
    : "");
  const top = ["todo", "social", "appr"].includes(S.tab) && S.sort === "chance" && list.length > 1 && !(dn[list[0].id]) ? list[0] : null;
  $("#list").innerHTML = (top ? `<li>${hero(top)}</li>` : "") + (top ? list.slice(1) : list).map(card).join("") || `<li class="empty">${S.tab === "win" ? "Nothing entered yet. Tick Done on the To enter tab to track a comp here." : "Nothing matches. Clear a filter."}</li>`;
  $("#bar").classList.toggle("show", S.tab === "auto" && sel.size > 0);
  $("#selcount").textContent = `${sel.size} selected`;
  store.set("comps-ui", S);
}
// Actions: POST /api/action (the Static Web App API; open to everyone; it caps requests per client IP). The page updates at
// once and a failed send is undone with a message.
let toastTimer;
function toast(msg, link) {
  const t = $("#toast"); t.textContent = msg;
  if (link) { const a = document.createElement("a"); a.href = link.href; a.textContent = " " + link.text; t.append(a); }
  t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 4500);
}
async function post(body) {   // "ok" | "limit" | "fail" | "net"
  try {
    const r = await fetch("/api/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.status === 429) return "limit";   // too many actions from this connection; wait a few minutes
    return r.status === 202 ? "ok" : "fail";
  } catch { return "net"; }
}
async function send(kind, ids, extra = {}) {   // up to 50 ids a request
  for (let i = 0; i < ids.length; i += 50) { const r = await post({ kind, ids: ids.slice(i, i + 50), ...extra }); if (r !== "ok") return r; }
  return "ok";
}
const SAID = { remove: "Removed. It leaves the lists within a couple of minutes.", broken: "Marked as not working and removed.",
               reenter: "Re-entry queued. It runs within a few minutes.", answer: "Answer saved. It goes in on the next entry run." };
const forEntries = (id, fn) => { for (const k of ["todo", "auto", "appr"]) for (const x of D[k]) if (String(x.id) === id) fn(x); };
async function act(kind, ids, extra) {
  ids = [...new Set(ids.map(String))]; if (!ids.length) return;
  const before = {}, now = Date.now();
  if (kind === "remove" || kind === "broken") { const g = gone(); for (const id of ids) g[id] = now; store.set("comps-removed", g); }
  if (kind === "reenter") { const p = pending(); for (const id of ids) p[id] = now; store.set("comps-pending", p); }
  if (kind === "answer") forEntries(ids[0], (x) => { before[x.id] = [x.a, x.st]; x.a = extra.answer; if (x.st) x.st = "ok"; });
  if (kind === "answer") { const m = store.get("comps-answers", {}); m[ids[0]] = { a: extra.answer, t: now }; store.set("comps-answers", m); editing.delete(ids[0]); delete drafts[ids[0]]; }
  sel.clear(); render(); toast("Sending…");
  const r = await send(kind, ids, extra);
  if (r === "ok") { toast(SAID[kind]); return; }
  if (kind === "remove" || kind === "broken") { const g = gone(); for (const id of ids) delete g[id]; store.set("comps-removed", g); }
  if (kind === "reenter") { const p = pending(); for (const id of ids) delete p[id]; store.set("comps-pending", p); }
  if (kind === "answer") { forEntries(ids[0], (x) => { [x.a, x.st] = before[x.id] || [x.a, x.st]; }); const m = store.get("comps-answers", {}); delete m[ids[0]]; store.set("comps-answers", m);
    editing.add(ids[0]); drafts[ids[0]] = extra.answer; }
  render();
  toast(r === "net" ? "No connection: nothing was sent." : r === "limit" ? "Too many actions just now: nothing was sent. Try again in a few minutes."
        : "The server did not accept it: nothing was sent.");
}
let syncToasted = false;
async function syncDone(kind, id) {   // best effort: the tick is already saved on this phone
  const say = (m) => { if (!syncToasted) { syncToasted = true; toast(m); } };
  const r = await send(kind, [id]);
  if (r === "limit") say("Too many actions just now: the tick is saved on this phone and will sync on a later tick.");
  else if (r !== "ok") say("Could not sync the tick; it is saved on this phone.");
}
document.addEventListener("click", async (e) => {
  const t = e.target.closest(".tab"); if (t) { S.tab = t.dataset.tab; S.cats = []; render(); return; }
  const c = e.target.closest(".chip"); if (c) { const k = c.dataset.cat; S.cats = S.cats.includes(k) ? S.cats.filter((x) => x !== k) : [...S.cats, k]; render(); return; }
  const a = e.target.closest("[data-act]");
  if (a) {
    const kind = a.dataset.act, ids = (a.dataset.ids || "").split(" ").filter(Boolean);
    if (kind === "remove" || kind === "broken") { act(kind, ids); return; }
    if (kind === "reenter") { act(kind, ids.filter((id) => !isPending(id))); return; }
    if (kind === "rmsel") { act("remove", [...sel]); return; }
    if (kind === "resel") { act("reenter", [...sel].filter((id) => !isPending(id))); return; }
    if (kind === "edit-answer") { editing.add(a.dataset.id); render(); const box = document.querySelector(`textarea[data-draft="${a.dataset.id}"]`); if (box) box.focus(); return; }
    if (kind === "cancel-answer") { editing.delete(a.dataset.id); delete drafts[a.dataset.id]; render(); return; }
    if (kind === "save-answer") {
      const x = D.appr.find((y) => String(y.id) === a.dataset.id), text = (drafts[a.dataset.id] ?? "").trim();
      if (!x || !text) { toast("Write the answer first."); return; }
      if (words(text) > x.lim) { toast(`That is ${words(text)} words; the limit is ${x.lim}.`); return; }
      act("answer", [a.dataset.id], { answer: text }); return;
    }
  }
  const b = e.target.closest("button.copy"); if (b) { try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch { b.textContent = "Select and copy the text"; } setTimeout(() => (b.textContent = "Copy answer"), 2000); }
});
document.addEventListener("input", (e) => {
  const id = e.target.dataset && e.target.dataset.draft; if (!id) return;
  drafts[id] = e.target.value;
  const x = D.appr.find((y) => String(y.id) === id), n = words(e.target.value), out = document.querySelector(`[data-count="${id}"]`);
  if (x && out) { out.textContent = `${n} of ${x.lim} words`; out.classList.toggle("over", n > x.lim); }
});
document.addEventListener("change", (e) => {
  if (e.target.dataset.draft) return;   // a re-render here would swap the Save button out from under the tap
  if (e.target.classList.contains("tick")) {
    const id = e.target.dataset.id, on = e.target.checked, d = store.get("comps-done", {}), u = store.get("comps-undone", {}), now = Date.now();
    if (on) d[id] = now; else { delete d[id]; u[id] = now; }
    for (const k of Object.keys(u)) if (now - u[k] > 30 * 864e5) delete u[k];
    store.set("comps-done", d); store.set("comps-undone", u); render();
    if (/^\d{5,9}$/.test(id)) syncDone(on ? "done" : "undone", id);   // Freebies ticks (f:<url>) stay on this phone
    return;
  }
  if (e.target.classList.contains("pick")) { e.target.checked ? sel.add(e.target.dataset.id) : sel.delete(e.target.dataset.id); render(); return; }
  if (e.target.id === "hide") S.hide = e.target.checked; if (e.target.id === "grp") S.grp = e.target.value;
  if (e.target.id === "close") S.close = e.target.value; if (e.target.id === "min") S.min = e.target.value; if (e.target.id === "sort") S.sort = e.target.value;
  render();
});
$("#q").addEventListener("input", (e) => { S.q = e.target.value; render(); });
(function () {   // answers saved from this phone show until a build carries them (then they are dropped), for 3 days at most
  const mine = store.get("comps-answers", {}); let dirty = false;
  for (const id of Object.keys(mine)) {
    let same = false; forEntries(id, (x) => { if (x.a === mine[id].a) same = true; });
    if (same || Date.now() - mine[id].t > 3 * 864e5) { delete mine[id]; dirty = true; } else forEntries(id, (x) => { x.a = mine[id].a; if (x.st) x.st = "ok"; });
  }
  if (dirty) store.set("comps-answers", mine);
})();
render();
</script></body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page())
    (out / "staticwebapp.config.json").write_text(json.dumps(SWA_CONFIG, indent=2) + "\n")
    print(f"site: wrote {out / 'index.html'} and {out / 'staticwebapp.config.json'}")


if __name__ == "__main__":
    sys.exit(main())
