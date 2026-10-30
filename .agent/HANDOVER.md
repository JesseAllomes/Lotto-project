# Handover (2026-10-30)

**Done**
- `SURVEY.md`: ranked survey of Australian lotteries.
- m1: winning-numbers register, 10,157 draws in `data/draws/` (daily `draws.yml`).
- m2: Lucky Lotteries jackpot tracker, `data/jackpots/STATUS.md`; GitHub issue at $30M Mega / $23M Super and at break-even (daily `jackpots.yml`).
- m3: competition register `data/comps/comps.jsonl` + `comps.csv` (competitions.com.au; 512 listings, 485 open to Vic).
- m5: `data/comps/odds.csv` (draw type, purchase, entry limit, bonus entries, prizes, entry types, cap) and `skill.csv`.
- m6: `data/comps/terms.jsonl`: ticket caps from promoters' terms (9 caps: RSL 10.76M, Mater 30.1M, Endeavour 1.5M/1.35M, yourtown 500k ...).
- m4: `data/comps/skill_ranked.csv`: effort, chance, skill (1-5) and overall (0-10) for each open skill comp.
- `comps.yml` (daily 21:17 UTC) runs comps -> comp_terms -> comp_odds --tags -> skill_rank. Run 41059812922 verified.

**In progress: m7 lotto opportunities** (chunks in `.agent/drainclamp-project.json`)
- c1 done: `analysis/lotto_games.py` (division rules, fund shares, exact odds, current-format start draws).
- c3 done: `analysis/lotto_numbers.py` -> `data/analysis/NUMBERS.md`: least-picked set per game (high numbers 37-47;
  estimated +24% to +51% per division win; holdout r 0.18-0.66) and most-drawn set (chi-square p 0.08-0.94: random).
  Prize fund per draw = median(winners x dividend / share) is in `prize_fund()`.
- c2 next: `analysis/lotto_sales.py` (entries index per draw, jackpot reconstruction for Oz Lotto / Powerball).
- c4: `analysis/lotto_ev.py` ticket value by game and jackpot, ranked opportunities; `data/analysis/LOTTO.md`.
- Ideas not done: model Powerball's PB-number popularity; pattern effects (runs, multiples of 5) on sharing.
- Then m8: competition value per entry (prize vs cap x price) and `REPORT.md`.

**Competitions extra (2026-10-30)**: odds.csv / skill lists carry entry_route (agent_ok 149, agent_assist 33,
manual 288, unknown 42) and automation_banned (from full terms when fetched). Decision stands: the owner enters.

**m9 auto-entry (LIVE since 2026-10-30 14:39 UTC)**: decisions in DC:DECISIONS. Repo is PUBLIC (unlimited minutes).
- `entries.yml` every 3 h (UTC :05): up to 5 rounds ~5 min apart; live unless var ENTRANT_LIVE=0; ENTER_BANNED=0 stops
  entering comps whose terms ban automation. Owner's 9 ENTRANT_* secrets are set. No screenshots (public repo).
- Pacing (entry_queue.may_enter): no stated limit/unlimited -> bursts of 5 per UTC 3-hour window, 5 min apart; terms
  flag excessive/bulk or ban automation -> 4 a day, 5 h apart; daily/weekly/capped/once as stated (full terms win).
- First live run 41073527299: 9 entered (4 comps), 70 "no confirmation", 27 no_submit, 23 click timeouts, 17 captcha.
  Fixed 2026-10-30 ~16:30 UTC: competition form preferred over discount pop-ups/footer sign-ups, JS buttons and
  "Sign up"/"Subscribe" labels, overlays dismissed + JS-click fallback, success = new thank-you text, URL change or
  form cleared; "already entered" = one entry; two failures in a row -> manual list; pre-fix failures reset
  (RETRY_FROM). Dry re-check on the 30 failing pages: 23 pick the right button. Next: check the 18:05 UTC run.
- Never bypass CAPTCHAs/bot walls (owner asked; declined). c4 (skill-answer approval issues) not built yet.

**Owner asks (2026-10-30)**: caps and every odds variable where possible; skill comps as a separate list ranked by effort,
chance, skill and overall; lotto: analyse the data for optimised opportunities.

**Open to-dos**: t1 membership draws (LMCT+ etc.; not on the aggregator), t2 closed by m6.

Resume: invoke the drainclamp-build-adhd skill, choose lotto-project, then `dc_project.py next`.
Run Python with `-B`. Quote commit messages with a heredoc (`$30M` gets expanded).
