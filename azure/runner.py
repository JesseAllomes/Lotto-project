#!/usr/bin/env python3
"""Run one Lotto worker in an ephemeral Azure Container Apps Job.

The image carries the code (workers/, analysis/ under /app/repo) and this launcher; it does not use git.  Each due
execution pulls the job's data prefixes from the Azure Blob container lotto-data (azure/blobsync.py), runs one
bounded unit of work, uploads only the files that changed, and exits.  The `site` job builds the page from that data
and deploys it to the Static Web App.  Nothing sleeps until the next schedule window, so idle time is never billable.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actionqueue  # noqa: E402
import blobsync  # noqa: E402  (next to this file, in the image and in the repository)

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "JesseAllomes/Lotto-project")
REPO_ROOT = Path(os.environ.get("LOTTO_REPO_ROOT", "/app/repo"))
SWA_BIN = "/opt/playwright/node_modules/.bin/swa"
SITE_API_DIR = "azure/site-api"
SITE_API_PYTHON = "3.11"         # also set as platform.apiRuntime python:3.11 in staticwebapp.config.json (workers/site.py)
BURST_MINUTES = frozenset({5, 10, 15, 20, 25})
MAX_ISSUE_PAGES = 10
# Every external step is bounded (seconds), well inside the job's replicaTimeout (azure/jobs/*.json), so a hung
# step fails the run with its work saved instead of waiting for Azure to kill the replica.
QUEUE_TIMEOUT_S = 120
WORKER_TIMEOUT_S = 1500          # draws, jackpots
COMPS_TIMEOUT_S = 900            # workers.comps (capped by COMPS_MAX_NEW; progress is saved every 50 listings)
COMPS_MAX_NEW = 300
COMPS_STEP_TIMEOUT_S = 240       # comp_odds, skill_rank, winners
REENTER_BUILD_TIMEOUT_S = 120
# The actions job (azure/jobs/lotto-actions.json, replicaTimeout 600): pull, up to 20 queue messages, entrant, upload.
MAX_ACTIONS_PER_RUN = 20
ACTIONS_MAX_DEQUEUE = 3          # a message read more than this many times goes to the poison queue
ACTIONS_VISIBILITY_S = 900       # longer than replicaTimeout, so a second execution never sees a running one's messages
# The site job (replicaTimeout 900 in azure/jobs/lotto-site.json): pull, freebies, winners, build, deploy.
SITE_FREEBIES_TIMEOUT_S = 90
SITE_WINNERS_TIMEOUT_S = 60
SITE_BUILD_TIMEOUT_S = 120
SITE_DEPLOY_TIMEOUT_S = 420
# Entrant defaults when run from here (jobs also set these in env): coherent with replicaTimeout 280 on lotto-entries.
ENTRANT_DEFAULT_TIMEOUT_S = 150
ENTRANT_DEFAULT_CONCURRENCY = 3
ENTRANT_DEFAULT_ITEM_TIMEOUT_S = 85
ENTRANT_DEFAULT_MAX = 30
# Never handed to node/Chromium or the Python scrapers.  The identity variables let a process mint storage tokens.
SECRET_VARS = (
    "GITHUB_TOKEN",
    "ENTRANT_PROFILE_JSON",
    "SWA_DEPLOY_TOKEN",
    "IDENTITY_ENDPOINT",
    "IDENTITY_HEADER",
)

# Blob prefixes pulled at the start of each job (blob name = repo-relative path).
DATA_PREFIXES = {
    "comps": ("data/comps/", "data/entries/"),
    "draws": ("data/draws/",),
    "jackpots": ("data/jackpots/",),
    "entries": ("data/comps/", "data/entries/"),
    "reenter": ("data/comps/", "data/entries/"),
    "actions": ("data/comps/", "data/entries/"),
    "site": ("data/comps/", "data/entries/"),
}
# What each job may upload (the site job uploads nothing).
PUSH_PATHS = {
    "comps": ("data/comps", "data/entries/winners.csv", "data/entries/winner_checks.jsonl"),
    "draws": ("data/draws",),
    "jackpots": ("data/jackpots",),
    "entries": ("data/entries",),
    "reenter": ("data/entries",),
    "actions": ("data/entries",),
}
PACE_BLOB = "data/entries/pace.json"


class ProfileError(Exception):
    """The profile secret is unusable; the message never contains the secret."""


def dry_run() -> bool:
    return os.environ.get("DRY_RUN") == "1"


def install_sigterm_handler() -> None:
    """Turn the container stop signal into SystemExit so `finally` blocks (the commit) run."""

    def terminate(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)


def entrant_timeout() -> int:
    try:
        return int(os.environ.get("ENTRANT_TIMEOUT_S") or ENTRANT_DEFAULT_TIMEOUT_S)
    except ValueError:
        return ENTRANT_DEFAULT_TIMEOUT_S


def load_profile() -> None:
    """Expand the single Key Vault profile secret into the entrant variables."""
    raw = os.environ.get("ENTRANT_PROFILE_JSON")
    if not raw:
        return
    try:
        profile = json.loads(raw)
    except ValueError:
        raise ProfileError("ENTRANT_PROFILE_JSON is not valid JSON") from None
    if not isinstance(profile, dict):
        raise ProfileError("ENTRANT_PROFILE_JSON must be a JSON object")
    names = {
        "first_name": "ENTRANT_FIRST_NAME",
        "last_name": "ENTRANT_LAST_NAME",
        "email": "ENTRANT_EMAIL",
        "phone": "ENTRANT_PHONE",
        "postcode": "ENTRANT_POSTCODE",
        "suburb": "ENTRANT_SUBURB",
        "state": "ENTRANT_STATE",
        "address": "ENTRANT_ADDRESS",
        "dob": "ENTRANT_DOB",
    }
    for source, target in names.items():
        value = profile.get(source)
        if value is None or str(value).strip() == "":
            continue
        if target not in os.environ:
            os.environ[target] = str(value)


def github_request(method: str, path: str, payload: object | None = None) -> object:
    if method != "GET" and dry_run():
        title = payload.get("title", "") if isinstance(payload, dict) else ""
        print(f"DRY_RUN: would {method} {path} {title}".rstrip(), flush=True)
        return {}
    token = os.environ.get("GITHUB_TOKEN", "")
    body = None if payload is None else json.dumps(payload).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "lotto-azure-worker",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def current_pace() -> dict:
    """data/entries/pace.json from the blob store (one GET, no full pull); a safe default when unreadable."""
    default = {"last_day_listings": 0, "next_run_minutes": 180}
    try:
        text = blobsync.read_text(PACE_BLOB)
        pace = json.loads(text) if text else None
    except (blobsync.BlobError, ValueError, OSError):
        return default
    return pace if isinstance(pace, dict) else default


def entry_due(now: dt.datetime, pace: dict) -> bool:
    """True only for one of the five burst slots in a standard or rush hour."""
    now = now.astimezone(dt.UTC)
    slot = (now.minute // 5) * 5
    standard = now.hour % 3 == 0
    rush = int(pace.get("last_day_listings") or 0) > 0
    return slot in BURST_MINUTES and (standard or rush)


def child_environment() -> dict[str, str]:
    """Environment for node and the Python scrapers: no token, profile JSON, identity or deploy token, no ENTRANT_*."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in SECRET_VARS and not key.startswith("ENTRANT_")
    }


