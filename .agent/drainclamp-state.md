<!-- drainclamp-build: state; schema=1; generation=51 -->
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
- How is competition data collected? -> public pages first; accounts are fine where they are worth it (owner creates them; logins live in environment secrets, never in the repository); the agent enters free web-form competitions for the owner (see auto-entry decision); everything else the owner enters (source: user, 2026-10-30)
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
- Auto-entry? -> the agent enters free competitions that take a web form, with the owner's real details from GitHub secrets (never in the repo or chat); never paid entries; respects each comp's entry limit; skips any whose terms ban automated or third-party entry, and any with a CAPTCHA, login or human check (those go to the owner's manual list); leaves optional marketing boxes unticked; dry run first, live only once the owner switches it on (source: user, 2026-10-30)
- Skill-comp answers? -> drafted per competition and posted as a GitHub issue; submitted only after the owner approves or edits it (source: user, 2026-10-30)
- Approval? -> free chance comps are entered automatically, re-entered as often as each allows (daily, weekly, one-off); only skill comps wait for the owner's tick on a daily GitHub-issue checklist with the drafted answer (source: user, 2026-10-30)
- Pattern numbers? -> build pattern-based number sets and test them blind: methods fixed and pre-registered before scoring, scored only on held-out draws, against the exact random expectation; both 24 games per draw and one System 24 (source: user, 2026-10-30)
- Unstated or unlimited entry limits? -> no limit (owner: an allowed loophole); bursts of 5 per 3-hour window, 5 minutes apart; where the terms let the promoter act on excessive or bulk entries, 4 a day, 5 hours apart; daily = once a day, weekly = once a week, capped N = N total; a limit in the full terms wins over the summary. GitHub free minutes allow 4 runs a day; full bursts need another host (owner choosing: free cloud VM, public repo, lighter replays, or manual tap list) (source: user, 2026-10-30)
- Hosting for bursts? -> make Lotto-project public (unlimited Actions minutes); no screenshots, nothing personal logged; a free cloud VM later (source: user, 2026-10-30)
- Go live? -> yes, live by default (ENTRANT_LIVE=0 for dry run); 'enter everything': comps whose terms ban automated entry are entered too at the cautious pace (4 a day), ENTER_BANNED=0 to stop; CAPTCHAs and human checks are never bypassed (source: user, 2026-10-30)
- Skill answers, this round? -> owner approved all 25-words-style answers (2026-10-31); 8 written to data/entries/answers.json, within word limits, no invented personal facts; one entry per skill comp; future rounds still need approval (source: user)
- Manual entries? -> a website (GitHub Pages, workers/site.py, site.yml) listing every open comp to enter by hand, tick-off saved on the owner's phone (source: user, 2026-10-31)
- Azure migration? -> already moved by Codex to the owner's personal Azure; this work verifies it and turns it on (source: user, 2026-10-31)
- Azure auth? -> Azure CLI device-code login by the owner, CLI config in session scratch only; no credentials, tokens or secret values in the repo, chat or logs; secret and setting names only (source: user + repo decision)
- Cutover? -> per service: verify, dry run, owner approves, then turn the Azure schedule on and disable the matching GitHub Actions workflow in the same step so nothing runs twice (source: repo decision)
- Auto-entry on Azure? -> first Azure run is a dry run (ENTRANT_LIVE=0); live only after the owner approves and entries.yml is off (double entry would break stated entry limits) (source: repo decision)
- Times shown to the owner? -> Melbourne time (AEDT/AEST) only, never UTC (source: user, 2026-10-31)
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
| m9 | Auto-entry of free web-form competitions: candidates (free, agent_ok, not banned, within entry limit), Playwright form filler with owner details from secrets, dry run then live, entry log without personal data, manual list for the rest, skill answers approved via GitHub issues | workers/entrant.py;workers/entry_queue.py;data/entries/;.github/workflows/entries.yml;tests/test_entrant.py | pending | m5;m6 |
| az1 | Azure inventory and verification for Lotto: every resource Codex created mapped to the workflow it replaces (draws, jackpots, comps, entries, site, reenter, probe), checked against main for code version, schedule, settings and secret names; no changes | .agent/azure-inventory.md | done |  |
| az2 | Azure dry runs for Lotto: each job run once on Azure without live entry; outputs and git pushes compared with the GitHub Actions run | .agent/azure-inventory.md | pending | az1 |
| az3 | Lotto cutover: owner-approved Azure schedules on, matching GitHub Actions workflows off, first live runs checked | .github/workflows/;.agent/azure-inventory.md | pending | az2 |
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
- 2026-10-30T13:30:21+00:00 8f1745b9 m9 c1-c3: entry queue, Playwright entrant (dry by default), entries.yml; waiting on owner's secrets
- 2026-10-30T13:38:28+00:00 a85a45b2 m7 blind tests: re-picked each draw 0/90, fixed sets 0/40 beat chance (BLIND.md, BLIND_FIXED.md); no pattern edge
- 2026-10-30T13:50:15+00:00 c0f3592f every-line search: registered z invalid (overlapping lines); draw-level correction: no game beats chance (SfL p=0.059)
- 2026-10-30T13:57:04+00:00 9d6b30d9 Fable opportunity hunt: OPPORTUNITIES.md; top: Endeavour $200 book + one-time doubling (~170% of face after haircut, unverified offer); Superdraw RTP drifting up (watch); RSL/Mater/yourtown ruled out; proposed workers/sellthrough.py
- 2026-10-30T16:17:34+00:00 f420b599 m9 live: first live run 9 entered / 70 unconfirmed; entrant fixes (form choice, JS buttons, overlays, confirmation, retry rules)
- 2026-10-30T21:04:09+00:00 d6173abf site + register + answers; Fable entry routes; routing fixes (~62 comps to auto); AusComps second source
- 2026-10-31T05:03:13+00:00 0773ad9c az: Azure migration project opened; az1-az3 added (verify, dry run, cutover)
- 2026-10-31T05:07:28+00:00 696bef2a az1: inventory in .agent/azure-inventory.md; source not in any repo, sites empty, no job logs; blocked on owner (source access)
- 2026-10-31T05:23:13+00:00 2c1fc71b owner: source likely only in Codex cloud; grant any permissions needed; owner away (nap) - proceed autonomously within decisions
- 2026-10-31T05:36:57+00:00 ce8cd398 az1 done: runner review + fixes in azure/ (30 tests), image build workflow; az2 blocked on Azure write approval
- 2026-10-31T07:19:13+00:00 3417cebd owner: launch all, cost audit first, auto-deploy main->Azure behind cost guard. Applied: budget AUD20 alerts 25/50/100%+forecast (both emails), func 512MB x1, storage lifecycle+1d soft delete, Foundry keys off, Log Analytics 0.1GB/day on jobs env, OIDC deploy app 7ab2c182 (Contributor on RG, main only)
- 2026-10-31T07:47:00+00:00 23b6e8c7 az2 done: guarded deploy live (OIDC), dry runs ok (draws, jackpots, entries 11 queued/dry_ok); az3 partial: draws, jackpots, entries cut over to Azure 07:45Z, GitHub twins manual-only; comps pending dry run; reenter+site stay on GitHub
- 2026-10-31T09:37:02+00:00 676ea787 az3: first live Azure entries burst 8:05-8:26 pm Melbourne: 5 runs ok, 9 entered / 7 failed / 3 skipped, every run's log committed, site rebuilt on both hosts after each push; ~3 forms per run within the 150 s budget
<!-- /DC:LOG -->
