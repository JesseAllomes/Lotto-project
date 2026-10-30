<!-- drainclamp-build: state; schema=1; generation=24 -->
# DrainClamp state

<!-- DC:ARCH -->
- SURVEY.md → ranked survey of Australian lotteries for legal positive-EV situations (sources cited) → read
- work/scripts/ev_models.py → EV models per game; writes work/ev_results.md → `python3 -I work/scripts/ev_models.py`
- work/data/ → source documents and The Lott API snapshots (opendraws.json, latest10_*.json, lucky_*.json)
- workers/lott.py → shared The Lott API client (89-day windows, retries); workers/draws.py → data/draws/ (daily, draws.yml)
- workers/jackpots.py → data/jackpots/ (LuckyLotteries2 = Super, LuckyLotteries5 = Mega; jackpot = division 11, from 2015; STATUS.md; open.jsonl) → daily jackpots.yml, GitHub issue per cycle and level
- workers/comps.py → data/comps/comps.jsonl + comps.csv from competitions.com.au (sitemap → new listing pages; Event JSON-LD + facts block; open_to_vic; entry_platform) → daily comps.yml. Category slug is unreliable for charity lotteries (RSL, Mater, yourtown filed under cash/car): classify by brand in m4. Facebook/Instagram only via the aggregator (Meta terms forbid scraping)
- planned analysis/ → fairness tests on the draws register and competition value per entry (m4)
- optimisation: one shared HTTP client for The Lott; append-only registers de-duplicated by draw or listing id; run Python with -B; commit messages via quoted heredoc
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
- Odds variables? -> record every variable that moves the chance of winning: ticket or entry cap, entries sold where published, entry limit per person, purchase needed, number of prizes, draw type (chance, skill, instant win) (source: user, 2026-10-30)
- Skill competitions? -> a separate list (data/comps/skill.csv), judged on merit, kept apart from games of chance (source: user, 2026-10-30)
- Facebook? -> only via aggregator listings; no direct scraping (Meta terms) (source: default, owner told)
- Skill-competition ranking? -> three scores, effort required, chance of winning, skill level required, then an overall score (source: user, 2026-10-30)
- Lotto analysis? -> analyse the draw data for optimised opportunities (value per ticket by draw, less-shared numbers, timing), separate from the competition work (source: user, 2026-10-30)
<!-- /DC:DECISIONS -->

<!-- DC:ROADMAP -->
| id | goal | files | status | deps |
|---|---|---|---|---|
| m1 | Winning-numbers register: full draw history for The Lott draw games, backfilled, updated by a scheduled worker | workers/lott.py;workers/draws.py;data/draws/;.github/workflows/draws.yml;tests/test_draws.py | done |  |
| m2 | Lucky Lotteries Mega and Super jackpot tracker with history and alerts at $30M and $23M | workers/jackpots.py;data/jackpots/;.github/workflows/jackpots.yml;tests/test_jackpots.py | done | m1 |
| m3 | Competition register: competitions enterable from Victoria (prize homes, art unions, membership draws, trade promotions), scraped from public pages | workers/comps.py;data/comps/;.github/workflows/comps.yml;tests/test_comps.py | done |  |
| m5 | Odds variables per competition (chance or skill, purchase needed, entry limit, number of prizes, entry types) and a separate skill-competition list | workers/comp_odds.py;data/comps/odds.csv;data/comps/skill.csv;tests/test_comp_odds.py | done | m3 |
| m6 | Ticket and entry caps from promoters' own terms (charity lotteries and art unions first): cap, ticket price, prize value, permit, evidence | workers/comp_terms.py;data/comps/terms.jsonl;.github/workflows/comps.yml;tests/test_comp_terms.py | done | m3 |
| m4 | Skill-competition ranking: effort required, chance of winning, skill level required, overall score, for every open skill comp; rebuilt daily | analysis/skill_rank.py;data/comps/skill_ranked.csv;tests/test_skill_rank.py;.github/workflows/comps.yml | done | m5 |
| m7 | Lotto opportunities from the draw register: sales and prize pools inferred from dividends, ticket value per draw by game and jackpot, number-popularity model (division-1 sharing) to pick less-shared numbers, randomness checks, ranked opportunities | analysis/lotto_ev.py;analysis/popularity.py;analysis/fairness.py;data/analysis/;tests/test_lotto_analysis.py | pending | m1;m2 |
| m8 | Competition value per entry (prize value against cap and ticket price) and the plain-English REPORT.md over lotto and competitions | analysis/comps_value.py;REPORT.md | pending | m4;m6;m7 |
<!-- /DC:ROADMAP -->

<!-- DC:VERIFY -->
```json
[{"id": "unit", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "cwd": ".", "tier": "fast", "timeout_s": 300}]
```
<!-- /DC:VERIFY -->

<!-- DC:LOG -->
- 2026-10-30T11:46:36+00:00 cca33c7c m1 done: winning-numbers register of 10,157 Lott draws (1996/97 to now), daily token-free workflow verified on GitHub
- 2026-10-30T12:11:01+00:00 09e79993 m2 done: Lucky Lotteries jackpot tracker; 1,311 Mega + 3,882 Super draws (jackpots from 2015), daily jackpots.yml verified on GitHub (run 41052762530)
- 2026-10-30T12:33:21+00:00 bd84fbac m3 done: competition register, 512 open listings (485 open to Vic; 22 Facebook, 2 Instagram); daily comps.yml verified (run 41054436595)
- 2026-10-30T13:01:35+00:00 97eaab02 m5 done: odds.csv (draw type, purchase, entry limit, bonus entries, prizes, entry types) and skill.csv (84 open skill comps for Vic); tags.jsonl; comps.yml run 41058728219 ok
- 2026-10-30T13:18:15+00:00 bc2ad015 m6 done: comp_terms caps for 9/169 paid listings (every charity lottery and prize home; rest are trade promotions); m4 done: skill_ranked.csv (84 ranked); run 41059812922 ok
- 2026-10-30T13:21:45+00:00 ac6b56e6 entry_route + automation_banned on competitions; m7 c3: NUMBERS.md least-picked and most-drawn sets
<!-- /DC:LOG -->