def command(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
    env: dict | None = None,
    timeout: int | None = None,
):
    print("+", " ".join(args), flush=True)
    return subprocess.run(
        args,
        cwd=cwd,
        env=env if env is not None else child_environment(),
        check=check,
        timeout=timeout,
    )


def prepare(job: str) -> Path:
    """Pull the job's data prefixes into the image's repo folder (where the workers expect data/)."""
    root = REPO_ROOT
    root.mkdir(parents=True, exist_ok=True)
    count = blobsync.pull(DATA_PREFIXES[job], root)
    print(f"Pulled {count} file(s) from the blob store: {', '.join(DATA_PREFIXES[job])}", flush=True)
    return root


def push(root: Path, message: str, paths: list[str] | tuple[str, ...]) -> bool:
    """Upload the changed files under paths (conditional on the pulled ETags); DRY_RUN only lists them."""
    files = blobsync.local_files(root, paths)
    if not files:
        print("No generated paths exist", flush=True)
        return False
    if dry_run():
        names = blobsync.changed_names(files)
        print(f"DRY_RUN: would upload {len(names)} changed file(s) to the blob store: {message}", flush=True)
        return False
    uploaded = blobsync.push(files)
    print(f"{message}: uploaded {len(uploaded)} changed file(s)", flush=True)
    return bool(uploaded)


