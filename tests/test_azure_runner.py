"""Offline tests for the Azure Container Apps Jobs launcher (azure/runner.py): no network, no real git."""
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
SECRETS = {"GITHUB_TOKEN": "tok-123", "ENTRANT_PROFILE_JSON": json.dumps(PROFILE),
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "k", "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic abc"}


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
                    mock.patch.object(runner, "checkout") as checkout:
                code, out, err = run_main([job])
            self.assertEqual(code, 1, job)
            self.assertIn("not valid JSON", err)
            self.assertNotIn("secret-value", out + err)
            checkout.assert_not_called()

    def test_bad_profile_does_not_stop_draws(self):
        with patched_env(ENTRANT_PROFILE_JSON="{bad"), \
                mock.patch.object(runner, "checkout", return_value=(Path("."), {})) as checkout, \
                mock.patch.object(runner, "run_draws") as draws:
            code, _, _ = run_main(["draws"])
        self.assertEqual(code, 0)
        checkout.assert_called_once()
        draws.assert_called_once()

    def test_bad_profile_skips_only_the_winners_check_in_comps(self):
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            return ok()

        with patched_env(), mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push") as push, redirect_stdout(io.StringIO()):
            runner.run_comps(Path("."), {}, profile_ok=False)
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

    def git_calls(self, dry):
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            return ok(1 if args[:2] == ["git", "diff"] else 0)   # diff --cached --quiet exits 1: changes staged

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            with patched_env(**({"DRY_RUN": "1"} if dry else {})), \
                    mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                    redirect_stdout(io.StringIO()):
                result = runner.push(Path(tmp), {}, "msg", ["data"])
        return result, [c[1] for c in calls if c[0] == "git"]

    def test_dry_run_skips_commit_and_push(self):
        result, verbs = self.git_calls(dry=True)
        self.assertFalse(result)
        self.assertNotIn("push", verbs)
        self.assertNotIn("commit", verbs)

    def test_push_happens_without_dry_run(self):
        result, verbs = self.git_calls(dry=False)
        self.assertTrue(result)
        self.assertIn("push", verbs)

    def test_dry_run_skips_the_entry_commit_and_forces_entrant_dry(self):
        with patched_env(DRY_RUN="1", ENTRANT_LIVE="1"), mock.patch.object(runner, "command") as command:
            with redirect_stdout(io.StringIO()):
                runner.commit_entries(Path("."), {}, "m")
            command.assert_not_called()
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
                mock.patch.object(runner, "checkout", return_value=(Path("."), {})) as checkout, \
                mock.patch.object(runner, "run_entries") as run_entries:
            code, out, _ = run_main(["entries"])
        return code, out, checkout.called, run_entries.called

    def test_not_due_exits_without_cloning(self):
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
    def test_site_exits_without_cloning(self):
        with patched_env(), mock.patch.object(runner, "checkout") as checkout:
            code, out, _ = run_main(["site"])
        self.assertEqual(code, 0)
        self.assertIn("GitHub Pages", out)
        checkout.assert_not_called()


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
    def test_current_pace_falls_back_on_timeout_and_oserror(self):
        for exc in (TimeoutError("slow"), OSError("reset"), runner.urllib.error.URLError("x")):
            with mock.patch.object(runner, "github_request", side_effect=exc):
                self.assertEqual(runner.current_pace()["next_run_minutes"], 180)


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

    def test_git_keeps_its_auth_header_but_not_the_token_or_profile(self):
        with patched_env(ENTRANT_EMAIL="e", **{k: v for k, v in SECRETS.items() if k == "GITHUB_TOKEN"
                                              or k == "ENTRANT_PROFILE_JSON"}):
            env = runner.git_environment()
        self.assertTrue(env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic "))
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.https://github.com/.extraheader")
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("ENTRANT_PROFILE_JSON", env)
        self.assertNotIn("ENTRANT_EMAIL", env)

    def test_comps_children_see_only_what_they_need(self):
        seen = {}

        def fake_run(args, **kw):
            seen[args[2] if args[1] == "-m" else args[0]] = kw["env"]
            return ok()

        with patched_env(PATH="/bin", ENTRANT_LAST_NAME="Lee", ENTRANT_EMAIL="e", **SECRETS), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push"), redirect_stdout(io.StringIO()):
            runner.run_comps(Path("."), {})
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
                runner.run_comps(Path("."), {})
            except subprocess.CalledProcessError as exc:
                error = exc
        return calls, push, error

    def test_continues_after_comp_terms_timeout_and_still_pushes(self):
        calls, push, error = self.run_comps("workers.comp_terms")
        names = [c[0][2] for c in calls]
        self.assertEqual(names[-3:], ["workers.comp_odds", "analysis.skill_rank", "workers.winners"])
        self.assertIsNone(error)
        push.assert_called_once()
        timeouts = {c[0][2]: c[1]["timeout"] for c in calls}
        self.assertEqual(timeouts["workers.source_auscomps"], 25 * 60)
        self.assertEqual(timeouts["workers.comp_terms"], 30 * 60)

    def test_auscomps_failure_does_not_abort(self):
        calls, push, error = self.run_comps("workers.source_auscomps")
        self.assertIsNone(error)
        self.assertEqual(len(calls), 6)
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
                redirect_stdout(io.StringIO()):
            try:
                runner.run_entries(Path("."), {"GIT": "1"})
            except subprocess.TimeoutExpired as exc:
                error = exc
        return calls, error

    def test_timeout_still_commits(self):
        calls, error = self.run_entries()
        self.assertIsNotNone(error)
        node = [kw for args, kw in calls if args[0] == "node"][0]
        self.assertEqual(node["timeout"], 420)
        self.assertEqual(calls[-1][0][:2], ["bash", "workers/commit_entries.sh"])
        self.assertEqual(calls[-1][1]["env"], {"GIT": "1"})

    def test_timeout_is_configurable(self):
        calls, _ = self.run_entries(ENTRANT_TIMEOUT_S="90")
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
            return subprocess.CompletedProcess(args, 0, "[]", "")

        with tempfile.TemporaryDirectory() as tmp, patched_env(ISSUE_TITLE="reenter x", ISSUE_NUMBER="7"), \
                mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "github_request", side_effect=lambda *a: posted.append(a) or {}), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.run_reenter(Path(tmp), {})
        self.assertEqual([p[0] for p in posted], ["POST", "PATCH"])
        self.assertIn("Re-entry failed", posted[0][2]["body"])
        self.assertEqual(posted[1][2], {"state": "closed"})


if __name__ == "__main__":
    unittest.main()
