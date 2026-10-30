"""The owner's competition page: what to enter by hand, best first, with a tick-off list.

    python3 -m workers.site                 # writes site/index.html (published by .github/workflows/site.yml)
    python3 -m workers.site --out DIR       # somewhere else

One static page, built from the registers after each run. It lists every open competition a Victorian can enter
that the auto-entrant cannot: bot-checked web forms (CAPTCHA, Shopify), social-media entries, forms it failed on,
and the rest of the manual list, highest prize first within the soonest-closing. Each card opens the entry page in
a new tab; "Done" ticks are kept in the phone's own browser storage. The repository is public, so the page holds
no personal details; the approved skill answers are shown so they can be copied.
"""
import argparse
import csv
import datetime as dt
import html
import json
import sys
from pathlib import Path

from workers import comps

ROOT = comps.ROOT
ENTRIES = ROOT / "data" / "entries"
OUT = ROOT / "site"
GROUPS = [
    ("web", "Web forms with a human check", "Quick: open, let autofill do it, tick the box, submit."),
    ("social", "Facebook, Instagram and other social", "Like, comment or follow as the post asks."),
    ("other", "Everything else", "Receipts, in-store, apps or unclear entry: read the page."),
]


def group_of(reason, platform, url):
    if platform in ("facebook", "instagram", "tiktok", "x", "youtube"):
        return "social"
    if any(k in reason for k in ("captcha", "human_check", "failing", "no_form", "unfillable", "login",
                                 "terms ban")) or "/pages/" in (url or ""):
        return "web"
    return "other"


def why(reason):
    r = reason.replace("entrant blocked: ", "")
    return {"captcha": "human check (CAPTCHA)", "human_check": "the site's bot check", "no_form": "form not reachable",
            "unfillable": "a field only you can answer", "login": "needs a login",
            "entry route manual": "manual entry", "entry route unknown": "entry method unclear",
            "terms ban automated entry": "terms ban automated entry"}.get(r, r if not r.startswith("failing") else
                                                                          "the auto-entrant failed here")


def load_answers(entries=ENTRIES):
    path = entries / "answers.json"
    return json.loads(path.read_text()) if path.exists() else {}


def items(entries=ENTRIES, today=None):
    today = (today or dt.date.today()).isoformat()
    ans = load_answers(entries)
    path = entries / "manual.csv"
    rows = list(csv.DictReader(open(path))) if path.exists() else []
    out = []
    for r in rows:
        closes = (r.get("closes") or "")[:10]
        if closes and closes < today or not r.get("entry_url"):
            continue
        out.append({"id": r["id"], "title": r["title"], "brand": r.get("brand") or "",
                    "prize": float(r["prize_pool"]) if r.get("prize_pool") else 0.0, "closes": closes,
                    "url": r["entry_url"], "why": why(r.get("reason") or ""),
                    "group": group_of(r.get("reason") or "", r.get("entry_platform") or "", r["entry_url"]),
                    "answer": ans.get(str(r["id"]))})
    out.sort(key=lambda x: (x["closes"] or "9999", -x["prize"]))
    return out


def stats(entries=ENTRIES):
    path = entries / "log.jsonl"
    log = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    live = [x for x in log if x.get("mode") == "live" and x.get("result") == "entered"]
    return {"entries": len(live), "comps": len({x["id"] for x in live})}


def register(entries=ENTRIES):
    path = entries / "register.csv"
    return list(csv.DictReader(open(path))) if path.exists() else []


def melb(utc_text):
    """'2026-10-30 19:31' (UTC) as Melbourne time, e.g. 'Sat 31 Oct, 6:31am'."""
    from zoneinfo import ZoneInfo
    t = dt.datetime.strptime(utc_text, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).astimezone(
        ZoneInfo("Australia/Melbourne"))
    return t.strftime("%a %d %b, %I:%M%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")


def answer_block(text):
    e = html.escape
    return (f'<div class="ans"><p class="answer">{e(text)}</p>'
            f'<button class="copy" data-copy="{e(text)}">Copy answer</button></div>')


def card(x):
    e = html.escape
    prize = f"${x['prize']:,.0f}" if x["prize"] else "prize n/a"
    return (f'<li class="card" data-id="{e(x["id"])}"><div class="top"><span class="prize">{prize}</span>'
            f'<span class="closes">closes {e(x["closes"] or "?")}</span></div>'
            f'<a class="title" href="{e(x["url"])}" target="_blank" rel="noopener">{e(x["title"])}</a>'
            f'<div class="meta">{e(x["brand"])} · {e(x["why"])}</div>'
            + (answer_block(x["answer"]) if x.get("answer") else "") +
            f'<div class="row"><a class="go" href="{e(x["url"])}" target="_blank" rel="noopener">Open entry page</a>'
            f'<label class="done"><input type="checkbox"> Done</label></div></li>')


