#!/usr/bin/env python3
"""Cost guard: refuses changes that could let the Azure jobs (or the workflows around them) run away with money.

    python3 -B tools/cost_guard.py --limits azure/limits.json [--live live/] [--json]

Stdlib only, no network, no Azure calls.  Exit 0 = pass, 1 = violations, 2 = configuration error.
One line per violation, `RULE path:line message`, then a summary with the worst-case USD a month per job.

Checks (the numbering follows the cost audit; the function checks C4/C5 and the C9 budget alarm do not apply
to this repository, which has no function app):
  C1   cron: parsed and enumerated; runs a day and the smallest gap between runs stay inside the limits
  C2   job envelope: trigger, timeout, size, parallelism, retries, env caps, pinned image, secret placement,
       timeout shorter than the cron gap (no overlapping executions)
  C3   cost model: runs x seconds x price, summed, against the monthly budget (and an all-timeouts ceiling)
  C6   resources: names in azure/inventory.json (optional) must be in the allowed list
  C7   code: unbounded subprocess/network calls (ratchet), unbounded loops, long sleeps, retry counts,
       module caps, secrets in source
  C8   workflows: timeouts, concurrency, self-dispatch, workflow_run, push loops, issue guards, cron volume
  C10  limits ratchet: azure/limits.json may not loosen against the base ref unless LIMITS_APPROVED=1
  C12  site actions: the Static Web App API (azure/site-api) has only the declared routes, needs the owner role at the
       edge (SWA_CONFIG in workers/site.py), caps body size, ids, answer length and kinds, and the retired
       issue-triggered workflows are gone; the Event job (lotto-actions) is bounded in C2 (executions, polling, queue)
  DRIFT  with --live DIR: exports of the live jobs are checked with C1-C3 and must equal azure/jobs/*.json
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_DIRS = ("azure", "workers", "tools")
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "GitHub fine-grained token": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "Azure API key": re.compile(r"\bda2-[a-z0-9]{20,}"),
    "storage account key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    "SAS signature": re.compile(r"[?&]sig=[A-Za-z0-9%+/]{20,}"),
}
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|KEY|PROFILE_JSON|CREDENTIAL", re.I)
UNBOUNDED_CALLS = {"run", "Popen", "call", "check_call", "check_output", "urlopen"}
UNBOUNDED_NAMES = {"command", "run_soft"}
SCAN_START = dt.date(2026, 1, 1)        # fixed, so cron results never depend on the clock


class ConfigError(Exception):
    pass


class Report:
    def __init__(self) -> None:
        self.violations: list[tuple[str, str, int, str]] = []
        self.notes: list[str] = []
        self.costs: dict[str, dict] = {}

    def fail(self, rule: str, path: str | Path, line: int, message: str) -> None:
        self.violations.append((rule, str(path), line, message))

    def note(self, message: str) -> None:
        self.notes.append(message)


# ---------------------------------------------------------------------------------------------------------- cron
def _field(text: str, low: int, high: int, name: str) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        m = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", part)
        if not m:
            raise ConfigError(f"cron {name} field {text!r}: only numbers, *, ranges, lists and /n are supported")
        base, step = m.group(1), int(m.group(2) or 1)
        if step < 1:
            raise ConfigError(f"cron {name} field {text!r}: step must be at least 1")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start, end = (int(x) for x in base.split("-"))
        else:
            start = int(base)
            end = high if m.group(2) else start
        if not (low <= start <= end <= high):
            raise ConfigError(f"cron {name} field {text!r} is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> dict:
    parts = expr.split()
    if len(parts) != 5:
        raise ConfigError(f"cron {expr!r}: need 5 fields")
    minute, hour, dom, month, dow = parts
    dows = {d % 7 for d in _field(dow, 0, 7, "day-of-week")}
    return {
        "minutes": sorted(_field(minute, 0, 59, "minute")),
        "hours": sorted(_field(hour, 0, 23, "hour")),
        "dom": _field(dom, 1, 31, "day-of-month"),
        "dom_any": dom == "*",
        "month": _field(month, 1, 12, "month"),
        "dow": dows,
        "dow_any": dow == "*",
    }


def _day_matches(c: dict, day: dt.date) -> bool:
    if day.month not in c["month"]:
        return False
    in_dom, in_dow = day.day in c["dom"], (day.isoweekday() % 7) in c["dow"]
    if c["dom_any"] or c["dow_any"]:
        return in_dom and in_dow            # a restricted field alone decides
    return in_dom or in_dow                 # both restricted: cron fires on either


@functools.lru_cache(maxsize=None)
def cron_stats(expr: str) -> dict:
    """Runs a day (worst day), runs in the busiest 30 days, smallest gap in minutes, over a fixed year."""
    c = parse_cron(expr)
    per_day = len(c["minutes"]) * len(c["hours"])
    times = sorted(h * 60 + m for h in c["hours"] for m in c["minutes"])
    gaps = [b - a for a, b in zip(times, times[1:])]
    days = [(SCAN_START + dt.timedelta(days=i)) for i in range(366)]
    hits = [1 if _day_matches(c, d) else 0 for d in days]
    if not any(hits):
        return {"parked": True, "per_day": 0, "per_30d": 0, "min_gap_min": None}
    busiest = max(sum(hits[i:i + 30]) for i in range(0, 366 - 29))
    idx = [i for i, h in enumerate(hits) if h]
    for a, b in zip(idx, idx[1:]):
        gaps.append((b - a) * 1440 + times[0] - times[-1])
    if len(idx) == 1 or not gaps:
        gaps.append(366 * 1440)
    return {"parked": False, "per_day": per_day, "per_30d": busiest * per_day, "min_gap_min": min(gaps)}


# ------------------------------------------------------------------------------------------------------ job view
def _memory_gi(text: str) -> float:
    m = re.fullmatch(r"([\d.]+)\s*(Gi|Mi)", str(text))
    if not m:
        raise ConfigError(f"memory {text!r} is not like 1Gi")
    return float(m.group(1)) / (1024 if m.group(2) == "Mi" else 1)


def job_view(doc: dict) -> dict:
    """The fields the guard cares about, from a desired file or a live `az containerapp job show` export."""
    props = doc.get("properties", {})
    conf = props.get("configuration", {})
    trigger = conf.get("triggerType")
    tc = conf.get("scheduleTriggerConfig") or conf.get("manualTriggerConfig") or conf.get("eventTriggerConfig") or {}
    containers = props.get("template", {}).get("containers") or []
    if len(containers) != 1:
        raise ConfigError(f"{doc.get('name')}: expected exactly one container, found {len(containers)}")
    c = containers[0]
    env = {e["name"]: ({"secretRef": e["secretRef"]} if "secretRef" in e else {"value": e.get("value")})
           for e in c.get("env", [])}
    res = c.get("resources", {})
    return {
        "name": doc.get("name"),
        "trigger": trigger,
        "cron": (conf.get("scheduleTriggerConfig") or {}).get("cronExpression"),
        "timeout": conf.get("replicaTimeout"),
        "retry": conf.get("replicaRetryLimit"),
        "parallelism": tc.get("parallelism"),
        "completion": tc.get("replicaCompletionCount"),
        "cpu": res.get("cpu"),
        "memory_gi": _memory_gi(res["memory"]) if res.get("memory") else None,
        "image": c.get("image"),
        "args": c.get("args") or [],
        "env": env,
        "secrets": sorted(s["name"] for s in conf.get("secrets") or []),
        "secret_urls": sorted((s["name"], s.get("keyVaultUrl")) for s in conf.get("secrets") or []),
        "registries": sorted((r.get("server"), r.get("username"), r.get("passwordSecretRef"))
                             for r in conf.get("registries") or []),
        "identities": sorted(k.lower() for k in (doc.get("identity", {}).get("userAssignedIdentities") or {})),
        "event": event_view(conf.get("eventTriggerConfig")),
    }


def event_view(cfg: dict | None) -> dict | None:
    """The scale settings of an Event job, reduced to what the limits and the drift check compare."""
    if cfg is None:
        return None
    scale = cfg.get("scale") or {}
    rules = []
    for r in scale.get("rules") or []:
        meta = r.get("metadata") or {}
        rules.append({"name": r.get("name"), "type": r.get("type"), "queue": meta.get("queueName"),
                      "account": meta.get("accountName"), "queue_length": str(meta.get("queueLength")),
                      "identity": (r.get("identity") or "").lower(), "has_auth": bool(r.get("auth"))})
    return {"max_executions": scale.get("maxExecutions"), "polling_s": scale.get("pollingInterval"),
            "min_executions": scale.get("minExecutions"), "rules": sorted(rules, key=lambda r: str(r["name"]))}


def _num(value: object) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------- C1, C2, C3
def check_job(rep: Report, rel: str, name: str, view: dict, limits: dict, live: bool) -> dict | None:
    """C1 and C2 for one job; returns its cron stats (None when it has no cron)."""
    jl = limits["jobs"].get(name)
    if jl is None:
        rep.fail("C2", rel, 1, f"{name} has no entry in limits.json jobs")
        return None
    stats = None
    if view["trigger"] != jl["trigger"]:
        rep.fail("C2", rel, 1, f"triggerType {view['trigger']!r} must be {jl['trigger']!r}")
    if view["trigger"] == "Schedule":
        if not view["cron"]:
            rep.fail("C1", rel, 1, "Schedule job has no cronExpression")
        else:
            stats = cron_stats(view["cron"])
            if stats["parked"]:
                rep.note(f"{name}: cron {view['cron']!r} is PARKED (never fires in a year)")
            else:
                if stats["per_day"] > jl["max_runs_per_day"]:
                    rep.fail("C1", rel, 1, f"cron {view['cron']!r} fires {stats['per_day']} times a day, "
                                           f"limit {jl['max_runs_per_day']}")
                if stats["min_gap_min"] < jl["min_interval_min"]:
                    rep.fail("C1", rel, 1, f"cron {view['cron']!r} runs {stats['min_gap_min']} minutes apart, "
                                           f"limit {jl['min_interval_min']}")
    check_event(rep, rel, view, jl)
    timeout = view["timeout"]
    if not isinstance(timeout, int) or timeout <= 0:
        rep.fail("C2", rel, 1, f"replicaTimeout {timeout!r} must be a positive number of seconds")
        timeout = None
    elif timeout > jl["max_replica_timeout_s"]:
        rep.fail("C2", rel, 1, f"replicaTimeout {timeout}s exceeds {jl['max_replica_timeout_s']}s")
    if timeout and stats and not stats["parked"] and stats["min_gap_min"] is not None \
            and timeout >= stats["min_gap_min"] * 60:
        rep.fail("C2", rel, 1, f"replicaTimeout {timeout}s is not shorter than the {stats['min_gap_min']}-minute "
                               "cron gap: executions could overlap")
    if view["cpu"] is None or view["cpu"] > jl["max_cpu"]:
        rep.fail("C2", rel, 1, f"cpu {view['cpu']} exceeds {jl['max_cpu']}")
    if view["memory_gi"] is None or view["memory_gi"] > jl["max_memory_gi"]:
        rep.fail("C2", rel, 1, f"memory {view['memory_gi']} GiB exceeds {jl['max_memory_gi']}")
    for key, want in (("parallelism", jl["parallelism"]), ("completion", jl["replica_completion_count"])):
        if view[key] != want:
            rep.fail("C2", rel, 1, f"{key} is {view[key]!r}, must be {want}")
    if view["retry"] is None or view["retry"] > jl["replica_retry_limit"]:
        rep.fail("C2", rel, 1, f"replicaRetryLimit {view['retry']!r} exceeds {jl['replica_retry_limit']}")
    env = view["env"]
    for var, cap in jl.get("max_env", {}).items():
        got = _num(env.get(var, {}).get("value"))
        if got is None:
            rep.fail("C2", rel, 1, f"env {var} must be set (a number, at most {cap})")
        elif got > cap:
            rep.fail("C2", rel, 1, f"env {var}={got:g} exceeds {cap}")
    et = _num(env.get("ENTRANT_TIMEOUT_S", {}).get("value"))
    if et is not None and timeout and et + 120 > timeout:
        rep.fail("C2", rel, 1, f"ENTRANT_TIMEOUT_S {et:g} + 120 s of git and commit time must fit replicaTimeout {timeout}")
    image = view["image"] or ""
    pinned = re.search(r"@sha256:[0-9a-f]{64}$", image) or re.search(r":sha-[0-9a-f]{40}$", image)
    if image == "IMAGE" and not live:
        pass                                            # placeholder, replaced by the deploy workflow
    elif not pinned or image.endswith(":latest"):
        rep.fail("C2", rel, 1, f"image {image!r} must be pinned by @sha256:<digest> (or :sha-<40 hex>), never :latest")
    elif limits.get("image_repository") and not image.startswith(limits["image_repository"] + (":" if ":sha-" in image else "@")):
        rep.fail("C2", rel, 1, f"image {image!r} is not from {limits['image_repository']}")
    allowed = set(jl.get("may_hold_secrets", []))
    for var, ref in env.items():
        if "secretRef" in ref:
            if ref["secretRef"] not in view["secrets"]:
                rep.fail("C2", rel, 1, f"env {var} refers to undefined secret {ref['secretRef']!r}")
            if var not in allowed:
                rep.fail("C2", rel, 1, f"env {var} is a secret this job may not hold (may_hold_secrets {sorted(allowed)})")
        elif SECRET_NAME.search(var) and var not in jl.get("plain_env_ok", []):
            rep.fail("C2", rel, 1, f"env {var} looks like a secret but is a plain value: use a Key Vault secretRef")
    if "entrant-profile" in view["secrets"] and "ENTRANT_PROFILE_JSON" not in allowed:
        rep.fail("C2", rel, 1, "secret entrant-profile is defined on a job that may not hold the profile")
    return stats


def check_event(rep: Report, rel: str, view: dict, jl: dict) -> None:
    """C2 for an Event job: one execution at a time, polled no faster than the limit, scaled only by the declared queue
    through the job's managed identity (no connection string or key in an `auth` block)."""
    ev, lim = view["event"], jl.get("event")
    if view["trigger"] != "Event":
        if ev is not None:
            rep.fail("C2", rel, 1, "eventTriggerConfig on a job that is not an Event job")
        return
    if ev is None or lim is None:
        rep.fail("C2", rel, 1, "an Event job needs eventTriggerConfig and an `event` block in its limits")
        return
    if not isinstance(ev["max_executions"], int) or not 1 <= ev["max_executions"] <= lim["max_executions"]:
        rep.fail("C2", rel, 1, f"maxExecutions {ev['max_executions']!r} must be 1 to {lim['max_executions']}")
    if ev["min_executions"] not in (None, 0):
        rep.fail("C2", rel, 1, f"minExecutions {ev['min_executions']!r} must be 0: nothing may run while the queue is empty")
    if not isinstance(ev["polling_s"], int) or ev["polling_s"] < lim["min_polling_interval_s"]:
        rep.fail("C2", rel, 1, f"pollingInterval {ev['polling_s']!r} is below {lim['min_polling_interval_s']} s")
    if not ev["rules"]:
        rep.fail("C2", rel, 1, "an Event job needs a scale rule")
    for r in ev["rules"]:
        if r["type"] not in lim["rule_types"]:
            rep.fail("C2", rel, 1, f"scale rule {r['name']!r} type {r['type']!r} is not one of {lim['rule_types']}")
        if r["queue"] not in lim["queues"]:
            rep.fail("C2", rel, 1, f"scale rule {r['name']!r} watches queue {r['queue']!r}, allowed {lim['queues']}")
        if r["account"] not in lim["accounts"]:
            rep.fail("C2", rel, 1, f"scale rule {r['name']!r} watches storage account {r['account']!r}, allowed {lim['accounts']}")
        if not r["identity"] or r["identity"] not in view["identities"]:
            rep.fail("C2", rel, 1, f"scale rule {r['name']!r} must authenticate with the job's managed identity")
        if r["has_auth"]:
            rep.fail("C2", rel, 1, f"scale rule {r['name']!r} has an auth block: use the managed identity, not a secret")


