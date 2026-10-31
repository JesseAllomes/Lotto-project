# Azure inventory: Lotto (az1, 2026-10-31)

Subscription "Azure subscription 1", resource group rg-personal-automation-aue (australiaeast). Read-only check.

| GitHub workflow | Azure resource | Status |
|---|---|---|
| draws.yml | job lotto-draws (args `draws`) | parked: cron `0 0 29 2 *`; 1 run 2026-10-31 03:36Z "Succeeded", output unknown |
| jackpots.yml | job lotto-jackpots | parked, never run |
| comps.yml | job lotto-comps (timeout 5400 s) | parked, never run |
| entries.yml | job lotto-entries (timeout **180 s**) | parked, never run |
| reenter.yml | job lotto-reenter (manual), started by func-personal webhook | never run |
| site.yml (Pages) | static web app swa-lotto (ambitious-plant-0e97ae900.6.azurestaticapps.net) | **empty**: Azure placeholder page |
| probe.yml | none | n/a (manual tool) |

Shared: identity id-personal-*, Key Vault kv-personal-v5ethud2i3cf (secret names: entrant-profile-json,
ghcr-publish-token, github-webhook-secret, lotto-github-token, melbcup-github-token), env cae-personal-*.

Findings
1. Source not in any repository: image ghcr.io/jesseallomes/lotto-project-azure:latest is private and its build
   source is not in Lotto-project or any repo this account lists. Function code is a package in blob container
   function-deployment. Neither is reviewable from git yet.
2. Tag `latest`, not pinned to a commit.
3. No logging: the Container Apps environment has no Log Analytics, so job output is lost.
4. lotto-entries replicaTimeout 180 s; the GitHub run takes far longer (bursts ~5 min apart). Must be raised.
5. Every job gets ENTRANT_PROFILE_JSON (owner's personal details), including draws and jackpots, which do not need it.
6. Kill switches: AZURE_JOBS_DISABLED=1 on all jobs; ENTRANT_LIVE=1 (first Azure entry run must be 0 per decision).
7. Owner's own account lacks Storage Blob Data roles on stpersonalv5ethud2i3cfq (subscription Owner, so can self-grant).
8. Unrelated: rg-jesseallomes-9487 holds an AI Services (Foundry) account; not part of this migration.
