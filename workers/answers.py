"""The owner's approved answers for skill competitions (data/entries/answers.json).

    python3 -m workers.answers "answer: 76111" < issue_body.txt     # save the answer written in an issue body
    python3 -m workers.answers --question 76111                     # print the question for a listing

The site's Write answer / Edit button opens a pre-filled issue "answer: <id>" whose body holds the question and a line
"---"; the owner writes the answer below that line and submits. .github/workflows/answer.yml (owner's issues only)
saves it here when it fits the word limit the question states ("25 words or less"; 25 when none is stated) and is
not empty; the auto-entrant uses it on its next run, or at once through Submit all approved. Writing the answer in
the issue is the approval: nothing else is invented on the owner's behalf.
"""
import json
import re
import sys

from workers import comps, entry_queue

ENTRIES = entry_queue.ENTRIES
DEFAULT_LIMIT = 25
QUESTION = r"(?i)[^.?!]*(?:\d+ words|tell us|in (?:\d+|twenty[- ]five|fifty) words|what (?:is|would|was)|why|how would|" \
           r"describe|share|question)[^.?!]*[.?!]"


def question(r, queued=None):
    """The question a skill competition asks: the queue's when it has one, else the first question-like sentence of
    the listing summary."""
    if queued:
        return queued
    m = re.search(QUESTION, re.sub(r"\*\*[^*]+\*\*", " ", r.get("description") or ""))
    return re.sub(r"\s+", " ", m.group(0)).strip()[:300] if m else ""


def word_limit(text):
    m = re.search(r"(?i)(\d+|twenty[- ]five|fifty)\s*words", text or "")
    if not m:
        return DEFAULT_LIMIT
    return {"twenty-five": 25, "twenty five": 25, "fifty": 50}.get(m.group(1).lower()) or int(m.group(1))


def from_body(body):
    """The answer written below the '---' line of the issue body (whitespace tidied)."""
    part = body.split("---", 1)[1] if "---" in (body or "") else (body or "")
    return re.sub(r"\s+", " ", part).strip().strip('"').strip()


def save(title, body, store=comps.STORE, entries=ENTRIES):
    """(ok, message). Saves answers.json[id] when the answer fits the limit."""
    m = re.search(r"\b(\d{5,9})\b", title or "")
    recs = {json.loads(l)["comp"]["id"]: json.loads(l)["comp"] for l in comps.stored(store).values()}
    if not m or int(m.group(1)) not in recs:
        return False, "No known competition id in the title."
    i, text = int(m.group(1)), from_body(body)
    limit = word_limit((body or "").split("---", 1)[0] + " " + question(recs[i]))
    n = len(re.findall(r"[\w'’-]+", text))
    if not text:
        return False, "The answer was empty: write it below the --- line."
    if n > limit:
        return False, f"The answer has {n} words; the limit is {limit}. Nothing saved: edit and submit again."
    path = entries / "answers.json"
    answers = json.loads(path.read_text()) if path.exists() else {}
    answers[str(i)] = text
    path.write_text(json.dumps(answers, indent=1, ensure_ascii=False) + "\n")
    return True, f"Saved ({n} of {limit} words) for {i}: {recs[i].get('title', '')}. It goes in on the next entry run."


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--question"]:
        recs = {json.loads(l)["comp"]["id"]: json.loads(l)["comp"] for l in comps.stored(comps.STORE).values()}
        print(question(recs[int(args[1])]))
        return 0
    ok, msg = save(" ".join(args), sys.stdin.read())
    print(msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