def job_cost(view: dict, stats: dict | None, jl: dict, prices: dict) -> dict:
    rate = view["cpu"] * prices["aca_vcpu_s"] + view["memory_gi"] * prices["aca_gib_s"]
    if view["trigger"] == "Schedule":
        runs = 0 if stats is None else stats["per_30d"]
    else:
        runs = jl["max_runs_per_day"] * 30
    timeout = view["timeout"] or 0
    billed = min(jl.get("budget_s_per_run", timeout), timeout)
    return {"runs_per_30d": runs, "budget_usd": round(runs * billed * rate, 2),
            "ceiling_usd": round(runs * timeout * rate, 2)}


def check_costs(rep: Report, label: str, costs: dict, limits: dict) -> None:
    budget = limits["budget_usd_month"]
    total = round(sum(c["budget_usd"] for c in costs.values()), 2)
    ceiling = round(sum(c["ceiling_usd"] for c in costs.values()), 2)
    rep.costs[label] = {"jobs": costs, "total_usd": total, "ceiling_usd": ceiling}
    if total > budget["total"]:
        rep.fail("C3", label, 1, f"worst-case spend USD {total}/month exceeds the budget of USD {budget['total']}")
    if ceiling > budget["hard_ceiling_all_timeouts"]:
        rep.fail("C3", label, 1, f"if every run used its full timeout the spend would be USD {ceiling}/month, "
                                 f"over the ceiling of USD {budget['hard_ceiling_all_timeouts']}")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc}") from None


