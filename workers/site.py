"""The owner's competition page: search, filter and tick off what to enter by hand; see and re-enter the auto-entries.

    python3 -m workers.site                 # writes site/index.html (published by .github/workflows/site.yml)
    python3 -m workers.site --out DIR       # somewhere else

One static page built from the registers after each run. All the data is embedded as JSON and the phone does the
searching, filtering and sorting. Four tabs:
  Remove       (and Doesn't work: "broken: <ids>", not counted as a dislike)
               on To enter and Auto-entered: opens a pre-filled issue "remove: <ids>" (.github/workflows/remove.yml,
               owner only) that stops entries, drops the comp from both lists and records it for the owner's pattern
               of likes and dislikes (workers/removals.py -> data/entries/PREFERENCES.md); hidden on the phone at once.
  To enter     open competitions a Victorian can enter that the auto-entrant cannot (bot-checked web forms,
               social media, everything else), each with its prize category, Open button, approved answer with a
               Copy button, and a Done tick kept in the phone's browser storage.
  Auto-entered the auto-entry register: every competition entered automatically, how many times, when last, with a
               Re-enter button (opens a pre-filled GitHub issue; .github/workflows/reenter.yml acts on the owner's
               issues only) and multi-select to re-enter several at once.
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

from workers import comps, entry_queue

ROOT = comps.ROOT
ENTRIES = ROOT / "data" / "entries"
FREEBIES = ROOT / "data" / "freebies" / "freebies.csv"
OUT = ROOT / "site"
REPO = "JesseAllomes/Lotto-project"
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
    if platform in ("facebook", "instagram", "tiktok", "x", "youtube"):
        return "social"
    if any(k in reason for k in ("captcha", "human_check", "failing", "no_form", "unfillable", "login",
                                 "terms ban")) or "/pages/" in (url or ""):
        return "web"
    return "other"


def why(reason):
    r = reason.replace("entrant blocked: ", "")
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


def close_of(rec, fallback=""):
    """(Melbourne closing date, '6:00pm' closing time) from the listing's stated or listed closing time."""
    t = entry_queue.closes_at(rec) if rec else None
    if not t:
        return fallback[:10], ""
    t = t.astimezone(MELB)
    return t.date().isoformat(), t.strftime("%I:%M%p").lstrip("0").lower()


def removed(entries=ENTRIES):
    """Ids the owner removed (data/entries/log_removed.jsonl, written by workers/removals.py)."""
    path = entries / "log_removed.jsonl"
    rows = (json.loads(l) for l in path.read_text().splitlines() if l.strip()) if path.exists() else ()
    return {str(r["id"]) for r in rows if r.get("result") == "removed"}


def load_answers(entries=ENTRIES):
    path = entries / "answers.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _num(x):
    try:
        return float(x) if x not in (None, "") else 0.0
    except ValueError:
        return 0.0


def records():
    return {str(r["id"]): r for r in (json.loads(l)["comp"] for l in comps.stored(comps.STORE).values())}


def items(entries=ENTRIES, today=None, recs=None):
    """The 'To enter' list."""
    today = (today or dt.date.today()).isoformat()
    ans, recs = load_answers(entries), recs if recs is not None else records()
    path = entries / "manual.csv"
    out = []
    for r in (csv.DictReader(open(path)) if path.exists() else []):
        rec = recs.get(r["id"], {})
        closes, at = close_of(rec, r.get("closes") or "")
        if closes and closes < today or not r.get("entry_url"):
            continue
        pv, est = comps.prize_value(rec or r)
        out.append({"id": r["id"], "t": comps.clean_title(r["title"]), "b": r.get("brand") or "", "p": pv or 0, "pe": est,
                    "c": closes, "ct": at, "u": r["entry_url"], "w": why(r.get("reason") or ""),
                    "g": group_of(r.get("reason") or "", r.get("entry_platform") or "", r["entry_url"]),
                    "k": category(r["title"], rec.get("category_slug")), "a": ans.get(str(r["id"])),
                    "s": rec.get("source_site") or "competitions.com.au"})
    return out


