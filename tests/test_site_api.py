"""Offline tests for the Static Web App API (azure/site-api): validation, the owner role, the queue SAS, 202."""
import base64
import importlib.util
import io
import json
import sys
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

API = Path(__file__).resolve().parent.parent / "azure" / "site-api"
SPEC = importlib.util.spec_from_file_location("lotto_actions_api", API / "lotto_actions.py")
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)

SIG = "SIGNATURE" + "abcdef0123456789" * 3                    # never appears in a log or a response
SAS = f"https://stpersonalv5ethud2i3cfq.queue.core.windows.net/lotto-actions?sv=2022-11-02&sp=a&se=2027-01-01&sig={SIG}"
ENV = {"ACTIONS_QUEUE_SAS": SAS}


def principal(roles=("anonymous", "authenticated", "owner"), user="owner-login"):
    doc = {"identityProvider": "github", "userId": "1", "userDetails": user, "userRoles": list(roles)}
    return base64.b64encode(json.dumps(doc).encode()).decode()


def headers(**kw):
    h = {"x-ms-client-principal": principal(), "content-type": "application/json"}
    h.update({k.replace("_", "-"): v for k, v in kw.items()})
    return h


def call(doc, hdrs=None, env=ENV, send=None, method="POST", raw=None):
    body = raw if raw is not None else json.dumps(doc).encode()
    sent = []
    send = send or (lambda sas, text: sent.append((sas, text)))
    status, payload = api.handle(method, hdrs if hdrs is not None else headers(), body, env, send)
    return status, payload, sent


class Validation(unittest.TestCase):
    def ok(self, doc):
        status, payload, sent = call(doc)
        self.assertEqual((status, payload), (202, {"queued": True}), doc)
        self.assertEqual(len(sent), 1)
        return json.loads(base64.b64decode(sent[0][1]))

    def bad(self, doc, status=400):
        got, payload, sent = call(doc)
        self.assertEqual(got, status, doc)
        self.assertEqual(sent, [], doc)
        self.assertIn("error", payload)

    def test_every_kind_is_queued_with_a_message_id_and_time(self):
        for kind in ("remove", "broken", "reenter", "done", "undone"):
            msg = self.ok({"kind": kind, "ids": ["75870", "76058"]})
            self.assertEqual((msg["v"], msg["kind"], msg["ids"]), (1, kind, ["75870", "76058"]))
            self.assertRegex(msg["id"], r"^[0-9a-f]{32}$")
            self.assertGreater(msg["t"], 1_700_000_000_000)
        msg = self.ok({"kind": "answer", "ids": ["75870"], "answer": "Because it is fun."})
        self.assertEqual(msg["answer"], "Because it is fun.")

    def test_duplicate_ids_are_collapsed(self):
        self.assertEqual(self.ok({"kind": "remove", "ids": ["75870", "75870"]})["ids"], ["75870"])

    def test_unknown_kind_and_shape(self):
        for doc in ({"kind": "delete", "ids": ["75870"]}, {"ids": ["75870"]}, {"kind": 1, "ids": ["75870"]},
                    {"kind": ["remove"], "ids": ["75870"]}, [], "remove", None, 5,
                    {"kind": "remove", "ids": ["75870"], "extra": 1}):
            self.bad(doc)

    def test_ids_are_digit_strings_in_a_list_of_at_most_fifty(self):
        for ids in ([], "75870", [75870], ["75 870"], ["7587a"], ["-75870"], ["75870\n"], ["१२३४५"], [None], [["75870"]],
                    ["1234"], ["1234567890"], ["75870", 1], None, {"0": "75870"}):
            self.bad({"kind": "remove", "ids": ids})
        self.ok({"kind": "remove", "ids": [str(10000 + i) for i in range(api.MAX_IDS)]})
        self.bad({"kind": "remove", "ids": [str(10000 + i) for i in range(api.MAX_IDS + 1)]})
        self.assertEqual(api.MAX_IDS, 50)

    def test_answer_rules(self):
        self.bad({"kind": "answer", "ids": ["75870"]})
        self.bad({"kind": "answer", "ids": ["75870"], "answer": "   "})
        self.bad({"kind": "answer", "ids": ["75870"], "answer": 5})
        self.bad({"kind": "answer", "ids": ["75870", "75871"], "answer": "x"})
        self.bad({"kind": "answer", "ids": ["75870"], "answer": "bell\x07"})
        self.bad({"kind": "remove", "ids": ["75870"], "answer": "not for this kind"})
        self.ok({"kind": "answer", "ids": ["75870"], "answer": "a" * api.MAX_ANSWER_CHARS})
        self.bad({"kind": "answer", "ids": ["75870"], "answer": "a" * (api.MAX_ANSWER_CHARS + 1)})
        self.ok({"kind": "answer", "ids": ["75870"], "answer": "two\nlines\tand tab"})
        self.assertEqual(api.MAX_ANSWER_CHARS, 2000)

    def test_body_size_limit(self):
        self.assertEqual(api.MAX_BODY_BYTES, 16384)
        big = json.dumps({"kind": "answer", "ids": ["75870"], "answer": "a" * 2000, "pad": "x" * 20000}).encode()
        status, _, sent = call(None, raw=big)
        self.assertEqual((status, sent), (413, []))
        status, _, sent = call({"kind": "remove", "ids": ["75870"]}, headers(content_length="99999"))
        self.assertEqual((status, sent), (413, []))
        status, _, _ = call({"kind": "remove", "ids": ["75870"]}, headers(content_length="abc"))
        self.assertEqual(status, 400)

    def test_not_json(self):
        for raw in (b"", b"{", b"\xff\xfe", b"[" * 5000, b"nope"):
            status, payload, sent = call(None, raw=raw)
            self.assertEqual((status, sent), (400, []), raw)
            self.assertNotIn("nope", json.dumps(payload))

    def test_errors_never_echo_the_input(self):
        status, payload, _ = call({"kind": "remove", "ids": ["<script>alert(1)</script>"]})
        self.assertEqual(status, 400)
        self.assertNotIn("script", json.dumps(payload))

    def test_content_type_and_method(self):
        status, _, sent = call({"kind": "remove", "ids": ["75870"]}, headers(content_type="text/plain"))
        self.assertEqual((status, sent), (415, []))
        for method in ("GET", "PUT", "DELETE", "OPTIONS"):
            status, _, sent = call({"kind": "remove", "ids": ["75870"]}, method=method)
            self.assertEqual((status, sent), (405, []), method)