def check_jobs(rep: Report, root: Path, jobs_dir: Path, limits: dict, live: bool) -> dict[str, dict]:
    views: dict[str, dict] = {}
    costs: dict[str, dict] = {}
    for name, jl in limits["jobs"].items():
        path = jobs_dir / f"{name}.json"
        rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        if not path.exists():
            rep.fail("C2", rel, 1, f"{name} is in limits.json but its {'live export' if live else 'file'} is missing")
            continue
        view = job_view(load_json(path))
        if view["name"] != name:
            rep.fail("C2", rel, 1, f"file names job {view['name']!r}, expected {name!r}")
        views[name] = view
        stats = check_job(rep, rel, name, view, limits, live)
        if view["cpu"] is not None and view["memory_gi"] is not None:
            costs[name] = job_cost(view, stats, jl, limits["prices"])
    for path in sorted(jobs_dir.glob("*.json")):
        if path.stem not in limits["jobs"]:
            rep.fail("C2", str(path), 1, f"{path.stem} is not listed in limits.json jobs")
    check_costs(rep, "live" if live else "azure/jobs", costs, limits)
    return views


def check_drift(rep: Report, desired: dict[str, dict], live: dict[str, dict], expected_image: str | None) -> None:
    for name, want in desired.items():
        got = live.get(name)
        if got is None:
            continue
        for key in ("trigger", "cron", "timeout", "retry", "parallelism", "completion", "cpu", "memory_gi",
                    "args", "env", "secret_urls", "registries", "identities", "event"):
            if want[key] != got[key]:
                rep.fail("DRIFT", f"live/{name}.json", 1, f"{key} differs from azure/jobs/{name}.json: "
                                                         f"live {got[key]!r}, desired {want[key]!r}")
        if expected_image and got["image"] != expected_image:
            rep.fail("DRIFT", f"live/{name}.json", 1, f"image is {got['image']!r}, expected {expected_image!r}")
        elif want["image"] != "IMAGE" and want["image"] != got["image"]:
            rep.fail("DRIFT", f"live/{name}.json", 1, f"image is {got['image']!r}, file says {want['image']!r}")


