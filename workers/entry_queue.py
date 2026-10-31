"""Which free competitions the entrant may enter today, and the manual list for the owner.

    python3 -m workers.entry_queue      # writes data/entries/queue.csv, queue.json (for workers/entrant.mjs), manual.csv

A listing joins the queue when it is open, a Victorian can enter, entry is free, the entry is a web form
(entry_route agent_ok), its terms do not ban automated or third-party entry (comp_odds and comp_terms), and its
entry limit allows another entry now (log.jsonl). The limit comes from the full terms when they state one
(comp_terms), else from the listing summary: once -> one entry ever; daily -> one per Melbourne day; weekly -> one
a week; capped N -> N in total; unlimited, or no limit stated anywhere (owner's call: an unstated limit is no limit)
-> up to BURST entries in any rolling BURST_HOURS, at least GAP_MINUTES apart (owner: 5 every 3 hours, 5 minutes apart),
spread at random through the day outside the quiet hours (11pm-3am Melbourne); but where the terms say the promoter may act on excessive or bulk entries, at
most EXCESSIVE_PER_DAY a day, at least EXCESSIVE_GAP_HOURS apart. The queue only says whether a listing is due now;
how often the entrant runs (entries.yml, or a machine running it every 5 minutes) sets the actual pace. Skill competitions also need an answer the
owner has approved (data/entries/answers.json, filled from the approval issues).
Every other open, Victorian, free competition goes on manual.csv with the reason, as does any listing the entrant
had to skip (CAPTCHA, login, human check, a required field it could not fill).
No personal details are read or written here.
"""
import csv
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from workers import comp_odds, comps, comp_terms

STORE = comps.STORE
ENTRIES = comps.ROOT / "data" / "entries"
QUEUE_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "last_day", "draw_type", "entry_limit", "needs_answer",
                "question", "terms_checked", "entry_url"]
MANUAL_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "draw_type", "reason", "entry_platform", "entry_url"]
MELB = ZoneInfo("Australia/Melbourne")
BURST = int(os.environ.get("ENTRY_BURST") or 5)
BURST_HOURS = 3
GAP_MINUTES = 5
EXCESSIVE_PER_DAY = 4
EXCESSIVE_GAP_HOURS = 5
# Last day (owner, 2026-10-31: "more entries in anything that closes today"): in a competition's final 24 hours a
# burst may come every LAST_DAY_BURST_HOURS instead of every BURST_HOURS (no stated limit only), the excessive-entry
# pace keeps its 4 a day but LAST_DAY_EXCESSIVE_GAP_HOURS apart, a listing comp_terms has not read yet is entered at
# that cautious pace instead of waiting, and a listing blocked for failing gets one more try. Stated limits (once,
# daily, weekly, capped) never change: entering past them can void every entry.
LAST_DAY_BURST_HOURS = 1
LAST_DAY_EXCESSIVE_GAP_HOURS = 3
RETRY_ON_LAST_DAY = ("failing", "no_form")
# Owner's call (2026-10-30, "enter everything"): comps whose terms ban automated entry are entered too, at the
# cautious excessive-entry pace. Repository variable ENTER_BANNED=0 puts them back on the manual list.
ENTER_BANNED = os.environ.get("ENTER_BANNED", "1") != "0"
# Failures logged before the entrant fixes of 30 Oct 2026 (popup forms, JS buttons, overlays, confirmation) get a
# clean slate: they say nothing about the fixed entrant.
RETRY_FROM = "2026-10-30T16:30:00Z"
# Owner, 31 Oct: no automatic entries from 11pm to 3am Melbourne time; entries spread at random through the rest of
# the day (entries.yml picks random run times and round gaps; the queue is shuffled), the per-comp limits unchanged.
QUIET_FROM, QUIET_TO = 23, 3


def quiet(now):
    """True from 11pm to 3am in Melbourne: no automatic entries."""
    h = now.astimezone(MELB).hour
    return h >= QUIET_FROM or h < QUIET_TO


def next_sleep(now, rng=random):
    """Seconds until the next entries run: a random 25-55 minutes, or a random time in the first half hour after the
    quiet hours end."""
    gap = dt.timedelta(minutes=rng.randint(25, 55))
    t = now + gap
    if quiet(t):
        local = t.astimezone(MELB)
        wake = local.replace(hour=QUIET_TO, minute=0, second=0, microsecond=0)
        if wake <= local:
            wake += dt.timedelta(days=1)
        t = wake.astimezone(dt.timezone.utc) + dt.timedelta(minutes=rng.randint(0, 30))
    return int((t - now).total_seconds())