class Access(unittest.TestCase):
    DOC = {"kind": "remove", "ids": ["75870"]}

    def test_no_principal_is_401_and_wrong_role_is_403(self):
        h = headers()
        del h["x-ms-client-principal"]
        self.assertEqual(call(self.DOC, h)[0:3:2], (401, []))
        self.assertEqual(call(self.DOC, headers(x_ms_client_principal="not base64 json!"))[0], 401)
        self.assertEqual(call(self.DOC, headers(x_ms_client_principal=base64.b64encode(b"[1]").decode()))[0], 401)
        for roles in (("anonymous",), ("anonymous", "authenticated"), ("Owner",), ()):
            status, _, sent = call(self.DOC, headers(x_ms_client_principal=principal(roles)))
            self.assertEqual((status, sent), (403, []), roles)

    def test_header_names_are_case_insensitive(self):
        h = {"X-MS-Client-Principal": principal(), "Content-Type": "application/json; charset=utf-8"}
        self.assertEqual(call(self.DOC, h)[0], 202)

    def test_owner_login_setting_pins_the_account(self):
        env = dict(ENV, OWNER_LOGIN="Owner-Login")
        self.assertEqual(call(self.DOC, env=env)[0], 202)
        self.assertEqual(call(self.DOC, headers(x_ms_client_principal=principal(user="someone-else")), env=env)[0], 403)


