"""Offline tests for tools/cost_guard.py: the repository as delivered passes, and each rule has a failing fixture."""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("cost_guard", REPO / "tools" / "cost_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

DIGEST = "ghcr.io/jesseallomes/lotto-azure-runner@sha256:" + "a" * 64


class Fixture(unittest.TestCase):
    """A scratch copy of the parts of the repository the guard reads, edited per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("azure", "workers", "tools", ".github"):
            shutil.copytree(REPO / name, self.root / name, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        self.limits = self.root / "azure" / "limits.json"

    def check(self, **kw):
        return guard.run_checks(self.limits, self.root, **kw)

    def rules(self, **kw):
        return {v[0] for v in self.check(**kw).violations}

    def messages(self, **kw):
        return [v[3] for v in self.check(**kw).violations]

    def edit_json(self, path, fn):
        doc = json.loads(path.read_text())
        fn(doc)
        path.write_text(json.dumps(doc, indent=2))

    def edit_job(self, name, fn):
        self.edit_json(self.root / "azure" / "jobs" / f"{name}.json", fn)

    def edit_limits(self, fn):
        self.edit_json(self.limits, fn)

    @staticmethod
    def container(doc):
        return doc["properties"]["template"]["containers"][0]

    @staticmethod
    def conf(doc):
        return doc["properties"]["configuration"]

    def set_env(self, doc, name, value=None, secret=None):
        env = [e for e in self.container(doc)["env"] if e["name"] != name]
        if value is not None:
            env.append({"name": name, "value": value})
        if secret is not None:
            env.append({"name": name, "secretRef": secret})
        self.container(doc)["env"] = env

    def edit_file(self, rel, fn):
        path = self.root / rel
        path.write_text(fn(path.read_text()))

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def make_live(self, mutate=None):
        live = self.root / "live"
        live.mkdir(exist_ok=True)
        for path in (self.root / "azure" / "jobs").glob("*.json"):
            doc = json.loads(path.read_text().replace('"IMAGE"', json.dumps(DIGEST)))
            if mutate:
                mutate(path.stem, doc)
            (live / path.name).write_text(json.dumps(doc))
        return live


class AsDelivered(Fixture):
    def test_repository_passes(self):
        rep = self.check()
        self.assertEqual(rep.violations, [])
        self.assertLessEqual(rep.costs["azure/jobs"]["total_usd"], 15)

    def test_real_repo_cli_passes(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = guard.main(["--limits", str(REPO / "azure" / "limits.json"), "--base", "no-such-ref"])
        self.assertEqual(code, 0, out.getvalue())

    def test_live_azure_job_has_no_scheduled_github_twin(self):
        # An Azure job that is switched on and a scheduled GitHub workflow doing the same work would
        # enter every competition twice and race each other's pushes.
        for path in (REPO / "azure" / "jobs").glob("*.json"):
            env = guard.job_view(json.loads(path.read_text()))["env"]
            if env["AZURE_JOBS_DISABLED"] != {"value": "0"}:
                continue
            twin = REPO / ".github" / "workflows" / (path.stem.removeprefix("lotto-") + ".yml")
            if twin.exists():
                text = twin.read_text()
                self.assertNotIn("schedule:", text, twin.name)
                self.assertIn("github.event.inputs.manual == 'yes'", text, twin.name)

    def test_profile_only_where_allowed(self):
        for path in (REPO / "azure" / "jobs").glob("*.json"):
            view = guard.job_view(json.loads(path.read_text()))
            holds = "ENTRANT_PROFILE_JSON" in view["env"]
            self.assertEqual(holds, path.stem in ("lotto-entries", "lotto-reenter", "lotto-comps"), path.name)


class Cron(unittest.TestCase):
    def test_parked_cron_runs_nothing(self):
        self.assertTrue(guard.cron_stats("0 0 29 2 *")["parked"])

    def test_entries_cron_counts(self):
        s = guard.cron_stats("5,10,15,20,25 * * * *")
        self.assertEqual((s["per_day"], s["min_gap_min"], s["per_30d"]), (120, 5, 3600))

    def test_daily_cron(self):
        s = guard.cron_stats("23 12 * * *")
        self.assertEqual((s["per_day"], s["min_gap_min"], s["per_30d"]), (1, 1440, 30))

    def test_steps_ranges_and_weekdays(self):
        self.assertEqual(guard.cron_stats("*/15 9-17 * * 1-5")["per_day"], 36)
        self.assertEqual(guard.cron_stats("0 0 1 * *")["per_30d"], 2)    # a 30-day window can hold two 1sts
        self.assertEqual(guard.cron_stats("0 */6 * * *")["min_gap_min"], 360)

    def test_unsupported_syntax_is_a_config_error(self):
        for bad in ("@daily", "0 0 * * MON", "0 0 L * *", "* * * *", "61 * * * *", "0/0 * * * *", "0 0 ? * *"):
            with self.assertRaises(guard.ConfigError, msg=bad):
                guard.cron_stats(bad)


class C1(Fixture):
    def test_entries_every_minute(self):
        self.edit_job("lotto-entries", lambda d: self.conf(d)["scheduleTriggerConfig"].update(cronExpression="* * * * *"))
        msgs = self.messages()
        self.assertTrue(any("1440 times a day" in m for m in msgs), msgs)
        self.assertTrue(any("1 minutes apart" in m for m in msgs), msgs)

    def test_draws_hourly(self):
        self.edit_job("lotto-draws", lambda d: self.conf(d)["scheduleTriggerConfig"].update(cronExpression="23 * * * *"))
        self.assertIn("C1", self.rules())

    def test_gap_below_limit_even_when_runs_a_day_are_fine(self):
        self.edit_limits(lambda d: d["jobs"]["lotto-entries"].update(min_interval_min=10))
        self.assertIn("C1", self.rules())

    def test_schedule_without_cron(self):
        self.edit_job("lotto-draws", lambda d: self.conf(d).pop("scheduleTriggerConfig"))
        self.assertIn("C1", self.rules())

    def test_unsupported_cron_is_exit_2(self):
        self.edit_job("lotto-draws", lambda d: self.conf(d)["scheduleTriggerConfig"].update(cronExpression="@daily"))
        err = io.StringIO()
        with redirect_stderr(err):
            code = guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base", "none"])
        self.assertEqual(code, 2)
        self.assertIn("CONFIG ERROR", err.getvalue())


class C2(Fixture):
    def assert_fails(self, name, fn, text=None):
        self.edit_job(name, fn)
        msgs = self.messages()
        self.assertIn("C2", self.rules())
        if text:
            self.assertTrue(any(text in m for m in msgs), msgs)

    def test_event_trigger(self):
        self.assert_fails("lotto-reenter", lambda d: self.conf(d).update(triggerType="Event"), "triggerType")

    def test_timeout_over_limit(self):
        self.assert_fails("lotto-draws", lambda d: self.conf(d).update(replicaTimeout=7200), "exceeds 1800")

    def test_timeout_must_be_shorter_than_the_cron_gap(self):
        self.edit_limits(lambda d: d["jobs"]["lotto-entries"].update(max_replica_timeout_s=900))
        self.assert_fails("lotto-entries", lambda d: self.conf(d).update(replicaTimeout=420), "overlap")

    def test_entrant_timeout_needs_headroom(self):
        self.edit_limits(lambda d: d["jobs"]["lotto-entries"]["max_env"].update(ENTRANT_TIMEOUT_S=420))
        self.assert_fails("lotto-entries", lambda d: self.set_env(d, "ENTRANT_TIMEOUT_S", "200"), "120")

    def test_cpu_and_memory(self):
        self.assert_fails("lotto-draws", lambda d: self.container(d)["resources"].update(cpu=1.0), "cpu")
        self.assert_fails("lotto-draws", lambda d: self.container(d)["resources"].update(memory="2Gi"), "memory")

    def test_parallelism_completion_retry(self):
        self.assert_fails("lotto-draws", lambda d: self.conf(d)["scheduleTriggerConfig"].update(parallelism=2), "parallelism")
        self.assert_fails("lotto-draws", lambda d: self.conf(d)["scheduleTriggerConfig"].update(replicaCompletionCount=3), "completion")
        self.assert_fails("lotto-draws", lambda d: self.conf(d).update(replicaRetryLimit=1), "replicaRetryLimit")

    def test_env_caps_and_presence(self):
        self.assert_fails("lotto-entries", lambda d: self.set_env(d, "ENTRANT_CONCURRENCY", "6"), "ENTRANT_CONCURRENCY=6")
        self.assert_fails("lotto-reenter", lambda d: self.set_env(d, "ENTRANT_CONCURRENCY"), "must be set")

    def test_image_must_be_pinned(self):
        self.assert_fails("lotto-draws", lambda d: self.container(d).update(image="ghcr.io/jesseallomes/lotto-azure-runner:latest"), "pinned")
        self.assert_fails("lotto-draws", lambda d: self.container(d).update(image="ghcr.io/jesseallomes/lotto-azure-runner"), "pinned")

    def test_image_from_another_repository(self):
        self.assert_fails("lotto-draws", lambda d: self.container(d).update(image="ghcr.io/someone/else@sha256:" + "b" * 64), "not from")

    def test_pinned_digest_is_accepted(self):
        self.edit_job("lotto-draws", lambda d: self.container(d).update(image=DIGEST))
        self.assertEqual(self.rules(), set())

    def test_profile_secret_on_a_job_that_may_not_hold_it(self):
        def add(d):
            self.conf(d)["secrets"].append({"name": "entrant-profile", "keyVaultUrl": "https://kv/x", "identity": "i"})
            self.set_env(d, "ENTRANT_PROFILE_JSON", secret="entrant-profile")
        self.assert_fails("lotto-draws", add, "may not hold")

    def test_secret_as_plain_value(self):
        self.assert_fails("lotto-draws", lambda d: self.set_env(d, "GITHUB_TOKEN", value="abc"), "plain value")

    def test_secret_ref_must_exist(self):
        self.assert_fails("lotto-draws", lambda d: self.set_env(d, "GITHUB_TOKEN", secret="nope"), "undefined secret")

    def test_job_missing_from_limits_or_files(self):
        self.edit_limits(lambda d: d["jobs"].pop("lotto-reenter"))
        self.assertTrue(any("not listed" in m for m in self.messages()))
        (self.root / "azure" / "jobs" / "lotto-draws.json").unlink()
        self.assertTrue(any("is missing" in m for m in self.messages()))


class C3(Fixture):
    def test_cost_over_budget(self):
        self.edit_limits(lambda d: d["jobs"]["lotto-entries"].pop("budget_s_per_run"))
        rep = self.check()
        self.assertIn("C3", {v[0] for v in rep.violations})
        self.assertGreater(rep.costs["azure/jobs"]["total_usd"], 15)

    def test_budget_lowered(self):
        self.edit_limits(lambda d: d["budget_usd_month"].update(total=5))
        self.assertIn("C3", self.rules())

    def test_ceiling(self):
        self.edit_limits(lambda d: d["budget_usd_month"].update(hard_ceiling_all_timeouts=10))
        self.assertTrue(any("full timeout" in m for m in self.messages()))

    def test_parked_cron_costs_nothing(self):
        self.edit_job("lotto-entries", lambda d: self.conf(d)["scheduleTriggerConfig"].update(cronExpression="0 0 29 2 *"))
        rep = self.check()
        self.assertEqual(rep.costs["azure/jobs"]["jobs"]["lotto-entries"]["budget_usd"], 0)
        self.assertEqual(rep.violations, [])

    def test_manual_job_is_charged_for_its_run_cap(self):
        self.edit_limits(lambda d: d["jobs"]["lotto-reenter"].update(max_runs_per_day=100))
        self.assertIn("C3", self.rules())


class C6(Fixture):
    def inventory(self, items):
        path = self.root / "azure" / "inventory.json"
        path.write_text(json.dumps(items))
        return path

    def test_known_types_pass(self):
        self.inventory([{"name": "a", "type": "Microsoft.App/jobs"}])
        self.assertEqual(self.rules(), set())

    def test_new_resource_type(self):
        self.inventory([{"name": "fd", "type": "Microsoft.Cdn/profiles"}])
        self.assertIn("C6", self.rules())

    def test_log_analytics_needs_a_daily_cap(self):
        self.edit_limits(lambda d: d["allowed_resource_types"].append("Microsoft.OperationalInsights/workspaces"))
        self.inventory([{"name": "law", "type": "Microsoft.OperationalInsights/workspaces", "properties": {}}])
        self.assertIn("C6", self.rules())
        self.inventory([{"name": "law", "type": "Microsoft.OperationalInsights/workspaces",
                         "properties": {"workspaceCapping": {"dailyQuotaGb": 0.1}}}])
        self.assertNotIn("C6", self.rules())


class C7(Fixture):
    def test_unbounded_subprocess_trips_the_ratchet(self):
        self.write("workers/extra.py", "import subprocess\n\ndef go():\n    subprocess.run(['true'])\n")
        self.assertTrue(any("no timeout" in m for m in self.messages()))

    def test_unbounded_urlopen_and_runner_helpers(self):
        self.write("workers/extra.py", "import urllib.request\n\ndef go(u):\n    urllib.request.urlopen(u)\n    command(['x'], 1)\n    run_soft(['y'], 1)\n")
        self.assertTrue(any("3 subprocess/network calls" in m for m in self.messages()))

    def test_timeout_none_does_not_count_as_a_timeout(self):
        self.write("workers/extra.py", "import subprocess\nsubprocess.run(['true'], timeout=None)\n")
        self.assertIn("C7", self.rules())

    def test_timeout_keyword_is_enough(self):
        self.write("workers/extra.py", "import subprocess\nsubprocess.run(['true'], timeout=5)\n")
        self.assertNotIn("C7", self.rules())

    def test_removing_a_timeout_in_the_runner(self):
        self.edit_file("azure/runner.py", lambda t: t.replace("timeout=COMMIT_ENTRIES_TIMEOUT_S,", "", 1))
        self.assertIn("C7", self.rules())

    def test_while_true_without_exit(self):
        self.write("workers/extra.py", "def go():\n    while True:\n        pass\n")
        self.assertTrue(any("no break or return" in m for m in self.messages()))

    def test_while_true_without_counter_or_deadline(self):
        self.write("workers/extra.py", "def go(q):\n    while True:\n        if q():\n            break\n")
        self.assertTrue(any("no counter or deadline" in m for m in self.messages()))

    def test_while_true_with_a_deadline_is_fine(self):
        self.write("workers/extra.py", "import time\ndef go(q):\n    deadline = time.monotonic() + 5\n    while True:\n        if q() or time.monotonic() > deadline:\n            break\n")
        self.assertNotIn("C7", self.rules())

    def test_long_sleep(self):
        self.write("workers/extra.py", "import time\ntime.sleep(3600)\n")
        self.assertTrue(any("longer than 60" in m for m in self.messages()))
        self.write("workers/extra.sh", "sleep 300\n")
        self.assertIn("C7", self.rules())

    def test_retry_loop_over_five(self):
        self.write("workers/extra.py", "import urllib.request\ndef go(u):\n    for _ in range(9):\n        urllib.request.urlopen(u, timeout=5)\n")
        self.assertTrue(any("retry loop runs 9" in m for m in self.messages()))
        self.write("workers/extra.py", "import urllib.request\ndef go(u):\n    for _ in range(5):\n        urllib.request.urlopen(u, timeout=5)\n")
        self.assertNotIn("C7", self.rules())

    def test_issue_page_cap(self):
        self.edit_file("azure/runner.py", lambda t: t.replace("MAX_ISSUE_PAGES = 10", "MAX_ISSUE_PAGES = 100"))
        self.assertTrue(any("MAX_ISSUE_PAGES" in m for m in self.messages()))

    def test_runner_entrant_defaults_and_comps_cap(self):
        self.edit_file("azure/runner.py", lambda t: t.replace("ENTRANT_DEFAULT_CONCURRENCY = 3", "ENTRANT_DEFAULT_CONCURRENCY = 8"))
        self.assertTrue(any("ENTRANT_DEFAULT_CONCURRENCY" in m for m in self.messages()))
        self.edit_file("azure/runner.py", lambda t: t.replace("ENTRANT_DEFAULT_CONCURRENCY = 8", "ENTRANT_DEFAULT_CONCURRENCY = 3")
                       .replace('"workers.comps", "--max", str(COMPS_MAX_NEW)', '"workers.comps"'))
        self.assertTrue(any("--max" in m for m in self.messages()))

    def test_entrant_node_defaults(self):
        self.edit_file("workers/entrant.mjs", lambda t: t.replace("ENTRANT_MAX || 200", "ENTRANT_MAX || 5000"))
        self.assertTrue(any("entrant default max" in m for m in self.messages()))
        self.edit_file("workers/entrant.mjs", lambda t: t.replace("ENTRANT_MAX || 5000", "ENTRANT_MAX || 200")
                       .replace("ENTRANT_CONCURRENCY || 6", "ENTRANT_CONCURRENCY || 40"))
        self.assertTrue(any("entrant default concurrency" in m for m in self.messages()))

    def test_node_while_true(self):
        self.write("workers/extra.mjs", "while (true) {\n  await x();\n}\n")
        self.assertIn("C7", self.rules())

    def test_secrets_in_source(self):
        for text in ("t = 'ghp_" + "a1" * 15 + "'", "t = 'AccountKey=" + "A" * 30 + "=='", "t = 'https://x/y?sig=" + "Ab1" * 10 + "'",
                     "t = 'github_pat_" + "x" * 30 + "'", "t = 'da2-" + "a" * 26 + "'"):
            self.write("workers/leak.py", text + "\n")
            self.assertTrue(any("keep secrets out" in m for m in self.messages()), text)

    def test_issue_title_that_would_trigger_the_workflows(self):
        self.write("workers/extra.py", "def f():\n    return {'title': 'Reenter: 1', 'body': 'x'}\n")
        self.assertIn("C8", self.rules())
        self.write("workers/extra.py", "def f(x):\n    return x(title=f'remove {1}')\n")
        self.assertIn("C8", self.rules())
        self.write("workers/extra.py", "def f():\n    return {'title': '[jackpot] fine'}\n")
        self.assertNotIn("C8", self.rules())


WORKFLOW = """name: {name}
on:
{on}
permissions:
  contents: write
concurrency:
  group: {name}
  cancel-in-progress: false
jobs:
  work:
    runs-on: ubuntu-latest
    timeout-minutes: 10
{extra}    steps:
      - run: {run}
"""


class C8(Fixture):
    def workflow(self, name="x", on="  workflow_dispatch: {}", run="echo hi", extra=""):
        self.write(f".github/workflows/{name}.yml", WORKFLOW.format(name=name, on=on, run=run, extra=extra))

    def test_clean_workflow_passes(self):
        self.workflow()
        self.assertNotIn("C8", self.rules())

    def test_missing_timeout(self):
        self.edit_file(".github/workflows/draws.yml", lambda t: t.replace("    timeout-minutes: 30\n", ""))
        self.assertTrue(any("no timeout-minutes" in m for m in self.messages()))

    def test_timeout_too_long(self):
        self.edit_file(".github/workflows/draws.yml", lambda t: t.replace("timeout-minutes: 30", "timeout-minutes: 3000"))
        self.assertTrue(any("exceeds" in m for m in self.messages()))

    def test_pushing_workflow_needs_concurrency_without_cancel(self):
        self.workflow(run="git push")
        self.assertNotIn("C8", self.rules())
        self.edit_file(".github/workflows/x.yml", lambda t: t.replace("cancel-in-progress: false", "cancel-in-progress: true"))
        self.assertTrue(any("concurrency" in m for m in self.messages()))
        self.edit_file(".github/workflows/x.yml", lambda t: t.replace("concurrency:\n  group: x\n  cancel-in-progress: true\n", ""))
        self.assertIn("C8", self.rules())

    def test_commit_script_counts_as_pushing(self):
        self.workflow(run='bash workers/commit_entries.sh "m"')
        self.edit_file(".github/workflows/x.yml", lambda t: t.replace("cancel-in-progress: false", "cancel-in-progress: true"))
        self.assertIn("C8", self.rules())

    def test_self_dispatch(self):
        self.workflow(name="loop", run="gh workflow run loop.yml --ref main")
        self.assertTrue(any("starts itself" in m for m in self.messages()))
        self.edit_limits(lambda d: d["ratchet"]["self_dispatch_workflows"].append("loop.yml"))
        self.assertNotIn("C8", self.rules())

    def test_dispatching_another_workflow_is_fine(self):
        self.workflow(name="a", run="gh workflow run site.yml --ref main")
        self.assertNotIn("C8", self.rules())

    def test_workflow_run_only_where_allowed(self):
        self.workflow(name="chain", on="  workflow_run:\n    workflows: [draws]\n    types: [completed]")
        self.assertTrue(any("workflow_run" in m for m in self.messages()))
        self.edit_file(".github/workflows/site.yml", lambda t: t.replace("[comps, entries]", "[comps, entries, draws]"))
        self.assertIn("C8", self.rules())

    def test_push_without_paths_in_a_pushing_workflow(self):
        self.workflow(name="p", on="  push:\n    branches: [main]", run="git push")
        self.assertTrue(any("without `paths:`" in m for m in self.messages()))
        self.workflow(name="p", on="  push:\n    branches: [main]\n    paths: [\"data/**\"]", run="git push")
        self.assertNotIn("C8", self.rules())

    def test_issues_workflow_needs_both_guards(self):
        self.workflow(name="i", on="  issues:\n    types: [opened]")
        self.assertTrue(any("repository-owner" in m for m in self.messages()))
        guarded = ("    if: github.event.issue.user.login == github.repository_owner && "
                   "startsWith(github.event.issue.title, 'zzz')\n")
        self.workflow(name="i", on="  issues:\n    types: [opened]", extra=guarded)
        self.assertNotIn("C8", self.rules())
        only_owner = "    if: github.event.issue.user.login == github.repository_owner\n"
        self.workflow(name="i", on="  issues:\n    types: [opened]", extra=only_owner)
        self.assertIn("C8", self.rules())

    def test_cron_volume(self):
        self.workflow(name="busy", on='  schedule:\n    - cron: "* * * * *"')
        self.assertTrue(any("times a day" in m for m in self.messages()))

    def test_issue_title_in_a_workflow(self):
        self.workflow(name="t", run='gh issue create --title "reenter: 1" --body x')
        self.assertTrue(any("reenter/remove" in m for m in self.messages()))

    def test_exemption_is_explicit(self):
        self.edit_limits(lambda d: d["workflows"]["concurrency_exempt"].clear())
        self.assertTrue(any("concurrency" in m for m in self.messages()))

    def test_reusable_workflow_call_needs_no_timeout(self):
        self.write(".github/workflows/call.yml", "name: call\non:\n  workflow_dispatch: {}\njobs:\n  guard:\n    uses: ./.github/workflows/x.yml\n")
        self.assertNotIn("C8", self.rules())


class C10(Fixture):
    def base(self):
        path = self.root / "base.json"
        shutil.copy(self.limits, path)
        return path

    def loosen_and_check(self, fn):
        base = json.loads(self.limits.read_text())
        self.edit_limits(fn)
        return self.check(base=base)

    def test_unchanged_passes(self):
        self.assertEqual(self.check(base=json.loads(self.limits.read_text())).violations, [])

    def test_raising_a_number_fails(self):
        rep = self.loosen_and_check(lambda d: d["jobs"]["lotto-draws"].update(max_replica_timeout_s=3600))
        self.assertIn("C10", {v[0] for v in rep.violations})

    def test_adding_to_a_list_fails(self):
        rep = self.loosen_and_check(lambda d: d["jobs"]["lotto-draws"]["may_hold_secrets"].append("ENTRANT_PROFILE_JSON"))
        self.assertIn("C10", {v[0] for v in rep.violations})

    def test_lowering_a_minimum_fails(self):
        rep = self.loosen_and_check(lambda d: d["jobs"]["lotto-entries"].update(min_interval_min=1))
        self.assertTrue(any("min_interval_min" in v[3] for v in rep.violations))

    def test_cheaper_price_fails(self):
        rep = self.loosen_and_check(lambda d: d["prices"].update(aca_vcpu_s=0.0000001))
        self.assertTrue(any("aca_vcpu_s" in v[3] for v in rep.violations))

    def test_new_job_or_removed_limit_fails(self):
        rep = self.loosen_and_check(lambda d: d["jobs"].update(extra={}))
        self.assertTrue(any("new entry" in v[3] for v in rep.violations))
        rep = self.loosen_and_check(lambda d: d["jobs"]["lotto-entries"].pop("max_env"))
        self.assertTrue(any("limit removed" in v[3] for v in rep.violations))

    def test_tightening_passes(self):
        rep = self.loosen_and_check(lambda d: (d["jobs"]["lotto-draws"].update(max_replica_timeout_s=900),
                                                d["jobs"]["lotto-entries"].update(min_interval_min=10),
                                                d["workflows"]["concurrency_exempt"].clear()))
        self.assertNotIn("C10", {v[0] for v in rep.violations})

    def test_owner_approval_lets_it_through(self):
        with mock.patch.dict(os.environ, {"LIMITS_APPROVED": "1"}):
            rep = self.loosen_and_check(lambda d: d["jobs"]["lotto-draws"].update(max_replica_timeout_s=3600))
        self.assertNotIn("C10", {v[0] for v in rep.violations})
        self.assertTrue(any("approved" in n for n in rep.notes))

    def test_cli_base_file(self):
        base = self.base()
        self.edit_limits(lambda d: d["code"].update(max_issue_pages=50))
        with redirect_stdout(io.StringIO()):
            code = guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base-file", str(base)])
        self.assertEqual(code, 1)

    def test_missing_base_is_skipped(self):
        rep = self.check(base=None)
        self.assertTrue(any("C10 skipped" in n for n in rep.notes))


class Drift(Fixture):
    def test_matching_live_state_passes(self):
        live = self.make_live()
        self.assertEqual(self.check(live_dir=live, expected_image=DIGEST).violations, [])

    def test_unpatched_live_state_fails(self):
        def stale(name, doc):
            self.container(doc)["image"] = "ghcr.io/jesseallomes/lotto-project-azure:latest"
            self.conf(doc)["replicaTimeout"] = 180 if name == "lotto-entries" else self.conf(doc)["replicaTimeout"]
        rules = self.rules(live_dir=self.make_live(stale))
        self.assertIn("C2", rules)
        self.assertIn("DRIFT", rules)

    def test_portal_edit_is_drift(self):
        def edit(name, doc):
            if name == "lotto-comps":
                self.set_env(doc, "EXTRA", value="1")
        rep = self.check(live_dir=self.make_live(edit))
        self.assertTrue(any(v[0] == "DRIFT" and "env differs" in v[3] for v in rep.violations))

    def test_live_state_is_held_to_the_limits_too(self):
        def edit(name, doc):
            if name == "lotto-draws":
                self.container(doc)["resources"]["cpu"] = 2.0
                self.conf(doc)["scheduleTriggerConfig"]["cronExpression"] = "* * * * *"
        rep = self.check(live_dir=self.make_live(edit))
        rules = {v[0] for v in rep.violations}
        self.assertTrue({"C1", "C2", "C3", "DRIFT"} <= rules, rules)

    def test_missing_live_job(self):
        live = self.make_live()
        (live / "lotto-entries.json").unlink()
        self.assertTrue(any("live export" in m for m in self.messages(live_dir=live)))

    def test_wrong_image_digest(self):
        live = self.make_live()
        self.assertTrue(any("expected" in m for m in self.messages(
            live_dir=live, expected_image="ghcr.io/jesseallomes/lotto-azure-runner@sha256:" + "b" * 64)))

    def test_secret_reference_drift(self):
        def edit(name, doc):
            if name == "lotto-draws":
                self.conf(doc)["secrets"][1]["keyVaultUrl"] = "https://kv/secrets/other"
        rep = self.check(live_dir=self.make_live(edit))
        self.assertTrue(any("secret_urls" in v[3] for v in rep.violations))

    def test_cli_live(self):
        live = self.make_live()
        out = io.StringIO()
        with redirect_stdout(out):
            code = guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base", "none",
                               "--live", str(live), "--image", DIGEST])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("cost[live]", out.getvalue())


class Cli(Fixture):
    def test_exit_codes_and_line_format(self):
        out = io.StringIO()
        self.edit_job("lotto-draws", lambda d: self.conf(d).update(replicaRetryLimit=1))
        with redirect_stdout(out):
            code = guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base", "none"])
        self.assertEqual(code, 1)
        self.assertRegex(out.getvalue(), r"(?m)^C2 azure/jobs/lotto-draws\.json:1 replicaRetryLimit")

    def test_bad_limits_file_is_exit_2(self):
        self.limits.write_text("{not json")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base", "none"]), 2)

    def test_missing_key_is_exit_2(self):
        self.edit_limits(lambda d: d.pop("prices"))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base", "none"]), 2)

    def test_json_output(self):
        out = io.StringIO()
        with redirect_stdout(out):
            guard.main(["--limits", str(self.limits), "--root", str(self.root), "--base", "none", "--json"])
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["violations"], [])
        self.assertIn("azure/jobs", doc["costs"])


if __name__ == "__main__":
    unittest.main()
