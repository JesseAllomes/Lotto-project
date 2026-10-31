"""Offline tests for the site actions: workers/actions.py (apply each kind), azure/actionqueue.py (queue REST) and the
`actions` mode of azure/runner.py (delete only after the upload, poison handling).  No network, no real storage."""
import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "azure"))

import actionqueue  # noqa: E402
import blobsync  # noqa: E402
from workers import actions, comps  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("azure_runner_actions", REPO / "azure" / "runner.py")
api = load("lotto_actions_api_for_actions", REPO / "azure" / "site-api" / "lotto_actions.py")

FORM = "**How do I enter the competition?** Complete the online entry form. **How is the winner selected?** Random draw."


def rec(i, title="Win a Wine Hamper", closes="2099-12-01T23:59:59+10:00", **kw):
    return {"id": i, "title": title, "brand": "Shop", "prize_pool": 500.0, "closes": closes, "open_to_vic": True,
            "entry_url": f"https://shop.example/{i}", "url": f"u{i}", "description": kw.get("description", FORM)}


def message_text(kind, ids, answer=None, ident=None, t=1_760_000_000_000):
    doc = {"v": 1, "id": ident or os.urandom(16).hex(), "t": t, "kind": kind, "ids": ids}
    if answer is not None:
        doc["answer"] = answer
    return base64.b64encode(json.dumps(doc).encode()).decode()


def patched_env(**extra):
    return mock.patch.dict(os.environ, extra, clear=True)


