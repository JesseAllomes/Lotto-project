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
            self.assertEqual(holds, path.stem in ("lotto-entries", "lotto-reenter", "lotto-comps", "lotto-actions"), path.name)

    def test_github_token_only_where_issues_are_still_made(self):
        for path in (REPO / "azure" / "jobs").glob("*.json"):
            view = guard.job_view(json.loads(path.read_text()))
            self.assertEqual("GITHUB_TOKEN" in view["env"], path.stem in ("lotto-jackpots", "lotto-reenter"), path.name)

    def test_every_job_reads_the_blob_store_through_the_identity(self):
        for path in (REPO / "azure" / "jobs").glob("*.json"):
            view = guard.job_view(json.loads(path.read_text()))
            self.assertEqual(view["env"]["LOTTO_DATA_ACCOUNT"], {"value": "stpersonalv5ethud2i3cfq"}, path.name)
            self.assertIn("AZURE_CLIENT_ID", view["env"], path.name)
            self.assertEqual(len(view["identities"]), 1, path.name)

    def test_site_job_every_two_hours_with_only_the_deploy_token(self):
        view = guard.job_view(json.loads((REPO / "azure" / "jobs" / "lotto-site.json").read_text()))
        self.assertEqual((view["cron"], view["timeout"], view["cpu"], view["memory_gi"]), ("37 */2 * * *", 900, 0.5, 1.0))
        self.assertEqual(view["args"], ["site"])
        self.assertEqual(view["env"]["SWA_DEPLOY_TOKEN"], {"secretRef": "swa-deploy-token"})
        self.assertEqual(dict(view["secret_urls"])["swa-deploy-token"],
                         "https://kv-personal-v5ethud2i3cf.vault.azure.net/secrets/swa-lotto-deploy-token")
        self.assertNotIn("GITHUB_TOKEN", view["env"])
        self.assertNotIn("ENTRANT_PROFILE_JSON", view["env"])
        stats = guard.cron_stats(view["cron"])
        self.assertEqual((stats["per_day"], stats["min_gap_min"]), (12, 120))

    def test_site_workflow_deploys_to_azure_only_by_hand(self):
        text = (REPO / ".github" / "workflows" / "site.yml").read_text()
        azure = text[text.index("\n  azure:"):]
        self.assertIn("github.event_name == 'workflow_dispatch'", azure.split("steps:")[0])


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
        self.edit_file("azure/runner.py", lambda t: t.replace("timeout=QUEUE_TIMEOUT_S,", "", 1))
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
                self.conf(doc)["secrets"][-1]["keyVaultUrl"] = "https://kv/secrets/other"
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


