#!/usr/bin/env python3
"""Azure Blob storage for the Lotto registers (container lotto-data), stdlib only.

The Azure jobs no longer use git for data.  A job pulls the blobs under its prefixes into the image's
/app/repo/data/... (blob name = repo-relative path, e.g. data/comps/comps.jsonl), runs its worker unchanged, then
pushes back only the files whose content changed.  Each pulled blob's ETag is remembered and the upload is
conditional on it (If-Match; If-None-Match: * for a new file), so a concurrent writer is never overwritten:
  * append-only *.jsonl registers: on a conflict take the remote lines first, add the new local lines the remote
    does not have, and retry (up to MERGE_RETRIES times);
  * any other file: fail loudly and keep the remote version.

Auth is the Container Apps managed identity (IDENTITY_ENDPOINT + IDENTITY_HEADER), user-assigned when
AZURE_CLIENT_ID is set.  The token is never printed.  Every call has a timeout.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable

API_VERSION = "2021-08-06"
DEFAULT_ACCOUNT = "stpersonalv5ethud2i3cfq"
DEFAULT_CONTAINER = "lotto-data"
RESOURCE = "https://storage.azure.com/"
TOKEN_API_VERSION = "2019-08-01"
CLIENT_ID_PLACEHOLDER = "USER_ASSIGNED_CLIENT_ID"
REQUEST_TIMEOUT_S = 60
TOKEN_TIMEOUT_S = 30
HTTP_ATTEMPTS = 3                # transient failures (429, 5xx, network) per request
MERGE_RETRIES = 3                # union-merge retries after a 412 on a *.jsonl register
MAX_LIST_PAGES = 200
LIST_PAGE_SIZE = 5000
TOKEN_REFRESH_MARGIN_S = 300
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
CONFLICT_STATUSES = frozenset({409, 412})   # a conditional header failed (a create-only PUT may answer 409)


class BlobError(Exception):
    """A storage call failed; the message never contains a token."""


class BlobHTTPError(BlobError):
    def __init__(self, status: int, detail: str = "") -> None:
        super().__init__(f"storage returned HTTP {status}" + (f": {detail}" if detail else ""))
        self.status = status


class BlobConflict(BlobError):
    """A conditional write lost the race (HTTP 412, or 409 for a create-only write)."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quote_etag(etag: str) -> str:
    etag = etag.strip()
    return etag if etag.startswith(('"', "W/")) else f'"{etag}"'


def merge_jsonl(remote: str, local: str) -> str:
    """Remote lines first, then the local lines the remote does not already hold (blank lines dropped)."""
    out = [line for line in remote.splitlines() if line.strip()]
    seen = set(out)
    for line in local.splitlines():
        if line.strip() and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out) + "\n" if out else ""


def container_url() -> str:
    account = os.environ.get("LOTTO_DATA_ACCOUNT") or DEFAULT_ACCOUNT
    container = os.environ.get("LOTTO_DATA_CONTAINER") or DEFAULT_CONTAINER
    if not re.fullmatch(r"[a-z0-9]{3,24}", account):
        raise BlobError(f"LOTTO_DATA_ACCOUNT {account!r} is not a storage account name")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", container):
        raise BlobError(f"LOTTO_DATA_CONTAINER {container!r} is not a container name")
    return f"https://{account}.blob.core.windows.net/{container}"


def blob_url(name: str) -> str:
    return f"{container_url()}/{urllib.parse.quote(name, safe='/')}"


def safe_name(name: str) -> str:
    parts = name.split("/")
    if not name or name.startswith("/") or any(p in ("", ".", "..") for p in parts) or "\\" in name:
        raise BlobError(f"refusing unsafe blob name {name!r}")
    return name


