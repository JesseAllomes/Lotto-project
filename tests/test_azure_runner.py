"""Offline tests for the Azure Container Apps Jobs launcher (azure/runner.py): no network, no real storage."""
import importlib.util
import io
import json
import os
import signal
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location("azure_runner", Path(__file__).resolve().parent.parent / "azure" / "runner.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

PROFILE = {"first_name": "Ann", "last_name": "Lee", "email": "ann@example.com", "phone": None, "postcode": "",
           "suburb": "  ", "state": "VIC", "address": None, "dob": "1990-01-02"}
SECRETS = {"GITHUB_TOKEN": "tok-123", "ENTRANT_PROFILE_JSON": json.dumps(PROFILE), "SWA_DEPLOY_TOKEN": "swa-tok",
           "IDENTITY_ENDPOINT": "http://identity.local/msi/token", "IDENTITY_HEADER": "hdr-secret"}


def patched_env(**extra):
    return mock.patch.dict(os.environ, extra, clear=True)


def ok(returncode=0):
    return subprocess.CompletedProcess([], returncode, "", "")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch.object(runner.signal, "signal"):
        code = runner.main(argv)
    return code, out.getvalue(), err.getvalue()


class Profile(unittest.TestCase):
    def test_null_and_empty_values_are_skipped_never_none(self):
        with patched_env(ENTRANT_PROFILE_JSON=json.dumps(PROFILE)):
            runner.load_profile()
            self.assertEqual(os.environ["ENTRANT_FIRST_NAME"], "Ann")
            self.assertEqual(os.environ["ENTRANT_DOB"], "1990-01-02")
            for name in ("ENTRANT_PHONE", "ENTRANT_ADDRESS", "ENTRANT_POSTCODE", "ENTRANT_SUBURB"):
                self.assertNotIn(name, os.environ)
            self.assertNotIn("None", [v for k, v in os.environ.items() if k.startswith("ENTRANT_")])

    def test_existing_env_wins_over_profile(self):
        with patched_env(ENTRANT_PROFILE_JSON=json.dumps(PROFILE), ENTRANT_EMAIL="x@example.com"):
            runner.load_profile()
            self.assertEqual(os.environ["ENTRANT_EMAIL"], "x@example.com")

    def test_bad_json_message_does_not_echo_the_secret(self):
        with patched_env(ENTRANT_PROFILE_JSON="{secret-value"):
            with self.assertRaises(runner.ProfileError) as ctx:
                runner.load_profile()
        self.assertNotIn("secret-value", str(ctx.exception))

    def test_bad_profile_is_ignored_when_the_kill_switch_is_on(self):
        with patched_env(ENTRANT_PROFILE_JSON="{bad", AZURE_JOBS_DISABLED="1"):
            code, out, _ = run_main(["entries"])
        self.assertEqual(code, 0)
        self.assertIn("disabled", out)

    def test_bad_profile_fails_entries_and_reenter_without_echo(self):
        for job in ("entries", "reenter"):
            with patched_env(ENTRANT_PROFILE_JSON="{secret-value", FORCE="1"), \
                    mock.patch.object(runner, "current_pace", return_value={}), \
                    mock.patch.object(runner, "prepare") as prepare:
                code, out, err = run_main([job])
            self.assertEqual(code, 1, job)
            self.assertIn("not valid JSON", err)
            self.assertNotIn("secret-value", out + err)
            prepare.assert_not_called()

    def test_bad_profile_does_not_stop_draws(self):
        with patched_env(ENTRANT_PROFILE_JSON="{bad"), \
                mock.patch.object(runner, "prepare", return_value=Path(".")) as prepare, \
                mock.patch.object(runner, "run_draws") as draws:
            code, _, _ = run_main(["draws"])
        self.assertEqual(code, 0)
        prepare.assert_called_once_with("draws")
        draws.assert_called_once_with(Path("."))

    def test_bad_profile_skips_only_the_winners_check_in_comps(self):
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            return ok()

        with patched_env(), mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push") as push, redirect_stdout(io.StringIO()):
            runner.run_comps(Path("."), profile_ok=False)
        self.assertFalse(any("workers.winners" in a for c in calls for a in c))
        self.assertTrue(any("analysis.skill_rank" in a for c in calls for a in c))
        push.assert_called_once()


class DryRunAndForce(unittest.TestCase):
    def test_dry_run_blocks_github_writes_but_not_reads(self):
        with patched_env(DRY_RUN="1"), mock.patch.object(runner.urllib.request, "urlopen") as urlopen, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(runner.github_request("POST", "issues", {"title": "t", "body": "b"}), {})
            runner.github_request("POST", "issues/3/comments", {"body": "x"})
            runner.github_request("PATCH", "issues/3", {"state": "closed"})
            urlopen.assert_not_called()
        self.assertIn("DRY_RUN: would POST issues t", out.getvalue())
        with patched_env(DRY_RUN="1"), mock.patch.object(runner.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
            self.assertEqual(runner.github_request("GET", "issues"), [])
            urlopen.assert_called_once()

    def test_writes_go_through_without_dry_run(self):
        with patched_env(), mock.patch.object(runner.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            runner.github_request("POST", "issues", {"title": "t"})
            urlopen.assert_called_once()

    def push_calls(self, dry, changed=True):
        """Run runner.push over a real folder with blobsync's network calls mocked out."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            (Path(tmp) / "data/a.csv").write_text("1")
            with patched_env(**({"DRY_RUN": "1"} if dry else {})), \
                    mock.patch.object(runner.blobsync, "push", return_value=["data/a.csv"] if changed else []) as push, \
                    mock.patch.object(runner.blobsync, "changed_names", return_value=["data/a.csv"]) as names, \
                    redirect_stdout(io.StringIO()) as out:
                result = runner.push(Path(tmp), "msg", ["data"])
        return result, push, names, out.getvalue()

    def test_dry_run_skips_the_upload(self):
        result, push, names, out = self.push_calls(dry=True)
        self.assertFalse(result)
        push.assert_not_called()
        names.assert_called_once()
        self.assertIn("DRY_RUN: would upload 1 changed file", out)

    def test_upload_happens_without_dry_run(self):
        result, push, _, out = self.push_calls(dry=False)
        self.assertTrue(result)
        push.assert_called_once()
        self.assertEqual([p.name for p in push.call_args.args[0]], ["a.csv"])
        self.assertIn("uploaded 1 changed file", out)

    def test_nothing_changed_uploads_nothing_new(self):
        result, push, _, _ = self.push_calls(dry=False, changed=False)
        self.assertFalse(result)

    def test_no_generated_paths_means_no_blob_calls(self):
        with tempfile.TemporaryDirectory() as tmp, patched_env(), \
                mock.patch.object(runner.blobsync, "push") as push, redirect_stdout(io.StringIO()):
            self.assertFalse(runner.push(Path(tmp), "msg", ["data"]))
        push.assert_not_called()

    def test_dry_run_rebuilds_locally_but_uploads_nothing_after_entries(self):
        calls = []
        with patched_env(DRY_RUN="1", ENTRANT_LIVE="1"), \
                mock.patch.object(runner.subprocess, "run", side_effect=lambda a, **kw: calls.append(a) or ok()), \
                mock.patch.object(runner.blobsync, "push") as push, \
                mock.patch.object(runner.blobsync, "changed_names", return_value=[]), \
                tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            (Path(tmp) / "data/entries").mkdir(parents=True)
            (Path(tmp) / "data/entries/log.jsonl").write_text("{}\n")
            runner.finish_entries(Path(tmp), "m")
            push.assert_not_called()
            self.assertEqual(runner.entrant_environment(Path("."))["ENTRANT_LIVE"], "0")
        with patched_env(ENTRANT_LIVE="1"):
            self.assertEqual(runner.entrant_environment(Path("."))["ENTRANT_LIVE"], "1")

    def test_dry_run_jackpots_creates_no_issue(self):
        alerts = [{"key": "k1", "title": "[jackpot] k1", "body": "b"}]
        with patched_env(DRY_RUN="1"), mock.patch.object(runner.urllib.request, "urlopen") as urlopen, \
                redirect_stdout(io.StringIO()):
            urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
            runner.create_alert_issues(alerts)
            methods = [c.args[0].get_method() for c in urlopen.call_args_list]
        self.assertEqual(methods, ["GET"])

    def run_entries_main(self, **env):
        with patched_env(**env), mock.patch.object(runner, "current_pace", return_value={"last_day_listings": 0}), \
                mock.patch.object(runner, "entry_due", return_value=False), \
                mock.patch.object(runner, "prepare", return_value=Path(".")) as prepare, \
                mock.patch.object(runner, "run_entries") as run_entries:
            code, out, _ = run_main(["entries"])
        return code, out, prepare.called, run_entries.called

    def test_not_due_exits_without_pulling(self):
        code, out, cloned, ran = self.run_entries_main()
        self.assertEqual((code, cloned, ran), (0, False, False))
        self.assertIn("not due", out)

    def test_force_bypasses_the_burst_window_gate(self):
        code, _, cloned, ran = self.run_entries_main(FORCE="1")
        self.assertEqual((code, cloned, ran), (0, True, True))

    def test_force_does_not_bypass_entries_disabled(self):
        _, _, cloned, ran = self.run_entries_main(FORCE="1", ENTRIES_DISABLED="1")
        self.assertEqual((cloned, ran), (False, False))


class Site(unittest.TestCase):
    def run_site(self, **env):
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            if args[:2] == [runner.sys.executable, "-m"] and args[2] == "workers.site":
                out = Path(kw["cwd"]) / "site"
                out.mkdir(exist_ok=True)
                (out / "index.html").write_text("<html></html>")
            return ok()

        error = None
        with tempfile.TemporaryDirectory() as tmp, patched_env(PATH="/bin", **env), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), redirect_stdout(io.StringIO()) as out:
            try:
                runner.run_site(Path(tmp))
            except Exception as exc:
                error = exc
        return calls, error, out.getvalue()

    def test_site_is_a_job_that_pulls_comps_and_entries_only(self):
        self.assertEqual(runner.DATA_PREFIXES["site"], ("data/comps/", "data/entries/"))
        self.assertNotIn("site", runner.PUSH_PATHS)               # the site job uploads no data

    def test_site_main_pulls_then_builds_and_never_pushes(self):
        with patched_env(), mock.patch.object(runner, "prepare", return_value=Path(".")) as prepare, \
                mock.patch.object(runner, "run_site") as run_site, mock.patch.object(runner, "push") as push:
            code, _, _ = run_main(["site"])
        self.assertEqual(code, 0)
        prepare.assert_called_once_with("site")
        run_site.assert_called_once_with(Path("."))
        push.assert_not_called()

    def test_site_runs_the_site_yml_steps_in_order_then_deploys(self):
        calls, error, _ = self.run_site(SWA_DEPLOY_TOKEN="swa-tok")
        self.assertIsNone(error)
        names = [c[0][2] if c[0][1] == "-m" else c[0][0] for c in calls]
        self.assertEqual(names, ["workers.freebies", "workers.winners", "workers.site", runner.SWA_BIN])
        self.assertEqual(calls[2][0][-2:], ["--out", "site"])
        self.assertEqual(calls[3][0], [runner.SWA_BIN, "deploy", "site", "--env", "production"])
        for args, kw in calls:
            self.assertIsNotNone(kw["timeout"], args)
        self.assertLess(sum(kw["timeout"] for _, kw in calls) + 60, 900)     # fits replicaTimeout 900

    def test_deploy_token_only_reaches_the_cli_through_its_environment(self):
        calls, _, out = self.run_site(SWA_DEPLOY_TOKEN="swa-tok", GITHUB_TOKEN="gh", IDENTITY_HEADER="h")
        for args, kw in calls:
            self.assertNotIn("swa-tok", " ".join(args))
            if args[0] == runner.SWA_BIN:
                self.assertEqual(kw["env"]["SWA_CLI_DEPLOYMENT_TOKEN"], "swa-tok")
                self.assertNotIn("SWA_DEPLOY_TOKEN", kw["env"])
            else:
                self.assertNotIn("SWA_CLI_DEPLOYMENT_TOKEN", kw["env"])
                self.assertNotIn("SWA_DEPLOY_TOKEN", kw["env"])
            self.assertNotIn("GITHUB_TOKEN", kw["env"])
            self.assertNotIn("IDENTITY_HEADER", kw["env"])
        self.assertNotIn("swa-tok", out)

    def test_freebies_and_winners_failures_do_not_stop_the_build(self):
        def fake_run(args, **kw):
            if args[2:3] in (["workers.freebies"], ["workers.winners"]):
                if args[2] == "workers.freebies":
                    raise subprocess.TimeoutExpired(args, kw["timeout"])
                return ok(1)
            Path(kw["cwd"], "site").mkdir(exist_ok=True)
            Path(kw["cwd"], "site/index.html").write_text("x")
            return ok()

        with tempfile.TemporaryDirectory() as tmp, patched_env(SWA_DEPLOY_TOKEN="t"), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run) as run, redirect_stdout(io.StringIO()):
            runner.run_site(Path(tmp))
        self.assertEqual(run.call_count, 4)

    def test_failed_build_does_not_deploy(self):
        def fake_run(args, **kw):
            if args[2:3] == ["workers.site"]:
                raise subprocess.CalledProcessError(1, args)
            return ok()

        with tempfile.TemporaryDirectory() as tmp, patched_env(SWA_DEPLOY_TOKEN="t"), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run) as run, redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.run_site(Path(tmp))
        self.assertFalse(any(c.args[0][0] == runner.SWA_BIN for c in run.call_args_list))

    def test_missing_index_html_stops_before_deploy(self):
        with tempfile.TemporaryDirectory() as tmp, patched_env(SWA_DEPLOY_TOKEN="t"), \
                mock.patch.object(runner.subprocess, "run", side_effect=lambda a, **kw: ok()) as run, \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "index.html"):
                runner.run_site(Path(tmp))
        self.assertFalse(any(c.args[0][0] == runner.SWA_BIN for c in run.call_args_list))

    def test_deploy_needs_the_token_and_the_message_does_not_leak(self):
        with patched_env(), mock.patch.object(runner.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "SWA_DEPLOY_TOKEN is required"):
                runner.deploy_site(Path("."))
        run.assert_not_called()

    def test_dry_run_builds_but_does_not_deploy(self):
        calls, error, out = self.run_site(DRY_RUN="1", SWA_DEPLOY_TOKEN="swa-tok")
        self.assertIsNone(error)
        self.assertFalse(any(args[0] == runner.SWA_BIN for args, _ in calls))
        self.assertIn("DRY_RUN: would deploy", out)

    def test_kill_switch_stops_the_site_job_before_any_pull(self):
        with patched_env(AZURE_JOBS_DISABLED="1"), mock.patch.object(runner, "prepare") as prepare:
            code, out, _ = run_main(["site"])
        self.assertEqual(code, 0)
        self.assertIn("disabled", out)
        prepare.assert_not_called()


class Prepare(unittest.TestCase):
    def test_prefixes_per_job_match_the_old_sparse_data_dirs(self):
        self.assertEqual(runner.DATA_PREFIXES["draws"], ("data/draws/",))
        self.assertEqual(runner.DATA_PREFIXES["jackpots"], ("data/jackpots/",))
        for job in ("comps", "entries", "reenter"):
            self.assertEqual(runner.DATA_PREFIXES[job], ("data/comps/", "data/entries/"))

    def test_prepare_pulls_into_the_repo_root_and_returns_it(self):
        with tempfile.TemporaryDirectory() as tmp, patched_env(LOTTO_REPO_ROOT=tmp), \
                mock.patch.object(runner, "REPO_ROOT", Path(tmp)), \
                mock.patch.object(runner.blobsync, "pull", return_value=5) as pull, redirect_stdout(io.StringIO()):
            root = runner.prepare("comps")
        self.assertEqual(root, Path(tmp))
        pull.assert_called_once_with(("data/comps/", "data/entries/"), Path(tmp))

    def test_nothing_in_the_runner_uses_git_any_more(self):
        source = Path(runner.__file__).read_text()
        for word in ("git clone", '"git"', "sparse-checkout", "commit_entries.sh", "GITHUB_BRANCH"):
            self.assertNotIn(word, source)


class Issues(unittest.TestCase):
    def test_pages_until_an_empty_page(self):
        pages = [[{"title": f"old {i}"} for i in range(100)],
                 [{"title": "[jackpot] seen-key"}, {"title": "pr", "pull_request": {}}],
                 []]
        posted = []

        def fake(method, path, payload=None):
            if method == "GET":
                return pages[int(path.rsplit("page=", 1)[1]) - 1]
            posted.append(payload)
            return {}

        alerts = [{"key": "seen-key", "title": "[jackpot] seen-key", "body": ""},
                  {"key": "new-key", "title": "[jackpot] new-key", "body": ""}]
        with mock.patch.object(runner, "github_request", side_effect=fake) as request:
            runner.create_alert_issues(alerts)
        gets = [c.args[1] for c in request.call_args_list if c.args[0] == "GET"]
        self.assertEqual(gets, [f"issues?state=all&per_page=100&page={n}" for n in (1, 2, 3)])
        self.assertEqual([p["title"] for p in posted], ["[jackpot] new-key"])


class Pace(unittest.TestCase):
    def test_current_pace_reads_the_blob(self):
        with mock.patch.object(runner.blobsync, "read_text", return_value='{"last_day_listings": 4}') as read:
            self.assertEqual(runner.current_pace()["last_day_listings"], 4)
        read.assert_called_once_with("data/entries/pace.json")

    def test_current_pace_falls_back_when_unreadable(self):
        for outcome in (runner.blobsync.BlobError("x"), TimeoutError("slow"), OSError("reset"), ValueError("bad"),
                        "not json", "[1]", None):
            effect = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with mock.patch.object(runner.blobsync, "read_text", **effect):
                self.assertEqual(runner.current_pace()["next_run_minutes"], 180, outcome)


class Scrub(unittest.TestCase):
    def test_child_environment_has_no_secrets_or_entrant_vars(self):
        with patched_env(PATH="/bin", ENTRANT_EMAIL="e", ENTRANT_LAST_NAME="Lee", **SECRETS):
            env = runner.child_environment()
        self.assertEqual(env, {"PATH": "/bin"})

    def test_entrant_gets_entrant_vars_but_no_secrets(self):
        with patched_env(PATH="/bin", ENTRANT_EMAIL="e", ENTRANT_CONCURRENCY="2", **SECRETS):
            env = runner.entrant_environment(Path("/r"), Path("/q.json"), reenter=True)
        self.assertEqual(env["ENTRANT_EMAIL"], "e")
        self.assertEqual(env["ENTRANT_CONCURRENCY"], "2")
        self.assertEqual(env["ENTRANT_QUEUE"], "/q.json")
        for name in SECRETS:
            self.assertNotIn(name, env)

    def test_children_get_no_identity_or_deploy_credentials(self):
        with patched_env(PATH="/bin", AZURE_CLIENT_ID="cid", LOTTO_DATA_ACCOUNT="acct", **SECRETS):
            env = runner.child_environment()
        self.assertEqual(env, {"PATH": "/bin", "AZURE_CLIENT_ID": "cid", "LOTTO_DATA_ACCOUNT": "acct"})

    def test_comps_children_see_only_what_they_need(self):
        seen = {}

        def fake_run(args, **kw):
            seen[args[2] if args[1] == "-m" else args[0]] = kw["env"]
            return ok()

        with patched_env(PATH="/bin", ENTRANT_LAST_NAME="Lee", ENTRANT_EMAIL="e", **SECRETS), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push"), redirect_stdout(io.StringIO()):
            runner.run_comps(Path("."))
        self.assertEqual(seen["workers.winners"].get("ENTRANT_LAST_NAME"), "Lee")
        for name, env in seen.items():
            for secret in SECRETS:
                self.assertNotIn(secret, env, name)
            self.assertNotIn("ENTRANT_EMAIL", env, name)
            if name != "workers.winners":
                self.assertNotIn("ENTRANT_LAST_NAME", env, name)


class Comps(unittest.TestCase):
    def run_comps(self, fail):
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            if fail in args:
                if fail == "workers.comp_terms":
                    raise subprocess.TimeoutExpired(args, kw["timeout"])
                if kw["check"]:
                    raise subprocess.CalledProcessError(1, args)
                return ok(1)
            return ok()

        error = None
        with patched_env(), mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push") as push, redirect_stdout(io.StringIO()):
            try:
                runner.run_comps(Path("."))
            except subprocess.CalledProcessError as exc:
                error = exc
        return calls, push, error

    def test_continues_after_comp_terms_timeout_and_still_pushes(self):
        calls, push, error = self.run_comps("workers.comp_terms")
        names = [c[0][2] if c[0][0] != "node" else c[0][1] for c in calls]
        self.assertEqual(names[-3:], ["workers.comp_odds", "analysis.skill_rank", "workers.winners"])
        self.assertIn("workers/link_check.mjs", names)
        self.assertIsNone(error)
        push.assert_called_once()
        timeouts = {n: c[1]["timeout"] for n, c in zip(names, calls)}
        self.assertEqual(timeouts["workers.source_auscomps"], 15 * 60)
        self.assertEqual(timeouts["workers.comp_terms"], 20 * 60)
        self.assertLessEqual(sum(c[1]["timeout"] for c in calls), 5400 - 300)

    def test_auscomps_failure_does_not_abort(self):
        calls, push, error = self.run_comps("workers.source_auscomps")
        self.assertIsNone(error)
        self.assertEqual(len(calls), 9)
        push.assert_called_once()

    def test_push_runs_even_when_a_hard_step_fails(self):
        _, push, error = self.run_comps("workers.comp_odds")
        self.assertIsNotNone(error)
        push.assert_called_once()


class Entries(unittest.TestCase):
    def run_entries(self, **env):
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            if args[0] == "node":
                raise subprocess.TimeoutExpired(args, kw["timeout"])
            return ok()

        error = None
        with patched_env(ENTRANT_EMAIL="e", **env), mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push") as push, redirect_stdout(io.StringIO()):
            try:
                runner.run_entries(Path("."))
            except subprocess.TimeoutExpired as exc:
                error = exc
        return calls, error, push

    def test_timeout_still_rebuilds_and_uploads(self):
        calls, error, push = self.run_entries()
        self.assertIsNotNone(error)
        node = [kw for args, kw in calls if args[0] == "node"][0]
        self.assertEqual(node["timeout"], 150)
        after = [args[2] for args, _ in calls[calls.index(next(c for c in calls if c[0][0] == "node")) + 1:]]
        self.assertEqual(after, ["workers.entry_queue", "workers.removals"])     # what commit_entries.sh rebuilt
        push.assert_called_once()
        self.assertEqual(push.call_args.args[2], ("data/entries",))
        self.assertIn("entries: Azure", push.call_args.args[1])

    def test_timeout_is_configurable(self):
        calls, _, _ = self.run_entries(ENTRANT_TIMEOUT_S="90")
        self.assertEqual([kw["timeout"] for args, kw in calls if args[0] == "node"], [90])

    def test_sigterm_becomes_system_exit(self):
        with mock.patch.object(runner.signal, "signal") as install:
            runner.install_sigterm_handler()
        signum, handler = install.call_args.args
        self.assertEqual(signum, signal.SIGTERM)
        with self.assertRaises(SystemExit):
            handler(signal.SIGTERM, None)


class Reenter(unittest.TestCase):
    def test_failure_still_comments_and_closes(self):
        posted = []

        def fake_run(args, **kw):
            if args[0] == "node":
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, '[{"id": 1}]', "")

        with tempfile.TemporaryDirectory() as tmp, patched_env(ISSUE_TITLE="reenter x", ISSUE_NUMBER="7"), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push") as push, \
                mock.patch.object(runner, "github_request", side_effect=lambda *a: posted.append(a) or {}), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.run_reenter(Path(tmp))
        push.assert_called_once()
        self.assertEqual(push.call_args.args[2], ("data/entries",))
        self.assertEqual([p[0] for p in posted], ["POST", "PATCH"])
        self.assertIn("Re-entry failed", posted[0][2]["body"])
        self.assertEqual(posted[1][2], {"state": "closed"})

    def test_summary_lists_this_runs_rows_even_after_a_merge_rewrote_the_log(self):
        posted = []

        def fake_run(args, **kw):
            if args[0] == "node":
                log = Path(kw["env"]["ENTRANT_LOG"])
                log.write_text('{"id": 1, "result": "old"}\n{"id": 2, "result": "entered"}\n')
            return subprocess.CompletedProcess(args, 0, '[{"id": 2}]', "")

        def merge(root, message, paths):                    # a conflict merged other rows in at the front
            (root / "data/entries/log_reenter.jsonl").write_text('{"id": 9, "result": "other"}\n{"id": 1, "result": "old"}\n')

        with tempfile.TemporaryDirectory() as tmp, patched_env(ISSUE_TITLE="reenter x", ISSUE_NUMBER="7", ENTRANT_EMAIL="e"), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push", side_effect=merge), \
                mock.patch.object(runner, "github_request", side_effect=lambda *a: posted.append(a) or {}), \
                redirect_stdout(io.StringIO()):
            (Path(tmp) / "data/entries").mkdir(parents=True)
            (Path(tmp) / "data/entries/log_reenter.jsonl").write_text('{"id": 1, "result": "old"}\n')
            runner.run_reenter(Path(tmp))
        self.assertEqual(posted[0][2]["body"], "Re-entry results:\n- 2: entered")


class CostBounds(unittest.TestCase):
    """The loop and runaway limits from the cost audit (risks 3, 11, 12, 14)."""

    def test_issue_paging_is_capped(self):
        self.assertLessEqual(runner.MAX_ISSUE_PAGES, 10)
        pages = []

        def fake_request(method, path, payload=None):
            pages.append(path)
            return [{"title": "x"}]            # never ends: only the cap stops the loop

        with mock.patch.object(runner, "github_request", side_effect=fake_request):
            runner.create_alert_issues([])
        self.assertEqual(len(pages), runner.MAX_ISSUE_PAGES)

    def test_jackpots_pushes_data_before_issue_work(self):
        order = []

        def fake_run(args, **kw):
            Path(args[args.index("--alerts") + 1]).write_text("[]")
            return ok()

        with tempfile.TemporaryDirectory() as tmp, patched_env(), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push", side_effect=lambda *a: order.append("push")), \
                mock.patch.object(runner, "create_alert_issues", side_effect=lambda a: order.append("issues")):
            runner.run_jackpots(Path(tmp))
        self.assertEqual(order, ["push", "issues"])

    def test_comps_runs_with_a_cap_and_a_timeout(self):
        calls = []
        with patched_env(), mock.patch.object(runner.subprocess, "run", side_effect=lambda a, **kw: calls.append((a, kw)) or ok()), \
                mock.patch.object(runner, "push"), redirect_stdout(io.StringIO()):
            runner.run_comps(Path("."))
        args, kw = [c for c in calls if "workers.comps" in c[0]][0]
        self.assertEqual(args[args.index("--max") + 1], str(runner.COMPS_MAX_NEW))
        self.assertIsNotNone(kw["timeout"])

    def test_every_subprocess_step_has_a_timeout(self):
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            if args[2:3] == ["workers.site"]:
                Path(kw["cwd"], "site").mkdir(exist_ok=True)
                Path(kw["cwd"], "site/index.html").write_text("x")
            return subprocess.CompletedProcess(args, 0, "[{}]", "")

        with tempfile.TemporaryDirectory() as tmp, \
                patched_env(GITHUB_TOKEN="t", ENTRANT_EMAIL="e", ISSUE_TITLE="reenter 1", ISSUE_NUMBER="3",
                            SWA_DEPLOY_TOKEN="s"), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push"), \
                mock.patch.object(runner, "github_request", return_value=[]), redirect_stdout(io.StringIO()):
            root = Path(tmp)
            runner.run_draws(root)
            runner.run_entries(root)
            runner.run_reenter(root)
            runner.run_site(root)
        self.assertGreater(len(calls), 8)
        for args, kw in calls:
            self.assertIsNotNone(kw.get("timeout"), args)

    def test_blob_calls_are_bounded(self):
        # Every urlopen in blobsync has a timeout and the retry and merge loops are small (the cost guard checks too).
        self.assertLessEqual(runner.blobsync.HTTP_ATTEMPTS, 5)
        self.assertLessEqual(runner.blobsync.MERGE_RETRIES, 3)
        self.assertLessEqual(runner.blobsync.REQUEST_TIMEOUT_S, 120)

    def test_a_failed_upload_after_the_worker_still_raises(self):
        with tempfile.TemporaryDirectory() as tmp, patched_env(), \
                mock.patch.object(runner.subprocess, "run", side_effect=lambda a, **kw: ok()), \
                mock.patch.object(runner.blobsync, "local_files", return_value=[Path(tmp) / "x"]), \
                mock.patch.object(runner.blobsync, "push", side_effect=runner.blobsync.BlobError("conflict")), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(runner.blobsync.BlobError, "conflict"):
                runner.run_draws(Path(tmp))


class EntrantBounds(unittest.TestCase):
    def test_entrant_environment_is_bounded_by_default(self):
        with patched_env(ENTRANT_EMAIL="e"):
            env = runner.entrant_environment(Path("."))
        self.assertEqual(env["ENTRANT_CONCURRENCY"], "3")
        self.assertEqual(env["ENTRANT_MAX"], str(runner.ENTRANT_DEFAULT_MAX))
        budget, item = int(env["ENTRANT_BUDGET_S"]), int(env["ENTRANT_ITEM_TIMEOUT_S"])
        self.assertLess(budget + item, runner.entrant_timeout())

    def test_job_settings_win_over_defaults(self):
        with patched_env(ENTRANT_CONCURRENCY="2", ENTRANT_TIMEOUT_S="100"):
            env = runner.entrant_environment(Path("."))
        self.assertEqual(env["ENTRANT_CONCURRENCY"], "2")
        self.assertEqual(env["ENTRANT_BUDGET_S"], "10")

    def test_default_timeout_fits_the_entries_job(self):
        self.assertEqual(runner.entrant_timeout(), 150)

    def test_empty_queue_skips_node(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, patched_env(ENTRANT_EMAIL="e"), \
                mock.patch.object(runner.subprocess, "run", side_effect=lambda a, **kw: calls.append(a) or ok()), \
                mock.patch.object(runner, "push") as push, redirect_stdout(io.StringIO()):
            root = Path(tmp)
            (root / "data/entries").mkdir(parents=True)
            (root / "data/entries/queue.json").write_text("[]")
            runner.run_entries(root)
        self.assertFalse(any(c[0] == "node" for c in calls))
        push.assert_called_once()

    def test_queue_with_items_runs_node(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, patched_env(ENTRANT_EMAIL="e"), \
                mock.patch.object(runner.subprocess, "run", side_effect=lambda a, **kw: calls.append(a) or ok()), \
                mock.patch.object(runner, "push"), redirect_stdout(io.StringIO()):
            root = Path(tmp)
            (root / "data/entries").mkdir(parents=True)
            (root / "data/entries/queue.json").write_text('[{"id": 1}]')
            runner.run_entries(root)
        self.assertTrue(any(c[0] == "node" for c in calls))


if __name__ == "__main__":
    unittest.main()