class EventJob(Fixture):
    """lotto-actions, the only Event job: bounded executions, polling and queue; the identity, not a secret, reads the queue."""

    @staticmethod
    def event(doc):
        return doc["properties"]["configuration"]["eventTriggerConfig"]

    def rule(self, doc):
        return self.event(doc)["scale"]["rules"][0]

    def fails(self, fn, text):
        self.edit_job("lotto-actions", fn)
        self.assertIn("C2", self.rules())
        self.assertTrue(any(text in m for m in self.messages()), self.messages())

    def test_the_actions_job_as_delivered(self):
        view = guard.job_view(json.loads((REPO / "azure" / "jobs" / "lotto-actions.json").read_text()))
        self.assertEqual((view["trigger"], view["timeout"], view["retry"], view["parallelism"], view["completion"]),
                         ("Event", 600, 0, 1, 1))
        self.assertEqual(view["args"], ["actions"])
        self.assertIn(view["env"]["AZURE_JOBS_DISABLED"], ({"value": "0"}, {"value": "1"}))  # an explicit switch either way
        self.assertEqual(view["env"]["ENTRANT_PROFILE_JSON"], {"secretRef": "entrant-profile"})
        self.assertNotIn("GITHUB_TOKEN", view["env"])
        ev = view["event"]
        self.assertEqual((ev["max_executions"], ev["polling_s"], ev["min_executions"]), (1, 60, 0))
        (rule,) = ev["rules"]
        self.assertEqual((rule["type"], rule["queue"], rule["account"], rule["queue_length"]),
                         ("azure-queue", "lotto-actions", "stlottoactions", "1"))
        self.assertEqual([rule["identity"]], view["identities"])
        self.assertFalse(rule["has_auth"])

    def test_only_the_actions_job_may_be_an_event_job(self):
        for name in ("lotto-draws", "lotto-site"):
            self.edit_job(name, lambda d: self.conf(d).update(triggerType="Event"))
            self.assertTrue(any("triggerType" in m for m in self.messages()), name)
        for name in ("lotto-reenter", "lotto-draws"):                                  # and no event config on the others
            self.edit_job(name, lambda d: self.conf(d).update(triggerType=self.conf(d)["triggerType"],
                                                              eventTriggerConfig=self.event(json.loads(
                                                                  (REPO / "azure/jobs/lotto-actions.json").read_text()))))
            self.assertTrue(any("not an Event job" in m for m in self.messages()), name)

    def test_the_actions_job_must_stay_an_event_job(self):
        self.fails(lambda d: self.conf(d).update(triggerType="Manual"), "triggerType")

    def test_one_execution_at_a_time(self):
        self.fails(lambda d: self.event(d)["scale"].update(maxExecutions=2), "maxExecutions")
        self.fails(lambda d: self.event(d)["scale"].pop("maxExecutions"), "maxExecutions")
        self.fails(lambda d: self.event(d).update(parallelism=2), "parallelism")

    def test_nothing_runs_while_the_queue_is_empty(self):
        self.fails(lambda d: self.event(d)["scale"].update(minExecutions=1), "minExecutions")

    def test_polling_no_faster_than_the_limit(self):
        self.fails(lambda d: self.event(d)["scale"].update(pollingInterval=5), "pollingInterval")

    def test_only_the_declared_queue_and_account_and_rule_type(self):
        self.fails(lambda d: self.rule(d)["metadata"].update(queueName="other"), "watches queue")
        self.fails(lambda d: self.rule(d)["metadata"].update(accountName="someoneelse"), "storage account")
        self.fails(lambda d: self.rule(d).update(type="azure-servicebus"), "type")
        self.fails(lambda d: self.event(d)["scale"].update(rules=[]), "needs a scale rule")

    def test_the_rule_authenticates_with_the_managed_identity_not_a_secret(self):
        self.fails(lambda d: self.rule(d).pop("identity"), "managed identity")
        self.fails(lambda d: self.rule(d).update(identity="/subscriptions/x/other"), "managed identity")
        self.fails(lambda d: self.rule(d).update(auth=[{"secretRef": "conn", "triggerParameter": "connection"}]), "auth block")

    def test_timeout_and_secrets_follow_the_normal_rules(self):
        self.fails(lambda d: self.conf(d).update(replicaTimeout=1800), "exceeds 600")
        self.fails(lambda d: self.set_env(d, "GITHUB_TOKEN", secret="github-token"), "undefined secret")
        self.edit_job("lotto-actions", lambda d: self.conf(d)["secrets"].append({"name": "github-token", "keyVaultUrl": "u", "identity": "i"}))
        self.edit_job("lotto-actions", lambda d: self.set_env(d, "GITHUB_TOKEN", secret="github-token"))
        self.assertTrue(any("may not hold" in m for m in self.messages()))

    def test_an_event_job_is_charged_for_its_run_cap(self):
        rep = self.check()
        self.assertEqual(rep.costs["azure/jobs"]["jobs"]["lotto-actions"]["runs_per_30d"], 240)
        self.assertLess(rep.costs["azure/jobs"]["total_usd"], 15)
        self.assertLessEqual(rep.costs["azure/jobs"]["ceiling_usd"], 27)
        self.edit_limits(lambda d: d["jobs"]["lotto-actions"].update(max_runs_per_day=500))
        self.assertIn("C3", self.rules())

    def test_an_event_job_needs_its_event_limits(self):
        self.edit_limits(lambda d: d["jobs"]["lotto-actions"].pop("event"))
        self.assertTrue(any("`event` block" in m for m in self.messages()))

    def test_live_scale_settings_are_compared(self):
        def edit(name, doc):
            if name == "lotto-actions":
                self.event(doc)["scale"]["maxExecutions"] = 5
                self.event(doc)["scale"]["pollingInterval"] = 10
        rep = self.check(live_dir=self.make_live(edit))
        self.assertTrue(any(v[0] == "DRIFT" and "event differs" in v[3] for v in rep.violations))
        self.assertIn("C2", {v[0] for v in rep.violations})
        self.assertEqual(self.check(live_dir=self.make_live(), expected_image=DIGEST).violations, [])

    def test_loosening_the_event_limits_needs_approval(self):
        base = json.loads(self.limits.read_text())
        self.edit_limits(lambda d: d["jobs"]["lotto-actions"]["event"].update(max_executions=3, min_polling_interval_s=5))
        rep = self.check(base=base)
        text = " ".join(v[3] for v in rep.violations)
        self.assertIn("max_executions", text)
        self.assertIn("min_polling_interval_s", text)

    def test_the_new_job_is_a_loosening_against_a_base_without_it(self):
        base = json.loads(self.limits.read_text())
        del base["jobs"]["lotto-actions"], base["site_api"]
        rep = self.check(base=base)
        self.assertTrue(any("lotto-actions: new entry" in v[3] for v in rep.violations))
        with mock.patch.dict(os.environ, {"LIMITS_APPROVED": "1"}):
            self.assertEqual(self.check(base=base).violations, [])