# ------------------------------------------------------------------------------------------------------- C6
def check_inventory(rep: Report, root: Path, limits: dict, path: Path | None) -> None:
    path = path or root / "azure" / "inventory.json"
    if not path.exists():
        rep.note("C6 skipped: no azure/inventory.json")
        return
    inventory = load_json(path)
    items = inventory if isinstance(inventory, list) else inventory.get("resources", [])
    allowed = set(limits.get("allowed_resource_types", []))
    for item in items:
        kind = item.get("type", "")
        if kind not in allowed:
            rep.fail("C6", path, 1, f"resource {item.get('name')!r} has type {kind} which is not in allowed_resource_types")
        if kind.lower() == "microsoft.operationalinsights/workspaces":
            cap = (item.get("properties", {}).get("workspaceCapping") or {}).get("dailyQuotaGb")
            if cap is None or float(cap) > limits.get("log_analytics_max_daily_gb", 0.5) or float(cap) <= 0:
                rep.fail("C6", path, 1, f"Log Analytics workspace {item.get('name')!r} needs dailyQuotaGb "
                                        f"<= {limits.get('log_analytics_max_daily_gb', 0.5)}")


# ------------------------------------------------------------------------------------------------------- C7
def code_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for d in CODE_DIRS:
        base = root / d
        if base.is_dir():
            out += [p for p in sorted(base.rglob("*")) if p.suffix in suffixes and "__pycache__" not in p.parts
                    and "node_modules" not in p.parts]
    return out


