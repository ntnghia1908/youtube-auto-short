"""CP8.34 D3 / D7: server-side progress of downloads started with ``?dl=<token>`` (in memory, expires after 6 h).

The page that queues several downloads cannot see when a native browser download ends, so the download routes
report to a token table and the page polls ``GET /api/downloads/{token}``. ``done`` means the server pushed the last
byte (D7), not that the phone has written the file. A new request with the same token (a download manager retrying)
resets the entry: the latest request counts. A download without ``dl`` never touches this module.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable

from starlette.responses import Response
from starlette.types import Receive, Scope, Send

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
TTL_SECONDS = 6 * 3600
MAX_ENTRIES = 5000

SENDING, DONE, ABORTED = "sending", "done", "aborted"
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


class _Entry:
    __slots__ = ("seq", "state", "bytes_sent", "bytes_total", "touched")

    def __init__(self, seq: int):
        self.seq = seq
        self.state = SENDING
        self.bytes_sent = 0
        self.bytes_total: int | None = None
        self.touched = 0.0


class DownloadTable:
    def __init__(self, clock: Callable[[], float] = time.monotonic, ttl: float = TTL_SECONDS):
        self._clock = clock
        self._ttl = ttl
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._seq = 0

    def _purge(self, now: float) -> None:
        for token in [t for t, e in self._entries.items() if now - e.touched > self._ttl]:
            del self._entries[token]
        while len(self._entries) > MAX_ENTRIES:
            del self._entries[min(self._entries, key=lambda t: self._entries[t].touched)]

    def begin(self, token: str, *, state: str = SENDING) -> int:
        """A request for ``token`` arrived: reset the entry to the latest request; returns its sequence number."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            self._seq += 1
            entry = _Entry(self._seq)
            entry.state = state
            entry.touched = now
            self._entries[token] = entry
            return entry.seq

    def update(self, token: str, seq: int, *, state: str | None = None, bytes_sent: int | None = None,
               bytes_total: int | None = None, only_if_sending: bool = False) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or entry.seq != seq:  # an older request of the same token never overwrites a newer one
                return
            if only_if_sending and entry.state != SENDING:
                return
            if state is not None:
                entry.state = state
            if bytes_sent is not None:
                entry.bytes_sent = bytes_sent
            if bytes_total is not None:
                entry.bytes_total = bytes_total
            entry.touched = self._clock()

    def get(self, token: str) -> dict | None:
        with self._lock:
            now = self._clock()
            entry = self._entries.get(token)
            if entry is None or now - entry.touched > self._ttl:
                self._entries.pop(token, None)
                return None
            return {"state": entry.state, "bytes_sent": entry.bytes_sent, "bytes_total": entry.bytes_total}


class TrackedResponse(Response):
    """Wraps a finished ``FileResponse`` / ``StreamingResponse``: counts the bytes it sends and reports to the table.
    ``done`` = the last byte of the file (a Range response: up to the last byte of the file) was sent; a client that
    goes away first (exception, cancellation or the response returning without its final chunk) = ``aborted``."""

    def __init__(self, inner: Response, table: DownloadTable, token: str):
        super().__init__(status_code=inner.status_code)
        self.inner = inner
        self.table = table
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        table, token = self.table, self.token
        seq = table.begin(token)
        # the server's zero-copy ``pathsend`` would hide the bytes: ask for plain body chunks
        extensions = {k: v for k, v in scope.get("extensions", {}).items() if k != "http.response.pathsend"}
        inner_scope = {**scope, "extensions": extensions}
        state = {"start": 0, "total": None, "last": None, "sent": 0, "finished": False}

        async def counting_send(message):
            kind = message["type"]
            if kind == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                crange = _CONTENT_RANGE.match(headers.get(b"content-range", b"").decode("latin-1"))
                if message.get("status") == 206 and crange:
                    state["start"], state["last"], state["total"] = (int(g) for g in crange.groups())
                elif b"content-length" in headers:
                    try:
                        state["total"] = int(headers[b"content-length"])
                    except ValueError:
                        pass
                table.update(token, seq, bytes_total=state["total"])
            await send(message)  # a failed send (client gone) raises here, before anything is counted
            if kind == "http.response.body":
                state["sent"] += len(message.get("body", b""))
                table.update(token, seq, bytes_sent=state["start"] + state["sent"])
                if not message.get("more_body", False):
                    state["finished"] = True
                    last, total = state["last"], state["total"]
                    if last is None or total is None or last == total - 1:  # a partial Range stays "sending"
                        table.update(token, seq, state=DONE, only_if_sending=True)

        try:
            await self.inner(inner_scope, receive, counting_send)
        except BaseException:
            table.update(token, seq, state=ABORTED, only_if_sending=True)
            raise
        if not state["finished"]:  # returned without the final chunk: the client disconnected
            table.update(token, seq, state=ABORTED, only_if_sending=True)