def run_soft(args: list[str], cwd: Path, *, env: dict, timeout: int | None = None) -> None:
    """A step that may fail or overrun without stopping the job (continue-on-error)."""
    try:
        command(args, cwd, env=env, check=False, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"Step did not finish, continuing: {type(exc).__name__}", flush=True)


def run_comps(root: Path, profile_ok: bool = True) -> None:
    scrape = child_environment()
    try:
        command(
            [sys.executable, "-m", "workers.comps", "--max", str(COMPS_MAX_NEW)],
            root,
            env=scrape,
            timeout=COMPS_TIMEOUT_S,
        )
        run_soft(
            [sys.executable, "-m", "workers.source_auscomps", "--max", "600"],
            root,
            env=scrape,
            timeout=15 * 60,
        )
        run_soft(
            [sys.executable, "-m", "workers.comp_terms"],
            root,
            env=scrape,
            timeout=20 * 60,
        )
        # Same as comps.yml; shorter caps so every step fits the job's 5400 s replicaTimeout.
        run_soft(
            [sys.executable, "-m", "workers.entry_pages", "--max", "300"],
            root,
            env=scrape,
            timeout=8 * 60,
        )
        run_soft(
            [sys.executable, "-m", "workers.entry_pages", "--targets"],
            root,
            env=scrape,
            timeout=COMPS_STEP_TIMEOUT_S,
        )
        run_soft(
            ["node", "workers/link_check.mjs"],
            root,
            env=scrape,
            timeout=10 * 60,
        )
        command(
            [sys.executable, "-m", "workers.comp_odds", "--tags"],
            root,
            env=scrape,
            timeout=COMPS_STEP_TIMEOUT_S,
        )
        command(
            [sys.executable, "-m", "analysis.skill_rank"],
            root,
            env=scrape,
            timeout=COMPS_STEP_TIMEOUT_S,
        )
        if profile_ok:
            winners = dict(scrape)
            if os.environ.get("ENTRANT_LAST_NAME"):
                winners["ENTRANT_LAST_NAME"] = os.environ["ENTRANT_LAST_NAME"]
            run_soft(
                [sys.executable, "-m", "workers.winners", "--check"],
                root,
                env=winners,
                timeout=COMPS_STEP_TIMEOUT_S,
            )
        else:
            print("Profile is unusable; winners check skipped", flush=True)
    finally:
        push(
            root,
            f"comps: Azure update {dt.datetime.now(dt.UTC):%Y-%m-%d}",
            PUSH_PATHS["comps"],
        )


def run_draws(root: Path) -> None:
    command(
        [sys.executable, "-m", "workers.draws"],
        root,
        env=child_environment(),
        timeout=WORKER_TIMEOUT_S,
    )
    push(
        root,
        f"draws: Azure update {dt.datetime.now(dt.UTC):%Y-%m-%d}",
        PUSH_PATHS["draws"],
    )


def create_alert_issues(alerts: list[dict]) -> None:
    titles: set[str] = set()
    for page in range(1, MAX_ISSUE_PAGES + 1):
        issues = github_request("GET", f"issues?state=all&per_page=100&page={page}")
        if not issues:
            break
        titles.update(
            issue.get("title", "") for issue in issues if "pull_request" not in issue
        )
    for alert in alerts:
        if not any(alert["key"] in title for title in titles):
            github_request(
                "POST", "issues", {"title": alert["title"], "body": alert["body"]}
            )


def run_jackpots(root: Path) -> None:
    alert_path = root / ".azure-alerts.json"
    command(
        [sys.executable, "-m", "workers.jackpots", "--alerts", str(alert_path)],
        root,
        env=child_environment(),
        timeout=WORKER_TIMEOUT_S,
    )
    # Data first: a slow or failing GitHub issues API must not lose the day's register.
    push(
        root,
        f"jackpots: Azure update {dt.datetime.now(dt.UTC):%Y-%m-%d}",
        PUSH_PATHS["jackpots"],
    )
    create_alert_issues(json.loads(alert_path.read_text()))


