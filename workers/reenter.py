"""Owner-requested re-entries: turn a "reenter: <ids>" request into a queue file for workers/entrant.mjs.

    python3 -m workers.reenter "reenter: 75870 76058" > queue.json

Used by workers/actions.py (the actions job) for the site's Re-enter and Submit now buttons.
Only listings in the register that are still open are queued; approved skill answers go with them. The entrant
still skips CAPTCHAs, logins and bot checks, and the results go to data/entries/log_reenter.jsonl.
"""
import datetime as dt
import json
import re
import sys

from workers import comps, entry_queue


def build(text, store=comps.STORE, entries=entry_queue.ENTRIES, today=None):
    today = (today or dt.date.today()).isoformat()
    ids = list(dict.fromkeys(int(x) for x in re.findall(r"\b(\d{5,9})\b", text or "")))
    recs = {r["id"]: r for r in (json.loads(l)["comp"] for l in comps.stored(store).values())}
    path = entries / "answers.json"
    answers = json.loads(path.read_text()) if path.exists() else {}
    out = []
    for i in ids:
        r = recs.get(i)
        if not r or not r.get("entry_url") or (entry_queue.close_date(r) or "9") < today:
            continue
        out.append({"id": i, "entry_url": r["entry_url"], "answer": answers.get(str(i))})
    return out


def main(argv=None):
    print(json.dumps(build(" ".join(sys.argv[1:] if argv is None else argv)), indent=1))


if __name__ == "__main__":
    sys.exit(main())
