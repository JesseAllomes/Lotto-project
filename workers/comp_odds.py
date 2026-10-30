"""Odds variables for each competition in the register, and the separate list of skill competitions.

    python3 -m workers.comp_odds         # rebuild data/comps/odds.csv and data/comps/skill.csv from comps.jsonl
    python3 -m workers.comp_odds --tags  # first record each open listing's entry types (competitions.com.au type pages)

The source is the promoter's terms as summarised on each listing: question-and-answer sections such as
"How do I enter the competition?" and "How is the winner selected?". From these it records what moves the
chance of winning:
  draw_type    skill (judged on merit), chance (random draw), instant (instant win) or unclear
  purchase     yes / no / unknown: whether entry needs a purchase or ticket
  entry_limit  once, daily, weekly, per_purchase, unlimited, capped (entry_limit_n per person) or unknown
  bonus        yes when extra entries can be earned (referrals, shares, comments), which raises one person's chance
  entry_route  how an entry can be made: agent_ok (an online form only, which an agent could fill in), agent_assist
               (an online form plus an online payment the owner approves), manual (in store, receipt or scan, social
               media action, SMS, phone, post, app, upload) or unknown
  automation_banned  yes when the terms say automated, scripted, bulk or third-party entries are invalid; otherwise
               unknown (most full terms do say so: check before letting anything enter for you)
  prizes       how many prizes there are, when stated
  cap          the ticket or entry cap, filled from the promoter's own terms (data/comps/terms.jsonl, m6)
The summaries are the aggregator's, not the promoter's wording: evidence columns quote them so a row can be
checked against the full terms before entering.
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path

from workers import comps

STORE = comps.STORE
ODDS_FIELDS = ["id", "title", "brand", "prize_pool", "prizes", "closes", "open_to_vic", "entry_platform", "draw_type",
               "purchase", "entry_limit", "entry_limit_n", "bonus", "entry_route", "automation_banned", "entry_types", "cap", "cap_source", "evidence_selection",
               "evidence_entry", "entry_url", "url"]
SKILL_FIELDS = ["id", "title", "brand", "prize_pool", "prizes", "closes", "task", "question", "entry_limit",
                "entry_limit_n", "bonus", "purchase", "entry_route", "automation_banned", "judging", "entry_platform", "entry_url", "url"]
SKILL_ENTRY_TYPES = {"25-words-or-less", "creative-competitions", "quiz-competitions"}
ENTRY_TYPES = ["25-words-or-less", "codeword-entry", "creative-competitions", "daily-entry", "facebook-competitions",
               "free-entry", "instagram-competitions", "instant-win", "interactive-games", "kids-competitions",
               "quick-entry", "quiz-competitions", "recurring-competitions", "registration-required", "shop-scan-win",
               "sms-entry", "survey-competitions", "twitter-competitions", "voting-competitions"]
TYPE_PAGE = "https://www.competitions.com.au/{}/?page={}"
MAX_PAGES = 40
RAFFLE_BRAND = re.compile(r"(?i)lotter|art union|raffle|prize home")
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def sections(desc):
    """{topic: text} from the '**Question?** answer' summary. Topics: enter, select, prize, eligible, other."""
    out = {}
    parts = re.split(r"\*\*(.+?)\*\*", html.unescape(desc or ""))
    for q, a in zip(parts[1::2], parts[2::2]):
        ql = q.lower()
        if re.search(r"select|chosen|determin|judg|winners? (?:be )?(?:drawn|picked)", ql):
            topic = "select"
        elif re.search(r"enter|entry|participat", ql) and not re.search(r"who (?:can|is eligible)|eligib", ql):
            topic = "enter"
        elif "prize" in ql and "unclaimed" not in ql:
            topic = "prize"
        elif re.search(r"eligib|who can", ql):
            topic = "eligible"
        else:
            topic = "other"
        out[topic] = (out.get(topic, "") + " " + re.sub(r"\s+", " ", a)).strip()
    return out


def draw_type(sec, desc):
    text = sec.get("select") or desc or ""
    skill = re.search(r"(?i)game of skill|chance plays no part|judg|merit|creativ|most (?:original|humorous|"
                      r"interesting)|best (?:answer|entr|photo|response)|criteria|closest (?:prediction|guess|answer)"
                      r"|most accurate", text)
    chance = re.search(r"(?i)random|drawn|\bdraw(?:ing)?\b|lottery|raffle", text)
    instant = re.search(r"(?i)instant(?:ly)? win|winning moment|instantly", text)
    if re.search(r"(?i)game of skill|chance plays no part", desc or "") or (skill and not chance):
        return "skill"
    if instant and not skill:
        return "instant"
    if chance and not skill:
        return "chance"
    return "unclear" if (skill or chance or instant) else "unknown"


def purchase(sec, desc, brand):
    text = sec.get("enter") or desc or ""
    if re.search(r"(?i)no purchase (?:is )?(?:necessary|required)|free to enter|free entry", text):
        return "no"
    if RAFFLE_BRAND.search(brand or "") or re.search(
            r"(?i)\bpurchas|\bbuy\b|\bspend|tickets? (?:cost|priced|from \$)|receipt|transaction|membership", text):
        return "yes"
    if re.search(r"(?i)sign(?:ing)? up|subscrib|\blike\b|\bfollow|comment|complete (?:the|an|their) (?:online )?"
                 r"(?:form|entry)|register|submit|fill (?:in|out)", text):
        return "no"
    return "unknown"


def bonus(sec, desc):
    t = sec.get("enter") or desc or ""
    return "yes" if re.search(r"(?i)(?:additional|bonus|extra) entr|refer(?:ral|ring)? (?:a )?friends? .{0,40}entr"
                              r"|entries (?:can|may) be earned", t) else "no"


def entry_limit(sec, desc):
    """(limit, n): how often one person may enter."""
    t = sec.get("enter") or desc or ""
    m = re.search(r"(?i)(?:maximum|max\.?|up to|limit(?:ed)? to|no more than) (?:of )?(\d+|"
                  + "|".join(NUM) + r") entr(?:y|ies) (?:per|each) (?:person|entrant|day|week)", t)
    if m:
        n = m.group(1).lower()
        n = int(n) if n.isdigit() else NUM[n]
        return ("once", None) if n == 1 else ("capped", n)
    rules = [("daily", r"(?i)(?:once|one entry) (?:per|a|each) day|per day|each day|daily"),
             ("weekly", r"(?i)(?:once|one entry) (?:per|a|each) week|per week|weekly"),
             ("per_purchase", r"(?i)(?:each|every|per) (?:eligible |qualifying )?(?:purchase|transaction|ticket)"
                              r"|for every \$"),
             ("unlimited", r"(?i)multiple entries (?:are )?(?:allowed|permitted|accepted)|unlimited entr|as many "
                           r"(?:times|entries)|enter (?:as often|multiple times)"),
             ("once", r"(?i)(?:one|single|only 1|1) entry (?:per|only)|enter once|only (?:one|1) entry|limited to "
                      r"one|once only|one entry per (?:person|entrant|household)")]
    for name, pat in rules:
        if re.search(pat, t):
            return name, None
    return "unknown", None


def terms_limit(text):
    """(limit, n) from explicit entry-limit wording in full terms, or (None, None) when the terms set none.
    Stricter than entry_limit: only sentences about entries per person, day or week count."""
    who = r"(?:person|entrant|individual|household|e-?mail(?: address)?|participant)"
    n_ = r"(\d+|" + "|".join(NUM) + r")"
    m = re.search(r"(?i)(?:maximum|max\.?|up to|limit(?:ed)? to|no more than) (?:of )?" + n_ +
                  r" (?:valid )?entr(?:y|ies) (?:per|each|a) (" + who + r"|day|week|month)", text)
    if m:
        n = m.group(1).lower()
        n = int(n) if n.isdigit() else NUM[n]
        unit = m.group(2).lower()
        if unit in ("day", "week"):
            return ("daily" if unit == "day" else "weekly"), (n if n > 1 else None)
        return ("once", None) if n == 1 else ("capped", n)
    rules = [("daily", r"(?i)(?:once|one (?:\(1\) )?entry) (?:per|a|each) (?:calendar )?day|enter (?:once )?(?:daily|"
                       r"each day|every day)|one entry per " + who + r" per day"),
             ("weekly", r"(?i)(?:once|one (?:\(1\) )?entry) (?:per|a|each) (?:calendar )?week|one entry per " + who +
                        r" per week"),
             ("unlimited", r"(?i)multiple entries (?:are |will be )?(?:allowed|permitted|accepted)|unlimited entr|"
                           r"(?:may|can) enter (?:as many times|multiple times|more than once)"),
             ("once", r"(?i)(?:one|single|only 1|1) (?:\(1\) )?entry (?:per|only)|(?:may|can) (?:only )?enter once|"
                      r"only (?:one|1) (?:\(1\) )?entry|limited to one|once only|one entry per " + who +
                      r"|more than one entry[^.]{0,60}(?:invalid|void|disqualif)")]
    for name, pat in rules:
        if re.search(pat, text):
            return name, None
    return None, None


MANUAL = (r"(?i)in[- ]store|stores?'s?\b|outlet|venue|retailer|receipt|scan|barcode|social (?:media )?(?:channel|"
          r"post|page)|install|"
          r"\bsms\b|text (?:the|your|a) |phone|call |by post|mail (?:in|your)|post (?:your|the) entry|download the "
          r"app|via the app|\bapp\b|upload|comment|\blike\b|follow|\btag\b|share (?:the|this) post|direct message|"
          r"\bDM\b|container|refund point|click the button in the email|loyalty card|swipe|membership card")
BANNED = (r"(?i)(?:automat|script|macro|\bbots?\b|bulk|third[- ]party|agent)[^.]{0,80}(?:invalid|void|not (?:be )?"
          r"(?:accepted|permitted|valid)|prohibit|disqualif|ineligible|rejected)|(?:entries|entry) (?:made|submitted|"
          r"generated|lodged) (?:by|using|through|via) (?:any )?(?:automat|script|macro|bots?|bulk|third[- ]party)")


def entry_route(sec, desc, platform, buy):
    t = sec.get("enter") or desc or ""
    if platform in ("facebook", "instagram", "tiktok", "x", "youtube") or re.search(MANUAL, t):
        return "manual"
    if not t:
        return "unknown"
    if re.search(r"(?i)online|website|entry form|form on|web ?page|complete (?:the|an|their)|submit|register|"
                 r"subscrib|sign(?:ing)? up|newsletter|email list|mailing list", t):
        return "agent_assist" if buy == "yes" else "agent_ok"
    return "unknown"


def prizes(title, sec):
    m = re.search(r"(?i)\b1 of (\d[\d,]*)|\b(\d[\d,]*) x\b|share of (\d[\d,]*) prizes", title or "")
    if m:
        return int(next(g for g in m.groups() if g).replace(",", ""))
    m = re.search(r"(?i)\b(\d[\d,]*|" + "|".join(NUM) + r") (?:\w+ ){0,3}(?:prizes|winners)\b", sec.get("prize", ""))
    if m:
        n = m.group(1).lower().replace(",", "")
        return int(n) if n.isdigit() else NUM[n]
    return None


def task(sec, desc):
    t = (sec.get("enter") or "") + " " + (desc or "")
    for name, pat in [("prediction (closest guess)", r"(?i)closest (?:prediction|guess)|predict"),
                      ("25 words or less", r"(?i)\d+ words or (?:less|fewer)"), ("photo", r"(?i)photo|image|picture"),
                      ("video", r"(?i)\bvideo|\bfilm\b|commercial|\breel\b|tiktok"), ("recipe", r"(?i)recipe"), ("drawing or art", r"(?i)drawing|artwork|"
                      r"colou?r(?:ing)?[- ]in"), ("story or poem", r"(?i)\bstory|poem"), ("quiz", r"(?i)quiz|trivia"),
                      ("written answer", r"(?i)answer|question|tell us|explain|why|response|prompt|caption")]:
        if re.search(pat, t):
            return name
    return "other"


def question(sec):
    m = re.search(r"[\"“]([^\"”]{8,300})[\"”]", sec.get("enter") or "")
    return m.group(1) if m else None


def type_ids(page_html):
    return {int(x) for x in re.findall(r'data-comp-id="(\d+)"', page_html)}


def crawl_tags(store=STORE, fetch=comps.get, delay=comps.DELAY_S):
    """Append (listing id, entry type) pairs not yet recorded, walking each type's pages until one adds nothing."""
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    have = {(i, t) for i, ts in tags(store).items() for t in ts}
    new = []
    for t in ENTRY_TYPES:
        seen = set()
        for n in range(1, MAX_PAGES + 1):
            url = TYPE_PAGE.format(t, n)
            try:
                ids = type_ids(fetch(url))
            except (OSError, ValueError) as exc:
                print(f"skip {url}: {exc}", flush=True)
                break
            time.sleep(delay)
            if not ids - seen:
                break
            for i in sorted(ids - seen):
                if (i, t) not in have:
                    new.append({"fetched_utc": fetched, "source": url, "id": i, "entry_type": t})
            seen |= ids
    store.mkdir(parents=True, exist_ok=True)
    with open(store / "tags.jsonl", "a") as fh:
        for r in new:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"comp_odds: {len(new)} new entry-type tags", flush=True)
    return len(new)


