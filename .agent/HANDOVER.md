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
- 2026-10-30 19:05 UTC: GitHub's scheduler skipped the 15:05/18:05 runs (draws/jackpots ran ~6 h late). entries.yml
  now chains itself (commit, sleep to next 3-h window, `gh workflow run`), cron kept as backup.
- Run 41112453305 (first with fixes): 6 entered (3 comps); most failures are Shopify `/pages/` forms answering
  "error"/"try again" (Shopify bot protection). Now: a /challenge redirect = captcha, "try again/something went
  wrong/blocked" = human_check (manual list); failures log a masked `said` line for diagnosis. Next: read `said`
  lines from the next live run and fix real form errors ("is required"/"please fill" on komo, eva, getit).
- 2026-10-31: owner approved this round's 25-words answers: 8 in data/entries/answers.json (one entry per skill
  comp). Website https://jesseallomes.github.io/Lotto-project/ (workers/site.py, site.yml; Pages source = Actions):
  auto-entry register (data/entries/register.csv) at top, answers beside their buttons, manual list with Done ticks.
  entries.yml refreshes the site after each burst.
- Fable ENTRY_ROUTES.md: alternative entry routes rare (4/245). Fixed routing bugs ("phone" and "follow" too broad;
  bonus-entry sentences ignored): ~62 comps moved manual -> agent_ok.
- Second source: workers/source_auscomps.py (AusComps sitemaps + pages, ids 10,000,000 + post id, dedup vs
  competitions.com.au); probe.yml fetches candidate pages to the `probe` branch for parser work.
- 2026-10-31 later: site v2 (tabs To enter / Auto-entered / Freebies, search, category chips, filters, sort);
  Re-enter button -> pre-filled issue "reenter: <ids>" -> reenter.yml (owner's issues only) -> log_reenter.jsonl.
  Freebies: workers/freebies.py reads OzBargain /freebies (VIC + national) in site.yml. OzCoupons does not resolve
  (www.ozcoupons.com.au, ozcoupons.com: no DNS from GitHub runners).
- 2026-10-31 (c5/c6): Fable CAPTCHA_CHECK.md applied: skip only a visible interactive challenge on the chosen form
  (entrant.mjs interactiveChallenge/challengeAfterSubmit); page interstitials log `blocked`; "try again" = failed;
  earlier captcha/human_check skips reset (entry_queue.CHECK_FIX_FROM). Last-day rules (entry_queue): stated close
  time from the summary (closes_at), 5/hour bursts for no-limit comps, cautious pace for unread terms, one more try
  for failing/no_form; pace.json makes entries.yml chain hourly. "allowed one entry" wording now reads as once
  (Wild Earth 75870 had 11 entries before this). Winners tracker workers/winners.py -> data/entries/winners.csv
  (comps.yml runs --check with ENTRANT_LAST_NAME: surname yes/no on winners pages, never the name); site Winners tab.
- 2026-10-31 later: entrant fills 6 forms at once (ENTRANT_CONCURRENCY), cap 200/round. Commit step is now
  workers/commit_entries.sh (keeps the run's new log lines, resets to main, re-appends, rebuilds, pushes); run
  41135966222's log was lost to a rebase conflict and is recorded as result "unknown" (counts against stated limits
  only). comp_terms follows "T&Cs"/"TCs" links (Bunnings 75274: one entry; owner's 200-entry request declined).
  Mantine/komo forms: untyped text inputs, label data-required, listbox pickers (State -> VIC, country -> Australia)
  and "+NN" dial-code buttons switched to +61 (fixes 76141 "Field is required").
- PENDING (2026-10-31 ~07:30 UTC): (1) owner to pick product-ui prototype 1 tickets / 2 high-score board / 3 splatter
  poster (scratchpad proto/make.py; skill at /home/user/jesseallomes/product-ui, prototype loop: build only after pick);
  (2) Sonnet audit running -> data/analysis/AUDIT_SONNET.md (sample scratchpad audit_sample.json): apply fixes;
  (3) link_check.mjs full run (data/comps/link_checks.jsonl) -> commit when done. Owner: terse replies, DrainClamp
  output contract, purge reminders at chunk boundaries.
- OWNER RULES (2026-10-31): multi-step processes go to a Sonnet subagent (Agent, model sonnet) with one final report;
  no step-by-step messages; owner's new messages take priority over running work. Terse replies (DrainClamp contract).
  Pending: comps@asynym.dev via Cloudflare Email Routing once CLOUDFLARE_API_TOKEN is a GitHub secret (token kept in
  Azure; needs Zone Email Routing Rules Edit, Zone DNS Edit, Account Email Routing Addresses Edit).
- Never bypass CAPTCHAs/bot walls (owner asked; declined). c4 (skill-answer approval issues) not built yet.

**Owner asks (2026-10-30)**: caps and every odds variable where possible; skill comps as a separate list ranked by effort,
chance, skill and overall; lotto: analyse the data for optimised opportunities.

**Open to-dos**: t1 membership draws (LMCT+ etc.; not on the aggregator), t2 closed by m6.

Resume: invoke the drainclamp-build-adhd skill, choose lotto-project, then `dc_project.py next`.
Run Python with `-B`. Quote commit messages with a heredoc (`$30M` gets expanded).
