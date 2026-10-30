"""Ranked list of open skill competitions a Victorian can enter: effort, chance, skill level, overall score.

    python3 -m analysis.skill_rank     # writes data/comps/skill_ranked.csv from data/comps/skill.csv

Scores run 1 to 5 and come from the listing's terms summary, not from entrant counts (promoters do not publish
them), so "chance" is an estimate of how thin the field is likely to be, not a probability.

  effort   1 quick answer ... 5 a produced video; +1 when a purchase is needed or the word limit is over 100
  skill    1 closest guess ... 4 video, recipe, art or a story; public-vote finals count as 2 (popularity, not merit)
  chance   starts at 3; more prizes, a purchase or a high effort bar thin the field (up); a large prize, unlimited
           entries for everyone, or a public vote widen it (down)
  overall  0 to 10: half chance, a quarter low effort, a quarter low skill needed. Weights are in WEIGHTS.
"""
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

from workers import comp_odds, comps

STORE = comps.STORE
OUT = "skill_ranked.csv"
WEIGHTS = {"chance": 0.5, "effort": 0.25, "skill": 0.25}
TASK_EFFORT = {"prediction (closest guess)": 1, "quiz": 1, "written answer": 2, "25 words or less": 2,
               "story or poem": 3, "photo": 3, "other": 2, "recipe": 4, "drawing or art": 4, "video": 5}
TASK_SKILL = {"prediction (closest guess)": 1, "quiz": 2, "written answer": 3, "25 words or less": 3,
              "story or poem": 4, "photo": 3, "other": 3, "recipe": 4, "drawing or art": 4, "video": 4}
FIELDS = ["rank", "overall", "chance", "effort", "skill", "title", "brand", "prize_pool", "prizes", "prize_per_winner",
          "closes", "days_left", "task", "word_limit", "public_vote", "question", "entry_limit", "purchase", "why",
          "entry_url", "url"]


def clamp(x, lo=1.0, hi=5.0):
    return max(lo, min(hi, x))


def word_limit(text):
    m = re.search(r"(?i)(\d+) words? or (?:less|fewer)|(?:maximum|max\.?|up to|no more than) (?:of )?(\d+) words", text)
    return int(m.group(1) or m.group(2)) if m else None


def score(row, desc, today):
    """Effort, skill, chance (1-5), overall (0-10) and the reasons, for one skill-list row."""
    task = row["task"] or "other"
    sec = comp_odds.sections(desc)
    text = " ".join([sec.get("enter", ""), sec.get("select", ""), row.get("question") or ""])
    words = word_limit(text)
    vote = bool(re.search(r"(?i)public vot|most votes|voting", sec.get("select", "") or desc))
    prizes = int(row["prizes"]) if row.get("prizes") else 1
    pool = float(row["prize_pool"]) if row.get("prize_pool") else None
    why = []

    effort = TASK_EFFORT.get(task, 2)
    if row.get("purchase") == "yes":
        effort += 1
        why.append("purchase needed")
    if words and words > 100:
        effort += 1
        why.append(f"{words}-word limit")
    effort = clamp(effort)

    skill = 2 if vote else TASK_SKILL.get(task, 3)
    if vote:
        why.append("public vote decides")

    chance = 3.0 + 0.4 * (effort - 2)
    if prizes >= 10:
        chance += 1.5
    elif prizes >= 3:
        chance += 1.0
    elif prizes == 2:
        chance += 0.5
    if prizes > 1:
        why.append(f"{prizes} prizes")
    if pool is not None and pool / prizes >= 10_000:
        chance -= 1.0
        why.append("big prize draws a crowd")
    elif pool is not None and pool / prizes >= 2_000:
        chance -= 0.5
    elif pool is not None and pool / prizes < 300:
        chance += 0.5
        why.append("small prize, fewer entrants")
    if row.get("entry_limit") == "unlimited":
        chance -= 0.5
        why.append("others may enter many times")
    if row.get("purchase") == "yes":
        chance += 0.5
    if vote:
        chance -= 1.0
    chance = round(clamp(chance), 1)

    overall = round(2 * (WEIGHTS["chance"] * chance + WEIGHTS["effort"] * (6 - effort) + WEIGHTS["skill"] * (6 - skill)),
                    1)
    closes = (row.get("closes") or "")[:10]
    days = (dt.date.fromisoformat(closes) - today).days if closes else None
    return {"overall": overall, "chance": chance, "effort": int(effort), "skill": int(skill), "word_limit": words,
            "public_vote": vote, "prize_per_winner": round(pool / prizes) if pool else None, "days_left": days,
            "why": "; ".join(why)}


def run(store=STORE, today=None):
    today = today or dt.date.today()
    descs = {json.loads(l)["comp"]["id"]: json.loads(l)["comp"].get("description") or ""
             for l in comps.stored(store).values()}
    path = store / "skill.csv"
    rows = list(csv.DictReader(open(path))) if path.exists() else []
    out = [dict(r, **score(r, descs.get(int(r["id"]), ""), today)) for r in rows]
    out.sort(key=lambda r: (-r["overall"], -r["chance"], r["closes"] or "9"))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    with open(store / OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    print(f"skill_rank: {len(out)} skill competitions ranked", flush=True)
    return out


def main(argv=None):
    run()


if __name__ == "__main__":
    sys.exit(main())
