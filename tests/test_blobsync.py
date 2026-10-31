"""Offline tests for azure/blobsync.py (Blob storage sync for the Azure jobs): urllib is mocked, nothing leaves the box."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from http.client import HTTPMessage
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "azure"))
import blobsync  # noqa: E402

IDENTITY = {"IDENTITY_ENDPOINT": "http://identity.local/msi/token", "IDENTITY_HEADER": "hdr-secret",
            "AZURE_CLIENT_ID": "11111111-2222-3333-4444-555555555555"}
TOKEN = "tok-abcdef"
HOST = "stpersonalv5ethud2i3cfq.blob.core.windows.net"


class Response:
    def __init__(self, body=b"", status=200, headers=None):
        self._body, self.status = body, status
        self.headers = HTTPMessage()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeStorage:
    """An in-memory container behind urlopen: ETags, conditional PUTs, listing with paging, token endpoint."""

    def __init__(self, blobs=None, page=1000, create_conflict=412):
        self.blobs = {k: (v, 1) for k, v in (blobs or {}).items()}
        self.page, self.create_conflict = page, create_conflict
        self.calls = []                  # (method, url, headers, timeout)
        self.token_calls = 0
        self.before_put = None           # hook: called with (name) just before a PUT is evaluated
        self.fail_next = []              # statuses to answer before behaving normally

    def etag(self, name):
        return f'"0x{self.blobs[name][1]:04d}"'

    def set(self, name, data):
        old = self.blobs.get(name)
        self.blobs[name] = (data, (old[1] + 1) if old else 1)

    def text(self, name):
        return self.blobs[name][0].decode()

    def error(self, url, code):
        return urllib.error.HTTPError(url, code, "x", HTTPMessage(), io.BytesIO(b"<Error>detail</Error>"))

    def __call__(self, request, timeout=None):
        url, method = request.full_url, request.get_method()
        headers = {k.lower(): v for k, v in request.header_items()}
        self.calls.append((method, url, headers, timeout))
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc == "identity.local":
            self.token_calls += 1
            return Response(json.dumps({"access_token": TOKEN, "expires_on": str(int(time.time()) + 3600)}).encode())
        assert parsed.netloc == HOST, url
        assert headers.get("authorization") == f"Bearer {TOKEN}"
        assert headers.get("x-ms-version") == "2021-08-06"
        if self.fail_next:
            raise self.error(url, self.fail_next.pop(0))
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/lotto-data":
            return self.list(query)
        name = path[len("/lotto-data/"):]
        if method == "GET":
            if name not in self.blobs:
                raise self.error(url, 404)
            return Response(self.blobs[name][0], headers={"ETag": self.etag(name)})
        assert method == "PUT"
        if self.before_put:
            self.before_put(name)
        if headers.get("if-none-match") == "*" and name in self.blobs:
            raise self.error(url, self.create_conflict)
        if "if-match" in headers and (name not in self.blobs or headers["if-match"] != self.etag(name)):
            raise self.error(url, 412)
        assert headers.get("x-ms-blob-type") == "BlockBlob"
        self.set(name, request.data)
        return Response(status=201, headers={"ETag": self.etag(name)})

    def list(self, query):
        prefix = query["prefix"][0]
        names = sorted(n for n in self.blobs if n.startswith(prefix))
        start = int(query["marker"][0]) if "marker" in query else 0
        chunk = names[start:start + self.page]
        more = start + self.page < len(names)
        blobs = "".join(f"<Blob><Name>{n}</Name><Properties><Etag>{self.etag(n).strip(chr(34))}</Etag></Properties></Blob>"
                        for n in chunk)
        marker = f"<NextMarker>{start + self.page}</NextMarker>" if more else "<NextMarker />"
        return Response(f"<EnumerationResults><Blobs>{blobs}</Blobs>{marker}</EnumerationResults>".encode())

    def methods(self, method):
        return [c for c in self.calls if c[0] == method]

    def puts(self):
        return [urllib.parse.unquote(urllib.parse.urlparse(c[1]).path).split("/lotto-data/")[1]
                for c in self.methods("PUT")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, IDENTITY, clear=True)
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch.object(blobsync.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def serve(self, storage):
        patcher = mock.patch.object(blobsync.urllib.request, "urlopen", side_effect=storage)
        patcher.start()
        self.addCleanup(patcher.stop)
        return storage

    def store(self, blobs=None, **kw):
        storage = self.serve(FakeStorage(blobs, **kw))
        return blobsync.BlobStore(), storage

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def read(self, rel):
        return (self.root / rel).read_text()


class Token(Base):
    def test_token_comes_from_the_managed_identity_endpoint(self):
        store, storage = self.store()
        self.assertEqual(store.token(), TOKEN)
        method, url, headers, timeout = storage.calls[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(method, "GET")
        self.assertEqual(query["resource"], ["https://storage.azure.com/"])
        self.assertEqual(query["client_id"], [IDENTITY["AZURE_CLIENT_ID"]])
        self.assertEqual(query["api-version"], ["2019-08-01"])
        self.assertEqual(headers["x-identity-header"], "hdr-secret")
        self.assertEqual(timeout, blobsync.TOKEN_TIMEOUT_S)

    def test_token_is_cached_and_refreshed_near_expiry(self):
        store, storage = self.store()
        store.token()
        store.token()
        self.assertEqual(storage.token_calls, 1)
        store._expires = time.time() + 10          # inside the refresh margin
        store.token()
        self.assertEqual(storage.token_calls, 2)

    def test_system_assigned_identity_sends_no_client_id(self):
        del os.environ["AZURE_CLIENT_ID"]
        store, storage = self.store()
        store.token()
        self.assertNotIn("client_id", urllib.parse.parse_qs(urllib.parse.urlparse(storage.calls[0][1]).query))

    def test_placeholder_client_id_fails_before_any_call(self):
        os.environ["AZURE_CLIENT_ID"] = "USER_ASSIGNED_CLIENT_ID"
        store, storage = self.store()
        with self.assertRaisesRegex(blobsync.BlobError, "placeholder"):
            store.token()
        self.assertEqual(storage.calls, [])

    def test_missing_identity_environment(self):
        del os.environ["IDENTITY_ENDPOINT"]
        store, _ = self.store()
        with self.assertRaisesRegex(blobsync.BlobError, "managed identity"):
            store.token()

    def test_token_failure_does_not_echo_the_header_or_token(self):
        def boom(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 400, "bad", HTTPMessage(), io.BytesIO(b"hdr-secret"))
        with mock.patch.object(blobsync.urllib.request, "urlopen", side_effect=boom):
            with self.assertRaises(blobsync.BlobError) as ctx:
                blobsync.BlobStore().token()
        self.assertNotIn("hdr-secret", str(ctx.exception))

    def test_stale_token_is_refetched_once_on_401(self):
        store, storage = self.store({"data/a.csv": b"x"})
        storage.fail_next = [401]
        self.assertEqual(store.get("data/a.csv")[0], b"x")
        self.assertEqual(storage.token_calls, 2)


class Pull(Base):
    def test_pull_downloads_prefixes_and_records_etags(self):
        store, storage = self.store({
            "data/comps/comps.jsonl": b'{"id": 1}\n', "data/comps/odds.csv": b"a,b\n",
            "data/entries/log.jsonl": b'{"r": 1}\n', "data/draws/Powerball.csv": b"never pulled"})
        count = store.pull(("data/comps/", "data/entries/"), self.root)
        self.assertEqual(count, 3)
        self.assertEqual(self.read("data/comps/comps.jsonl"), '{"id": 1}\n')
        self.assertEqual(self.read("data/entries/log.jsonl"), '{"r": 1}\n')
        self.assertFalse((self.root / "data/draws").exists())
        self.assertEqual(store.etags["data/comps/odds.csv"], storage.etag("data/comps/odds.csv"))
        self.assertEqual(store.digests["data/comps/odds.csv"], blobsync.sha256(b"a,b\n"))

    def test_every_call_has_a_timeout_and_the_pinned_api_version(self):
        store, storage = self.store({"data/comps/a.csv": b"1"})
        store.pull(("data/comps/",), self.root)
        store.push([self.root / "data/comps/a.csv"])
        self.assertTrue(storage.calls)
        for _, _, headers, timeout in storage.calls:
            self.assertIsNotNone(timeout)
        for _, url, headers, _ in storage.calls:
            if HOST in url:
                self.assertEqual(headers["x-ms-version"], "2021-08-06")
                self.assertIn("x-ms-date", headers)

    def test_listing_follows_markers(self):
        blobs = {f"data/draws/{i:03d}.csv": str(i).encode() for i in range(7)}
        store, storage = self.store(blobs, page=3)
        self.assertEqual(store.pull(("data/draws/",), self.root), 7)
        gets = [c for c in storage.methods("GET") if HOST in c[1]]
        self.assertEqual(len(gets), 3 + 7)                         # 3 listing pages, 7 downloads

    def test_prefix_ends_at_the_folder(self):
        store, _ = self.store({"data/comps/a.csv": b"1", "data/comps2/b.csv": b"2"})
        store.pull(("data/comps/",), self.root)
        self.assertFalse((self.root / "data/comps2").exists())

    def test_empty_container_is_an_error_unless_allowed(self):
        store, _ = self.store({})
        with self.assertRaisesRegex(blobsync.BlobError, "migrate_data_to_blob"):
            store.pull(("data/draws/",), self.root)
        self.assertEqual(store.pull(("data/draws/",), self.root, allow_empty=True), 0)

    def test_module_pull_honours_lotto_allow_empty(self):
        _, _ = self.store({})
        with self.assertRaises(blobsync.BlobError):
            blobsync.pull(("data/draws/",), self.root)
        os.environ["LOTTO_ALLOW_EMPTY"] = "1"
        self.assertEqual(blobsync.pull(("data/draws/",), self.root), 0)

    def test_unsafe_blob_names_are_refused(self):
        for bad in ("../x", "data/../../x", "/abs", "data//x", ""):
            with self.assertRaises(blobsync.BlobError, msg=bad):
                blobsync.safe_name(bad)

    def test_account_and_container_come_from_the_environment(self):
        os.environ["LOTTO_DATA_ACCOUNT"] = "otheraccount1"
        self.assertEqual(blobsync.container_url(), "https://otheraccount1.blob.core.windows.net/lotto-data")
        os.environ["LOTTO_DATA_ACCOUNT"] = "evil.example.com/x"
        with self.assertRaises(blobsync.BlobError):
            blobsync.container_url()

    def test_transient_errors_are_retried_then_raised(self):
        store, storage = self.store({"data/a.csv": b"x"})
        storage.fail_next = [503, 429]
        self.assertEqual(store.get("data/a.csv")[0], b"x")
        storage.fail_next = [503, 503, 503]
        with self.assertRaises(blobsync.BlobHTTPError) as ctx:
            store.get("data/a.csv")
        self.assertEqual(ctx.exception.status, 503)

    def test_read_text_returns_none_for_a_missing_blob(self):
        _, storage = self.store({"data/entries/pace.json": b'{"a": 1}'})
        self.assertEqual(blobsync.read_text("data/entries/pace.json"), '{"a": 1}')
        self.assertIsNone(blobsync.read_text("data/entries/nope.json"))


class Push(Base):
    def pulled(self, blobs):
        store, storage = self.store(blobs)
        store.pull(("data/",), self.root)
        return store, storage

    def test_unchanged_files_are_not_uploaded(self):
        store, storage = self.pulled({"data/comps/a.csv": b"1\n", "data/comps/b.jsonl": b'{"a": 1}\n'})
        self.assertEqual(store.push(blobsync.local_files(self.root, ["data/comps"])), [])
        self.assertEqual(storage.puts(), [])

    def test_changed_file_is_uploaded_with_if_match_on_the_pulled_etag(self):
        store, storage = self.pulled({"data/comps/a.csv": b"1\n", "data/comps/b.csv": b"2\n"})
        etag = storage.etag("data/comps/a.csv")
        self.write("data/comps/a.csv", "1\n2\n")
        self.assertEqual(store.push(blobsync.local_files(self.root, ["data/comps"])), ["data/comps/a.csv"])
        _, _, headers, timeout = storage.methods("PUT")[0]
        self.assertEqual(headers["if-match"], etag)
        self.assertNotIn("if-none-match", headers)
        self.assertEqual(headers["x-ms-blob-type"], "BlockBlob")
        self.assertIsNotNone(timeout)
        self.assertEqual(storage.text("data/comps/a.csv"), "1\n2\n")
        self.assertEqual(storage.puts(), ["data/comps/a.csv"])

    def test_new_file_is_created_with_if_none_match_star(self):
        store, storage = self.pulled({"data/comps/a.csv": b"1\n"})
        self.write("data/comps/new.csv", "x\n")
        self.assertEqual(store.push([self.root / "data/comps/new.csv"]), ["data/comps/new.csv"])
        self.assertEqual(storage.methods("PUT")[0][2]["if-none-match"], "*")
        self.assertNotIn("if-match", storage.methods("PUT")[0][2])

    def test_a_second_push_is_a_no_op_and_etags_move_on(self):
        store, storage = self.pulled({"data/comps/a.csv": b"1\n"})
        self.write("data/comps/a.csv", "2\n")
        paths = [self.root / "data/comps/a.csv"]
        store.push(paths)
        store.push(paths)
        self.assertEqual(len(storage.puts()), 1)
        self.write("data/comps/a.csv", "3\n")
        store.push(paths)                                   # uses the ETag from the previous push
        self.assertEqual(storage.text("data/comps/a.csv"), "3\n")

    def test_missing_local_file_is_ignored(self):
        store, storage = self.pulled({"data/comps/a.csv": b"1\n"})
        (self.root / "data/comps/a.csv").unlink()
        self.assertEqual(store.push([self.root / "data/comps/a.csv"]), [])
        self.assertEqual(storage.puts(), [])

    def test_relative_paths_work_too(self):
        store, storage = self.pulled({"data/comps/a.csv": b"1\n"})
        self.write("data/comps/a.csv", "2\n")
        self.assertEqual(store.push([Path("data/comps/a.csv")]), ["data/comps/a.csv"])

    def test_path_outside_the_data_root_is_refused(self):
        store, _ = self.pulled({"data/comps/a.csv": b"1\n"})
        with self.assertRaises(blobsync.BlobError):
            store.push([Path("/etc/passwd")])

    def test_push_before_pull_is_an_error(self):
        store, _ = self.store()
        with self.assertRaises(blobsync.BlobError):
            store.push([self.root / "data/a.csv"])


class Conflicts(Base):
    LOG = "data/entries/log.jsonl"

    def pulled(self, blobs, **kw):
        store, storage = self.store(blobs, **kw)
        store.pull(("data/",), self.root)
        return store, storage

    def test_jsonl_412_is_union_merged_remote_first_and_retried(self):
        store, storage = self.pulled({self.LOG: b'{"n": 1}\n{"n": 2}\n'})
        self.write(self.LOG, '{"n": 1}\n{"n": 2}\n{"n": 3}\n')            # this run appended n=3
        storage.set(self.LOG, b'{"n": 1}\n{"n": 2}\n{"n": 9}\n')           # someone else appended n=9 meanwhile
        self.assertEqual(store.push([self.root / self.LOG]), [self.LOG])
        want = '{"n": 1}\n{"n": 2}\n{"n": 9}\n{"n": 3}\n'
        self.assertEqual(storage.text(self.LOG), want)
        self.assertEqual(self.read(self.LOG), want)                        # the local copy shows the merge too
        self.assertEqual(len(storage.puts()), 2)
        self.assertEqual(storage.methods("PUT")[1][2]["if-match"], '"0x0002"')       # the ETag of the remote it merged

    def test_merge_does_not_duplicate_lines_already_there(self):
        store, storage = self.pulled({self.LOG: b'{"n": 1}\n'})
        self.write(self.LOG, '{"n": 1}\n{"n": 2}\n')
        storage.set(self.LOG, b'{"n": 1}\n{"n": 2}\n')                     # the same line landed remotely
        store.push([self.root / self.LOG])
        self.assertEqual(storage.text(self.LOG), '{"n": 1}\n{"n": 2}\n')

    def test_jsonl_keeps_merging_while_others_keep_writing_up_to_three_retries(self):
        store, storage = self.pulled({self.LOG: b'{"n": 1}\n'})
        self.write(self.LOG, '{"n": 1}\n{"n": 2}\n')
        counter = {"n": 0}

        def interfere(name):
            if counter["n"] < 3:                                           # loses the race on the first 3 PUTs
                counter["n"] += 1
                storage.set(name, storage.blobs[name][0] + f'{{"x": {counter["n"]}}}\n'.encode())
        storage.before_put = interfere
        store.push([self.root / self.LOG])
        self.assertEqual(len(storage.puts()), 4)                           # 1 try + 3 retries
        self.assertEqual(storage.text(self.LOG).splitlines()[-1], '{"n": 2}')

    def test_jsonl_gives_up_after_three_retries(self):
        store, storage = self.pulled({self.LOG: b'{"n": 1}\n'})
        self.write(self.LOG, '{"n": 1}\n{"n": 2}\n')
        storage.before_put = lambda name: storage.set(name, storage.blobs[name][0] + b'{"x": 0}\n')
        with self.assertRaisesRegex(blobsync.BlobError, "still conflicting"):
            store.push([self.root / self.LOG])
        self.assertEqual(len(storage.puts()), blobsync.MERGE_RETRIES + 1)

    def test_new_jsonl_that_already_exists_remotely_is_merged_on_409(self):
        store, storage = self.pulled({"data/entries/other.csv": b"x"}, create_conflict=409)
        storage.set("data/jackpots/new.jsonl", b'{"remote": 1}\n')         # appeared after our pull
        self.write("data/jackpots/new.jsonl", '{"local": 1}\n')
        store.push([self.root / "data/jackpots/new.jsonl"])
        self.assertEqual(storage.text("data/jackpots/new.jsonl"), '{"remote": 1}\n{"local": 1}\n')

    def test_json_412_fails_loudly_and_keeps_the_remote(self):
        store, storage = self.pulled({"data/entries/pace.json": b'{"v": 1}'})
        self.write("data/entries/pace.json", '{"v": 2}')
        storage.set("data/entries/pace.json", b'{"v": 3}')
        with self.assertRaisesRegex(blobsync.BlobError, "pace.json.*kept"):
            store.push([self.root / "data/entries/pace.json"])
        self.assertEqual(storage.text("data/entries/pace.json"), '{"v": 3}')
        self.assertEqual(len(storage.puts()), 1)                           # no retry for non-registers

    def test_csv_conflict_is_not_merged_either(self):
        store, storage = self.pulled({"data/entries/register.csv": b"a\n"})
        self.write("data/entries/register.csv", "a\nb\n")
        storage.set("data/entries/register.csv", b"a\nc\n")
        with self.assertRaises(blobsync.BlobError):
            store.push([self.root / "data/entries/register.csv"])
        self.assertEqual(storage.text("data/entries/register.csv"), "a\nc\n")

    def test_a_failed_file_does_not_stop_the_others_and_registers_go_first(self):
        store, storage = self.pulled({self.LOG: b'{"n": 1}\n', "data/entries/queue.json": b"[]",
                                      "data/entries/manual.csv": b"m\n"})
        self.write(self.LOG, '{"n": 1}\n{"n": 2}\n')
        self.write("data/entries/queue.json", "[1]")
        self.write("data/entries/manual.csv", "m\nn\n")
        storage.set("data/entries/queue.json", b"[9]")                     # conflicts, cannot be merged
        paths = blobsync.local_files(self.root, ["data/entries"])
        with self.assertRaises(blobsync.BlobError) as ctx:
            store.push(paths)
        self.assertIn("queue.json", str(ctx.exception))
        self.assertIn("uploaded 2", str(ctx.exception))
        self.assertEqual(storage.puts()[0], self.LOG)                      # the register is saved first
        self.assertEqual(storage.text("data/entries/manual.csv"), "m\nn\n")
        self.assertEqual(storage.text("data/entries/queue.json"), "[9]")

    def test_merge_jsonl_unit(self):
        self.assertEqual(blobsync.merge_jsonl("a\nb\n", "b\nc\n\nc\n"), "a\nb\nc\n")
        self.assertEqual(blobsync.merge_jsonl("", ""), "")
        self.assertEqual(blobsync.merge_jsonl("a", "b"), "a\nb\n")


class Helpers(Base):
    def test_local_files_lists_files_under_folders_and_single_files(self):
        self.write("data/comps/a.csv", "1")
        self.write("data/comps/sub/b.jsonl", "2")
        self.write("data/entries/winners.csv", "3")
        self.write("data/entries/log.jsonl", "4")
        got = blobsync.local_files(self.root, ["data/comps", "data/entries/winners.csv", "data/none"])
        self.assertEqual([p.relative_to(self.root).as_posix() for p in got],
                         ["data/comps/a.csv", "data/comps/sub/b.jsonl", "data/entries/winners.csv"])

    def test_quote_etag(self):
        self.assertEqual(blobsync.quote_etag("0x1"), '"0x1"')
        self.assertEqual(blobsync.quote_etag('"0x1"'), '"0x1"')


if __name__ == "__main__":
    unittest.main()
