# Handover (2026-10-30)

**Done**
- `SURVEY.md`: ranked survey of Australian lotteries.
- m1: winning-numbers register, 10,157 draws in `data/draws/`. Updated daily by `.github/workflows/draws.yml` (token-free; verified).
- m2: Lucky Lotteries jackpot tracker in `data/jackpots/` (1,311 Mega and 3,882 Super draws, gap-free; jackpot amounts from 2015).
  `STATUS.md` shows the live jackpots. `.github/workflows/jackpots.yml` runs daily at 12:41 UTC and opens one GitHub issue per
  jackpot cycle at the alert level ($30M Mega / $23M Super) and at break-even ($35M / $27.2M). Run 41052762530 verified.
  - Finding: Super Jackpot reached $33.0M (Oct 2022, above break-even for 45 draws); Mega $96M (Aug 2019, 255 draws above).

**Decisions**: in `.agent/drainclamp-state.md`, section DC:DECISIONS.
- Competitions: anything enterable from Victoria, not just cash.
- Data: public pages first; accounts are fine where they are worth it (the owner creates them; logins in environment secrets).
- Keno deferred.
- Alerts as GitHub issues.

**Next**: m3, competition register (`workers/comps.py`, `data/comps/`, `.github/workflows/comps.yml`). Then m4 analysis.

Resume: invoke the drainclamp-build-adhd skill, choose lotto-project, then `dc_project.py next`.
Run Python with `-B` so no `__pycache__` files are created. Quote commit messages with a heredoc (`$30M` gets expanded).
