#!/usr/bin/env python3
"""Run one Lotto worker in an ephemeral Azure Container Apps Job.

The image contains only this launcher and its runtime dependencies.  Each due
execution makes a shallow sparse checkout, runs one bounded unit of work,
commits the generated registers, and exits.  Nothing sleeps until the next
schedule window, so idle time is never billable.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "JesseAllomes/Lotto-project")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")
BURST_MINUTES = frozenset({5, 10, 15, 20, 25})
MAX_ISSUE_PAGES = 10
# Every external step is bounded (seconds), well inside the job's replicaTimeout (azure/jobs/*.json), so a hung
# step fails the run with its work saved instead of waiting for Azure to kill the replica.
CLONE_TIMEOUT_S = 120
GIT_STEP_TIMEOUT_S = 60
GIT_NETWORK_TIMEOUT_S = 90
QUEUE_TIMEOUT_S = 120
COMMIT_ENTRIES_TIMEOUT_S = 120
WORKER_TIMEOUT_S = 1500          # draws, jackpots
COMPS_TIMEOUT_S = 900            # workers.comps (capped by COMPS_MAX_NEW; progress is saved every 50 listings)
COMPS_MAX_NEW = 300
COMPS_STEP_TIMEOUT_S = 240       # comp_odds, skill_rank, winners
REENTER_BUILD_TIMEOUT_S = 120
# Entrant defaults when run from here (jobs also set these in env): coherent with replicaTimeout 280 on lotto-entries.
ENTRANT_DEFAULT_TIMEOUT_S = 150
ENTRANT_DEFAULT_CONCURRENCY = 3
ENTRANT_DEFAULT_ITEM_TIMEOUT_S = 85
ENTRANT_DEFAULT_MAX = 30
# Never handed to node/Chromium or the Python scrapers (git gets only its own auth header).
SECRET_VARS = (
    "GITHUB_TOKEN",
    "ENTRANT_PROFILE_JSON",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0",
    "GIT_CONFIG_VALUE_0",
)

SPARSE_PATHS = {
    "comps": ("workers", "analysis", "data/comps", "data/entries", ".gitattributes"),
    "draws": ("workers", "data/draws", ".gitattributes"),
    "jackpots": ("workers", "data/jackpots", ".gitattributes"),
    "entries": ("workers", "data/comps", "data/entries", ".gitattributes"),
    "reenter": ("workers", "data/comps", "data/entries", ".gitattributes"),
    "site": ("workers", "data/comps", "data/entries", ".gitattributes"),
}


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
    try:
        record = github_request("GET", f"contents/data/entries/pace.json?ref={BRANCH}")
        return json.loads(base64.b64decode(record["content"]))
    except (KeyError, ValueError, urllib.error.URLError, TimeoutError, OSError):
        return {"last_day_listings": 0, "next_run_minutes": 180}


def entry_due(now: dt.datetime, pace: dict) -> bool:
    """True only for one of the five burst slots in a standard or rush hour."""
    now = now.astimezone(dt.UTC)
    slot = (now.minute // 5) * 5
    standard = now.hour % 3 == 0
    rush = int(pace.get("last_day_listings") or 0) > 0
    return slot in BURST_MINUTES and (standard or rush)


def child_environment() -> dict[str, str]:
    """Environment for node and the Python scrapers: no token, profile JSON, git header or ENTRANT_*."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in SECRET_VARS and not key.startswith("ENTRANT_")
    }


def git_environment() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = child_environment()
    env.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


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


def checkout(job: str, parent: Path) -> tuple[Path, dict[str, str]]:
    env = git_environment()
    root = parent / "repo"
    command(
        [
            "git",
            "clone",
            "--depth=1",
            "--filter=blob:none",
            "--no-checkout",
            "--branch",
            BRANCH,
            f"https://github.com/{REPOSITORY}.git",
            str(root),
        ],
        parent,
        env=env,
        timeout=CLONE_TIMEOUT_S,
    )
    command(
        ["git", "sparse-checkout", "init", "--cone"],
        root,
        env=env,
        timeout=GIT_STEP_TIMEOUT_S,
    )
    command(
        ["git", "sparse-checkout", "set", *SPARSE_PATHS[job]],
        root,
        env=env,
        timeout=GIT_STEP_TIMEOUT_S,
    )
    command(["git", "checkout", BRANCH], root, env=env, timeout=GIT_NETWORK_TIMEOUT_S)
    command(
        ["git", "config", "user.name", "lotto-azure-worker"],
        root,
        env=env,
        timeout=GIT_STEP_TIMEOUT_S,
    )
    command(
        ["git", "config", "user.email", "azure@users.noreply.github.com"],
        root,
        env=env,
        timeout=GIT_STEP_TIMEOUT_S,
    )
    return root, env


def git_status(
    args: list[str], root: Path, env: dict[str, str], timeout: int, **options: object
) -> int:
    """Return a git step's exit code; a step that overruns its timeout counts as failed (124)."""
    try:
        return subprocess.run(
            args, cwd=root, env=env, check=False, timeout=timeout, **options
        ).returncode
    except subprocess.TimeoutExpired:
        print(f"Step timed out after {timeout}s: {' '.join(args[:2])}", flush=True)
        return 124


