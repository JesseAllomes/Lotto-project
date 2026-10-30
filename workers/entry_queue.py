"""Which free competitions the entrant may enter today, and the manual list for the owner.

    python3 -m workers.entry_queue      # writes data/entries/queue.csv and data/entries/manual.csv

A listing joins the queue when it is open, a Victorian can enter, entry is free, the entry is a web form
(entry_route agent_ok), its terms do not ban automated or third-party entry (comp_odds and comp_terms), and its
entry limit allows another entry now (log.jsonl): once (or unstated) -> one entry ever; daily -> one a day;
weekly -> one a week; unlimited or per-purchase -> one a day at most. Skill competitions also need an answer the
owner has approved (data/entries/answers.json, filled from the approval issues).
Every other open, Victorian, free competition goes on manual.csv with the reason, as does any listing the entrant
had to skip (CAPTCHA, login, human check, a required field it could not fill).
No personal details are read or written here.
"""
import csv
import datetime as dt
import json
import sys
from pathlib import Path

from workers import comp_odds, comps, comp_terms

STORE = comps.STORE
ENTRIES = comps.ROOT / "data" / "entries"
QUEUE_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "draw_type", "entry_limit", "needs_answer",
                "question", "terms_checked", "entry_url"]
MANUAL_FIELDS = ["id", "title", "brand", "prize_pool", "closes", "draw_type", "reason", "entry_platform", "entry_url"]
GAP_DAYS = {"once": None, "unknown": None, "daily": 1, "weekly": 7, "unlimited": 1, "per_purchase": 1, "capped": 1}
BLOCKING = {"captcha", "login", "human_check", "payment", "unfillable", "closed"}


def read_jsonl(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def may_enter(limit, entered_dates, today):
    """Whether the entry limit allows another entry today, given the dates of past successful entries."""
    if not entered_dates:
        return True
    gap = GAP_DAYS.get(limit)
    if gap is None:
        return False
    return (today - max(entered_dates)).days >= gap


def build(store=STORE, entries=ENTRIES, today=None):
    today = today or dt.date.today()
    iso = today.isoformat()
    tags, caps = comp_odds.tags(store), comp_odds.caps(store)
    terms = comp_terms.history(store)
    log = read_jsonl(entries / "log.jsonl")
    answers = json.loads((entries / "answers.json").read_text()) if (entries / "answers.json").exists() else {}
    entered, blocked = {}, {}
    for e in log:
        if e.get("mode") == "live" and e.get("result") == "entered":
            entered.setdefault(e["id"], []).append(dt.date.fromisoformat(e["time_utc"][:10]))
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
        if not may_enter(a["entry_limit"], entered.get(r["id"], []), today):
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
    ready = sum(1 for q in queue if not q["needs_answer"])
    print(f"entry_queue: {ready} ready to enter, {len(queue) - ready} waiting for an approved answer, "
          f"{len(manual)} on the manual list", flush=True)
    return queue, manual


def main(argv=None):
    build()


if __name__ == "__main__":
    sys.exit(main())
