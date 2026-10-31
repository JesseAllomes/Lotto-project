# Review: Azure runner.py vs GitHub workflows (read-only, 2026-10-31)

runner.py = scratchpad/codex-artifacts/image/fs/app/runner.py (373 lines). Job JSONs checked. No secrets quoted.
Facts from job JSONs: every cron is the placeholder `0 0 29 2 *` (never fires); reenter is Manual trigger;
AZURE_JOBS_DISABLED=1 on all five; replicaRetryLimit 0; 0.5 vCPU / 1 GiB; entrypoint `python3 /app/runner.py`.
Image has no repo code: it clones `main` at run time. Playwright version and `pdftotext`/git in the image: not verifiable here.

## Parity table
| mode | workflow | runner.py | match? | gap |
|---|---|---|---|---|
| draws | draws.yml: `workers.draws`, add data/draws, commit, `git push` | 225-232 same, plus pull --rebase -X theirs retry | yes | identity differs (see D12); data otherwise identical |
| jackpots | jackpots.yml: worker `--alerts`, issue per new key (`gh`, limit 200), commit data/jackpots, pull --rebase, push | 245-258 same order; issues via REST | mostly | issues read per_page=100 no paging (D7); author is the PAT owner not the bot (D8); `-X theirs` added |
| comps | comps.yml: comps, auscomps (25m, continue), comp_terms (30m, continue), comp_odds --tags, skill_rank, winners --check (`|| true`), commit, 4x pull/push | 202-222 same commands | NO | comp_terms has no timeout and no check=False (D3); poppler-utils install omitted (D9); total 5400 s cap vs 110 min |
| entries | entries.yml: queue, up to 5 rounds 5 min apart (entry_queue then entrant each), final queue, commit_entries.sh (`always()`), `gh workflow run site.yml`, sleep to next window, `gh workflow run entries.yml` | 273-292: ONE round per execution; cron expected every 5 min; `entry_due` gate (90-96); commit in `finally` | partial | 180 s timeout, no inner timeout (D1); no site refresh (D6); chaining replaced by cron (fine, cron not yet set); no force/dry path (D5) |
| reenter | reenter.yml: owner-only issue trigger, queue, entrant, entry_queue, commit, comment+close `always()`, site refresh | 295-338 | NO | nothing starts it (D4); comment/close skipped on any failure (D4); no owner check; result `reason` dropped |
| site | site.yml: freebies, winners, `workers.site`, deploy to Pages | none: `site` is accepted by main() (343) and clones, then silently does nothing (362-368) | NO | Azure Static Web App stays empty; keep site.yml (D6) |

## Defects
**D1 [blocker] entries: 180 s kill loses the log after real submissions.** replicaTimeout 180 (job-lotto-entries.json); runner.py:278 has no timeout; log is written in the temp clone (entrant.mjs:529, appendFileSync) and only committed by the `finally` at 284-292.
Scenario: clone + queue + Chromium + N forms (6 concurrent, up to 45 s goto each; last-day queue can be tens of comps) + commit/push retries exceed 180 s, or 1 GiB OOMs with 6 browser contexts. SIGKILL/SIGTERM skips `finally`; Python's default SIGTERM also skips it. Forms were already submitted but nothing is recorded, so the next burst 5 min later re-enters them, breaching once/daily/weekly limits (can void entries). entry_queue.py:55 already documents this exact incident ("a run whose log was lost").
Also: no way to see it happen, there is no Log Analytics (D11).

