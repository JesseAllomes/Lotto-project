"""A relative chance-of-winning estimate for free competitions, for sorting the site.

Nobody publishes how many people enter a free competition, so this is an estimate from what the listing shows:
    chance ~ prizes x your entries / expected entrants
    expected entrants = BASE x (prize value / $1,000)^0.5 x effort factor x (days open / 30)^0.5
- prizes: "1 of 5", "5 x", "1/5", "100 winners" in the title; 1 otherwise.
- your entries: 1, or the days left for a daily competition (at most 30).
- effort: entrants thin out where entering takes work (a judged answer, mail, a long form behind a bot check) and
  crowd in where it is one tap (social comment-and-tag giveaways).
Bands: the top fifth of open listings by this estimate is "high", the bottom two fifths "low". It ranks; it does not
promise odds.
"""
import datetime as dt
import math
import re

from workers import comp_odds, comps, entry_queue

BASE = 2000
EFFORT = {"skill": 0.25, "instant": 1.5, "social": 1.6, "manual": 0.7, "web": 1.0, "mail": 0.3}
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "twenty": 20, "fifty": 50, "hundred": 100}


def winners(r, prizes=None):
    """Prizes on offer: the larger of the title's count and the summary's ("10 winners", "1 in 100 wins")."""
    d = (r.get("description") or "").lower()
    found = [int(x) for x in re.findall(r"\b(\d{1,5}) (?:lucky )?(?:winners|prizes|prize packs|draws)\b", d)]
    found += [int(x) for x in re.findall(r"\b1 in (\d{1,5}) (?:wins|win|entrants? wins?)\b", d)]
    title_n = _title_winners(r)
    return max([title_n] + [n for n in found if 1 < n <= 10000])


def _title_winners(r):
    t = (r.get("title") or "").lower()
    m = re.search(r"\b1\s?(?:of|/)\s?(\d{1,5})\b|\b(\d{1,5})\s?x\b|\b(\d{1,5}) (?:winners|prizes|lucky)\b|"
                  r"\bone of (\w+)\b", t)
    if m:
        n = m.group(1) or m.group(2) or m.group(3)
        n = int(n) if n else WORDS.get(m.group(4) or "", 1)
        return max(1, n)
    return 1                  # comp_odds' prize count misreads amounts ("$2K" -> 2,000), so only the title counts


GATED = (r"(?i)existing (?:customer|member)s?|members? only|must be an? (?:active |registered )?(?:member|customer|subscriber)|"
         r"subscribers? (?:are|will be) (?:automatically )?entered|loyalty (?:program|member)|leave a (?:google )?review|"
         r"proof of purchase|holders? of an? (?:eligible )?(?:account|card)")


def effort(r, a):
    if a["draw_type"] == "skill":
        return "skill"
    if a["draw_type"] == "instant":
        return "instant"
    if a["entry_platform"] in ("facebook", "instagram", "tiktok", "x", "youtube"):
        return "social"
    if re.search(r"(?i)\bmail\b|post (?:your|an) entry|in[- ]store|receipt", r.get("description") or ""):
        return "mail"
    return "manual" if a["entry_route"] in ("manual", "agent_assist") else "web"


def estimate(r, a=None, today=None):
    """(score, kind, prizes): score = estimated chance of one person winning across their allowed entries."""
    a = a or comp_odds.assess(r)
    today = today or dt.date.today()
    value = comps.prize_value(r)[0] or 500.0
    closes = entry_queue.close_date(r)
    days_left = max(1, (dt.date.fromisoformat(closes) - today).days + 1) if closes else 30
    opened = r.get("opens") and str(r["opens"])[:10]
    try:
        days_open = max(7, (dt.date.fromisoformat(closes) - dt.date.fromisoformat(opened)).days) if opened and closes \
            else 30
    except ValueError:
        days_open = 30
    kind = effort(r, a)
    entrants = BASE * math.sqrt(max(value, 50) / 1000) * EFFORT[kind] * math.sqrt(days_open / 30)
    if re.search(GATED, r.get("description") or ""):
        entrants *= 0.5            # only members, customers or reviewers can enter: a smaller field (audit 31 Oct)
    mine = min(days_left, 30) if a["entry_limit"] == "daily" else 1
    n = winners(r, a.get("prizes"))
    return min(1.0, n * mine / max(entrants, 1.0)), kind, n


def bands(scores):
    """{id: "high"|"medium"|"low"} by fifths of the given {id: score}."""
    order = sorted(scores, key=lambda i: -scores[i])
    out = {}
    for k, i in enumerate(order):
        f = k / max(1, len(order))
        out[i] = "high" if f < 0.2 else "medium" if f < 0.6 else "low"
    return out


def reason(r, a=None, today=None):
    """A short why for the chance band: the factors that move the estimate most, best first."""
    a = a or comp_odds.assess(r)
    today = today or dt.date.today()
    _, kind, n = estimate(r, a, today)
    value = comps.prize_value(r)[0]
    closes = entry_queue.close_date(r)
    days_left = (dt.date.fromisoformat(closes) - today).days + 1 if closes else None
    good, bad = [], []
    if n > 1:
        good.append(f"{n:,} prizes")
    if re.search(GATED, r.get("description") or ""):
        good.append("members/customers only")
    if kind == "skill":
        good.append("judged answer keeps entries low")
    elif kind == "mail":
        good.append("mail-in, few bother")
    elif kind == "manual":
        good.append("fiddly entry thins the field")
    elif kind == "social":
        bad.append("social giveaways draw crowds")
    if a["entry_limit"] == "daily" and days_left:
        good.append(f"enter daily ({min(days_left, 30)} goes)")
    if value and value < 300:
        good.append("small prize, fewer entrants")
    elif value and value >= 20000:
        bad.append(f"${value:,.0f} draws crowds")
    elif value and value >= 5000 and n == 1:
        bad.append("one big prize")
    if n == 1 and not bad and not good:
        bad.append("one prize")
    parts = (good + bad) if len(good) >= len(bad) else (bad + good)
    return ", ".join(parts[:2]) or "typical web entry"
