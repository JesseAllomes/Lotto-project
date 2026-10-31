"""Site actions from the queue: apply what the owner tapped on the page, with the existing workers.

The site's buttons POST to the Static Web App API (azure/site-api), which puts one message per request on the Azure
Storage queue `lotto-actions`.  The Container Apps job lotto-actions (azure/runner.py, mode `actions`) reads the
messages and calls this module.  This module touches files only; the runner owns the queue, the blob store and the
browser, so nothing here needs a network.

    {"v": 1, "id": "<unique>", "t": <epoch ms>, "kind": "remove|broken|reenter|answer|done|undone",
     "ids": ["75870"], "answer": "text (answer only)"}

  remove, broken  workers.removals.record (log_removed.jsonl; "broken" = Doesn't work, not a dislike)
  answer          workers.answers.save (word limit; data/entries/answers.json)
  done, undone    data/entries/done.json {id: epoch ms}: the Done ticks, shared between devices and read by the page
  reenter         collected by the runner, which builds the queue with plan_reenter() and runs workers/entrant.mjs

Every message is validated again here (the queue is not trusted).  Each handled message adds one row to
data/entries/actions_applied.jsonl, which makes a redelivered message harmless.  That file must not be named log*:
workers.entry_queue reads every data/entries/log*.jsonl as an entry log.
"""
import base64
import binascii
import datetime as dt
import json
import re

from workers import answers, comps, entry_queue, reenter, removals

ENTRIES = entry_queue.ENTRIES
KINDS = ("remove", "broken", "reenter", "answer", "done", "undone")
MAX_IDS = 50
MAX_ANSWER_CHARS = 2000
MAX_MESSAGE_BYTES = 32 * 1024            # a decoded message; the API's body limit is 16 KB
ID_RE = re.compile(r"[0-9]{5,9}")
FIELDS = frozenset({"v", "id", "t", "kind", "ids", "answer"})
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DONE_FILE = "done.json"
APPLIED_FILE = "actions_applied.jsonl"


class Rejected(ValueError):
    """The message can never be applied (malformed or not allowed); it belongs on the poison queue."""


def decode(text):
    """The JSON document in a queue message: base64 JSON (what the API sends), or plain JSON."""
    text = (text or "").strip()
    if len(text) > MAX_MESSAGE_BYTES * 2:
        raise Rejected("message too large")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raw = text.encode("utf-8")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise Rejected("message too large")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Rejected("message is not JSON") from None


def validate(doc):
    """The normalised action {id, t, kind, ids, answer?}; the same rules as azure/site-api/lotto_actions.validate."""
    if not isinstance(doc, dict):
        raise Rejected("not an object")
    if set(doc) - FIELDS:
        raise Rejected("unknown field")
    kind = doc.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise Rejected("unknown kind")
    ids = doc.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > MAX_IDS or \
            not all(isinstance(i, str) and ID_RE.fullmatch(i) for i in ids):
        raise Rejected("bad ids")
    ident, t = doc.get("id"), doc.get("t")
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
        raise Rejected("bad action id")
    if not isinstance(t, int) or isinstance(t, bool) or t <= 0:
        raise Rejected("bad time")
    out = {"id": ident, "t": t, "kind": kind, "ids": list(dict.fromkeys(ids))}
    if kind == "answer":
        answer = doc.get("answer")
        if len(out["ids"]) != 1 or not isinstance(answer, str) or not answer.strip() \
                or len(answer) > MAX_ANSWER_CHARS or CONTROL.search(answer):
            raise Rejected("bad answer")
        out["answer"] = answer
    elif "answer" in doc:
        raise Rejected("answer is only for kind answer")
    return out


def parse(text):
    return validate(decode(text))


# ---------------------------------------------------------------------------------------------------- audit rows
def applied_ids(entries=ENTRIES):
    """Action ids already handled (data/entries/actions_applied.jsonl)."""
    return {r.get("action_id") for r in entry_queue.read_jsonl(entries / APPLIED_FILE)}


def record_result(entries, action, outcome, detail="", now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    entries.mkdir(parents=True, exist_ok=True)
    row = {"time_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "action_id": action["id"], "kind": action["kind"],
           "ids": action["ids"], "outcome": outcome, "detail": detail[:300]}
    with open(entries / APPLIED_FILE, "a") as fh:
        fh.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------------------------------------------ done.json
def load_done(entries=ENTRIES):
    path = entries / DONE_FILE
    try:
        doc = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}
    return {str(k): int(v) for k, v in doc.items() if isinstance(v, (int, float))} if isinstance(doc, dict) else {}


def set_done(ids, on, t, entries=ENTRIES):
    """Tick (on) or untick the ids; the time is the owner's tap, so the page can order ticks from different devices."""
    done = load_done(entries)
    for i in ids:
        if on:
            done[i] = max(t, done.get(i, 0))
        else:
            done.pop(i, None)
    entries.mkdir(parents=True, exist_ok=True)
    (entries / DONE_FILE).write_text(json.dumps(dict(sorted(done.items())), indent=1) + "\n")
    return len(ids)


# ---------------------------------------------------------------------------------------------------------- apply
def apply_one(action, store=comps.STORE, entries=ENTRIES):
    """Apply one validated action to the files; returns (outcome, detail).  outcome is "applied" or "rejected" (the
    action was understood but refused, e.g. an answer over its word limit: it is recorded and not retried) or
    "pending" for a re-entry, which the runner enters after the files are done.  Unexpected errors propagate: the
    message stays on the queue and is tried again."""
    kind, ids = action["kind"], action["ids"]
    if kind in ("remove", "broken"):
        done = removals.record(f"{kind}: {' '.join(ids)}", store, entries)
        return "applied", f"{kind}: recorded {len(done)} of {len(ids)}"
    if kind == "answer":
        ok, message = answers.save(f"answer: {ids[0]}", "---\n" + action["answer"], store, entries)
        return ("applied" if ok else "rejected"), message
    if kind in ("done", "undone"):
        set_done(ids, kind == "done", action["t"], entries)
        return "applied", f"{kind}: {len(ids)}"
    return "pending", "re-entry"


def plan_reenter(ids, store=comps.STORE, entries=ENTRIES, limit=None, today=None):
    """The entrant's queue for these ids: only open listings in the register (reenter.build), approved answers go with
    them, anything the owner removed is left out, and at most `limit` items (the entrant's ENTRANT_MAX)."""
    gone = {str(i) for i in removals.removed_ids(entries)}
    wanted = [i for i in dict.fromkeys(ids) if i not in gone]
    items = reenter.build("reenter: " + " ".join(wanted), store, entries, today)
    return items[:limit] if limit else items
