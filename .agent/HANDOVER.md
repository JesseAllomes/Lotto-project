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
- c2 next: `analysis/lotto_sales.py`. Every division bar a fixed Div 1 is pari-mutuel: prize fund F = winners x dividend / share
  (consistent across divisions); entries index from F; jackpot reconstruction for Oz Lotto / Powerball (J grows by Div1 share x F).
- c3: `analysis/popularity.py`. log(winners / expected) per draw per division, regressed on the drawn numbers -> per-number
  popularity; payout uplift of least-popular picks; backtest. This changes the payout when winning, not the chance.
- c4: fairness tests and `analysis/lotto_ev.py` (ticket value by game and jackpot); `data/analysis/LOTTO.md`.
- Then m8: competition value per entry (prize vs cap x price) and `REPORT.md`.

**Owner asks (2026-10-30)**: caps and every odds variable where possible; skill comps as a separate list ranked by effort,
chance, skill and overall; lotto: analyse the data for optimised opportunities.

**Open to-dos**: t1 membership draws (LMCT+ etc.; not on the aggregator), t2 closed by m6.

Resume: invoke the drainclamp-build-adhd skill, choose lotto-project, then `dc_project.py next`.
Run Python with `-B`. Quote commit messages with a heredoc (`$30M` gets expanded).