**D2 [blocker] cutover collision: GH and Azure both live = double entries.** No shared lock (GH `concurrency` is GH-only). ENTRANT_LIVE=1 and ENTRIES_DISABLED=0 are already set, so flipping AZURE_JOBS_DISABLED to 0 plus a real cron, with entries.yml still enabled or its in-flight sleeping run still alive (entries.yml:73-83 re-dispatches itself after up to 3 h), submits every form twice. Same for comps/jackpots (duplicate issues, racing pushes; `-X theirs` silently keeps one side's CSVs).

**D3 [blocker] comps: a failure or the 5400 s cap discards all work.** runner.py:211 `comp_terms` is check=True with no timeout (GH: 30 min, continue-on-error, "each listing is saved as it is read"). Any exception, or replicaTimeout 5400 s (GH allowed 110 min), kills the container before `push` (217): hours of scraped register lost, every day. Fix: `check=False, timeout=30*60` on line 211, and push in a `finally`.

**D4 [blocker for reenter cutover] reenter cannot work as built.** (a) No trigger: manual job; ISSUE_TITLE/ISSUE_NUMBER are not in the job env (runner.py:296-299), and nothing converts a GitHub issue event into a job start. (b) runner.py:317-324 raises on any entrant/commit failure, so lines 335-338 never run: issue stays open, no comment (GH uses `if: always()`). (c) No owner-only check (reenter.yml:18). Keep reenter.yml on GitHub.

**D5 [should-fix] no dry run without editing the job; dry run is not harmless.** Kill switches: AZURE_JOBS_DISABLED=1 returns 0 before clone for every mode (350-352); ENTRIES_DISABLED=1 only for entries (355); ENTRANT_LIVE only toggles submit inside entrant.mjs (dry rows are `mode:dry`, ignored by limits, entry_queue.py:171-174); ENTER_BANNED=1 queues comps whose terms ban automation, same as the GH default (entry_queue.py:51). Dry run needs `az containerapp job start --env-vars AZURE_JOBS_DISABLED=0 ENTRANT_LIVE=0` (override, no job edit). But: entries exits "not due" outside burst slots (:05-:29 of hours %3==0 UTC, or every hour in rush) and there is no force flag; draws/comps/jackpots have no dry mode and push real commits and create real issues; a dry entries run still commits dry rows and queue to main. Also failures from a broken Azure environment (D10) are logged as real `failed` rows in the shared log and feed the blocking logic that the GH side reads.

**D6 [should-fix] site refresh and deploy omitted.** entries.yml:68-72 and reenter.yml:63 run `gh workflow run site.yml`; runner has no equivalent. site.yml's `workflow_run` trigger needs GH comps/entries runs. Coverage after cutover is only site.yml's push trigger (fires for PAT pushes, not GITHUB_TOKEN pushes) and its 2-hour cron. The Pages site keeps working only if site.yml stays; the empty Azure Static Web App has no builder at all.

**D7 [should-fix] jackpot duplicate issues.** runner.py:236 reads `issues?state=all&per_page=100`, page 1 only; GH used `--limit 200`. Once more than 100 issues exist (reenter and alert issues accumulate), an old cycle's key falls off the page and the same alert is re-created daily. Also unhandled HTTP errors there abort before the data push (GH has the same order).

**D8 [should-fix] alert issues authored by the token owner.** GH created them as github-actions[bot], so the owner got email. Created with the owner's PAT, GitHub may not notify you of your own activity (check notification settings), which defeats the alert's purpose. Also a PAT-created issue fires workflows; titles are `[jackpot] ...` so reenter.yml (`startsWith 'reenter'`) ignores them.

**D9 [should-fix] comp_terms degrades silently without poppler-utils.** comps.yml:32 installs it; comp_terms.py:67 skips PDFs when `pdftotext` is absent. Missing stated caps push listings into the "terms unread, cautious" path (entry_queue.py:225-230), changing entry limits. Verify `pdftotext` exists in the image.

**D10 [should-fix] untested runtime assumptions.** Playwright version unpinned vs GH's `playwright@1.63.0` (entries.yml:48); Chromium in a container with default small /dev/shm and 1 GiB for 6 contexts (ENTRANT_CONCURRENCY default 6, entrant.mjs:502) may crash; Azure datacenter IPs may be blocked where GH IPs were not (probe.yml exists because some sites differ by network). Set ENTRANT_CONCURRENCY=2 in the job and dry-test.

**D11 [should-fix] no observability.** stdout is lost; failure shows only as a Failed execution. Pace gating (`current_pace` 82-87) catches URLError/ValueError/KeyError but not `TimeoutError`/OSError, so a socket timeout crashes the entries job before anything runs. Add a failure marker (e.g. an issue or a heartbeat file) or Log Analytics.

**D12 [minor] token handling is mostly good, with two exposures.** Good: token never in the clone URL, never in `command()`'s printed args (124), not written to .git/config (env-var `http.extraheader`, 99-113). Exposures: GITHUB_TOKEN, ENTRANT_PROFILE_JSON and the Basic-auth header var are inherited by every child, including `node`/Chromium (264, 275) and the scrapers; pass entrant only ENTRANT_*, NODE_PATH, PLAYWRIGHT_*. Commits use `azure@users.noreply.github.com` (153) but commit_entries.sh:9-10 overwrites with the GH bot identity, so provenance is mixed. Also `ghcr-publish-token` (a write-scoped token) is used as the pull credential, and `:latest` is mutable (pin a digest).

**D13 [minor] profile mapping.** All nine ENTRANT_* names are covered (runner.py:44-54 vs entrant.mjs:127-132: FIRST_NAME, LAST_NAME, EMAIL, PHONE, POSTCODE, SUBURB, STATE, ADDRESS, DOB), plus winners.py:228 uses ENTRANT_LAST_NAME (set). Problems: JSON keys are exact snake_case; a mismatched key is skipped silently (55-57). `str(profile[k])` turns JSON null into the literal "None" (57), which would be typed into a form. Existing env wins over profile (`not in os.environ`). A missing email makes entries print and skip submitting (277-282) but still commit; missing first/last raises inside entrant.mjs:508. Profile is parsed before the kill-switch check (348 vs 350): bad JSON crashes even a disabled job.

**D14 [minor] pacing drift.** GH loops five rounds with entry_queue re-run each round; Azure runs five separate executions, each paying clone latency. The 5-min per-comp gap (entry_queue.py:158) is already skipping alternate rounds in GH (log shows 10-min spacing), and Azure start jitter will do likewise. 288 invocations a day for entries; non-due ones exit cheaply (before clone) but cost one API call each.

## Minimum fixes before any dry run
1. Keep AZURE_JOBS_DISABLED=1 as the default; do the dry run with `az containerapp job start` env overrides, never by editing the job. Do not enable any real cron yet.
2. Set a real cron only after GH is disabled and any in-flight entries.yml run is cancelled (D2); never run both for entries.
3. entries: wrap entrant in `timeout=` about 120 s with commit still in `finally`, handle SIGTERM, raise replicaTimeout to at least 600, lower ENTRANT_CONCURRENCY to 2 (D1, D10).
4. comps: line 211 `check=False, timeout=1800`; push in `finally` (D3).
5. Add a DRY_RUN/FORCE env (skip the push and the issue creation, bypass `entry_due`) so a dry run changes nothing on main (D5).
6. Fix issues paging (`per_page=100&page=n`) and make the reenter issue comment/close run on failure; leave reenter and site on GitHub (D4, D6, D7).
7. Confirm `pdftotext`, git, Playwright version and Chromium launch inside the image; scrub env for the entrant; null-safe profile mapping (D9, D10, D12, D13).