class Queue(unittest.TestCase):
    def test_sas_url_must_point_at_the_actions_queue(self):
        url, query = api.queue_endpoint(SAS)
        self.assertEqual(url, "https://stpersonalv5ethud2i3cfq.queue.core.windows.net/lotto-actions/messages")
        self.assertIn("sig=", query)
        for bad in (None, "", "http://a.queue.core.windows.net/lotto-actions?sig=x",
                    "https://evil.example/lotto-actions?sig=x",
                    "https://a.queue.core.windows.net.evil.example/lotto-actions?sig=x",
                    "https://a.queue.core.windows.net/other-queue?sig=x",
                    "https://a.queue.core.windows.net/lotto-actions",
                    "https://u:p@a.queue.core.windows.net/lotto-actions?sig=x",
                    "https://a.queue.core.windows.net:8443/lotto-actions?sig=x",
                    "https://a.blob.core.windows.net/lotto-actions?sig=x"):
            with self.assertRaises(api.Misconfigured, msg=bad) as ctx:
                api.queue_endpoint(bad)
            self.assertNotIn("sig=x", str(ctx.exception))

    def test_put_message_request(self):
        seen = {}

        class Response:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(request, timeout=None):
            seen.update(url=request.full_url, method=request.get_method(), data=request.data, timeout=timeout,
                        headers={k.lower(): v for k, v in request.header_items()})
            return Response()

        with mock.patch.object(api.urllib.request, "urlopen", side_effect=fake_urlopen):
            api.enqueue(SAS, "dGV4dA==")
        self.assertTrue(seen["url"].startswith("https://stpersonalv5ethud2i3cfq.queue.core.windows.net/lotto-actions/messages?sv="))
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["data"], b"<QueueMessage><MessageText>dGV4dA==</MessageText></QueueMessage>")
        self.assertEqual(seen["timeout"], api.QUEUE_TIMEOUT_S)
        self.assertNotIn("authorization", seen["headers"])           # the SAS is the credential, in the query only

    def test_failures_are_502_and_the_sas_is_never_logged_or_returned(self):
        def http_error(*a, **kw):
            raise urllib.error.HTTPError(SAS, 403, "Forbidden", {}, io.BytesIO(SIG.encode()))

        def url_error(*a, **kw):
            raise urllib.error.URLError(SAS)

        for boom in (http_error, url_error, lambda *a, **kw: (_ for _ in ()).throw(TimeoutError(SAS))):
            with mock.patch.object(api.urllib.request, "urlopen", side_effect=boom), \
                    self.assertLogs("lotto_actions", level="DEBUG") as logs:
                status, payload, _ = call({"kind": "remove", "ids": ["75870"]}, send=api.enqueue)
            self.assertEqual(status, 502)
            self.assertNotIn(SIG, json.dumps(payload) + "\n".join(logs.output))
            self.assertNotIn("sig=", json.dumps(payload) + "\n".join(logs.output))

    def test_a_non_201_answer_is_a_failure(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with mock.patch.object(api.urllib.request, "urlopen", return_value=Response()), self.assertLogs("lotto_actions"):
            self.assertEqual(call({"kind": "remove", "ids": ["75870"]}, send=api.enqueue)[0], 502)

    def test_missing_or_wrong_setting_is_500_without_the_value(self):
        for env in ({}, {"ACTIONS_QUEUE_SAS": "https://evil.example/lotto-actions?sig=" + SIG}):
            with self.assertLogs("lotto_actions", level="DEBUG") as logs:
                status, payload, _ = call({"kind": "remove", "ids": ["75870"]}, env=env, send=api.enqueue)
            self.assertEqual(status, 500)
            self.assertNotIn(SIG, json.dumps(payload) + "\n".join(logs.output))

    def test_the_sas_reaches_only_the_send_function_and_never_the_message(self):
        status, payload, sent = call({"kind": "remove", "ids": ["75870"]})
        self.assertEqual((status, payload), (202, {"queued": True}))
        self.assertEqual(sent[0][0], SAS)
        self.assertNotIn(SIG, base64.b64decode(sent[0][1]).decode())
        self.assertNotIn(SIG, sent[0][1])

    def test_source_never_logs_the_setting(self):
        source = (API / "lotto_actions.py").read_text()
        self.assertNotIn("print(", source)
        for line in source.splitlines():
            if "log." in line:
                self.assertNotIn("sas", line.lower().replace("sas_url", ""), line)
        self.assertNotRegex(source, r"sig=[A-Za-z0-9%+/]{20,}")


class FunctionApp(unittest.TestCase):
    """function_app.py adapts the handler to Azure Functions: one POST route, action, anonymous at the function level."""

    def load(self):
        routes = []

        class FunctionApp:
            def __init__(self, http_auth_level=None):
                self.auth = http_auth_level

            def route(self, route, methods):
                def deco(fn):
                    routes.append((route, methods))
                    return fn
                return deco

        class HttpResponse:
            def __init__(self, body, status_code, mimetype, headers):
                self.body, self.status_code, self.mimetype, self.headers = body, status_code, mimetype, headers

        fake = types.ModuleType("azure.functions")
        fake.FunctionApp, fake.HttpResponse = FunctionApp, HttpResponse
        fake.AuthLevel = types.SimpleNamespace(ANONYMOUS="anonymous")
        fake.HttpRequest = object
        pkg = types.ModuleType("azure")
        pkg.functions = fake
        spec = importlib.util.spec_from_file_location("site_api_function_app", API / "function_app.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"azure": pkg, "azure.functions": fake, "lotto_actions": api}):
            spec.loader.exec_module(module)
        return module, routes

    def test_one_post_route(self):
        module, routes = self.load()
        self.assertEqual(routes, [("action", ["POST"])])

    def test_response_is_json_and_not_cached(self):
        module, _ = self.load()

        class Request:
            method = "POST"
            headers = headers()

            def get_body(self):
                return json.dumps({"kind": "remove", "ids": ["75870"]}).encode()

        class Created:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with mock.patch.object(api.urllib.request, "urlopen", return_value=Created()) as put, \
                mock.patch.dict(module.os.environ, ENV):
            response = module.action(Request())
        self.assertEqual((response.status_code, json.loads(response.body)), (202, {"queued": True}))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        put.assert_called_once()


class Folder(unittest.TestCase):
    def test_api_folder_has_what_static_web_apps_needs(self):
        for name in ("function_app.py", "host.json", "requirements.txt", "lotto_actions.py"):
            self.assertTrue((API / name).is_file(), name)
        self.assertIn("azure-functions", (API / "requirements.txt").read_text())
        self.assertEqual(json.loads((API / "host.json").read_text())["version"], "2.0")


if __name__ == "__main__":
    unittest.main()