def tags(store):
    """{listing id: sorted entry-type slugs} from tags.jsonl, if present."""
    path = store / "tags.jsonl"
    out = {}
    if path.exists():
        for l in path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                out.setdefault(r["id"], set()).add(r["entry_type"])
    return {k: sorted(v) for k, v in out.items()}


def caps(store):
    """{listing id: (cap, source url, automation banned)} from terms.jsonl (m6), latest record per listing."""
    path = store / "terms.jsonl"
    out = {}
    if path.exists():
        for l in path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                if r.get("cap") or r.get("automation_banned"):
                    out[r["id"]] = (r.get("cap"), r.get("source"), bool(r.get("automation_banned")))
    return out


def assess(r, entry_types=(), cap=None):
    desc = r.get("description") or ""
    sec = sections(desc)
    dtype = draw_type(sec, desc)
    if dtype in ("unknown", "unclear") and SKILL_ENTRY_TYPES & set(entry_types):
        dtype = "skill"
    limit, n = entry_limit(sec, desc)
    buy = purchase(sec, desc, r.get("brand"))
    if buy == "unknown" and "shop-scan-win" in entry_types:
        buy = "yes"
    elif buy == "unknown" and "free-entry" in entry_types:
        buy = "no"
    return {
        "id": r["id"], "title": r["title"], "brand": r.get("brand"), "prize_pool": r.get("prize_pool"),
        "prizes": prizes(r["title"], sec), "closes": r.get("closes"), "open_to_vic": r.get("open_to_vic"),
        "entry_platform": comps.platform(r.get("entry_url")), "draw_type": dtype,
        "purchase": buy, "entry_limit": limit, "entry_limit_n": n,
        "bonus": bonus(sec, desc),
        "entry_route": entry_route(sec, desc, comps.platform(r.get("entry_url")), buy),
        "automation_banned": "yes" if re.search(BANNED, desc) or (cap and cap[2:] == (True,)) else "unknown",
        "entry_types": " ".join(entry_types), "cap": cap[0] if cap else None, "cap_source": cap[1] if cap and cap[0] else None,
        "evidence_selection": (sec.get("select") or "")[:300], "evidence_entry": (sec.get("enter") or "")[:300],
        "entry_url": r.get("entry_url"), "url": r.get("url"),
        "task": task(sec, desc) if dtype == "skill" else None, "question": question(sec) if dtype == "skill" else None,
        "judging": (sec.get("select") or "")[:300] if dtype == "skill" else None,
    }


def _write(path, fields, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def run(store=STORE, today=None):
    today = (today or dt.date.today()).isoformat()
    t, c = tags(store), caps(store)
    recs = sorted((json.loads(l)["comp"] for l in comps.stored(store).values()), key=lambda r: r["id"])
    rows = [assess(r, t.get(r["id"], ()), c.get(r["id"])) for r in recs]
    _write(store / "odds.csv", ODDS_FIELDS, rows)
    skill = [x for x in rows if x["draw_type"] == "skill" and x["open_to_vic"] and (x["closes"] or "9")[:10] >= today]
    skill.sort(key=lambda x: x["closes"] or "9")
    _write(store / "skill.csv", SKILL_FIELDS, skill)
    kinds = {}
    for x in rows:
        kinds[x["draw_type"]] = kinds.get(x["draw_type"], 0) + 1
    print(f"comp_odds: {len(rows)} listings {kinds}; {len(skill)} open skill competitions for Victoria", flush=True)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", action="store_true", help="record entry types from the type pages first")
    a = ap.parse_args(argv)
    if a.tags:
        crawl_tags()
    run()


if __name__ == "__main__":
    sys.exit(main())