class C12(Fixture):
    """The site API: declared routes only, no login offered, caps and the per-IP rate cap in code, retired issue workflows gone."""

    API = "azure/site-api/lotto_actions.py"

    def fails(self, text):
        self.assertIn("C12", self.rules())
        self.assertTrue(any(text in m for m in self.messages()), self.messages())

    def test_delivered_repository_passes_c12(self):
        self.assertNotIn("C12", self.rules())

    def test_no_login_is_offered(self):
        self.edit_file("workers/site.py", lambda t: t.replace('        {"route": "/.auth/login/github", "statusCode": 404},\n', ""))
        self.fails("must 404 /.auth/login/github")
        self.setUp()
        self.edit_file("workers/site.py", lambda t: t.replace('"platform":', '"responseOverrides": {"401": {"redirect": "/.auth/login/github", "statusCode": 302}},\n    "platform":'))
        self.fails("must not redirect 401")

    def test_rate_cap_constants_must_exist_and_stay_within_limits(self):
        self.edit_file(self.API, lambda t: t.replace("RATE_LIMIT_MAX_ACTIONS = 30", "RATE_LIMIT_MAX_ACTIONS = 31"))
        self.fails("RATE_LIMIT_MAX_ACTIONS must be")
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace("RATE_LIMIT_MAX_ACTIONS = 30", "RATE_LIMIT_MAX_ACTIONS = 10 * 3"))
        self.fails("RATE_LIMIT_MAX_ACTIONS must be")              # not a literal the guard can read: refuse rather than guess
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace("RATE_WINDOW_S = 600", "RATE_WINDOW_S = 60"))
        self.fails("RATE_WINDOW_S must be")
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace("RATE_WINDOW_S = 600", "RATE_WINDOW_S_X = 600"))
        self.fails("RATE_WINDOW_S must be")
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace("return 429,", "return 400,"))
        self.fails("does not return 429")

    def test_runtime_and_config_must_exist(self):
        self.edit_file("workers/site.py", lambda t: t.replace('"python:3.11"', '"node:18"'))
        self.fails("apiRuntime")
        self.edit_file("workers/site.py", lambda t: t.replace("SWA_CONFIG = {", "OTHER = {"))
        self.fails("SWA_CONFIG")

    def test_only_the_declared_route_and_method(self):
        self.edit_file("azure/site-api/function_app.py", lambda t: t + '\n\n@app.route(route="state", methods=["GET"])\ndef state(req):\n    return None\n')
        self.fails("/api/state is not in allowed_routes")
        self.assertTrue(any("methods ['GET']" in m for m in self.messages()))
        self.setUp()
        self.edit_file("azure/site-api/function_app.py", lambda t: t.replace('methods=["POST"]', 'methods=["POST", "GET"]'))
        self.fails("methods")
        self.setUp()
        self.edit_file("azure/site-api/function_app.py", lambda t: t.replace('route="action", methods=["POST"]', 'route="action"'))
        self.fails("methods")

    def test_body_size_limit_must_exist_be_small_and_be_enforced(self):
        self.edit_file(self.API, lambda t: t.replace("MAX_BODY_BYTES = 16384", "MAX_BODY_BYTES = 1048576"))
        self.fails("MAX_BODY_BYTES must be")
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace("MAX_BODY_BYTES = 16384", "MAX_BODY_BYTES = 16 * 1024"))
        self.fails("MAX_BODY_BYTES must be")                      # not a literal the guard can read: refuse rather than guess
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace("if declared > MAX_BODY_BYTES or len(body) > MAX_BODY_BYTES:", "if False:"))
        self.fails("does not enforce MAX_BODY_BYTES")

    def test_id_answer_and_kind_caps(self):
        self.edit_file(self.API, lambda t: t.replace("MAX_IDS = 50", "MAX_IDS = 500"))
        self.fails("MAX_IDS")
        self.setUp()
        self.edit_file("workers/actions.py", lambda t: t.replace("MAX_ANSWER_CHARS = 2000", "MAX_ANSWER_CHARS = 20000"))
        self.fails("MAX_ANSWER_CHARS")
        self.setUp()
        self.edit_file(self.API, lambda t: t.replace('KINDS = ("remove",', 'KINDS = ("wipe", "remove",'))
        self.fails("KINDS")

    def test_retired_workflows_cannot_come_back(self):
        for name in ("reenter.yml", "remove.yml", "answer.yml"):
            self.assertFalse((REPO / ".github" / "workflows" / name).exists(), name)
            self.write(f".github/workflows/{name}", "name: x\non:\n  workflow_dispatch: {}\njobs: {}\n")
            self.assertIn((f".github/workflows/{name}", "C12"), {(v[1], v[0]) for v in self.check().violations})
            (self.root / ".github" / "workflows" / name).unlink()

    def test_api_without_limits_is_refused(self):
        self.edit_limits(lambda d: d.pop("site_api"))
        self.fails("no `site_api` block")

    def test_api_network_calls_need_a_timeout_and_no_sas_in_source(self):
        self.edit_file(self.API, lambda t: t.replace("urllib.request.urlopen(request, timeout=timeout)", "urllib.request.urlopen(request)"))
        self.assertTrue(any("unbounded" in n for n in self.check().notes) or "C7" in self.rules())
        self.assertIn("C7", self.rules())
        self.setUp()
        self.write("azure/site-api/leak.py", "u = 'https://x.queue.core.windows.net/q?sig=" + "Ab1" * 10 + "'\n")
        self.assertTrue(any("keep secrets out" in m for m in self.messages()))

    def test_runner_caps_for_the_actions_job(self):
        self.edit_file("azure/runner.py", lambda t: t.replace("MAX_ACTIONS_PER_RUN = 20", "MAX_ACTIONS_PER_RUN = 200"))
        self.assertTrue(any("MAX_ACTIONS_PER_RUN" in m for m in self.messages()))
        self.setUp()
        self.edit_file("azure/runner.py", lambda t: t.replace("ACTIONS_MAX_DEQUEUE = 3", "ACTIONS_MAX_DEQUEUE = 30"))
        self.assertTrue(any("ACTIONS_MAX_DEQUEUE" in m for m in self.messages()))

    def test_limits_for_the_api_cannot_be_loosened_without_approval(self):
        base = json.loads(self.limits.read_text())
        self.edit_limits(lambda d: d["site_api"].update(max_body_bytes=1048576))
        self.assertTrue(any("max_body_bytes" in v[3] for v in self.check(base=base).violations))
        self.edit_limits(lambda d: d["site_api"]["allowed_routes"].append("/api/state"))
        self.assertTrue(any("/api/state" in v[3] for v in self.check(base=base).violations))


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