# Result "unknown" (a run whose log was lost, e.g. 41135966222 on 30 Oct 2026): counted as a possible entry against
# stated limits (once, daily, weekly, capped) so they are never exceeded, but not in the register.
# CAPTCHA and bot-check skips logged before the narrower challenge detection (data/analysis/CAPTCHA_CHECK.md: most
# were invisible or passive checks, or widgets on another form) get a clean slate too.
CHECK_FIX_FROM = "2026-10-30T22:45:00Z"
# "Field is required" failures before the Mantine/komo form fixes (answer box, State and dial-code pickers).
FORM_FIX_FROM = "2026-10-30T23:20:00Z"
BLOCKING = {"captcha", "login", "human_check", "payment", "unfillable", "closed", "no_form", "blocked", "moved"}


def read_jsonl(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


REGISTER_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "entries", "first_entered_utc", "last_entered_utc",
                   "entry_url"]


def write_register(store, entries, entered):
    """data/entries/register.csv: every competition the entrant has entered, with how many times and when."""
    recs = {r["id"]: r for r in (json.loads(l)["comp"] for l in comps.stored(store).values())}
    rows = []
    for i, times in entered.items():
        r = recs.get(i, {})
        rows.append({"id": i, "title": r.get("title", ""), "brand": r.get("brand", ""),
                     "prize_pool": r.get("prize_pool"), "closes": close_date(r) if r else "", "entries": len(times),
                     "first_entered_utc": min(times).strftime("%Y-%m-%d %H:%M"),
                     "last_entered_utc": max(times).strftime("%Y-%m-%d %H:%M"), "entry_url": r.get("entry_url", "")})
    rows.sort(key=lambda x: (-x["entries"], x["title"]))
    entries.mkdir(parents=True, exist_ok=True)
    with open(entries / "register.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, REGISTER_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


# Promoters write AEST and AEDT loosely for "Eastern time", so a stated zone means that place's local time.
ZONES = {"aedt": "Australia/Melbourne", "aest": "Australia/Melbourne", "acdt": "Australia/Adelaide",
         "acst": "Australia/Adelaide", "awst": "Australia/Perth"}
# "closes at 6:00 PM AEDT on Saturday, 31 October 2026": the listing's timestamp is often a default (23:59 +10:00)
# while its summary states the promoter's real closing time.
STATED_CLOSE = (r"(?i)clos(?:es|ing)[^.]{0,30}?\b(\d{1,2})(?:[:.](\d\d))? ?([ap])\.?m\.? ?\(?(" + "|".join(ZONES) +
                r")\)?[^.]{0,25}?(\d{1,2})(?:st|nd|rd|th)? (january|february|march|april|may|june|july|august|september|"
                r"october|november|december),? (20\d\d)")
# "The competition closes at 11:59 PM Sydney time on 15 November 2026": a close date in the summary, any time format.
CLOSE_DATE = (r"(?i)\bclos(?:es|ing|e)\b[^.]{0,70}?\b(\d{1,2})(?:st|nd|rd|th)? (january|february|march|april|may|june|"
              r"july|august|september|october|november|december),? (20\d\d)")
MONTH_NO = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                        "september", "october", "november", "december"], 1)}


