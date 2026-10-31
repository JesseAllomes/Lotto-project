"""Winners tracker: when each competition is drawn, how winners are told, where names are published, and how long
a winner has to claim.

    python3 -m workers.winners            # writes data/entries/winners.csv from the listings (no network)
    python3 -m workers.winners --check    # also looks for the owner's surname on published winners pages

The listing summaries (competitions.com.au and AusComps) answer "How is the winner selected?", "How will the winner
be notified?" and "What happens if the prize is unclaimed?"; this reads those answers. Covered: every free
competition a Victorian can enter that is open or closed within the last LOOKBACK_DAYS, plus everything the entrant
has entered (data/entries/register.csv), so the owner's hand entries (ticked Done on the site) are covered too.

Status, from the Melbourne date: open -> closed, awaiting draw -> drawn: watch email/phone (until the notify and
claim windows have passed) -> claim window passed.

--check (site.yml, with ENTRANT_LAST_NAME from secrets): for drawn competitions whose summary names a winners page,
fetch it at most once a day for up to CHECK_DAYS after the draw and record whether the surname appears. The name is
never written anywhere: data/entries/winner_checks.jsonl holds only the id, time, page and a yes/no.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request

from workers import comp_odds, comps, entry_queue

STORE = comps.STORE
ENTRIES = entry_queue.ENTRIES
LOOKBACK_DAYS = 60
CHECK_DAYS = 30
DEFAULT_DRAW_DAYS = 7          # no draw date stated: assume drawn within a week of closing (marked "estimated")
FIELDS = ["id", "title", "brand", "prize_pool", "closes", "auto_entries", "status", "draw_date", "draw_estimated",
          "notify", "notify_within_days", "claim_within_days", "claim_by", "winners_page", "published_note", "name_seen",
          "checked_utc", "url"]
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "fourteen": 14, "fifteen": 15, "twenty": 20, "twenty-one": 21, "thirty": 30, "sixty": 60,
        "ninety": 90}
N = r"(\d{1,3}|" + "|".join(sorted(NUMS, key=len, reverse=True)) + r")(?: \(\d+\))?"
MONTH = "|".join(MONTHS)
DATE = (rf"(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?(?: of)? (?P<m1>{MONTH}),? (?P<y1>20\d\d)"
        rf"|(?P<m2>{MONTH}) (?P<d2>\d{{1,2}})(?:st|nd|rd|th)?,? (?P<y2>20\d\d)"
        r"|(?P<d3>\d{1,2})/(?P<m3>\d{1,2})/(?P<y3>(?:20)?\d\d)")
DRAW = (r"(?i)(?:drawn|draw(?:s)? (?:will )?(?:take|takes|took) place|draw (?:will be )?(?:held|conducted)|draw(?:s)? "
        r"(?:will )?occurs?|judg(?:ed|ing)|selected|chosen|determined|announced|winner)")
METHODS = [("email", r"e-?mail"), ("phone", r"phone|telephone|call"), ("SMS", r"\bsms\b|text message"),
           ("post", r"\bpost\b|\bmail\b|letter|in writing"), ("social DM", r"direct message|\bdm\b|instagram|facebook|"
                                                                           r"social media")]
URL = r"\b((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|au|co|nz|io)(?:\.au)?(?:/[^\s,;)\"']*)?)"


def num(s):
    s = s.lower()
    return int(s) if s.isdigit() else NUMS.get(s)


def parse_date(text, start=0):
    """First date in text (Australian day-first numeric dates) as a date, else None."""
    for m in re.finditer(DATE, text[start:], re.I):
        g = m.groupdict()
        try:
            if g["d1"]:
                return dt.date(int(g["y1"]), MONTHS[g["m1"].lower()], int(g["d1"]))
            if g["m2"]:
                return dt.date(int(g["y2"]), MONTHS[g["m2"].lower()], int(g["d2"]))
            y = int(g["y3"])
            return dt.date(y + 2000 if y < 100 else y, int(g["m3"]), int(g["d3"]))
        except ValueError:
            continue
    return None


def sections(desc):
    """{question: answer} from the "**Question?** answer" layout of the listing summaries."""
    parts = re.split(r"\*\*([^*]{3,200})\*\*", desc or "")
    return {parts[i].strip().lower(): html.unescape(parts[i + 1]).strip() for i in range(1, len(parts) - 1, 2)}


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def info(r):
    """What the listing says about the draw, notification, publication and claiming."""
    sec = sections(r.get("description"))
    pick = lambda *words: " ".join(a for q, a in sec.items() if any(w in q for w in words))
    selected, notified, unclaimed = pick("selected", "chosen", "drawn", "judg"), pick("notif", "contact"), pick("unclaim")
    everything = " ".join(sec.values()) or html.unescape(r.get("description") or "")
    closes = entry_queue.closes_at(r)
    closes_d = closes.astimezone(entry_queue.MELB).date() if closes else None
    out = {"draw_date": None, "draw_estimated": False, "notify": "", "notify_within_days": None,
           "claim_within_days": None, "claim_by": None, "winners_page": "", "published_note": ""}
    for s in sentences(selected + " " + notified) + sentences(everything):
        if re.search(DRAW, s):
            d = parse_date(s)
            if d and (not closes_d or d >= closes_d - dt.timedelta(days=1)):
                out["draw_date"] = d
                break
            m = re.search(rf"(?i)within {N} (business )?days? (?:after|of|following|from) (?:the )?(?:competition|"
                          rf"promotion|giveaway|entry period)?\s*(?:clos|end)", s)
            if m and closes_d and num(m.group(1)):
                days = num(m.group(1))
                out["draw_date"] = closes_d + dt.timedelta(days=days + (days // 5) * 2 if m.group(2) else days)
                break
    if not out["draw_date"] and closes_d:
        out["draw_date"], out["draw_estimated"] = closes_d + dt.timedelta(days=DEFAULT_DRAW_DAYS), True
    text = notified or " ".join(s for s in sentences(everything) if re.search(r"(?i)notif|contact", s))
    out["notify"] = ", ".join(name for name, pat in METHODS if re.search(pat, text, re.I))
    m = re.search(rf"(?i)(?:notif|contact)[^.]{{0,80}}within {N} (business )?days", text)
    if m:
        out["notify_within_days"] = num(m.group(1))
    claim = unclaimed + " " + " ".join(s for s in sentences(everything) if re.search(r"(?i)claim|respond|accept", s))
    m = re.search(rf"(?i)(?:claim(?:ed)?|respond|accept(?:ed)?|unclaimed|uncontactable)[^.]{{0,60}}(?:within|after) "
                  rf"{N} (?:business )?days", claim)
    if m:
        out["claim_within_days"] = num(m.group(1))
    m = re.search(r"(?i)(?:claim|respond|accept|contact)[^.]{0,60}\b(?:by|before)\b", claim)
    out["claim_by"] = parse_date(claim, m.end()) if m else None
    for s in sentences(everything):
        if re.search(r"(?i)\b(?:publish|announc|posted|displayed|listed)", s) and re.search(r"(?i)winner|name", s):
            out["published_note"] = s[:200]
            u = re.search(URL, s, re.I)
            if u and not re.search(r"(?i)^(?:e\.g|i\.e)", u.group(1)):
                page = u.group(1).rstrip(".")
                page = page if page.startswith("http") else "https://" + page
                host = re.match(r"https?://[^/]+", page).group(0)
                out["winners_page"] = host.lower() + page[len(host):]
            break
    return out


def status(r, i, today):
    closes = entry_queue.closes_at(r)
    if closes and closes.astimezone(entry_queue.MELB).date() >= today:
        return "open"
    d = i["draw_date"]
    if not d or d >= today:
        return "closed, awaiting draw"
    window = (i["notify_within_days"] or 7) + (i["claim_within_days"] or 14)
    passed = (i["claim_by"] and i["claim_by"] < today) or (today - d).days > window
    return "claim window passed" if passed else "drawn: watch email/phone"


def checks(entries=ENTRIES):
    out = {}
    for c in entry_queue.read_jsonl(entries / "winner_checks.jsonl"):
        out[c["id"]] = c                       # latest check wins
    return out


def build(store=STORE, entries=ENTRIES, today=None):
    today = today or dt.datetime.now(entry_queue.MELB).date()
    reg = {}
    if (entries / "register.csv").exists():
        reg = {int(x["id"]): int(x["entries"]) for x in csv.DictReader(open(entries / "register.csv"))}
    seen = checks(entries)
    rows = []
    for r in (json.loads(l)["comp"] for l in comps.stored(store).values()):
        closes = entry_queue.closes_at(r)
        recent = closes is None or (today - closes.astimezone(entry_queue.MELB).date()).days <= LOOKBACK_DAYS
        if r["id"] not in reg and not (r.get("open_to_vic") and recent and
                                       comp_odds.assess(r)["purchase"] != "yes"):
            continue
        i = info(r)
        c = seen.get(r["id"], {})
        rows.append({"id": r["id"], "title": r.get("title", ""), "brand": r.get("brand", ""),
                     "prize_pool": r.get("prize_pool"), "closes": entry_queue.close_date(r),
                     "auto_entries": reg.get(r["id"], 0), "status": status(r, i, today),
                     **i, "draw_date": i["draw_date"].isoformat() if i["draw_date"] else "",
                     "claim_by": i["claim_by"].isoformat() if i["claim_by"] else "",
                     "name_seen": {True: "yes", False: "no"}.get(c.get("name_seen"), ""),
                     "checked_utc": c.get("checked_utc", ""), "url": r.get("url", "")})
    order = {"drawn: watch email/phone": 0, "closed, awaiting draw": 1, "open": 2, "claim window passed": 3}
    rows.sort(key=lambda x: (x["name_seen"] != "yes", order[x["status"]], x["draw_date"] or "9"))
    entries.mkdir(parents=True, exist_ok=True)
    with open(entries / "winners.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return rows


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": comps.UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read(3_000_000).decode("utf-8", "replace")
    body = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def check(rows, surname, entries=ENTRIES, fetch=fetch_text, now=None, delay=comps.DELAY_S, max_pages=40):
    """Look for the surname on winners pages of drawn competitions; appends yes/no records, never the name."""
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(entry_queue.MELB).date()
    seen, done = checks(entries), 0
    pat = re.compile(rf"(?i)\b{re.escape(surname.strip())}\b")
    with open(entries / "winner_checks.jsonl", "a") as fh:
        for r in rows:
            if done >= max_pages or not r["winners_page"] or not r["draw_date"]:
                continue
            age = (today - dt.date.fromisoformat(r["draw_date"])).days
            last = seen.get(r["id"], {}).get("checked_utc", "")
            if not 0 <= age <= CHECK_DAYS or seen.get(r["id"], {}).get("name_seen") or \
                    last > (now - dt.timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ"):
                continue
            rec = {"id": r["id"], "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "page": r["winners_page"]}
            try:
                rec["name_seen"] = bool(pat.search(fetch(r["winners_page"])))
            except (OSError, ValueError) as exc:
                rec["error"] = type(exc).__name__
            fh.write(json.dumps(rec) + "\n")
            done += 1
            time.sleep(delay)
    return done


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    rows = build()
    surname = os.environ.get("ENTRANT_LAST_NAME", "")
    if a.check and surname:
        n = check(rows, surname)
        rows = build()
        print(f"winners: checked {n} winners pages", flush=True)
    c = {}
    for r in rows:
        c[r["status"]] = c.get(r["status"], 0) + 1
    print("winners: " + ", ".join(f"{v} {k}" for k, v in c.items()) +
          f"; surname seen on {sum(r['name_seen'] == 'yes' for r in rows)} winners pages", flush=True)


if __name__ == "__main__":
    sys.exit(main())
