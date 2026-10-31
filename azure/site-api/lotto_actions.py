"""POST /api/action: validate one site action and put it on the Azure Storage queue `lotto-actions`.

    {"kind": "remove|broken|reenter|answer|done|undone", "ids": ["75870"], "answer": "text (answer only)"}

Nothing is applied here.  The Container Apps job lotto-actions (azure/runner.py mode `actions`) drains the queue, applies
each action with the existing workers and deletes the message once the data is saved.  Standard library only.

The queue credential is an add-only SAS URL in the app setting ACTIONS_QUEUE_SAS (queue URL plus the SAS query string).
It is read from the environment per request, sent to the queue and nowhere else: never logged, never in a response,
never in an error message.  Only the failing HTTP status or exception class is logged.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from xml.sax.saxutils import escape

log = logging.getLogger("lotto_actions")

KINDS = ("remove", "broken", "reenter", "answer", "done", "undone")
MAX_BODY_BYTES = 16384
MAX_IDS = 50
MAX_ANSWER_CHARS = 2000
ID_RE = re.compile(r"[0-9]{5,9}")             # the listing ids in the registers (workers use the same pattern)
FIELDS = frozenset({"kind", "ids", "answer"})
REQUIRED_ROLE = "owner"
QUEUE_NAME = "lotto-actions"
QUEUE_HOST_SUFFIX = ".queue.core.windows.net"
QUEUE_API_VERSION = "2021-08-06"
QUEUE_TIMEOUT_S = 10
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Invalid(ValueError):
    """The request is not acceptable; the message is safe to return and never echoes the input."""


class Misconfigured(Exception):
    """ACTIONS_QUEUE_SAS is missing or does not point at the lotto-actions queue; the message holds no secret."""


def validate(doc: object) -> dict:
    """The normalised action {kind, ids, answer?} or Invalid."""
    if not isinstance(doc, dict):
        raise Invalid("the body must be a JSON object")
    if set(doc) - FIELDS:
        raise Invalid("unknown field")
    kind = doc.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise Invalid("unknown kind")
    ids = doc.get("ids")
    if not isinstance(ids, list) or not ids:
        raise Invalid("ids must be a non-empty list")
    if len(ids) > MAX_IDS:
        raise Invalid(f"at most {MAX_IDS} ids")
    if not all(isinstance(i, str) and ID_RE.fullmatch(i) for i in ids):
        raise Invalid("ids must be digit strings")
    out = {"kind": kind, "ids": list(dict.fromkeys(ids))}
    if kind == "answer":
        answer = doc.get("answer")
        if len(out["ids"]) != 1:
            raise Invalid("an answer is for exactly one id")
        if not isinstance(answer, str) or not answer.strip():
            raise Invalid("answer must be non-empty text")
        if len(answer) > MAX_ANSWER_CHARS:
            raise Invalid(f"answer is longer than {MAX_ANSWER_CHARS} characters")
        if CONTROL.search(answer):
            raise Invalid("answer holds control characters")
        out["answer"] = answer
    elif "answer" in doc:
        raise Invalid("answer is only for kind answer")
    return out


def principal(headers: dict) -> dict | None:
    """The Static Web Apps client principal (x-ms-client-principal, base64 JSON), None when absent or unreadable."""
    raw = headers.get("x-ms-client-principal")
    if not raw:
        return None
    try:
        doc = json.loads(base64.b64decode(raw, validate=True))
    except (ValueError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def queue_endpoint(sas_url: str | None) -> tuple[str, str]:
    """(queue messages URL, SAS query) from the ACTIONS_QUEUE_SAS value.  Refuses anything but https://<account>.queue
    .core.windows.net/lotto-actions?<sas>, so the credential can only ever go to that queue."""
    if not sas_url:
        raise Misconfigured("ACTIONS_QUEUE_SAS is not set")
    parts = urllib.parse.urlsplit(sas_url.strip())
    host = parts.hostname or ""
    if parts.scheme != "https" or not host.endswith(QUEUE_HOST_SUFFIX) or parts.path.rstrip("/") != "/" + QUEUE_NAME \
            or not parts.query or parts.port not in (None, 443) or parts.username or parts.fragment:
        raise Misconfigured(f"ACTIONS_QUEUE_SAS must be https://<account>{QUEUE_HOST_SUFFIX}/{QUEUE_NAME}?<sas>")
    return f"https://{host}/{QUEUE_NAME}/messages", parts.query


def message_text(action: dict, now_ms: int | None = None) -> str:
    """The queue message: the action plus a unique id and the time, as base64 JSON (what Azure queue tooling expects)."""
    doc = {"v": 1, "id": uuid.uuid4().hex, "t": int(time.time() * 1000) if now_ms is None else now_ms, **action}
    return base64.b64encode(json.dumps(doc, separators=(",", ":")).encode("utf-8")).decode("ascii")


def enqueue(sas_url: str | None, text: str, timeout: int = QUEUE_TIMEOUT_S) -> None:
    """Put one message on the queue (REST Put Message).  Raises Misconfigured, or RuntimeError('<reason>') with no secret."""
    url, query = queue_endpoint(sas_url)
    body = f"<QueueMessage><MessageText>{escape(text)}</MessageText></QueueMessage>".encode("utf-8")
    request = urllib.request.Request(
        f"{url}?{query}", data=body, method="POST",
        headers={"Content-Type": "application/xml", "x-ms-version": QUEUE_API_VERSION})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(type(exc).__name__) from None
    if status != 201:
        raise RuntimeError(f"HTTP {status}")


def handle(method: str, headers: dict, body: bytes, env: dict, send=enqueue) -> tuple[int, dict]:
    """(HTTP status, JSON payload).  send(sas_url, text) is the queue call (replaced in tests)."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    if method.upper() != "POST":
        return 405, {"error": "POST only"}
    who = principal(h)
    if who is None:
        return 401, {"error": "sign in"}
    if REQUIRED_ROLE not in (who.get("userRoles") or []):
        return 403, {"error": "not allowed"}
    owner = (env.get("OWNER_LOGIN") or "").strip().lower()
    if owner and str(who.get("userDetails") or "").lower() != owner:
        return 403, {"error": "not allowed"}
    if not str(h.get("content-type", "")).lower().startswith("application/json"):
        return 415, {"error": "send application/json"}
    try:
        declared = int(h.get("content-length") or 0)
    except ValueError:
        return 400, {"error": "bad content-length"}
    body = body or b""
    if declared > MAX_BODY_BYTES or len(body) > MAX_BODY_BYTES:
        return 413, {"error": f"body is over {MAX_BODY_BYTES} bytes"}
    try:
        action = validate(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return 400, {"error": str(exc) if isinstance(exc, Invalid) else "the body is not valid JSON"}
    try:
        send(env.get("ACTIONS_QUEUE_SAS"), message_text(action))
    except Misconfigured as exc:
        log.error("actions queue is not configured: %s", exc)
        return 500, {"error": "the queue is not configured"}
    except RuntimeError as exc:
        log.warning("queue put failed: %s", exc)
        return 502, {"error": "the queue did not accept it"}
    return 202, {"queued": True}
