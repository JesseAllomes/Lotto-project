#!/usr/bin/env python3
"""The Azure Storage queue lotto-actions over REST (stdlib only), for the `actions` job (azure/runner.py).

Auth is the Container Apps managed identity, through the token and bounded, retrying request code in blobsync.py
(resource https://storage.azure.com/ covers blobs and queues).  The identity needs the role Storage Queue Data
Contributor on the storage account (read, delete and put messages).  Tokens are never printed.
"""
from __future__ import annotations

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.sax.saxutils import escape

import blobsync

DEFAULT_QUEUE = "lotto-actions"
MAX_RECEIVE = 32                         # the most Azure returns in one call


@dataclass
class QueueMessage:
    id: str
    pop_receipt: str
    dequeue_count: int
    text: str                            # MessageText exactly as stored (the API writes base64 JSON)


def queue_name(env_name: str, default: str) -> str:
    name = os.environ.get(env_name) or default
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", name):
        raise blobsync.BlobError(f"{env_name} {name!r} is not a queue name")
    return name


class ActionQueue:
    def __init__(self, store: blobsync.BlobStore | None = None) -> None:
        self.store = store or blobsync.STORE
        self.name = queue_name("ACTIONS_QUEUE", DEFAULT_QUEUE)
        self.poison_name = queue_name("ACTIONS_POISON_QUEUE", f"{self.name}-poison")

    def url(self, name: str | None = None) -> str:
        # The queue lives in its own small account: the SWA API reaches it with a SAS, and the data account has shared keys off.
        account = os.environ.get("ACTIONS_QUEUE_ACCOUNT") or os.environ.get("LOTTO_DATA_ACCOUNT") or blobsync.DEFAULT_ACCOUNT
        if not re.fullmatch(r"[a-z0-9]{3,24}", account):
            raise blobsync.BlobError(f"LOTTO_DATA_ACCOUNT {account!r} is not a storage account name")
        return f"https://{account}.queue.core.windows.net/{name or self.name}"

    @staticmethod
    def _parse(body: bytes) -> list[QueueMessage]:
        try:
            tree = ET.fromstring(body)
        except ET.ParseError:
            raise blobsync.BlobError("storage returned an unreadable queue message list") from None
        out = []
        for m in tree.iter("QueueMessage"):
            try:
                count = int(m.findtext("DequeueCount") or 0)
            except ValueError:
                count = 0
            out.append(QueueMessage(m.findtext("MessageId") or "", m.findtext("PopReceipt") or "", count,
                                    m.findtext("MessageText") or ""))
        return out

    def has_messages(self) -> bool:
        """Peek (no visibility change, no dequeue count): is any message waiting?"""
        _, _, body = self.store.request("GET", f"{self.url()}/messages?peekonly=true&numofmessages=1&timeout=30")
        return bool(self._parse(body))

    def receive(self, count: int, visibility_s: int) -> list[QueueMessage]:
        """Up to `count` messages, hidden from other readers for visibility_s seconds; each read adds 1 to its count."""
        n = max(1, min(count, MAX_RECEIVE))
        query = urllib.parse.urlencode({"numofmessages": n, "visibilitytimeout": visibility_s, "timeout": 30})
        _, _, body = self.store.request("GET", f"{self.url()}/messages?{query}")
        return self._parse(body)

    def delete(self, message: QueueMessage, name: str | None = None) -> None:
        pop = urllib.parse.quote(message.pop_receipt, safe="")
        self.store.request("DELETE", f"{self.url(name)}/messages/{urllib.parse.quote(message.id, safe='')}?popreceipt={pop}&timeout=30")

    def put(self, name: str, text: str) -> None:
        body = f"<QueueMessage><MessageText>{escape(text)}</MessageText></QueueMessage>".encode("utf-8")
        self.store.request("POST", f"{self.url(name)}/messages?timeout=30", headers={"Content-Type": "application/xml"}, body=body)

    def move_to_poison(self, message: QueueMessage) -> None:
        """Copy to the poison queue, then delete from the main queue (a failed copy leaves the message where it is)."""
        self.put(self.poison_name, message.text)
        self.delete(message)
