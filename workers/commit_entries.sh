#!/usr/bin/env bash
# Commit the entrant's new log lines without losing them to a concurrent push (used by entries.yml).
#   bash workers/commit_entries.sh "entries: 2026-10-31 09:05"
# A plain `git pull --rebase` conflicted whenever anything else changed the regenerated files in data/entries during
# a run, and the run's log was lost. Instead: keep only the lines this run appended to data/entries/log*.jsonl, move
# to the latest main, append them there, rebuild the queue, manual list and register from the merged log, push.
set -u
msg="$1"
git config user.name "lotto-entries-worker"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
keep="${RUNNER_TEMP:-/tmp}/new_entry_logs"
rm -rf "$keep" && mkdir -p "$keep"
for f in data/entries/log*.jsonl; do
  [ -e "$f" ] || continue
  if git ls-files --error-unmatch "$f" > /dev/null 2>&1; then
    git diff --no-color -U0 -- "$f" | grep '^+{' | cut -c2- > "$keep/$(basename "$f")"
  else
    cp "$f" "$keep/$(basename "$f")"
  fi
done
for i in 1 2 3 4; do
  git fetch -q origin main && git reset -q --hard origin/main
  for f in "$keep"/*.jsonl; do
    [ -s "$f" ] && cat "$f" >> "data/entries/$(basename "$f")"
  done
  python3 -m workers.entry_queue > /dev/null
  python3 -m workers.removals > /dev/null || true     # PREFERENCES.md from the merged removals
  git add data/entries
  git diff --cached --quiet && exit 0
  git commit -q -m "$msg" && git push -q origin HEAD:main && exit 0
  sleep $((i * 5))
done
echo "could not push the entry log after 4 tries" >&2
exit 1