def autos(entries=ENTRIES, today=None, recs=None):
    """The 'Auto-entered' list: the register, plus approved skill answers still waiting to go in."""
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
    for k, v in ans.items():
        rec = recs.get(k)
        if k in seen or not rec or (entry_queue.close_date(rec) or "9") < today:
            continue
        pv, est = comps.prize_value(rec)
        out.append({"id": k, "t": comps.clean_title(rec["title"]), "b": rec.get("brand") or "", "p": pv or 0, "pe": est,
                    "c": entry_queue.close_date(rec), "u": rec.get("entry_url") or "", "n": 0, "l": "waiting",
                    "k": category(rec["title"], rec.get("category_slug")), "a": v, "open": True})
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


def page(entries=ENTRIES, today=None, built=None, freebie_path=FREEBIES):
    recs = records()
    gone = removed(entries)
    data = {"todo": [x for x in items(entries, today, recs) if x["id"] not in gone],
            "auto": [x for x in autos(entries, today, recs) if x["id"] not in gone], "free": freebies(freebie_path),
            "win": [x for x in winners(entries, recs) if x["id"] not in gone], "removed": len(gone),
            "stats": stats(entries), "groups": GROUP_NAMES, "categories": list(dict.fromkeys(c for c, _ in CATEGORIES)) + ["Other"],
            "repo": REPO, "built": built or dt.datetime.now(MELB).strftime("%a %d %b, %I:%M%p").replace(" 0", " ")}
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", blob)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comps to enter</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--accent:#0b6e4f;--chip:#ecebe6;--warn:#a15c00}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--card:#1c1c1f;--ink:#f2f2f4;--muted:#a1a1a8;--line:#2c2c31;--accent:#3ccf95;--chip:#26262b;--warn:#f0b35a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif}
header{background:var(--bg);border-bottom:1px solid var(--line)}
.wrap{max-width:820px;margin:0 auto;padding:12px 16px}h1{font-size:1.35rem;margin:0}
.sub,.meta,.hint{color:var(--muted);font-size:.88rem}
.tabs{display:flex;gap:6px;margin:10px 0 8px}.tab{flex:1;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:inherit;font-weight:600}
.tab[aria-selected=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
input[type=search],select{font:inherit;padding:8px 10px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
input[type=search]{width:100%}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.row>*{flex:1 1 auto}
.chips{display:flex;gap:6px;overflow-x:auto;padding:8px 0 2px;scrollbar-width:none}.chip{white-space:nowrap;padding:6px 10px;border-radius:999px;border:1px solid var(--line);background:var(--chip);color:var(--ink);font:inherit;font-size:.85rem}
.chip[aria-pressed=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
ul{list-style:none;padding:0;margin:0}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}
.top{display:flex;justify-content:space-between;gap:8px}.prize{font-weight:700;color:var(--accent)}.soon{color:var(--warn);font-weight:600}
.title{display:block;font-weight:600;color:var(--ink);text-decoration:none;margin:4px 0}
.tag{display:inline-block;font-size:.75rem;padding:2px 8px;border-radius:999px;background:var(--chip);color:var(--muted);margin-right:4px}
.acts{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-top:10px}
.go{background:var(--accent);color:#fff;text-decoration:none;padding:8px 12px;border-radius:8px;font-weight:600;border:0;font:inherit}
.ghost{background:transparent;color:var(--accent);border:1px solid var(--accent);padding:7px 11px;border-radius:8px;font:inherit;font-weight:600;text-decoration:none}
.done{display:flex;gap:6px;align-items:center}.done input{width:22px;height:22px}
.card.is-done{opacity:.45}.card.is-done .title{text-decoration:line-through}
.ans{background:var(--bg);border-radius:8px;padding:8px 10px;margin:8px 0}.ans p{margin:0 0 6px}
.bar{position:sticky;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;display:none}
.bar.show{display:flex;justify-content:space-between;align-items:center;gap:8px}.empty{color:var(--muted);text-align:center;padding:30px 0}
</style></head><body>
<header><div class="wrap">
<h1>Comps to enter</h1><div class="sub" id="summary"></div>
<div class="tabs" role="tablist"><button class="tab" data-tab="todo">To enter</button><button class="tab" data-tab="auto">Auto-entered</button><button class="tab" data-tab="win">Winners</button><button class="tab" data-tab="free">Freebies</button></div>
<input type="search" id="q" placeholder="Search prize, brand or title">
<div class="chips" id="cats"></div>
<div class="row" style="margin-top:6px">
<select id="grp"><option value="">All entry types</option></select>
<select id="close"><option value="">Any close date</option><option value="0">Closes today</option><option value="7">This week</option><option value="30">This month</option></select>
<select id="min"><option value="0">Any prize</option><option value="500">$500+</option><option value="2000">$2,000+</option><option value="10000">$10,000+</option></select>
<select id="sort"><option value="close">Closing soonest</option><option value="prize">Biggest prize</option><option value="az">A to Z</option></select>
</div>
<label class="done hint" style="margin-top:8px"><input type="checkbox" id="hide"> Hide done</label>
</div></header>
<main class="wrap"><div class="sub" id="count"></div><ul id="list"></ul></main>
<div class="bar" id="bar"><span id="selcount"></span><a class="ghost rmsel" id="rmselect" target="_blank" rel="noopener">Remove selected</a><a class="go" id="reselect" target="_blank" rel="noopener">Re-enter selected</a></div>
<script>
const D = __DATA__;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
                 set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
let S = Object.assign({ tab: "todo", q: "", cats: [], grp: "", close: "", min: "0", sort: "close", hide: false }, store.get("comps-ui", {}));
const done = () => store.get("comps-done", {});
const sel = new Set();
const today = new Date(); today.setHours(0, 0, 0, 0);
const days = (c) => c ? Math.round((new Date(c.slice(0, 10) + "T00:00:00") - today) / 864e5) : 9999;
const money = (p, est) => p ? (est ? "~$" : "$") + Math.round(p).toLocaleString("en-AU") : "prize n/a";   // ~ = estimated from the title
const rmIssue = (ids) => `https://github.com/${D.repo}/issues/new?title=${encodeURIComponent("remove: " + ids.join(" "))}&body=${encodeURIComponent("Remove these competitions: no more entries, off both lists, and add them to the pattern of what I don't like. Submit this issue; the remove workflow does the rest.")}`;
const gone = () => store.get("comps-removed", {});
const brokenIssue = (ids) => `https://github.com/${D.repo}/issues/new?title=${encodeURIComponent("broken: " + ids.join(" "))}&body=${encodeURIComponent("This competition doesn't work (entry page broken, closed early or not as listed). Stop entering it and take it off the lists; not a dislike. Submit this issue; the remove workflow does the rest.")}`;
const rmBtn = (x) => `<a class="ghost rm" href="${rmIssue([x.id])}" target="_blank" rel="noopener" data-id="${esc(x.id)}">Remove</a>` +
  `<a class="ghost rm" href="${brokenIssue([x.id])}" target="_blank" rel="noopener" data-id="${esc(x.id)}">Doesn't work</a>`;
const issue = (ids) => `https://github.com/${D.repo}/issues/new?title=${encodeURIComponent("reenter: " + ids.join(" "))}&body=${encodeURIComponent("Re-enter these competitions now. Submit this issue; the reenter workflow does the rest and closes it.")}`;
$("#summary").textContent = `${D.todo.length} to enter by hand · ${D.stats.entries} auto-entries in ${D.stats.comps} comps` + (D.removed ? ` · ${D.removed} removed` : "") + ` · updated ${D.built}`;
for (const [k, v] of Object.entries(D.groups)) $("#grp").insertAdjacentHTML("beforeend", `<option value="${k}">${esc(v)}</option>`);
const pool = () => S.tab === "todo" ? D.todo : S.tab === "auto" ? D.auto : S.tab === "win" ? D.win.filter((x) => x.n || done()[x.id] || x.seen === "yes") : D.free;
function chips() {
  const src = S.tab === "free" ? [...new Set(D.free.map((x) => x.k))] : D.categories;
  $("#cats").innerHTML = src.map((c) => { const n = pool().filter((x) => x.k === c).length;
    return n ? `<button class="chip" data-cat="${esc(c)}" aria-pressed="${S.cats.includes(c)}">${esc(c)} ${n}</button>` : ""; }).join("");
}
function card(x) {
  const d = days(x.c), soon = d <= 2 ? "soon" : "";
  const ans = x.a ? `<div class="ans"><p>${esc(x.a)}</p><button class="ghost copy" data-copy="${esc(x.a)}">Copy answer</button></div>` : "";
  const at = x.ct ? " " + esc(x.ct) : "";
  const when = x.c ? `<span class="${soon}">${d === 0 ? "closes today" + at : d === 1 ? "closes tomorrow" + at : "closes " + esc(x.c.slice(0, 10))}</span>` : "";
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
  if (S.tab === "auto") return `<li class="card"><div class="top"><span class="prize">${money(x.p, x.pe)}</span><span class="meta">${when}</span></div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>
    <div class="meta"><span class="tag">${esc(x.k)}</span>${esc(x.b)}</div>
    <div class="meta">${x.n ? `<b>${x.n}</b> ${x.n === 1 ? "entry" : "entries"} · last ${esc(x.l)}` : "waiting for the next burst"}</div>${ans}
    <div class="acts"><a class="ghost" href="${esc(x.u)}" target="_blank" rel="noopener">Open</a>
    ${rmBtn(x)}${x.open ? `<a class="go" href="${issue([x.id])}" target="_blank" rel="noopener">Re-enter</a><label class="done"><input type="checkbox" class="pick" data-id="${esc(x.id)}" ${sel.has(x.id) ? "checked" : ""}> Select</label>` : `<span class="meta">closed</span>`}</div></li>`;
  if (S.tab === "free") { const dn = !!done()["f:" + x.u];
    return `<li class="card ${dn ? "is-done" : ""}"><div class="top"><span class="tag">${esc(x.k)}</span><span class="meta">${esc(x.c)}</span></div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a><div class="meta">${esc(x.d)}</div>
    <div class="acts"><a class="go" href="${esc(x.u)}" target="_blank" rel="noopener">Get it</a><label class="done"><input type="checkbox" class="tick" data-id="f:${esc(x.u)}" ${dn ? "checked" : ""}> Done</label></div></li>`; }
  const isDone = !!done()[x.id];
  return `<li class="card ${isDone ? "is-done" : ""}"><div class="top"><span class="prize">${money(x.p, x.pe)}</span><span class="meta">${when}</span></div>
    <a class="title" href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>
    <div class="meta"><span class="tag">${esc(x.k)}</span><span class="tag">${esc(D.groups[x.g] || x.g)}</span>${esc(x.b)} · ${esc(x.w)}</div>${ans}
    <div class="acts"><a class="go" href="${esc(x.u)}" target="_blank" rel="noopener">Open entry page</a>${rmBtn(x)}<label class="done"><input type="checkbox" class="tick" data-id="${esc(x.id)}" ${isDone ? "checked" : ""}> Done</label></div></li>`;
}
function render() {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", t.dataset.tab === S.tab));
  $("#q").value = S.q; $("#grp").value = S.grp; $("#close").value = S.close; $("#min").value = S.min; $("#sort").value = S.sort; $("#hide").checked = S.hide;
  $("#grp").style.display = S.tab === "todo" ? "" : "none";
  chips();
  const q = S.q.trim().toLowerCase(), dn = done(), rm = gone(), P = pool().filter((x) => !rm[x.id]);
  const list = P.filter((x) => (!q || (x.t + " " + (x.b || "") + " " + (x.d || "") + " " + x.k).toLowerCase().includes(q))
    && (!S.cats.length || S.cats.includes(x.k)) && (S.tab !== "todo" || !S.grp || x.g === S.grp)
    && (S.close === "" || days(x.c) <= +S.close) && (S.tab === "free" || (x.p || 0) >= +S.min)
    && !(S.hide && S.tab === "todo" && dn[x.id]) && !(S.hide && S.tab === "free" && dn["f:" + x.u]));
  const by = { close: (a, b) => days(a.c) - days(b.c) || (b.p || 0) - (a.p || 0), prize: (a, b) => (b.p || 0) - (a.p || 0), az: (a, b) => a.t.localeCompare(b.t) };
  list.sort(by[S.sort]);
  const total = list.reduce((s, x) => s + (x.p || 0), 0);
  $("#count").textContent = `${list.length} shown` + (S.tab !== "free" ? ` · ${money(total)} in prizes` : "") + (S.tab === "todo" ? ` · ${P.filter((x) => !dn[x.id]).length} not done` : "") + (S.tab === "win" ? " · auto-entered and ticked Done; close-date filter uses the draw date" : "");
  $("#list").innerHTML = list.map(card).join("") || `<li class="empty">${S.tab === "win" ? "Nothing entered yet. Tick Done on the To enter tab to track a comp here." : "Nothing matches. Clear a filter."}</li>`;
  $("#bar").classList.toggle("show", S.tab === "auto" && sel.size > 0);
  $("#selcount").textContent = `${sel.size} selected`; $("#reselect").href = issue([...sel]); $("#rmselect").href = rmIssue([...sel]);
  store.set("comps-ui", S);
}
document.addEventListener("click", async (e) => {
  const t = e.target.closest(".tab"); if (t) { S.tab = t.dataset.tab; S.cats = []; render(); return; }
  const c = e.target.closest(".chip"); if (c) { const k = c.dataset.cat; S.cats = S.cats.includes(k) ? S.cats.filter((x) => x !== k) : [...S.cats, k]; render(); return; }
  const r = e.target.closest("a.rm, a.rmsel");
  if (r) {   // hide at once on this phone; the submitted issue makes it permanent and records it for the pattern
    const g = gone(); for (const id of (r.classList.contains("rmsel") ? [...sel] : [r.dataset.id])) g[id] = Date.now();
    store.set("comps-removed", g); if (r.classList.contains("rmsel")) sel.clear(); setTimeout(render, 50); return;
  }
  const b = e.target.closest("button.copy"); if (b) { try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch { b.textContent = "Select and copy the text"; } setTimeout(() => (b.textContent = "Copy answer"), 2000); }
});
document.addEventListener("change", (e) => {
  if (e.target.classList.contains("tick")) { const d = done(); if (e.target.checked) d[e.target.dataset.id] = Date.now(); else delete d[e.target.dataset.id]; store.set("comps-done", d); render(); return; }
  if (e.target.classList.contains("pick")) { e.target.checked ? sel.add(e.target.dataset.id) : sel.delete(e.target.dataset.id); render(); return; }
  if (e.target.id === "hide") S.hide = e.target.checked; if (e.target.id === "grp") S.grp = e.target.value;
  if (e.target.id === "close") S.close = e.target.value; if (e.target.id === "min") S.min = e.target.value; if (e.target.id === "sort") S.sort = e.target.value;
  render();
});
$("#q").addEventListener("input", (e) => { S.q = e.target.value; render(); });
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
    print(f"site: wrote {out / 'index.html'}")


if __name__ == "__main__":
    sys.exit(main())