class Data(unittest.TestCase):
    """A scratch data root with a few listings (comps) and an empty entries folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store, self.entries = self.root / "data" / "comps", self.root / "data" / "entries"
        self.entries.mkdir(parents=True)
        comps.append(self.store, [rec(10001), rec(10002, "Win a $500 Bunnings Voucher"), rec(10003, closes="2020-01-01T00:00:00+10:00"),
                                  rec(10004, "Win a Trip", description=FORM + " In 10 words or less, tell us why.")], "t")

    def rows(self, name):
        path = self.entries / name
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


class Parse(unittest.TestCase):
    def test_a_message_from_the_api_parses(self):
        text = api.message_text({"kind": "answer", "ids": ["10001"], "answer": "Because."})
        a = actions.parse(text)
        self.assertEqual((a["kind"], a["ids"], a["answer"]), ("answer", ["10001"], "Because."))
        self.assertRegex(a["id"], r"^[0-9a-f]{32}$")

    def test_plain_json_is_accepted_too(self):
        doc = {"v": 1, "id": "a" * 32, "t": 5, "kind": "done", "ids": ["10001"]}
        self.assertEqual(actions.parse(json.dumps(doc))["kind"], "done")

    def test_rejects_what_can_never_work(self):
        good = {"v": 1, "id": "a" * 32, "t": 5, "kind": "remove", "ids": ["10001"]}
        for patch in ({"kind": "wipe"}, {"ids": []}, {"ids": ["abc"]}, {"ids": [10001]}, {"id": "short"}, {"t": "now"}, {"t": True},
                      {"extra": 1}, {"answer": "x"}, {"ids": [str(10000 + i) for i in range(51)]}):
            with self.assertRaises(actions.Rejected, msg=patch):
                actions.parse(json.dumps({**good, **patch}))
        for text in ("", "not json", "[]", "null", base64.b64encode(b"\xff").decode(), "A" * 200_000):
            with self.assertRaises(actions.Rejected, msg=text[:20]):
                actions.parse(text)
        with self.assertRaises(actions.Rejected):
            actions.parse(json.dumps({**good, "kind": "answer", "ids": ["10001", "10002"], "answer": "x"}))
        with self.assertRaises(actions.Rejected):
            actions.parse(json.dumps({**good, "kind": "answer", "answer": "x" * 2001}))

    def test_worker_and_api_agree_on_the_limits(self):
        for name in ("KINDS", "MAX_IDS", "MAX_ANSWER_CHARS"):
            self.assertEqual(getattr(actions, name), getattr(api, name), name)
        self.assertEqual(actions.ID_RE.pattern, api.ID_RE.pattern)

    def test_worker_and_api_agree_on_requests(self):
        cases = [{"kind": k, "ids": ["10001"]} for k in api.KINDS if k != "answer"] + [
            {"kind": "answer", "ids": ["10001"], "answer": "ok"}, {"kind": "answer", "ids": ["10001"]},
            {"kind": "answer", "ids": ["10001"], "answer": ""}, {"kind": "remove", "ids": ["1"]},
            {"kind": "remove", "ids": ["10001", "10001"]}, {"kind": "remove", "ids": ["10001"], "answer": "x"},
            {"kind": "remove"}, {"ids": ["10001"]}, {"kind": "remove", "ids": "10001"}]
        for doc in cases:
            try:
                want = api.validate(doc)
            except api.Invalid:
                want = None
            try:
                got = actions.validate({"v": 1, "id": "b" * 32, "t": 9, **doc})
                got = {k: v for k, v in got.items() if k not in ("id", "t")}
            except actions.Rejected:
                got = None
            self.assertEqual(got, want, doc)


class Apply(Data):
    def apply(self, kind, ids, answer=None, t=1_760_000_000_000):
        a = {"id": os.urandom(16).hex(), "t": t, "kind": kind, "ids": ids}
        if answer is not None:
            a["answer"] = answer
        return actions.apply_one(a, self.store, self.entries)

    def test_remove_and_broken(self):
        self.assertEqual(self.apply("remove", ["10001", "99999"])[0], "applied")
        self.assertEqual(self.apply("broken", ["10002"])[0], "applied")
        rows = self.rows("log_removed.jsonl")
        self.assertEqual([(r["id"], r["why"], r["result"]) for r in rows],
                         [(10001, "not for me", "removed"), (10002, "doesn't work", "removed")])
        self.assertEqual(self.apply("remove", ["10001"])[1], "remove: recorded 0 of 1")          # already removed

    def test_answer_saved_within_the_limit_and_refused_over_it(self):
        outcome, detail = self.apply("answer", ["10004"], "Because it looks like a lot of fun")
        self.assertEqual(outcome, "applied", detail)
        self.assertEqual(json.loads((self.entries / "answers.json").read_text())["10004"], "Because it looks like a lot of fun")
        outcome, detail = self.apply("answer", ["10004"], "one two three four five six seven eight nine ten eleven")
        self.assertEqual(outcome, "rejected")
        self.assertIn("limit is 10", detail)
        self.assertEqual(json.loads((self.entries / "answers.json").read_text())["10004"], "Because it looks like a lot of fun")
        self.assertEqual(self.apply("answer", ["99999"], "x")[0], "rejected")                    # not in the register

    def test_answer_containing_a_dash_line_is_kept_whole_after_the_first_marker(self):
        self.assertEqual(self.apply("answer", ["10001"], "fun --- and games")[0], "applied")
        self.assertEqual(json.loads((self.entries / "answers.json").read_text())["10001"], "fun --- and games")

    def test_done_and_undone_share_one_file(self):
        self.apply("done", ["10001", "10002"], t=100)
        self.apply("done", ["10001"], t=50)                                                      # an older tick never moves it back
        self.assertEqual(json.loads((self.entries / "done.json").read_text()), {"10001": 100, "10002": 100})
        self.apply("undone", ["10001", "55555"])
        self.assertEqual(actions.load_done(self.entries), {"10002": 100})
        from workers import site
        self.assertEqual(site.load_done(self.entries), {"10002": 100})

    def test_reenter_is_left_to_the_runner(self):
        self.assertEqual(self.apply("reenter", ["10001"])[0], "pending")

    def test_reenter_plan_skips_closed_unknown_and_removed_and_honours_the_cap(self):
        self.apply("remove", ["10002"])
        (self.entries / "answers.json").write_text(json.dumps({"10001": "Because."}))
        plan = actions.plan_reenter(["10001", "10002", "10003", "99999", "10001"], self.store, self.entries)
        self.assertEqual(plan, [{"id": 10001, "entry_url": "https://shop.example/10001", "answer": "Because."}])
        self.assertEqual(len(actions.plan_reenter(["10001", "10004"], self.store, self.entries, limit=1)), 1)

    def test_audit_rows_are_not_named_log(self):
        a = {"id": "c" * 32, "t": 1, "kind": "remove", "ids": ["10001"]}
        actions.record_result(self.entries, a, "applied", "x" * 1000)
        self.assertFalse(actions.APPLIED_FILE.startswith("log"))
        self.assertEqual(actions.applied_ids(self.entries), {"c" * 32})
        self.assertLessEqual(len(self.rows(actions.APPLIED_FILE)[0]["detail"]), 300)


class FakeQueue:
    """The ActionQueue surface the runner uses; events show the order of the queue and upload calls."""

    def __init__(self, messages, events):
        self.messages, self.events, self.received_with = list(messages), events, None

    def has_messages(self):
        self.events.append("peek")
        return bool(self.messages)

    def receive(self, count, visibility_s):
        self.received_with = (count, visibility_s)
        self.events.append("receive")
        return self.messages[:count]

    def delete(self, message):
        self.events.append(f"delete {message.id}")

    def move_to_poison(self, message):
        self.events.append(f"poison {message.id}")


def qm(ident, text, count=1):
    return actionqueue.QueueMessage(ident, "pop-" + ident, count, text)


class RunActions(Data):
    def run_it(self, messages, push=None, env=None, run=None, queue=None, expect=None):
        queue = queue or FakeQueue(messages, [])
        self.events = queue.events
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            if run:
                run(args, kw)
            return subprocess.CompletedProcess(args, 0, "", "")

        def fake_push(root, message, paths):
            self.events.append("push")
            if push:
                push()

        def prepare(job):
            self.events.append(f"prepare {job}")
            return self.root

        env = dict({"ENTRANT_EMAIL": "e@example.com"}, **(env or {}))
        out = io.StringIO()
        error = None
        with patched_env(**env), mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push", side_effect=fake_push), mock.patch.object(runner, "prepare", side_effect=prepare), \
                redirect_stdout(out):
            try:
                runner.run_actions(queue=queue)
            except Exception as exc:                     # noqa: BLE001
                error = exc
        self.calls, self.out, self.queue = calls, out.getvalue(), queue
        return error

    def deleted(self):
        return [e.split()[1] for e in self.events if e.startswith("delete")]

    def test_deletes_only_after_the_upload(self):
        a, b = os.urandom(16).hex(), os.urandom(16).hex()
        error = self.run_it([qm("m1", message_text("remove", ["10001"], ident=a)), qm("m2", message_text("done", ["10002"], ident=b))])
        self.assertIsNone(error)
        self.assertEqual(self.events, ["peek", "prepare actions", "receive", "push", "delete m1", "delete m2"])
        self.assertEqual(self.queue.received_with, (20, 900))
        self.assertEqual(self.rows("log_removed.jsonl")[0]["id"], 10001)
        self.assertEqual(actions.load_done(self.entries), {"10002": 1_760_000_000_000})
        self.assertEqual(sorted(r["action_id"] for r in self.rows(actions.APPLIED_FILE)), sorted([a, b]))
        modules = [args[2] for args, _ in self.calls if args[1:2] == ["-m"]]
        self.assertEqual(modules, ["workers.entry_queue", "workers.removals"])       # the queue and PREFERENCES.md are rebuilt
        for _, kw in self.calls:
            self.assertIsNotNone(kw.get("timeout"))

    def test_a_failed_upload_deletes_nothing_and_fails_the_run(self):
        def boom():
            raise blobsync.BlobError("conflict")

        error = self.run_it([qm("m1", message_text("remove", ["10001"]))], push=boom)
        self.assertIsInstance(error, blobsync.BlobError)
        self.assertEqual(self.deleted(), [])
        self.assertNotIn("poison", " ".join(self.events))

    def test_nothing_waiting_pulls_nothing(self):
        self.assertIsNone(self.run_it([]))
        self.assertEqual(self.events, ["peek"])
        self.assertIn("No actions waiting", self.out)

    def test_messages_taken_by_someone_else_in_between_pull_but_change_nothing(self):
        queue = FakeQueue([qm("m1", message_text("remove", ["10001"]))], [])
        queue.receive = lambda c, v: []
        self.assertIsNone(self.run_it([], queue=queue))
        self.assertEqual(self.deleted(), [])

    def test_a_message_that_cannot_be_applied_is_retried_not_deleted(self):
        with mock.patch.object(actions, "apply_one", side_effect=[OSError("disk"), ("applied", "ok")]):
            error = self.run_it([qm("m1", message_text("remove", ["10001"])), qm("m2", message_text("remove", ["10002"]))])
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(self.deleted(), ["m2"])                                    # the good one is still applied and deleted
        self.assertIn("push", self.events)

    def test_a_refused_answer_is_recorded_and_deleted_not_retried(self):
        error = self.run_it([qm("m1", message_text("answer", ["10004"], "one two three four five six seven eight nine ten eleven"))])
        self.assertIsNone(error)
        self.assertEqual(self.deleted(), ["m1"])
        row = self.rows(actions.APPLIED_FILE)[0]
        self.assertEqual((row["outcome"], row["kind"]), ("rejected", "answer"))
        self.assertFalse((self.entries / "answers.json").exists())

    def test_a_redelivered_message_is_deleted_without_being_applied_again(self):
        ident = os.urandom(16).hex()
        self.run_it([qm("m1", message_text("remove", ["10001"], ident=ident))])
        with mock.patch.object(actions, "apply_one") as apply:
            self.run_it([qm("m1b", message_text("remove", ["10001"], ident=ident))])
        apply.assert_not_called()
        self.assertEqual(self.deleted(), ["m1b"])
        self.assertEqual(len(self.rows("log_removed.jsonl")), 1)

    def test_poison_after_three_reads(self):
        text = message_text("remove", ["10001"])
        error = self.run_it([qm("m3", text, count=3), qm("m4", text, count=4), qm("m9", text, count=9)])
        self.assertIsNone(error)
        self.assertEqual([e for e in self.events if e.startswith(("poison", "delete"))], ["poison m4", "poison m9", "delete m3"])
        self.assertEqual(len(self.rows("log_removed.jsonl")), 1)                    # m3 was applied, m4 and m9 never

    def test_a_malformed_message_goes_straight_to_the_poison_queue(self):
        error = self.run_it([qm("bad", "this is not a message"), qm("ok", message_text("remove", ["10001"]))])
        self.assertIsNone(error)
        self.assertEqual([e for e in self.events if e.startswith(("poison", "delete"))], ["poison bad", "delete ok"])

    def test_a_failed_poison_move_does_not_stop_the_others(self):
        class Queue(FakeQueue):
            def move_to_poison(self, message):
                raise blobsync.BlobError("no such queue")

        queue = Queue([qm("bad", "nope"), qm("ok", message_text("remove", ["10001"]))], [])
        self.assertIsNone(self.run_it([], queue=queue))
        self.assertEqual(self.deleted(), ["ok"])
        self.assertIn("Could not move", self.out)

    def test_dry_run_changes_nothing_in_azure(self):
        error = self.run_it([qm("m1", message_text("remove", ["10001"])), qm("p", "junk")], env={"DRY_RUN": "1"})
        self.assertIsNone(error)
        self.assertEqual([e for e in self.events if e.startswith(("poison", "delete"))], [])
        self.assertIn("DRY_RUN", self.out)

    def test_at_most_twenty_messages_a_run(self):
        self.assertEqual(runner.MAX_ACTIONS_PER_RUN, 20)
        self.assertEqual(runner.ACTIONS_MAX_DEQUEUE, 3)
        self.assertGreater(runner.ACTIONS_VISIBILITY_S, 600)          # longer than the job's replicaTimeout
        msgs = [qm(f"m{i}", message_text("done", ["10001"])) for i in range(30)]
        self.run_it(msgs)
        self.assertEqual(len(self.deleted()), 20)

    # ------------------------------------------------------------------------------------------------ re-entry
    def entrant_calls(self):
        return [(a, kw) for a, kw in self.calls if a[0] == "node"]

    def test_reenter_runs_the_entrant_once_for_the_whole_batch_with_the_existing_limits(self):
        queue_seen = []

        def run(args, kw):
            if args[0] == "node":
                queue_seen.append(json.loads(Path(kw["env"]["ENTRANT_QUEUE"]).read_text()))

        error = self.run_it([qm("r1", message_text("reenter", ["10001", "10003"])), qm("r2", message_text("reenter", ["10002", "10001"]))], run=run)
        self.assertIsNone(error)
        (args, kw), = self.entrant_calls()
        self.assertEqual(kw["timeout"], 150)
        self.assertEqual(kw["env"]["ENTRANT_LOG"], str(self.root / "data/entries/log_reenter.jsonl"))
        self.assertEqual((kw["env"]["ENTRANT_CONCURRENCY"], kw["env"]["ENTRANT_MAX"]), ("3", "30"))
        self.assertLess(int(kw["env"]["ENTRANT_BUDGET_S"]) + int(kw["env"]["ENTRANT_ITEM_TIMEOUT_S"]), 150)
        self.assertNotIn("ENTRANT_PROFILE_JSON", kw["env"])
        self.assertEqual([x["id"] for x in queue_seen[0]], [10001, 10002])         # closed 10003 left out, no duplicates
        self.assertEqual(self.deleted(), ["r1", "r2"])
        self.assertLess(self.events.index("push"), self.events.index("delete r1"))

    def test_reenter_skips_comps_removed_in_the_same_batch(self):
        queue_seen = []

        def run(args, kw):
            if args[0] == "node":
                queue_seen.append(json.loads(Path(kw["env"]["ENTRANT_QUEUE"]).read_text()))

        self.run_it([qm("a", message_text("remove", ["10001"])), qm("b", message_text("reenter", ["10001", "10002"]))], run=run)
        self.assertEqual([x["id"] for x in queue_seen[0]], [10002])

    def test_reenter_cap_comes_from_entrant_max(self):
        queue_seen = []

        def run(args, kw):
            if args[0] == "node":
                queue_seen.append(json.loads(Path(kw["env"]["ENTRANT_QUEUE"]).read_text()))

        self.run_it([qm("r", message_text("reenter", ["10001", "10002", "10004"]))], run=run, env={"ENTRANT_MAX": "2"})
        self.assertEqual(len(queue_seen[0]), 2)

    def test_nothing_open_to_reenter_starts_no_browser_but_is_handled(self):
        error = self.run_it([qm("r", message_text("reenter", ["10003", "99999"]))])
        self.assertIsNone(error)
        self.assertEqual(self.entrant_calls(), [])
        self.assertEqual(self.deleted(), ["r"])

    def test_reenter_without_the_profile_stays_on_the_queue_but_the_rest_is_applied(self):
        self.events = []
        queue = FakeQueue([qm("r", message_text("reenter", ["10001"])), qm("d", message_text("done", ["10002"]))], self.events)
        out = io.StringIO()
        with patched_env(), mock.patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                mock.patch.object(runner, "push"), mock.patch.object(runner, "prepare", return_value=self.root), redirect_stdout(out):
            with self.assertRaises(RuntimeError):
                runner.run_actions(queue=queue)
        self.assertEqual(self.deleted(), ["d"])
        self.assertIn("profile is not set", out.getvalue())
        with patched_env(ENTRANT_EMAIL="e"), mock.patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                mock.patch.object(runner, "push"), mock.patch.object(runner, "prepare", return_value=self.root), redirect_stdout(io.StringIO()):
            self.events.clear()
            with self.assertRaises(RuntimeError):
                runner.run_actions(profile_ok=False, queue=FakeQueue([qm("r", message_text("reenter", ["10001"]))], self.events))
        self.assertEqual(self.deleted(), [])

    def test_a_failed_entrant_leaves_the_reenter_message_for_a_retry(self):
        def run(args, kw):
            if args[0] == "node":
                raise subprocess.CalledProcessError(1, args)

        def fake_run(args, **kw):
            run(args, kw)
            return subprocess.CompletedProcess(args, 0, "", "")

        self.events = []
        queue = FakeQueue([qm("r", message_text("reenter", ["10001"])), qm("x", message_text("remove", ["10002"]))], self.events)
        with patched_env(ENTRANT_EMAIL="e"), mock.patch.object(runner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(runner, "push"), mock.patch.object(runner, "prepare", return_value=self.root), redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                runner.run_actions(queue=queue)
        self.assertEqual(self.deleted(), ["x"])

    def test_dry_run_never_submits(self):
        envs = []

        def run(args, kw):
            if args[0] == "node":
                envs.append(kw["env"])

        self.run_it([qm("r", message_text("reenter", ["10001"]))], run=run, env={"DRY_RUN": "1", "ENTRANT_LIVE": "1"})
        self.assertEqual(envs[0]["ENTRANT_LIVE"], "0")
        self.assertEqual(self.deleted(), [])


class Main(unittest.TestCase):
    def test_actions_is_a_known_mode_with_its_own_data_and_upload_paths(self):
        self.assertEqual(runner.DATA_PREFIXES["actions"], ("data/comps/", "data/entries/"))
        self.assertEqual(runner.PUSH_PATHS["actions"], ("data/entries",))

    def test_main_dispatches_without_pulling_first(self):
        with patched_env(), mock.patch.object(runner, "run_actions") as run, mock.patch.object(runner, "prepare") as prepare, \
                mock.patch.object(runner.signal, "signal"):
            self.assertEqual(runner.main(["actions"]), 0)
        run.assert_called_once_with(profile_ok=True)
        prepare.assert_not_called()

    def test_kill_switch_leaves_the_queue_alone(self):
        with patched_env(AZURE_JOBS_DISABLED="1"), mock.patch.object(runner, "run_actions") as run, \
                mock.patch.object(runner.signal, "signal"), redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["actions"]), 0)
        run.assert_not_called()

    def test_a_bad_profile_does_not_stop_removals_and_answers(self):
        with patched_env(ENTRANT_PROFILE_JSON="{bad"), mock.patch.object(runner, "run_actions") as run, \
                mock.patch.object(runner.signal, "signal"):
            self.assertEqual(runner.main(["actions"]), 0)
        run.assert_called_once_with(profile_ok=False)


class QueueRest(unittest.TestCase):
    """azure/actionqueue.py against a fake storage: URLs, parameters and parsing."""

    XML = (b'<?xml version="1.0"?><QueueMessagesList>'
           b"<QueueMessage><MessageId>id-1</MessageId><PopReceipt>AgAAAA==/x+y</PopReceipt><DequeueCount>2</DequeueCount>"
           b"<MessageText>dGV4dA==</MessageText></QueueMessage></QueueMessagesList>")

    def queue(self, body=XML):
        store = mock.Mock()
        store.request.return_value = (200, {}, body)
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"):
            return actionqueue.ActionQueue(store), store

    def test_receive_parses_and_bounds_the_request(self):
        q, store = self.queue()
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"):
            got = q.receive(500, 900)
        self.assertEqual(got, [actionqueue.QueueMessage("id-1", "AgAAAA==/x+y", 2, "dGV4dA==")])
        method, url = store.request.call_args.args
        self.assertEqual(method, "GET")
        self.assertTrue(url.startswith("https://stacct.queue.core.windows.net/lotto-actions/messages?"))
        self.assertIn("numofmessages=32", url)
        self.assertIn("visibilitytimeout=900", url)

    def test_peek_does_not_touch_visibility(self):
        q, store = self.queue()
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"):
            self.assertTrue(q.has_messages())
        self.assertIn("peekonly=true", store.request.call_args.args[1])
        q, _ = self.queue(b"<QueueMessagesList />")
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"):
            self.assertFalse(q.has_messages())

    def test_delete_quotes_the_pop_receipt(self):
        q, store = self.queue()
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"):
            q.delete(actionqueue.QueueMessage("id-1", "AgAAAA==/x+y", 1, "t"))
        method, url = store.request.call_args.args
        self.assertEqual(method, "DELETE")
        self.assertIn("/lotto-actions/messages/id-1?popreceipt=AgAAAA%3D%3D%2Fx%2By", url)

    def test_poison_move_copies_then_deletes_and_a_failed_copy_keeps_the_message(self):
        q, store = self.queue()
        message = actionqueue.QueueMessage("id-1", "pop", 4, "a<b&c")
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"):
            q.move_to_poison(message)
        (m1, u1), k1 = store.request.call_args_list[0].args, store.request.call_args_list[0].kwargs
        self.assertEqual((m1, k1["body"]), ("POST", b"<QueueMessage><MessageText>a&lt;b&amp;c</MessageText></QueueMessage>"))
        self.assertIn("/lotto-actions-poison/messages", u1)
        self.assertEqual(store.request.call_args_list[1].args[0], "DELETE")
        self.assertIn("/lotto-actions/messages/id-1", store.request.call_args_list[1].args[1])
        store.request.reset_mock()
        store.request.side_effect = blobsync.BlobHTTPError(404)
        with patched_env(LOTTO_DATA_ACCOUNT="stacct"), self.assertRaises(blobsync.BlobError):
            q.move_to_poison(message)
        self.assertEqual(store.request.call_count, 1)

    def test_names_are_validated(self):
        with patched_env(ACTIONS_QUEUE="Bad_Name"), self.assertRaises(blobsync.BlobError):
            actionqueue.ActionQueue(mock.Mock())
        with patched_env(LOTTO_DATA_ACCOUNT="x"):
            q = actionqueue.ActionQueue(mock.Mock())
            with self.assertRaises(blobsync.BlobError):
                q.url()

    def test_unreadable_listing(self):
        q, _ = self.queue(b"<<<")
        with self.assertRaises(blobsync.BlobError):
            q.receive(1, 1)

    def test_every_call_goes_through_the_bounded_blob_request(self):
        source = (REPO / "azure" / "actionqueue.py").read_text()
        self.assertNotIn("urlopen", source)               # blobsync.BlobStore.request adds the timeout, retries and token


if __name__ == "__main__":
    unittest.main()