def entrant_environment(
    root: Path, queue: Path | None = None, reenter: bool = False
) -> dict:
    out = child_environment()
    out.update(
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith("ENTRANT_") and key != "ENTRANT_PROFILE_JSON"
        }
    )
    out["NODE_PATH"] = "/opt/playwright/node_modules"
    # Bounded by default so a run ends, and its log is uploaded, before Azure kills the replica.
    timeout = entrant_timeout()
    out.setdefault("ENTRANT_ITEM_TIMEOUT_S", str(ENTRANT_DEFAULT_ITEM_TIMEOUT_S))
    try:
        item = int(out["ENTRANT_ITEM_TIMEOUT_S"])
    except ValueError:
        item = ENTRANT_DEFAULT_ITEM_TIMEOUT_S
        out["ENTRANT_ITEM_TIMEOUT_S"] = str(item)
    out.setdefault("ENTRANT_CONCURRENCY", str(ENTRANT_DEFAULT_CONCURRENCY))
    out.setdefault("ENTRANT_MAX", str(ENTRANT_DEFAULT_MAX))
    out.setdefault("ENTRANT_BUDGET_S", str(max(timeout - item - 5, 5)))
    if dry_run():
        out["ENTRANT_LIVE"] = "0"
    if queue:
        out["ENTRANT_QUEUE"] = str(queue)
    if reenter:
        out["ENTRANT_LOG"] = str(root / "data/entries/log_reenter.jsonl")
    return out


def finish_entries(root: Path, message: str) -> None:
    """Rebuild the queue, manual list, register and PREFERENCES.md from the log (the old GitHub flow did this after
    merging the log), then upload data/entries.  A log appended to elsewhere meanwhile is union-merged by blobsync."""
    scrape = child_environment()
    run_soft([sys.executable, "-m", "workers.entry_queue"], root, env=scrape, timeout=QUEUE_TIMEOUT_S)
    run_soft([sys.executable, "-m", "workers.removals"], root, env=scrape, timeout=QUEUE_TIMEOUT_S)
    push(root, message, PUSH_PATHS["entries"])


def queue_is_empty(path: Path) -> bool:
    """True when the entrant has nothing to enter, so node and Chromium need not start."""
    try:
        return not json.loads(path.read_text())
    except (OSError, ValueError):
        return False


def run_entries(root: Path) -> None:
    command(
        [sys.executable, "-m", "workers.entry_queue"],
        root,
        env=child_environment(),
        timeout=QUEUE_TIMEOUT_S,
    )
    run_env = entrant_environment(root)
    try:
        if queue_is_empty(root / "data/entries/queue.json"):
            print("Entry queue is empty; browser not started", flush=True)
        elif run_env.get("ENTRANT_EMAIL"):
            command(
                ["node", "workers/entrant.mjs"],
                root,
                env=run_env,
                timeout=entrant_timeout(),
            )
        else:
            print(
                "ENTRANT_EMAIL is unset; queue refreshed without submitting", flush=True
            )
    finally:
        finish_entries(root, f"entries: Azure {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M}")


def new_log_rows(log: Path, before: int) -> list[dict]:
    """The rows this run appended to the re-entry log (read before any merge with the stored copy)."""
    try:
        return (
            [json.loads(line) for line in log.read_text().splitlines()[before:]]
            if log.exists()
            else []
        )
    except ValueError:
        return []


def run_reenter(root: Path) -> None:
    title = os.environ.get("ISSUE_TITLE", "")
    number = os.environ.get("ISSUE_NUMBER", "")
    if not title or not number:
        raise RuntimeError("ISSUE_TITLE and ISSUE_NUMBER are required")
    log = root / "data/entries/log_reenter.jsonl"
    before = log.read_text().count("\n") if log.exists() else 0
    failure = ""
    rows: list[dict] | None = None
    try:
        queue = root / ".azure-reenter.json"
        result = subprocess.run(
            [sys.executable, "-m", "workers.reenter", title],
            cwd=root,
            env=child_environment(),
            check=True,
            capture_output=True,
            text=True,
            timeout=REENTER_BUILD_TIMEOUT_S,
        )
        queue.write_text(result.stdout)
        run_env = entrant_environment(root, queue, reenter=True)
        try:
            if queue_is_empty(queue):
                print("Nothing to re-enter; browser not started", flush=True)
            else:
                command(
                    ["node", "workers/entrant.mjs"],
                    root,
                    env=run_env,
                    timeout=entrant_timeout(),
                )
        finally:
            rows = new_log_rows(log, before)
            finish_entries(root, f"reenter: issue #{number}")
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if rows is None:
            rows = new_log_rows(log, before)
        summary = (
            "\n".join(f"- {row.get('id')}: {row.get('result')}" for row in rows)
            or "Nothing could be entered."
        )
        body = (
            f"Re-entry failed: {failure}\n{summary}"
            if failure
            else f"Re-entry results:\n{summary}"
        )
        try:
            github_request("POST", f"issues/{number}/comments", {"body": body})
            github_request("PATCH", f"issues/{number}", {"state": "closed"})
        except Exception as exc:  # never mask the run's own failure
            print(f"Could not report to issue #{number}: {type(exc).__name__}", flush=True)
            if not failure:
                raise