def closes_at(r):
    """The listing's closing time (UTC): the time its summary states when that falls on the listing's closing date,
    else its timestamp, a bare date meaning the end of that Melbourne day; None when unknown."""
    c = r.get("closes")
    if not c:
        return None
    try:
        t = dt.datetime.fromisoformat(c.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(c) <= 10 or (t.hour, t.minute) == (23, 59):
        # A bare date, or the aggregators' "end of day" (23:59:59 at a fixed +10:00 or +11:00): the end of that day in
        # Melbourne. Read literally, +10:00 in daylight saving is 00:59 the next day and showed every date a day late.
        t = dt.datetime.combine(t.date(), dt.time(23, 59), MELB)
    elif t.tzinfo is None:
        t = t.replace(tzinfo=MELB)
    desc = r.get("description") or ""
    said = re.search(CLOSE_DATE, desc)
    if said:
        try:
            day = dt.date(int(said.group(3)), MONTH_NO[said.group(2).lower()], int(said.group(1)))
            if t.year > dt.date.today().year + 3 or day > t.astimezone(MELB).date() + dt.timedelta(days=1):
                # the listing's year is a typo (2204), or the summary says the competition runs longer than listed:
                # trust the later, stated date (entering a closed comp only fails; missing an open one loses it)
                t = dt.datetime.combine(day, dt.time(23, 59), MELB)
        except ValueError:
            pass
    m = re.search(STATED_CLOSE, desc)
    if m:
        h, mi, ap, zone, d, mon, y = m.groups()
        h = int(h) % 12 + (12 if ap.lower() == "p" else 0)
        try:
            day = dt.date(int(y), MONTH_NO[mon.lower()], int(d))
            tz = ZoneInfo(ZONES[zone.lower()])
            stated = dt.datetime.combine(day, dt.time(h, int(mi or 0)), tz)
            if abs((stated.date() - t.date()).days) <= 1:
                return stated.astimezone(dt.timezone.utc)
        except ValueError:
            pass
    return t.astimezone(dt.timezone.utc)


def close_date(r):
    """The listing's closing date in Melbourne ("2026-10-31"), from closes_at; "" when unknown."""
    t = closes_at(r)
    return t.astimezone(MELB).date().isoformat() if t else ""


def last_day(r, now):
    """True in a listing's final 24 hours."""
    c = closes_at(r)
    return c is not None and dt.timedelta(0) <= c - now <= dt.timedelta(hours=24)


def may_enter(limit, entered, now, n=None, excessive=False, final=False):
    """Whether the entry limit allows another entry now, given the UTC datetimes of past successful entries.
    final: the listing's last day (shorter burst windows and gaps; stated limits unchanged)."""
    local = now.astimezone(MELB)
    today = [t for t in entered if t.astimezone(MELB).date() == local.date()]
    last = max(entered) if entered else None
    if limit == "once":
        return not entered
    if limit == "daily":
        return len(today) < (n or 1)
    if limit == "weekly":
        return not entered or (now - max(entered)).days >= 7
    if excessive:
        gap = LAST_DAY_EXCESSIVE_GAP_HOURS if final else EXCESSIVE_GAP_HOURS
        ok = len(today) < EXCESSIVE_PER_DAY and (last is None or now - last >= dt.timedelta(hours=gap))
        return ok and (limit != "capped" or len(entered) < (n or 1))
    hours = LAST_DAY_BURST_HOURS if final else BURST_HOURS
    window = [t for t in entered if now - t < dt.timedelta(hours=hours)]      # rolling window: no fixed clock slots
    ok = len(window) < BURST and (last is None or now - last >= dt.timedelta(minutes=GAP_MINUTES))
    return ok and (limit != "capped" or len(entered) < (n or 1))     # unlimited, unknown, capped


def build(store=STORE, entries=ENTRIES, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    tags, caps = comp_odds.tags(store), comp_odds.caps(store)
    terms = comp_terms.history(store)
    log = sorted((x for f in sorted(entries.glob("log*.jsonl")) for x in read_jsonl(f)),   # main and re-enter logs
                 key=lambda x: x.get("time_utc", ""))
    answers = json.loads((entries / "answers.json").read_text()) if (entries / "answers.json").exists() else {}
    entered, blocked, fails, done_once, tried, maybe, removed = {}, {}, {}, set(), {}, {}, set()
    for e in log:
        if e.get("result") == "removed":                   # the owner removed it (site Remove button, log_removed)
            removed.add(e["id"])
            continue
        tried[e["id"]] = e.get("time_utc", "")
        if e.get("mode") == "live" and e.get("result") == "unknown":   # a run whose log was lost: may have entered
            maybe.setdefault(e["id"], []).append(dt.datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00")))
            continue
        if e.get("mode") == "live" and e.get("result") == "entered":
            entered.setdefault(e["id"], []).append(
                dt.datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00")))
        if e.get("time_utc", "") < RETRY_FROM and (e.get("result") == "failed" or
                                                  e.get("reason") in ("no_submit", "unfillable")):
            continue
        if e.get("time_utc", "") < CHECK_FIX_FROM and e.get("reason") in ("captcha", "human_check"):
            continue
        if e.get("time_utc", "") < FORM_FIX_FROM and e.get("reason", "").startswith(("form said: is required",
                                                                                   "form said: please fill")):
            continue
        if e.get("result") in ("skipped", "failed", "entered", "dry_ok"):   # the latest attempt decides
            fails[e["id"]] = fails.get(e["id"], 0) + 1 if e.get("result") == "failed" else 0
            if e.get("result") == "skipped" and e.get("reason") in BLOCKING:
                blocked[e["id"]] = e["reason"]
            elif fails[e["id"]] >= 2:                         # two failures in a row: stop retrying, list it
                blocked[e["id"]] = f"failing ({e.get('reason', '')[:40]})"
            elif e.get("result") == "entered" and e.get("reason") == "already entered":
                done_once.add(e["id"])                        # the form keeps one entry per email: no more
            else:
                blocked.pop(e["id"], None)
    from workers import entry_pages            # imports this module
    pages = entry_pages.latest(store)
    queue, manual, last_day_ids = [], [], set()
    for r in (json.loads(l)["comp"] for l in comps.stored(store).values()):
        if not r.get("open_to_vic") or (closes_at(r) or now) < now:
            continue
        if r["id"] in removed:
            continue
        a = comp_odds.assess(r, tags.get(r["id"], ()), caps.get(r["id"]))
        final = last_day(r, now)
        start_of_last_day = ((closes_at(r) or now) - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if a["purchase"] == "yes":
            continue
        banned = a["automation_banned"] == "yes" or any(h.get("automation_banned") for h in terms.get(r["id"], []))
        checked = any(h.get("terms_read") for h in terms.get(r["id"], []))
        row = {**a, "terms_checked": checked, "last_day": final}
        reason = None
        if a["entry_route"] != "agent_ok":
            reason = f"entry route {a['entry_route']}"
        elif banned and not ENTER_BANNED:
            reason = "terms ban automated entry"
        elif pages.get(r["id"], {}).get("kind") in ("dead", "moved", "home", "wrong"):
            reason = f"entry link {pages[r['id']]['kind']} (workers/entry_pages.py)"
        elif r["id"] in blocked and not (final and blocked[r["id"]].startswith(RETRY_ON_LAST_DAY)
                                         and tried.get(r["id"], "") < start_of_last_day):
            reason = f"entrant blocked: {blocked[r['id']]}"
        if reason:
            manual.append({**row, "reason": reason})
            continue
        if r["id"] not in terms and not final:
            continue                      # wait until comp_terms has looked for an automation ban
        hist = terms.get(r["id"], [])
        stated = next((h for h in reversed(hist) if h.get("entry_limit_terms")), None)
        limit = stated["entry_limit_terms"] if stated else a["entry_limit"]
        n = stated.get("entry_limit_terms_n") if stated else a["entry_limit_n"]
        if a["draw_type"] == "skill":
            limit = "once"                    # one judged answer per competition: repeats of it add nothing
        row["entry_limit"] = limit
        if final and limit != "once" and r["id"] not in done_once:
            last_day_ids.add(r["id"])         # can take more entries today: keep entries.yml running hourly
        excessive = banned or not hist or any(h.get("excessive_clause") for h in hist)   # unread terms: cautious
        past = entered.get(r["id"], []) + (maybe.get(r["id"], []) if limit not in ("unlimited", "unknown") else [])
        if r["id"] in done_once or not may_enter(limit, past, now, n, excessive, final):
            continue
        row["needs_answer"] = a["draw_type"] == "skill" and str(r["id"]) not in answers
        queue.append(row)
    write_register(store, entries, entered)
    queue.sort(key=lambda x: (x["needs_answer"], x["closes"] or "9"))
    manual.sort(key=lambda x: x["closes"] or "9")
    entries.mkdir(parents=True, exist_ok=True)
    for name, fields, rows in (("queue.csv", QUEUE_FIELDS, queue), ("manual.csv", MANUAL_FIELDS, manual)):
        with open(entries / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    better = lambda q: pages.get(q["id"], {}).get("better_url") if pages.get(q["id"], {}).get("kind") == "terms" else None
    ready_items = [{"id": q["id"], "entry_url": better(q) or q["entry_url"], "answer": answers.get(str(q["id"]))}
                   for q in queue if not q["needs_answer"]]
    if quiet(now):
        ready_items = []                       # 11pm-3am Melbourne: nothing goes in
    first = [x for x in ready_items if x["id"] in last_day_ids]
    rest = [x for x in ready_items if x["id"] not in last_day_ids]
    random.shuffle(first)
    random.shuffle(rest)
    ready_items = first + rest                 # last-day comps first, otherwise a different order every round
    (entries / "queue.json").write_text(json.dumps(ready_items, indent=1))
    ready = len(ready_items)
    # entries.yml reads this to decide when its next run starts: hourly while any open listing is in its last day
    # and could still take an entry under the faster pace, else at the next 3-hour window.
    rush = len(last_day_ids)
    (entries / "pace.json").write_text(json.dumps({"last_day_listings": rush,
                                                   "next_run_minutes": 60 if rush else 180}) + "\n")
    print(f"entry_queue: {ready} ready to enter, {len(queue) - ready} waiting for an approved answer, "
          f"{len(manual)} on the manual list", flush=True)
    return queue, manual


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--next-sleep"]:
        print(next_sleep(dt.datetime.now(dt.timezone.utc)))
        return
    build()


if __name__ == "__main__":
    sys.exit(main())