class BlobStore:
    def __init__(self) -> None:
        self.root: Path | None = None
        self.etags: dict[str, str] = {}      # blob name -> ETag at pull/last push
        self.digests: dict[str, str] = {}    # blob name -> sha256 of the content at pull/last push
        self._token = ""
        self._expires = 0.0

    # ------------------------------------------------------------------------------------------------ auth
    def token(self) -> str:
        if self._token and time.time() < self._expires - TOKEN_REFRESH_MARGIN_S:
            return self._token
        endpoint = os.environ.get("IDENTITY_ENDPOINT")
        header = os.environ.get("IDENTITY_HEADER")
        if not endpoint or not header:
            raise BlobError("managed identity is not available (IDENTITY_ENDPOINT / IDENTITY_HEADER unset)")
        params = {"api-version": TOKEN_API_VERSION, "resource": RESOURCE}
        client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
        if client_id == CLIENT_ID_PLACEHOLDER:
            raise BlobError("AZURE_CLIENT_ID is still the placeholder; set the identity's client id in azure/jobs")
        if client_id:
            params["client_id"] = client_id
        request = urllib.request.Request(
            f"{endpoint}?{urllib.parse.urlencode(params)}", headers={"X-IDENTITY-HEADER": header}, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=TOKEN_TIMEOUT_S) as response:
                doc = json.loads(response.read())
            token = doc["access_token"]
        except urllib.error.HTTPError as exc:
            raise BlobError(f"managed identity token request failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            raise BlobError(f"managed identity token request failed: {type(exc).__name__}") from None
        try:
            expires = float(doc.get("expires_on"))
        except (TypeError, ValueError):
            expires = time.time() + 600
        self._token, self._expires = token, expires
        return token

    # ---------------------------------------------------------------------------------------------- requests
    def request(self, method: str, url: str, *, headers: dict | None = None, body: bytes | None = None):
        """One storage call; returns (status, response headers, body).  Raises BlobHTTPError or BlobError."""
        refreshed = False
        for attempt in range(1, HTTP_ATTEMPTS + 1):
            send = {
                "Authorization": f"Bearer {self.token()}",
                "x-ms-version": API_VERSION,
                "x-ms-date": format_datetime(dt.datetime.now(dt.UTC), usegmt=True),
            }
            send.update(headers or {})
            request = urllib.request.Request(url, data=body, headers=send, method=method)
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                    return response.status, response.headers, response.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:300].decode("utf-8", "replace") if hasattr(exc, "read") else ""
                if exc.code == 401 and not refreshed:
                    refreshed = True
                    self._token = ""                    # the cached token went stale: fetch one more
                    continue
                if exc.code in RETRY_STATUSES and attempt < HTTP_ATTEMPTS:
                    time.sleep(2 * attempt)
                    continue
                raise BlobHTTPError(exc.code, re.sub(r"\s+", " ", detail).strip()) from None
            except (urllib.error.URLError, OSError) as exc:
                if attempt < HTTP_ATTEMPTS:
                    time.sleep(2 * attempt)
                    continue
                raise BlobError(f"storage request failed: {type(exc).__name__}") from None
        raise BlobError("storage request failed")      # not reached; the loop returns or raises

    def list_blobs(self, prefix: str) -> list[tuple[str, str]]:
        """(name, etag) of every blob whose name starts with prefix."""
        found: list[tuple[str, str]] = []
        marker = ""
        for _ in range(MAX_LIST_PAGES):
            query = {"restype": "container", "comp": "list", "prefix": prefix, "maxresults": str(LIST_PAGE_SIZE)}
            if marker:
                query["marker"] = marker
            _, _, body = self.request("GET", f"{container_url()}?{urllib.parse.urlencode(query)}")
            try:
                tree = ET.fromstring(body)
            except ET.ParseError:
                raise BlobError("storage returned an unreadable blob listing") from None
            for blob in tree.iter("Blob"):
                name = blob.findtext("Name") or ""
                if name and not name.endswith("/"):
                    found.append((name, blob.findtext("Properties/Etag") or ""))
            marker = (tree.findtext("NextMarker") or "").strip()
            if not marker:
                return found
        raise BlobError(f"blob listing under {prefix!r} did not end after {MAX_LIST_PAGES} pages")

    def get(self, name: str) -> tuple[bytes, str] | None:
        """(content, etag), or None when the blob does not exist."""
        try:
            _, headers, body = self.request("GET", blob_url(name))
        except BlobHTTPError as exc:
            if exc.status == 404:
                return None
            raise
        return body, headers.get("ETag") or ""

    def put(self, name: str, data: bytes, etag: str | None) -> str:
        headers = {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": mimetypes.guess_type(name)[0] or "application/octet-stream",
        }
        if etag:
            headers["If-Match"] = quote_etag(etag)
        else:
            headers["If-None-Match"] = "*"
        try:
            _, response, _ = self.request("PUT", blob_url(name), headers=headers, body=data)
        except BlobHTTPError as exc:
            if exc.status in CONFLICT_STATUSES:
                raise BlobConflict(f"{name} was changed by someone else (HTTP {exc.status})") from None
            raise
        return response.get("ETag") or ""

    # ---------------------------------------------------------------------------------------------- pull
    def pull(self, prefixes: Iterable[str], dest: Path, allow_empty: bool = False) -> int:
        """Download every blob under the prefixes into dest/<blob name>; returns the number of files."""
        dest = Path(dest)
        self.root = dest
        count = 0
        for prefix in prefixes:
            for name, listed_etag in self.list_blobs(prefix):
                safe_name(name)
                got = self.get(name)
                if got is None:
                    continue                                    # deleted between the listing and the download
                data, etag = got
                target = dest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                self.etags[name] = etag or listed_etag
                self.digests[name] = sha256(data)
                count += 1
        if count == 0 and not allow_empty:
            raise BlobError(
                f"no blobs under {', '.join(prefixes)} in {container_url()}: run tools/migrate_data_to_blob.sh once "
                "(or set LOTTO_ALLOW_EMPTY=1 to start from nothing on purpose)"
            )
        return count

    # ---------------------------------------------------------------------------------------------- push
    def name_of(self, path: Path | str) -> str:
        if self.root is None:
            raise BlobError("push before pull: the data root is not known")
        path = Path(path)
        try:
            relative = path.resolve().relative_to(self.root.resolve()) if path.is_absolute() else path
        except ValueError:
            raise BlobError(f"{path} is outside {self.root}") from None
        return safe_name(relative.as_posix())

    def changed(self, paths: Iterable[Path | str]) -> list[tuple[str, Path, bytes]]:
        """(blob name, local file, content) for each existing file whose content differs from what was pulled."""
        out = []
        for path in paths:
            name = self.name_of(path)
            local = self.root / name
            if not local.is_file():
                continue
            data = local.read_bytes()
            if self.digests.get(name) != sha256(data):
                out.append((name, local, data))
        out.sort(key=lambda item: (not item[0].endswith(".jsonl"), item[0]))   # registers first
        return out

    def push(self, paths: Iterable[Path | str]) -> list[str]:
        """Upload the changed files; returns the blob names uploaded.  Every file is tried, then any failure raises."""
        uploaded: list[str] = []
        failures: list[str] = []
        for name, local, data in self.changed(paths):
            try:
                self.push_one(name, local, data)
                uploaded.append(name)
            except (BlobError, UnicodeError) as exc:
                failures.append(f"{name}: {exc}")
        if failures:
            raise BlobError(f"{len(failures)} file(s) not uploaded (uploaded {len(uploaded)}): " + "; ".join(failures))
        return uploaded

    def push_one(self, name: str, local: Path, data: bytes) -> None:
        etag = self.etags.get(name)
        for _ in range(MERGE_RETRIES + 1):
            try:
                new_etag = self.put(name, data, etag)
            except BlobConflict:
                if not name.endswith(".jsonl"):
                    raise BlobError(
                        f"{name} changed in storage since it was pulled; the stored version was kept and this "
                        "run's change was not uploaded"
                    ) from None
                got = self.get(name)
                if got is None:
                    etag = None                                 # deleted meanwhile: create it again
                    continue
                remote, etag = got
                data = merge_jsonl(remote.decode("utf-8"), data.decode("utf-8")).encode("utf-8")
                local.write_bytes(data)                         # the local copy now shows the merged register
                continue
            self.etags[name] = new_etag
            self.digests[name] = sha256(data)
            return
        raise BlobError(f"{name} still conflicting after {MERGE_RETRIES} merge retries")


STORE = BlobStore()


def pull(prefixes: Iterable[str], dest: Path, allow_empty: bool | None = None) -> int:
    if allow_empty is None:
        allow_empty = os.environ.get("LOTTO_ALLOW_EMPTY") == "1"
    return STORE.pull(tuple(prefixes), dest, allow_empty)


def push(changed_files: Iterable[Path | str]) -> list[str]:
    return STORE.push(changed_files)


def changed_names(paths: Iterable[Path | str]) -> list[str]:
    return [name for name, _, _ in STORE.changed(paths)]


def read_text(name: str) -> str | None:
    """One blob's text without a full pull (None when it does not exist)."""
    got = STORE.get(safe_name(name))
    return None if got is None else got[0].decode("utf-8")


def local_files(root: Path, paths: Iterable[str]) -> list[Path]:
    """Files under the given repo-relative files or folders that exist in root (what a job may upload)."""
    out: list[Path] = []
    for rel in paths:
        target = Path(root) / rel
        if target.is_dir():
            out.extend(p for p in sorted(target.rglob("*")) if p.is_file() and "__pycache__" not in p.parts)
        elif target.is_file():
            out.append(target)
    return out
