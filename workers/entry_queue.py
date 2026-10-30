"""Which free competitions the entrant may enter today, and the manual list for the owner.

    python3 -m workers.entry_queue      # writes data/entries/queue.csv, queue.json (for workers/entrant.mjs), manual.csv

A listing joins the queue when it is open, a Victorian can enter, entry is free, the entry is a web form
(entry_route agent_ok), its terms do not ban automated or third-party entry (comp_odds and comp_terms), and its
entry limit allows another entry now (log.jsonl). The limit comes from the full terms when they state one
(comp_terms), else from the listing summary: once -> one entry ever; daily -> one per Melbourne day; weekly -> one
a week; capped N -> N in total; unlimited, or no limit stated anywhere (owner's call: an unstated limit is no limit)
-> bursts: up to BURST entries in each BURST_HOURS window (UTC clock windows, matching the entries.yml schedule, so
daylight saving never splits a burst), at least GAP_MINUTES apart (owner: 5 every 3 hours, 5 minutes apart); but where the terms say the promoter may act on excessive or bulk entries, at
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
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from workers import comp_odds, comps, comp_terms

STORE = comps.STORE
ENTRIES = comps.ROOT / "data" / "entries"
QUEUE_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "draw_type", "entry_limit", "needs_answer",
                "question", "terms_checked", "entry_url"]
MANUAL_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "draw_type", "reason", "entry_platform", "entry_url"]
MELB = ZoneInfo("Australia/Melbourne")
BURST = int(os.environ.get("ENTRY_BURST") or 5)
BURST_HOURS = 3
GAP_MINUTES = 5
EXCESSIVE_PER_DAY = 4
EXCESSIVE_GAP_HOURS = 5
BLOCKING = {"captcha", "login", "human_check", "payment", "unfillable", "closed"}


def read_jsonl(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def may_enter(limit, entered, now, n=None, excessive=False):
    """Whether the entry limit allows another entry now, given the UTC datetimes of past successful entries."""
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
        ok = len(today) < EXCESSIVE_PER_DAY and (last is None or now - last >= dt.timedelta(hours=EXCESSIVE_GAP_HOURS))
        return ok and (limit != "capped" or len(entered) < (n or 1))
    slot = lambda t: (t.astimezone(dt.timezone.utc).date(), t.astimezone(dt.timezone.utc).hour // BURST_HOURS)
    window = [t for t in entered if slot(t) == slot(now)]
    ok = len(window) < BURST and (last is None or now - last >= dt.timedelta(minutes=GAP_MINUTES))
    return ok and (limit != "capped" or len(entered) < (n or 1))     # unlimited, unknown, capped


def build(store=STORE, entries=ENTRIES, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    iso = now.astimezone(MELB).date().isoformat()
    tags, caps = comp_odds.tags(store), comp_odds.caps(store)
    terms = comp_terms.history(store)
    log = read_jsonl(entries / "log.jsonl")
    answers = json.loads((entries / "answers.json").read_text()) if (entries / "answers.json").exists() else {}
    entered, blocked = {}, {}
    for e in log:
        if e.get("mode") == "live" and e.get("result") == "entered":
            entered.setdefault(e["id"], []).append(
                dt.datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00")))
        if e.get("result") == "skipped" and e.get("reason") in BLOCKING:
            blocked[e["id"]] = e["reason"]
    queue, manual = [], []
    for r in (json.loads(l)["comp"] for l in comps.stored(store).values()):
        if not r.get("open_to_vic") or (r.get("closes") or "9")[:10] < iso:
            continue
        a = comp_odds.assess(r, tags.get(r["id"], ()), caps.get(r["id"]))
        if a["purchase"] == "yes":
            continue
        banned = a["automation_banned"] == "yes" or any(h.get("automation_banned") for h in terms.get(r["id"], []))
        checked = any(h.get("terms_read") for h in terms.get(r["id"], []))
        row = {**a, "terms_checked": checked}
        reason = None
        if a["entry_route"] != "agent_ok":
            reason = f"entry route {a['entry_route']}"
        elif banned:
            reason = "terms ban automated entry"
        elif r["id"] in blocked:
            reason = f"entrant blocked: {blocked[r['id']]}"
        if reason:
            manual.append({**row, "reason": reason})
            continue
        if r["id"] not in terms:
            continue                      # wait until comp_terms has looked for an automation ban
        stated = next((h for h in reversed(terms[r["id"]]) if h.get("entry_limit_terms")), None)
        limit = stated["entry_limit_terms"] if stated else a["entry_limit"]
        n = stated.get("entry_limit_terms_n") if stated else a["entry_limit_n"]
        row["entry_limit"] = limit
        excessive = any(h.get("excessive_clause") for h in terms[r["id"]])
        if not may_enter(limit, entered.get(r["id"], []), now, n, excessive):
            continue
        row["needs_answer"] = a["draw_type"] == "skill" and str(r["id"]) not in answers
        queue.append(row)
    queue.sort(key=lambda x: (x["needs_answer"], x["closes"] or "9"))
    manual.sort(key=lambda x: x["closes"] or "9")
    entries.mkdir(parents=True, exist_ok=True)
    for name, fields, rows in (("queue.csv", QUEUE_FIELDS, queue), ("manual.csv", MANUAL_FIELDS, manual)):
        with open(entries / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    ready_items = [{"id": q["id"], "entry_url": q["entry_url"], "answer": answers.get(str(q["id"]))}
                   for q in queue if not q["needs_answer"]]
    (entries / "queue.json").write_text(json.dumps(ready_items, indent=1))
    ready = len(ready_items)
    print(f"entry_queue: {ready} ready to enter, {len(queue) - ready} waiting for an approved answer, "
          f"{len(manual)} on the manual list", flush=True)
    return queue, manual


def main(argv=None):
    build()


if __name__ == "__main__":
    sys.exit(main())
