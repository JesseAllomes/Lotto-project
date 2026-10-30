# Handover (2026-10-30)

**Done**
- `SURVEY.md`: ranked survey of Australian lotteries.
- m1: winning-numbers register, 10,157 draws in `data/draws/`. Updated daily by `.github/workflows/draws.yml` (token-free; one run verified).

**Decisions**: in `.agent/drainclamp-state.md`, section DC:DECISIONS.
- Competitions: anything enterable from Victoria, not just cash.
- Data: public pages first; accounts are fine where they are worth it (the owner creates them; logins in environment secrets).
- Keno deferred.
- Alerts as GitHub issues.

**Next**: the owner chooses which goes first.
- m2: Lucky Lotteries jackpot tracker. The Lott API lists the draws as LuckyLotteries2 and LuckyLotteries5. Alert at $30M Mega and $23M Super.
- m3: competition register.

Resume: invoke the drainclamp-build-adhd skill, choose lotto-project, then `dc_project.py next`.
Run Python with `-B` so no `__pycache__` files are created.