def worker_actions():
    """workers.actions, imported here because the image keeps the workers under REPO_ROOT, not next to this file."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    from workers import actions

    return actions


def run_actions(profile_ok: bool = True, queue: actionqueue.ActionQueue | None = None) -> None:
    """Drain the lotto-actions queue (the site's buttons, azure/site-api): at most MAX_ACTIONS_PER_RUN messages.

    Each message is applied with the existing workers (workers/actions.py), the changed data is uploaded, and only then
    is each applied message deleted, so a failure anywhere leaves it on the queue to be read again (it becomes
    invisible for ACTIONS_VISIBILITY_S).  A message read more than ACTIONS_MAX_DEQUEUE times, or one that can never
    be applied (malformed), is moved to the poison queue.  Re-entries run once for the whole batch with the same
    entrant limits as the reenter job.  A DRY_RUN changes and deletes nothing in Azure."""
    queue = queue or actionqueue.ActionQueue()
    if not queue.has_messages():           # a peek: no data is pulled for an execution that finds nothing to do
        print("No actions waiting", flush=True)
        return
    root = prepare("actions")
    actions = worker_actions()
    store, entries = root / "data" / "comps", root / "data" / "entries"
    received = queue.receive(MAX_ACTIONS_PER_RUN, ACTIONS_VISIBILITY_S)
    if not received:                       # another execution took them first
        print("No actions waiting", flush=True)
        return
    poison, plan = [], []
    for message in received:
        if message.dequeue_count > ACTIONS_MAX_DEQUEUE:
            poison.append(message)
            continue
        try:
            plan.append((message, actions.parse(message.text)))
        except actions.Rejected as exc:
            print(f"Message {message.id[:8]} can never be applied ({exc}); to the poison queue", flush=True)
            poison.append(message)
    seen = actions.applied_ids(entries)
    deletable, failed, results, reenter_for = [], [], [], {}
    for message, action in plan:
        if action["id"] in seen:           # applied and uploaded before, but the delete did not happen
            deletable.append(message)
            continue
        try:
            outcome, detail = actions.apply_one(action, store, entries)
        except Exception as exc:           # one bad message must not stop the others
            print(f"Action {action['id'][:8]} ({action['kind']}) failed: {type(exc).__name__}; left on the queue", flush=True)
            failed.append(message)
            continue
        if outcome == "pending":
            reenter_for[action["id"]] = (message, action)
        else:
            results.append((message, action, outcome, detail))
    if reenter_for:
        entered, detail = enter_actions(root, [i for _, a in reenter_for.values() for i in a["ids"]], profile_ok)
        for message, action in reenter_for.values():
            if entered:
                results.append((message, action, "applied", detail))
            else:
                print(f"Re-entry {action['id'][:8]} not done ({detail}); left on the queue", flush=True)
                failed.append(message)
    for message, action, outcome, detail in results:
        actions.record_result(entries, action, outcome, detail)
        deletable.append(message)
    print(f"Actions: {len(results)} handled, {len(failed)} to retry, {len(poison)} for the poison queue", flush=True)
    finish_entries(root, f"actions: {len(results)} from the site")      # raises when the upload fails: nothing is deleted
    if dry_run():
        print("DRY_RUN: no message moved or deleted", flush=True)
        return
    for message in poison:
        try:
            queue.move_to_poison(message)
        except blobsync.BlobError as exc:
            print(f"Could not move {message.id[:8]} to the poison queue: {exc}", flush=True)
    for message in deletable:
        try:
            queue.delete(message)
        except blobsync.BlobError as exc:      # the audit rows make the redelivered message a no-op
            print(f"Could not delete {message.id[:8]}: {exc}", flush=True)
    if failed:
        raise RuntimeError(f"{len(failed)} action(s) left on the queue to be tried again")


def enter_actions(root: Path, ids: list[str], profile_ok: bool) -> tuple[bool, str]:
    """Re-enter these ids now: (done, detail).  The same bounds as the reenter job: the entrant's ENTRANT_MAX, timeout
    and concurrency; closed or unknown listings are skipped; the log goes to data/entries/log_reenter.jsonl."""
    actions = worker_actions()
    run_env = entrant_environment(root, root / ".azure-actions-reenter.json", reenter=True)
    if not profile_ok or not run_env.get("ENTRANT_EMAIL"):
        return False, "the entrant profile is not set"
    try:
        limit = int(run_env["ENTRANT_MAX"])
    except ValueError:
        limit = ENTRANT_DEFAULT_MAX
    items = actions.plan_reenter(ids, root / "data" / "comps", root / "data" / "entries", limit)
    if not items:
        print("Nothing to re-enter; browser not started", flush=True)
        return True, "nothing to re-enter (closed, removed or not in the register)"
    queue_file = root / ".azure-actions-reenter.json"
    queue_file.write_text(json.dumps(items))
    try:
        command(["node", "workers/entrant.mjs"], root, env=run_env, timeout=entrant_timeout())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        return False, f"the entrant failed: {type(exc).__name__}"
    return True, f"re-entered {len(items)} of {len(set(ids))} (the log has the results)"


def run_site(root: Path) -> None:
    """The same steps as the build job of site.yml, then deploy the folder to the Static Web App."""
    scrape = child_environment()
    run_soft([sys.executable, "-m", "workers.freebies"], root, env=scrape, timeout=SITE_FREEBIES_TIMEOUT_S)
    run_soft([sys.executable, "-m", "workers.winners"], root, env=scrape, timeout=SITE_WINNERS_TIMEOUT_S)
    command(
        [sys.executable, "-m", "workers.site", "--out", "site"],
        root,
        env=scrape,
        timeout=SITE_BUILD_TIMEOUT_S,
    )
    for name in ("index.html", "staticwebapp.config.json"):
        if not (root / "site" / name).is_file():
            raise RuntimeError(f"the site build wrote no site/{name}; nothing to deploy")
    deploy_site(root)


def deploy_site(root: Path) -> None:
    """Deploy ./site and the managed API (azure/site-api) with the SWA CLI.  The token reaches the CLI only through its
    environment, never argv or logs."""
    if dry_run():
        print("DRY_RUN: would deploy site/ and the API azure/site-api to the Static Web App", flush=True)
        return
    if not (root / SITE_API_DIR / "function_app.py").is_file():
        raise RuntimeError(f"{SITE_API_DIR}/function_app.py is missing; the site buttons would have no API")
    token = os.environ.get("SWA_DEPLOY_TOKEN", "")
    if not token:
        raise RuntimeError("SWA_DEPLOY_TOKEN is required to deploy the site")
    env = child_environment()
    env["SWA_CLI_DEPLOYMENT_TOKEN"] = token
    command(
        [SWA_BIN, "deploy", "site", "--api-location", SITE_API_DIR, "--api-language", "python",
         "--api-version", SITE_API_PYTHON, "--env", "production"],
        root,
        env=env,
        timeout=SITE_DEPLOY_TIMEOUT_S,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1 or argv[0] not in DATA_PREFIXES:
        print(
            f"usage: {Path(sys.argv[0]).name} {'|'.join(DATA_PREFIXES)}", file=sys.stderr
        )
        return 2
    install_sigterm_handler()
    job = argv[0]
    if os.environ.get("AZURE_JOBS_DISABLED") == "1":
        print("Azure jobs are disabled by the cost kill switch")
        return 0
    profile_error = ""
    if job in ("entries", "reenter", "comps", "actions"):
        try:
            load_profile()
        except ProfileError as exc:
            profile_error = str(exc)
    if job == "entries":
        pace = current_pace()
        due = os.environ.get("FORCE") == "1" or entry_due(dt.datetime.now(dt.UTC), pace)
        if os.environ.get("ENTRIES_DISABLED") == "1" or not due:
            print(f"Entry round is not due: {pace}")
            return 0
    if profile_error and job in ("entries", "reenter"):
        print(f"{job}: {profile_error}; fix the profile secret", file=sys.stderr)
        return 1
    if job == "actions":                 # peeks at the queue first and pulls the data only when something waits
        run_actions(profile_ok=not profile_error)
        return 0
    root = prepare(job)
    if job == "comps":
        run_comps(root, profile_ok=not profile_error)
    else:
        {
            "draws": run_draws,
            "jackpots": run_jackpots,
            "entries": run_entries,
            "reenter": run_reenter,
            "site": run_site,
        }[job](root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
