# Handover (2026-10-30)

**Done**
- `SURVEY.md`: ranked survey of Australian lotteries.
- m1: winning-numbers register, 10,157 draws in `data/draws/`. Updated daily by `.github/workflows/draws.yml` (token-free; verified).
- m2: Lucky Lotteries jackpot tracker in `data/jackpots/` (1,311 Mega and 3,882 Super draws, gap-free; jackpot amounts from 2015).
  `STATUS.md` shows the live jackpots. `.github/workflows/jackpots.yml` runs daily at 12:41 UTC and opens one GitHub issue per
  jackpot cycle at the alert level ($30M Mega / $23M Super) and at break-even ($35M / $27.2M). Run 41052762530 verified.
  - Finding: Super Jackpot reached $33.0M (Oct 2022, above break-even for 45 draws); Mega $96M (Aug 2019, 255 draws above).

- m3: competition register in `data/comps/` (512 open listings from competitions.com.au; 485 open to Victoria; 22 enter on
  Facebook, 2 on Instagram). `.github/workflows/comps.yml` adds new listings daily at 21:17 UTC. Run 41054436595 verified.
  - Charity prize homes (RSL Art Union $14.7M, Mater $7.1M, Endeavour, yourtown) are filed under cash/car categories: classify by brand.
  - Facebook is covered only through the aggregator; Meta's terms forbid scraping it directly.

**Decisions**: in `.agent/drainclamp-state.md`, section DC:DECISIONS.
- Competitions: anything enterable from Victoria, not just cash.
- Data: public pages first; accounts are fine where they are worth it (the owner creates them; logins in environment secrets).
- Keno deferred.
- Alerts as GitHub issues.

**Next**: m4 analysis (`analysis/fairness.py`, `analysis/comps_value.py`, `REPORT.md`). Open to-dos t1 (membership draws such as
LMCT+, not on the aggregator) and t2 (prize-home ticket caps from permit T&Cs) in `.agent/drainclamp-project.json`.

Resume: invoke the drainclamp-build-adhd skill, choose lotto-project, then `dc_project.py next`.
Run Python with `-B` so no `__pycache__` files are created. Quote commit messages with a heredoc (`$30M` gets expanded).