def _has_timeout(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "timeout":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def _callee(call: ast.Call) -> tuple[str, str]:
    f = call.func
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else (f.value.attr if isinstance(f.value, ast.Attribute) else "")
        return base, f.attr
    if isinstance(f, ast.Name):
        return "", f.id
    return "", ""


def _range_count(node: ast.For) -> int | None:
    it = node.iter
    if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"):
        return None
    nums = [a.value for a in it.args if isinstance(a, ast.Constant) and isinstance(a.value, int)]
    if len(nums) != len(it.args):
        return None
    if len(nums) == 1:
        return nums[0]
    if len(nums) >= 2:
        return max(0, nums[1] - nums[0])
    return None


def _title_literals(tree: ast.AST):
    def first_text(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
            return str(node.values[0].value)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "title" and first_text(v) is not None:
                    yield node.lineno, first_text(v)
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "title" and first_text(kw.value) is not None:
                    yield node.lineno, first_text(kw.value)


def scan_python(rep: Report, root: Path, limits: dict) -> int:
    """C7 a-e over the Python files; returns the unbounded-call count."""
    unbounded = 0
    code = limits.get("code", {})
    for path in code_files(root, (".py",)):
        rel = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(), filename=str(rel))
        except SyntaxError as exc:
            raise ConfigError(f"{rel}: {exc}") from None
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def enclosing_function(node: ast.AST) -> ast.AST:
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return node
            return tree

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                base, name = _callee(node)
                subject = (base == "subprocess" and name in UNBOUNDED_CALLS) or name == "urlopen" \
                    or (base == "" and name in UNBOUNDED_NAMES)
                if subject and not _has_timeout(node):
                    unbounded += 1
                    rep.note(f"unbounded {name}() at {rel}:{node.lineno}")
                if base == "time" and name == "sleep" and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, (int, float)) and node.args[0].value > 60:
                    rep.fail("C7", rel, node.lineno, f"time.sleep({node.args[0].value}) is longer than 60 s")
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value in (True, 1):
                body = [n for stmt in node.body for n in ast.walk(stmt)]
                exits = any(isinstance(n, (ast.Break, ast.Return)) for n in body)
                func_src = ast.unparse(enclosing_function(node))
                bounded = re.search(r"deadline|monotonic|time\.time\(\)|attempt|\+= 1", func_src)
                if not exits:
                    rep.fail("C7", rel, node.lineno, "`while True` with no break or return")
                elif not bounded:
                    rep.fail("C7", rel, node.lineno, "`while True` with no counter or deadline")
                for n in body:
                    if isinstance(n, ast.Call) and _callee(n) == ("time", "sleep") and not bounded:
                        rep.fail("C7", rel, n.lineno, "sleep inside an unbounded loop")
            if isinstance(node, ast.For):
                n_iter = _range_count(node)
                text = ast.unparse(node)
                retries = n_iter is not None and re.search(r"urlopen|requests\.|['\"]push['\"]", text)
                if retries and n_iter > code.get("max_retry_loop", 5):
                    rep.fail("C7", rel, node.lineno, f"retry loop runs {n_iter} times, limit {code.get('max_retry_loop', 5)}")
            if isinstance(node, ast.Assign) and parents.get(node) is tree and rel.as_posix() == "azure/runner.py":
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                        cap = {"MAX_ISSUE_PAGES": code.get("max_issue_pages"),
                               "ENTRANT_DEFAULT_CONCURRENCY": code.get("runner_entrant_concurrency"),
                               "ENTRANT_DEFAULT_TIMEOUT_S": code.get("runner_entrant_timeout_s"),
                               "COMPS_MAX_NEW": code.get("comps_max_new"),
                               "MAX_ACTIONS_PER_RUN": code.get("max_actions_per_run"),
                               "ACTIONS_MAX_DEQUEUE": code.get("actions_max_dequeue")}.get(target.id)
                        if cap is not None and node.value.value > cap:
                            rep.fail("C7", rel, node.lineno, f"{target.id} = {node.value.value} exceeds {cap}")
        for line, title in _title_literals(tree):
            if re.match(r"\s*(reenter|remove)", title, re.I):
                rep.fail("C8", rel, line, f"issue title {title!r} would trigger the reenter/remove workflows")
        if rel.as_posix() == "azure/runner.py":
            capped = any(isinstance(n, ast.List) and {"workers.comps", "--max"} <= {
                e.value for e in n.elts if isinstance(e, ast.Constant)} for n in ast.walk(tree))
            if not capped:
                rep.fail("C7", rel, 1, "workers.comps must be run with --max")
    return unbounded


def scan_other(rep: Report, root: Path, limits: dict) -> None:
    code = limits.get("code", {})
    for path in code_files(root, (".mjs", ".sh")):
        rel = path.relative_to(root)
        lines = path.read_text().splitlines()
        for no, line in enumerate(lines, 1):
            if line.strip().startswith(("//", "#")):
                continue
            if path.suffix == ".mjs":
                if re.search(r"while\s*\(\s*(true|1)\s*\)", line):
                    block = "\n".join(lines[no:no + 40])
                    if not re.search(r"\b(break|return)\b", block):
                        rep.fail("C7", rel, no, "`while (true)` with no break or return")
                if re.search(r"\b(execSync|execFileSync|spawnSync)\(", line) and "timeout" not in line:
                    rep.fail("C7", rel, no, "child process without a timeout")
            if path.suffix == ".sh":
                m = re.search(r"\bsleep\s+(\d+)\b", line)
                if m and int(m.group(1)) > 60:
                    rep.fail("C7", rel, no, f"sleep {m.group(1)} is longer than 60 s")
    entrant = root / "workers" / "entrant.mjs"
    if entrant.exists():
        text = entrant.read_text()
        for label, pattern, cap in (
            ("entrant default max", r"ENTRANT_MAX\s*\|\|\s*(\d+)", code.get("entrant_default_max")),
            ("entrant default concurrency", r"ENTRANT_CONCURRENCY\s*\|\|\s*(\d+)", code.get("entrant_default_concurrency")),
        ):
            m = re.search(pattern, text)
            if cap is not None:
                if not m:
                    rep.fail("C7", "workers/entrant.mjs", 1, f"{label}: expected a default in `{pattern}`")
                elif int(m.group(1)) > cap:
                    rep.fail("C7", "workers/entrant.mjs", text[:m.start()].count("\n") + 1,
                             f"{label} is {m.group(1)}, limit {cap}")