def page(entries=ENTRIES, today=None, built=None):
    it, st, reg = items(entries, today), stats(entries), register(entries)
    manual_ids = {x["id"] for x in it}
    ans = load_answers(entries)
    recs = {str(r["id"]): r for r in (json.loads(l)["comp"] for l in comps.stored(comps.STORE).values())}
    entered_ids = {r["id"] for r in reg}
    queued = [(k, v) for k, v in ans.items() if k not in manual_ids and k not in entered_ids and k in recs
              and (recs[k].get("closes") or "9")[:10] >= (today or dt.date.today()).isoformat()]
    built = built or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = []
    for key, name, hint in GROUPS:
        g = [x for x in it if x["group"] == key]
        if g:
            sections.append(f'<section><h2>{name} <span class="count">{len(g)}</span></h2><p class="hint">{hint}</p>'
                            f'<ul>{"".join(card(x) for x in g)}</ul></section>')
    e = html.escape
    queued_html = "".join(
        f'<li class="card"><a class="title" href="{e(recs[k]["entry_url"])}" target="_blank" rel="noopener">'
        f'{e(recs[k]["title"])}</a><div class="meta">{e(recs[k].get("brand") or "")} · waiting for the auto-entrant</div>'
        f'{answer_block(v)}<div class="row"><a class="go" href="{e(recs[k]["entry_url"])}" target="_blank" '
        f'rel="noopener">Open entry page</a></div></li>' for k, v in queued)
    reg_rows = "".join(
        f'<tr><td><a href="{e(r["entry_url"])}" target="_blank" rel="noopener">{e(r["title"])}</a>'
        f'<div class="meta">{e(r["brand"])}' + (f' · ${float(r["prize_pool"]):,.0f}' if r.get("prize_pool") else "")
        + f' · closes {e(r["closes"] or "?")}</div></td><td class="num">{e(r["entries"])}</td>'
        f'<td class="when">{e(melb(r["last_entered_utc"]))}' + (f'<div class="meta">answer: {e(ans[r["id"]])}</div>'
                                                            if r["id"] in ans else "") + '</td></tr>'
        for r in reg)
    total = sum(x["prize"] for x in it)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comps to enter</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--accent:#0b6e4f;--done:#9a9a9f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121214;--card:#1c1c1f;--ink:#f2f2f4;--muted:#a1a1a8;--line:#2c2c31;--accent:#3ccf95;--done:#5f5f66}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif}}
header,main{{max-width:760px;margin:0 auto;padding:16px}}h1{{font-size:1.5rem;margin:.2rem 0}}h2{{font-size:1.1rem;margin:1.6rem 0 .2rem}}
.sub,.hint,.meta,.closes{{color:var(--muted);font-size:.9rem}}.count{{color:var(--muted);font-weight:400}}
ul{{list-style:none;padding:0;margin:.5rem 0}}.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:8px 0}}
.top{{display:flex;justify-content:space-between;gap:8px}}.prize{{font-weight:700;color:var(--accent)}}
.title{{display:block;font-weight:600;color:var(--ink);text-decoration:none;margin:4px 0}}
.row{{display:flex;justify-content:space-between;align-items:center;margin-top:8px;gap:8px}}
.go{{background:var(--accent);color:#fff;text-decoration:none;padding:8px 12px;border-radius:8px;font-weight:600}}
.done{{display:flex;gap:6px;align-items:center;font-size:.95rem}}.done input{{width:22px;height:22px}}
.card.is-done{{opacity:.45}}.card.is-done .title{{text-decoration:line-through;color:var(--done)}}
.ans{{background:var(--bg);border-radius:8px;padding:8px 10px;margin:8px 0}}.answer{{margin:0 0 6px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:.95rem}}
td a{{color:var(--ink);font-weight:600;text-decoration:none}}.num{{font-weight:700;color:var(--accent);text-align:center}}
.when{{font-size:.85rem;color:var(--muted)}}
.bar{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:8px}}.answer{{margin:.3rem 0 0}}
button{{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink)}}
</style></head><body>
<header><h1>Comps to enter</h1>
<p class="sub">{len(it)} open competitions to enter by hand (about ${total:,.0f} in prizes). The auto-entrant has made
{st["entries"]} entries in {st["comps"]} competitions. Updated {built}.</p>
<div class="bar"><label class="done"><input type="checkbox" id="hide"> Hide done</label>
<span class="sub" id="left"></span></div></header>
<main><section><h2>Auto-entry register <span class="count">{len(reg)}</span></h2>
<p class="hint">Every competition the auto-entrant has entered, how many times, and the latest entry. Updates after each burst.</p>
<table><thead><tr><th>Competition</th><th>Entries</th><th>Last entered</th></tr></thead><tbody>{reg_rows}</tbody></table></section>
<section><h2>Skill answers waiting to go in <span class="count">{len(queued)}</span></h2>
<p class="hint">Approved answers the auto-entrant will submit; enter by hand with Copy answer if you like.</p><ul>{queued_html}</ul></section>
{"".join(sections)}
</main>
<script>
const KEY = "comps-done";
const load = () => {{ try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch {{ return {{}}; }} }};
const save = (d) => {{ try {{ localStorage.setItem(KEY, JSON.stringify(d)); }} catch {{}} }};
const hide = document.getElementById("hide");
function paint() {{
  const d = load(); let left = 0;
  document.querySelectorAll("li[data-id]").forEach((li) => {{
    const on = !!d[li.dataset.id]; li.querySelector("input").checked = on; li.classList.toggle("is-done", on);
    li.style.display = on && hide.checked ? "none" : ""; if (!on) left++;
  }});
  document.getElementById("left").textContent = left + " left to do";
}}
document.addEventListener("click", async (e) => {{
  const b = e.target.closest("button.copy"); if (!b) return;
  try {{ await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; }}
  catch {{ b.textContent = "Select and copy the text"; }}
  setTimeout(() => (b.textContent = "Copy answer"), 2000);
}});
document.addEventListener("change", (e) => {{
  const li = e.target.closest("li[data-id]");
  if (li) {{ const d = load(); if (e.target.checked) d[li.dataset.id] = Date.now(); else delete d[li.dataset.id]; save(d); }}
  paint();
}});
paint();
</script></body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page())
    print(f"site: wrote {out / 'index.html'}")


if __name__ == "__main__":
    sys.exit(main())
