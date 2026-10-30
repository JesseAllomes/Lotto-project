<!-- drainclamp-build: state; schema=1; generation=8 -->
# DrainClamp state

<!-- DC:ARCH -->
- SURVEY.md → ranked survey of Australian lotteries for legal positive-EV situations (sources cited) → read
- work/scripts/ev_models.py → EV models per game; writes work/ev_results.md → `python3 -I work/scripts/ev_models.py`
- work/data/ → source documents and The Lott API snapshots (opendraws.json, latest10_*.json, lucky_*.json)
- planned workers/ → token-free scrapers run by .github/workflows/ (stdlib Python, append-only CSV/JSONL in data/)
- planned analysis/ → fairness tests on the draws register; value per entry for competitions
- optimisation: one shared HTTP client for The Lott API (workers/lott.py); append-only, de-duplicated by draw or competition id
<!-- /DC:ARCH -->

<!-- DC:DECISIONS -->
- Keno in the winning-numbers register? -> deferred; v1 covers The Lott draw games (Saturday, Monday and Wednesday Lotto, Oz Lotto, Powerball, Set for Life) (source: default, owner may change)
- Which competitions? -> any competition the owner can legally enter from Victoria, monetary or not (prize homes, art unions, LMCT+-style membership draws, trade promotions, free-entry and skill comps) (source: user)
- How is competition data collected? -> public pages first; accounts are fine where they are worth it (owner creates them; logins live in environment secrets, never in the repository); no entries on the owner's behalf; the owner enters (source: user, 2026-10-30)
- How are alerts sent? -> GitHub issues in this repository, which email the owner (source: default)
- How is data collected and collated? -> token-free scripts and GitHub Actions only; Fable only on request, with scripts doing collection (source: user, CLAUDE.md)
- Legality -> only legal play within published game rules; no fraud, tampering or terms-of-service breaches (source: user)
- Registers -> append-only, every record carries its source URL and fetch time (source: repo convention from melbcup live collector)
- Push -> git push origin main (source: user)
<!-- /DC:DECISIONS -->

<!-- DC:ROADMAP -->
| id | goal | files | status | deps |
| m1 | Winning-numbers register: full draw history for The Lott draw games, backfilled, updated by a scheduled worker | workers/lott.py; workers/draws.py; data/draws/; .github/workflows/draws.yml; tests/test_draws.py | done | |
| m2 | Lucky Lotteries Mega and Super jackpot tracker with history and alerts at $30M and $23M | workers/jackpots.py; data/jackpots/; .github/workflows/jackpots.yml; tests/test_jackpots.py | pending | m1 |
| m3 | Competition register: competitions enterable from Victoria (prize homes, art unions, membership draws, trade promotions), scraped from public pages | workers/comps.py; data/comps/; .github/workflows/comps.yml; tests/test_comps.py | pending | |
| m4 | Analysis: draw fairness tests on the register; odds and value per entry for competitions; plain report | analysis/fairness.py; analysis/comps_value.py; REPORT.md | pending | m1;m3 |
<!-- /DC:ROADMAP -->

<!-- DC:VERIFY -->
```json
[{"id": "unit", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "cwd": ".", "tier": "fast", "timeout_s": 300}]
```
<!-- /DC:VERIFY -->

<!-- DC:LOG -->
- 2026-10-30T11:46:36+00:00 cca33c7c m1 done: winning-numbers register of 10,157 Lott draws (1996/97 to now), daily token-free workflow verified on GitHub
<!-- /DC:LOG -->
