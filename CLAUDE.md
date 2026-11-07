# Working rules from the owner

- **Collect and collate data with repeatable workers that use no tokens**, wherever possible. That
  means scripts, GitHub Actions and scheduled jobs (for example `tools/live_collector.py`), not
  agents. Agents cost tokens.
- **Never start Fable without the owner asking.** Fable is reserved for complex analysis, critical
  thinking and outside-the-box thinking, and only on request. When Fable runs, scripts do the data
  collection and token burn is kept to a minimum.
- **Run substantial multi-step work under the `drainclamp-build-adhd` skill**, so its state is
  durable and tracked by milestone.
- Be mindful of credits.
- Push to main with `git push origin main`.
- Keep API keys out of the repository.
- **DrainClamp is compulsory** (owner, 2026-11-07): every session and multi-step task starts with
  the `drainclamp-build-adhd` skill at Gate S and follows its gates; no ad-hoc drifting.
- **product-ui is compulsory for every UI change** (`/home/user/jesseallomes/product-ui`):
  prototypes first, no production UI until the owner says BUILD.