def scan_secrets(rep: Report, root: Path) -> None:
    for sub in ("azure", "workers", "tools", ".github"):
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.stat().st_size > 2_000_000:
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for label, pattern in SECRET_PATTERNS.items():
                for m in pattern.finditer(text):
                    rep.fail("C7", path.relative_to(root), text[:m.start()].count("\n") + 1,
                             f"looks like a {label}: keep secrets out of the repository")


# ------------------------------------------------------------------------------------------------------- C8
def _top_blocks(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Top-level key -> (first line, last line) of its block (0-based, inclusive)."""
    keys = [(i, m.group(1)) for i, l in enumerate(lines) if (m := re.match(r"([A-Za-z_\"'][^\s:]*):", l))]
    out = {}
    for n, (i, key) in enumerate(keys):
        end = keys[n + 1][0] - 1 if n + 1 < len(keys) else len(lines) - 1
        out[key.strip("\"'")] = (i, end)
    return out


def check_workflows(rep: Report, root: Path, limits: dict) -> None:
    wl = limits.get("workflows", {})
    ratchet = limits.get("ratchet", {})
    total_fires = 0
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        rel = path.relative_to(root)
        lines = path.read_text().splitlines()
        live_lines = [(i + 1, l) for i, l in enumerate(lines) if not l.lstrip().startswith("#")]
        text = "\n".join(l for _, l in live_lines)
        blocks = _top_blocks(lines)
        # jobs and their timeouts
        if "jobs" in blocks:
            start, end = blocks["jobs"]
            job_starts = [(i, re.match(r"  (\S+):\s*$", lines[i]).group(1)) for i in range(start + 1, end + 1)
                          if re.match(r"  (\S+):\s*$", lines[i])]
            for n, (i, job) in enumerate(job_starts):
                stop = job_starts[n + 1][0] if n + 1 < len(job_starts) else end + 1
                body = lines[i + 1:stop]
                if any(re.match(r"    uses:", l) for l in body):
                    continue                                     # a reusable-workflow call has no timeout of its own
                found = [(int(m.group(1)), i + 2 + k) for k, l in enumerate(body) if (m := re.match(r"    timeout-minutes:\s*(\d+)", l))]
                if not found:
                    rep.fail("C8", rel, i + 1, f"job {job} has no timeout-minutes")
                elif found[0][0] > wl.get("max_timeout_minutes", 300):
                    rep.fail("C8", rel, found[0][1], f"job {job} timeout-minutes {found[0][0]} exceeds {wl.get('max_timeout_minutes', 300)}")
        pushing = re.search(r"\bgit push\b|commit_entries\.sh", text) is not None
        if pushing and path.name not in wl.get("concurrency_exempt", []):
            conc = blocks.get("concurrency")
            block = "\n".join(lines[conc[0]:conc[1] + 1]) if conc else ""
            if not conc or not re.search(r"cancel-in-progress:\s*false", block):
                rep.fail("C8", rel, (conc[0] + 1) if conc else 1,
                         "a workflow that pushes needs `concurrency:` with `cancel-in-progress: false`")
        for no, line in live_lines:
            for m in re.finditer(r"gh workflow run (\S+)", line):
                target = m.group(1).strip("\"'")
                target = target if target.endswith((".yml", ".yaml")) else target + ".yml"
                if target == path.name and path.name not in ratchet.get("self_dispatch_workflows", []):
                    rep.fail("C8", rel, no, f"{path.name} starts itself with `gh workflow run`")
            m = re.search(r"title\s+[\"']((?:reenter|remove)[^\"']*)", line, re.I)
            if m and "--title" in line:
                rep.fail("C8", rel, no, f"issue title {m.group(1)!r} would trigger the reenter/remove workflows")
        on = blocks.get("on") or blocks.get("true")
        on_text = "\n".join(lines[on[0]:on[1] + 1]) if on else ""
        if re.search(r"^\s+workflow_run:", on_text, re.M):
            allowed = ratchet.get("workflow_run_allowed", {}).get(path.name)
            m = re.search(r"workflows:\s*\[([^\]]*)\]", on_text)
            named = {w.strip().strip("\"'") for w in m.group(1).split(",")} if m else set()
            if allowed is None or not named <= set(allowed):
                rep.fail("C8", rel, 1, f"workflow_run on {sorted(named)} is not allowed for {path.name}")
        push_block = re.search(r"^  push:\s*\n((?:    .*\n?|\s*\n)*)", on_text, re.M)
        if push_block is not None and pushing and "paths:" not in push_block.group(1):
            rep.fail("C8", rel, 1, "on: push without `paths:` in a workflow that pushes can loop")
        if re.search(r"^\s+issues:", on_text, re.M):
            if "github.event.issue.user.login == github.repository_owner" not in text \
                    or not re.search(r"startsWith\(github\.event\.issue\.title", text):
                rep.fail("C8", rel, 1, "an issues workflow needs the repository-owner check and a startsWith title guard")
        for no, line in live_lines:
            m = re.search(r"cron:\s*[\"']([^\"']+)[\"']", line)
            if m:
                total_fires += cron_stats(m.group(1))["per_day"]
    if total_fires > wl.get("max_cron_fires_per_day", 300):
        rep.fail("C8", ".github/workflows", 1, f"workflow crons fire {total_fires} times a day, limit {wl.get('max_cron_fires_per_day', 300)}")


# ------------------------------------------------------------------------------------------------------ C12
SITE_API_DIR = "azure/site-api"
API_PREFIX = "/api/"


def _module_literals(path: Path) -> dict[str, object]:
    """Module-level NAME = <literal> assignments, read without importing (so no module code runs)."""
    out: dict[str, object] = {}
    for node in ast.parse(path.read_text(), filename=str(path)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass
    return out


def _route_decorators(tree: ast.AST) -> list[tuple[int, str, list[str]]]:
    """(line, route, methods) of every `@<app>.route(route=..., methods=[...])`."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "route":
                    kw = {k.arg: k.value for k in dec.keywords}
                    route = ast.literal_eval(kw["route"]) if "route" in kw else ""
                    methods = ast.literal_eval(kw["methods"]) if "methods" in kw else []
                    found.append((dec.lineno, str(route), [str(m).upper() for m in methods]))
    return found


def check_site_api(rep: Report, root: Path, limits: dict) -> None:
    sl = limits.get("site_api")
    api = root / SITE_API_DIR
    if sl is None:
        if api.is_dir():
            rep.fail("C12", SITE_API_DIR, 1, "the API exists but limits.json has no `site_api` block")
        return
    for name in sl.get("retired_workflows", []):
        if (root / ".github" / "workflows" / name).exists():
            rep.fail("C12", f".github/workflows/{name}", 1, "retired: the site buttons use the API, not GitHub issues")
    # the Static Web App configuration the site build writes (workers/site.py SWA_CONFIG)
    site_py = root / "workers" / "site.py"
    config = _module_literals(site_py).get("SWA_CONFIG") if site_py.exists() else None
    if not isinstance(config, dict):
        rep.fail("C12", "workers/site.py", 1, "SWA_CONFIG (the staticwebapp.config.json the build writes) is missing")
        config = {}
    role = sl["required_role"]
    api_routes = [r for r in config.get("routes", []) if str(r.get("route", "")).startswith(API_PREFIX)]
    for r in api_routes:
        if r.get("allowedRoles") != [role]:
            rep.fail("C12", "workers/site.py", 1, f"route {r.get('route')} allowedRoles must be exactly {[role]}, "
                                                  f"got {r.get('allowedRoles')!r}")
    if not any(r.get("route") == API_PREFIX + "*" for r in api_routes):
        rep.fail("C12", "workers/site.py", 1, f"SWA_CONFIG has no {API_PREFIX}* route requiring the {role} role")
    if (config.get("platform") or {}).get("apiRuntime") != sl["api_runtime"]:
        rep.fail("C12", "workers/site.py", 1, f"platform.apiRuntime must be {sl['api_runtime']!r}")
    if not api.is_dir():
        rep.fail("C12", SITE_API_DIR, 1, "the API folder is missing")
        return
    # routes and methods the function app declares
    app_py = api / "function_app.py"
    if app_py.exists():
        for line, route, methods in _route_decorators(ast.parse(app_py.read_text(), filename=str(app_py))):
            if API_PREFIX + route not in sl["allowed_routes"]:
                rep.fail("C12", f"{SITE_API_DIR}/function_app.py", line, f"route {API_PREFIX + route} is not in allowed_routes "
                                                                         f"{sl['allowed_routes']}")
            if not methods or not set(methods) <= set(sl["allowed_methods"]):
                rep.fail("C12", f"{SITE_API_DIR}/function_app.py", line, f"methods {methods} must be within {sl['allowed_methods']}")
    else:
        rep.fail("C12", SITE_API_DIR, 1, "function_app.py is missing")
    # caps in the handler and in the worker that re-validates the message
    for rel in (f"{SITE_API_DIR}/lotto_actions.py", "workers/actions.py"):
        path = root / rel
        if not path.exists():
            rep.fail("C12", rel, 1, "file is missing")
            continue
        lit = _module_literals(path)
        for const, key in (("MAX_IDS", "max_ids"), ("MAX_ANSWER_CHARS", "max_answer_chars")):
            if not isinstance(lit.get(const), int) or not 0 < lit[const] <= sl[key]:
                rep.fail("C12", rel, 1, f"{const} must be a number from 1 to {sl[key]}, got {lit.get(const)!r}")
        if not isinstance(lit.get("KINDS"), tuple) or not set(lit["KINDS"]) <= set(sl["allowed_kinds"]):
            rep.fail("C12", rel, 1, f"KINDS must be within {sl['allowed_kinds']}")
        if rel.endswith("lotto_actions.py"):
            size = lit.get("MAX_BODY_BYTES")
            if not isinstance(size, int) or not 0 < size <= sl["max_body_bytes"]:
                rep.fail("C12", rel, 1, f"MAX_BODY_BYTES must be a number from 1 to {sl['max_body_bytes']}, got {size!r}")
            handler = next((n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "handle"), None)
            compared = handler is not None and any(
                isinstance(c, ast.Compare) and any(isinstance(n, ast.Name) and n.id == "MAX_BODY_BYTES" for n in ast.walk(c))
                for c in ast.walk(handler))
            if not compared:
                rep.fail("C12", rel, 1, "handle() does not enforce MAX_BODY_BYTES (no comparison against it)")


# ------------------------------------------------------------------------------------------------------ C10
LOOSER_WHEN_SMALLER = ("min_",)


def _loosened(old: object, new: object, path: str, out: list[str], smaller_is_looser: bool = False) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in new:
            if key.startswith("_"):
                continue
            if key not in old:
                out.append(f"{path}/{key}: new entry")
            else:
                _loosened(old[key], new[key], f"{path}/{key}", out,
                          smaller_is_looser or key.startswith(LOOSER_WHEN_SMALLER) or key == "prices")
        for key in old:
            if key not in new and not key.startswith("_"):
                out.append(f"{path}/{key}: limit removed")
    elif isinstance(old, list) and isinstance(new, list):
        for item in new:
            if item not in old:
                out.append(f"{path}: gained {item!r}")
    elif isinstance(old, (int, float)) and isinstance(new, (int, float)) and not isinstance(old, bool):
        if (new < old) if smaller_is_looser else (new > old):
            out.append(f"{path}: {old} -> {new}")


def check_ratchet(rep: Report, limits: dict, base: dict | None) -> None:
    if base is None:
        rep.note("C10 skipped: no base limits to compare with")
        return
    out: list[str] = []
    _loosened(base, limits, "", out)
    for item in out:
        if os.environ.get("LIMITS_APPROVED") == "1":
            rep.note(f"C10 loosened (approved): {item}")
        else:
            rep.fail("C10", "azure/limits.json", 1, f"loosened against the base: {item}")
    if limits.get("ratchet", {}).get("unbounded_subprocess") is None:
        rep.fail("C10", "azure/limits.json", 1, "ratchet.unbounded_subprocess is missing")


def git_show(root: Path, ref: str) -> dict | None:
    try:
        shown = subprocess.run(["git", "show", f"{ref}:azure/limits.json"], cwd=root, capture_output=True,
                               text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if shown.returncode != 0:
        return None
    try:
        return json.loads(shown.stdout)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------- main
def run_checks(limits_path: Path, root: Path, live_dir: Path | None = None, base: dict | None = None,
               inventory: Path | None = None, expected_image: str | None = None) -> Report:
    rep = Report()
    limits = load_json(limits_path)
    for key in ("prices", "budget_usd_month", "jobs", "ratchet"):
        if key not in limits:
            raise ConfigError(f"{limits_path}: missing {key!r}")
    desired = check_jobs(rep, root, root / "azure" / "jobs", limits, live=False)
    if live_dir is not None:
        live = check_jobs(rep, root, live_dir, limits, live=True)
        check_drift(rep, desired, live, expected_image)
    rep.note("C4/C5 skipped: this repository has no function app")
    check_inventory(rep, root, limits, inventory)
    unbounded = scan_python(rep, root, limits)
    scan_other(rep, root, limits)
    scan_secrets(rep, root)
    cap = limits["ratchet"].get("unbounded_subprocess", 0)
    if unbounded > cap:
        rep.fail("C7", "azure/ workers/ tools/", 1, f"{unbounded} subprocess/network calls have no timeout; "
                                                     f"the ratchet allows {cap} and may only fall")
    elif unbounded < cap:
        rep.note(f"ratchet can be lowered: unbounded_subprocess {cap} -> {unbounded}")
    check_workflows(rep, root, limits)
    check_site_api(rep, root, limits)
    check_ratchet(rep, limits, base)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limits", required=True, type=Path)
    ap.add_argument("--live", type=Path, help="directory of `az containerapp job show` exports, one <job>.json each")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--base", default="origin/main", help="git ref whose azure/limits.json the ratchet compares with")
    ap.add_argument("--base-file", type=Path, help="a limits file to compare with instead of a git ref")
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--image", help="the image every live job must run (repo@sha256:digest)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    limits_path = a.limits if a.limits.exists() else root / a.limits
    try:
        base = load_json(a.base_file) if a.base_file else git_show(root, a.base)
        rep = run_checks(limits_path, root, a.live, base, a.inventory, a.image)
    except (ConfigError, KeyError) as exc:
        print(f"CONFIG ERROR {exc!r}" if isinstance(exc, KeyError) else f"CONFIG ERROR {exc}", file=sys.stderr)
        return 2
    rep.violations.sort()
    if a.json:
        print(json.dumps({"violations": [dict(zip(("rule", "path", "line", "message"), v)) for v in rep.violations],
                          "notes": rep.notes, "costs": rep.costs}, indent=2))
    else:
        for rule, path, line, message in rep.violations:
            print(f"{rule} {path}:{line} {message}")
        for label, c in rep.costs.items():
            print(f"cost[{label}] worst-case USD {c['total_usd']}/month "
                  f"(all runs at full timeout: USD {c['ceiling_usd']}) " +
                  ", ".join(f"{n} {v['budget_usd']}" for n, v in sorted(c["jobs"].items())))
        for note in rep.notes:
            if not note.startswith("unbounded "):
                print(f"note {note}")
        print(f"cost_guard: {'FAIL' if rep.violations else 'ok'} ({len(rep.violations)} violations)")
    return 1 if rep.violations else 0


if __name__ == "__main__":
    sys.exit(main())