def push(root: Path, env: dict[str, str], message: str, paths: list[str]) -> bool:
    present = [path for path in paths if (root / path).exists()]
    if not present:
        print("No generated paths exist", flush=True)
        return False
    command(["git", "add", *present], root, env=env, timeout=GIT_STEP_TIMEOUT_S)
    if (
        git_status(["git", "diff", "--cached", "--quiet"], root, env, GIT_STEP_TIMEOUT_S)
        == 0
    ):
        print("No generated changes", flush=True)
        return False
    if dry_run():
        print(f"DRY_RUN: would commit and push to {BRANCH}: {message}", flush=True)
        return False
    command(["git", "commit", "-m", message], root, env=env, timeout=GIT_STEP_TIMEOUT_S)
    for attempt in range(1, 5):
        if (
            git_status(
                ["git", "pull", "--rebase", "-X", "theirs", "origin", BRANCH],
                root,
                env,
                GIT_NETWORK_TIMEOUT_S,
            )
            == 0
            and git_status(
                ["git", "push", "origin", f"HEAD:{BRANCH}"],
                root,
                env,
                GIT_NETWORK_TIMEOUT_S,
            )
            == 0
        ):
            return True
        git_status(
            ["git", "rebase", "--abort"],
            root,
            env,
            GIT_STEP_TIMEOUT_S,
            capture_output=True,
        )
        time.sleep(attempt * 5)
    raise RuntimeError("could not push generated data after four attempts")


def run_soft(args: list[str], cwd: Path, *, env: dict, timeout: int | None = None) -> None:
    """A step that may fail or overrun without stopping the job (continue-on-error)."""
    try:
        command(args, cwd, env=env, check=False, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"Step did not finish, continuing: {type(exc).__name__}", flush=True)


def run_comps(root: Path, env: dict[str, str], profile_ok: bool = True) -> None:
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
            env,
            f"comps: Azure update {dt.datetime.now(dt.UTC):%Y-%m-%d}",
            ["data/comps", "data/entries/winners.csv", "data/entries/winner_checks.jsonl"],
        )


def run_draws(root: Path, env: dict[str, str]) -> None:
    command(
        [sys.executable, "-m", "workers.draws"],
        root,
        env=child_environment(),
        timeout=WORKER_TIMEOUT_S,
    )
    push(
        root,
        env,
        f"draws: Azure update {dt.datetime.now(dt.UTC):%Y-%m-%d}",
        ["data/draws"],
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


def run_jackpots(root: Path, env: dict[str, str]) -> None:
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
        env,
        f"jackpots: Azure update {dt.datetime.now(dt.UTC):%Y-%m-%d}",
        ["data/jackpots"],
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
    # Bounded by default so a run ends, and its log is committed, before Azure kills the replica.
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


def commit_entries(root: Path, env: dict[str, str], message: str) -> None:
    if dry_run():
        print(f"DRY_RUN: would commit and push the entry log: {message}", flush=True)
        return
    command(
        ["bash", "workers/commit_entries.sh", message],
        root,
        env=env,
        timeout=COMMIT_ENTRIES_TIMEOUT_S,
    )


def queue_is_empty(path: Path) -> bool:
    """True when the entrant has nothing to enter, so node and Chromium need not start."""
    try:
        return not json.loads(path.read_text())
    except (OSError, ValueError):
        return False


def run_entries(root: Path, env: dict[str, str]) -> None:
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
        commit_entries(
            root, env, f"entries: Azure {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M}"
        )


def run_reenter(root: Path, env: dict[str, str]) -> None:
    title = os.environ.get("ISSUE_TITLE", "")
    number = os.environ.get("ISSUE_NUMBER", "")
    if not title or not number:
        raise RuntimeError("ISSUE_TITLE and ISSUE_NUMBER are required")
    log = root / "data/entries/log_reenter.jsonl"
    before = log.read_text().count("\n") if log.exists() else 0
    failure = ""
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
            command(
                [sys.executable, "-m", "workers.entry_queue"],
                root,
                env=child_environment(),
                timeout=QUEUE_TIMEOUT_S,
            )
            commit_entries(root, env, f"reenter: issue #{number}")
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            rows = (
                [json.loads(line) for line in log.read_text().splitlines()[before:]]
                if log.exists()
                else []
            )
        except ValueError:
            rows = []
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


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1 or argv[0] not in SPARSE_PATHS:
        print(
            f"usage: {Path(sys.argv[0]).name} {'|'.join(SPARSE_PATHS)}", file=sys.stderr
        )
        return 2
    install_sigterm_handler()
    job = argv[0]
    if job == "site":
        print("The site stays on GitHub Pages (site.yml); nothing to do here")
        return 0
    if os.environ.get("AZURE_JOBS_DISABLED") == "1":
        print("Azure jobs are disabled by the cost kill switch")
        return 0
    profile_error = ""
    if job in ("entries", "reenter", "comps"):
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
    with tempfile.TemporaryDirectory(prefix=f"lotto-{job}-") as directory:
        root, env = checkout(job, Path(directory))
        if job == "comps":
            run_comps(root, env, profile_ok=not profile_error)
        else:
            {
                "draws": run_draws,
                "jackpots": run_jackpots,
                "entries": run_entries,
                "reenter": run_reenter,
            }[job](root, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
