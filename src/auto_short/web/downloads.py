"""CP8.34 D3 / D7 (+ Amendment A1): server-side progress of downloads started with ``?dl=<token>`` (in memory,
expires after 6 h).

The page that queues several downloads cannot see when a native browser download ends, so the download routes
report to a token table and the page polls ``GET /api/downloads/{token}``. A browser (Chrome on Android) may fetch one
file with several parallel Range requests under the same URL, hence the same token: the table merges the byte
intervals of every request of a token. ``done`` means the server pushed the last byte (D7), not that the phone has
written the file. A download without ``dl`` never touches this module.

State rules (A1b), ``bytes_total`` known (file size from ``Content-Range`` / ``Content-Length``):
``done`` = the merged intervals cover ``[0, bytes_total)``; else ``sending`` while a request is running; with no
running request ``aborted`` if the last request ended by disconnect / error, else (a slice ended normally, others are
expected) ``sending``. ``bytes_total`` unknown (zip stream): the latest request alone decides, as before.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable

import anyio
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

log = logging.getLogger("auto_short")

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
TTL_SECONDS = 6 * 3600
MAX_ENTRIES = 5000

SENDING, DONE, ABORTED = "sending", "done", "aborted"
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def merge_interval(intervals: list[list[int]], start: int, end: int) -> None:
    """Add ``[start, end)`` to a sorted list of disjoint intervals, merging overlaps and neighbours (in place)."""
    if end <= start:
        return
    out: list[list[int]] = []
    placed = False
    for a, b in intervals:
        if b < start:
            out.append([a, b])
        elif end < a:
            if not placed:
                out.append([start, end])
                placed = True
            out.append([a, b])
        else:
            start, end = min(start, a), max(end, b)
    if not placed:
        out.append([start, end])
    intervals[:] = out


class _Entry:
    def __init__(self):
        self.intervals: list[list[int]] = []
        self.active = 0
        self.total: int | None = None
        self.last_end: str | None = None  # "finished" | "aborted" (how the last request ended)
        self.finished_whole = False  # unknown total: a request sent its final chunk
        self.touched = 0.0

    def covered(self) -> int:
        return sum(b - a for a, b in self.intervals)

    def state(self) -> str:
        if self.total is not None:
            if self.total == 0 or self.covered() >= self.total:
                return DONE
        elif self.finished_whole:
            return DONE
        if self.active > 0:
            return SENDING
        return ABORTED if self.last_end == ABORTED else SENDING


class DownloadTable:
    def __init__(self, clock: Callable[[], float] = time.monotonic, ttl: float = TTL_SECONDS):
        self._clock = clock
        self._ttl = ttl
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def _purge(self, now: float) -> None:
        for token in [t for t, e in self._entries.items() if now - e.touched > self._ttl and e.active == 0]:
            del self._entries[token]
        while len(self._entries) > MAX_ENTRIES:
            del self._entries[min(self._entries, key=lambda t: self._entries[t].touched)]

    def begin(self, token: str) -> str:
        """A request for ``token`` arrived (it counts as running); returns the token for the later calls."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            entry = self._entries.setdefault(token, _Entry())
            if entry.total is None:  # unknown total (zip): the latest request alone decides
                entry.intervals, entry.finished_whole = [], False
            entry.active += 1
            entry.touched = now
        return token

    def fail(self, token: str) -> None:
        """The route answered with an error: the token ends as ``aborted``."""
        with self._lock:
            entry = self._entries.setdefault(token, _Entry())
            entry.active, entry.last_end, entry.touched = 0, ABORTED, self._clock()

    def set_total(self, token: str, total: int | None) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None and total is not None:
                entry.total = total
                entry.touched = self._clock()

    def add_bytes(self, token: str, start: int, end: int) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None:
                merge_interval(entry.intervals, start, end)
                entry.touched = self._clock()

    def end(self, token: str, how: str) -> str:
        """A request ended (``finished`` = its final chunk was handed to the server, ``aborted`` = disconnect / error);
        returns the token's state afterwards."""
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return ABORTED
            entry.active = max(0, entry.active - 1)
            entry.last_end = how
            if how == "finished" and entry.total is None:
                entry.finished_whole = True
            entry.touched = self._clock()
            return entry.state()

    def get(self, token: str) -> dict | None:
        with self._lock:
            now = self._clock()
            entry = self._entries.get(token)
            if entry is None or (now - entry.touched > self._ttl and entry.active == 0):
                self._entries.pop(token, None)
                return None
            return {"state": entry.state(), "bytes_sent": entry.covered(), "bytes_total": entry.total}


class TrackedResponse(Response):
    """Wraps a finished ``FileResponse`` / ``StreamingResponse``: counts the bytes it sends and reports to the table.
    A1a: ``receive()`` is watched in parallel; an ``http.disconnect`` before the final chunk was handed to ``send``
    cancels the response (uvicorn's ``send`` silently drops after a disconnect, so reading the file to its end would
    look like a finished download). A disconnect that arrives while / after the final chunk is not an abort."""

    def __init__(self, inner: Response, table: DownloadTable, token: str):
        super().__init__(status_code=inner.status_code)
        self.inner = inner
        self.table = table
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        table, token = self.table, self.token
        table.begin(token)
        # the server's zero-copy ``pathsend`` would hide the bytes: ask for plain body chunks
        extensions = {k: v for k, v in scope.get("extensions", {}).items() if k != "http.response.pathsend"}
        inner_scope = {**scope, "extensions": extensions}
        st = {"start": 0, "total": None, "last": None, "sent": 0, "final": False, "completed": False,
              "disconnected": False, "exc": None, "status": None}

        async def counting_send(message):
            kind = message["type"]
            if kind == "http.response.start":
                st["status"] = message.get("status")
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                crange = _CONTENT_RANGE.match(headers.get(b"content-range", b"").decode("latin-1"))
                if message.get("status") == 206 and crange:
                    st["start"], st["last"], st["total"] = (int(g) for g in crange.groups())
                    st["last"] += 1  # exclusive end of the slice
                elif b"content-length" in headers:
                    try:
                        st["total"] = int(headers[b"content-length"])
                    except ValueError:
                        pass
                table.set_total(token, st["total"])
            if kind == "http.response.body":
                n = len(message.get("body", b""))
                begin = st["start"] + st["sent"]
                st["sent"] += n
                if not message.get("more_body", False):
                    st["final"] = True  # before the await: a disconnect reported meanwhile is not an abort
                await send(message)
                table.add_bytes(token, begin, begin + n)
                return
            await send(message)

        async def watch(tg):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    st["disconnected"] = True
                    if not st["final"]:
                        tg.cancel_scope.cancel()
                    return

        async def run(tg):
            try:
                await self.inner(inner_scope, receive, counting_send)
                st["completed"] = True
            except Exception as exc:  # re-raised after the bookkeeping below
                st["exc"] = exc
            tg.cancel_scope.cancel()

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(watch, tg)
                tg.start_soon(run, tg)
        except BaseException:  # cancelled from outside (the server gave up on the request)
            table.end(token, ABORTED)
            self._log(scope, st, ABORTED)
            raise
        ok = st["exc"] is None and st["final"]
        how = "finished" if ok else ABORTED
        after = table.end(token, how)
        self._log(scope, st, "done" if (ok and after == DONE) else ("partial" if ok else ABORTED), after)
        if st["exc"] is not None:
            raise st["exc"]

    def _log(self, scope: Scope, st: dict, result: str, after: str | None = None) -> None:
        if after is None:
            after = (self.table.get(self.token) or {}).get("state", "?")
        rng = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"range"), "-")
        log.info("web: tải [%s…] %s range=%s đã gửi %d/%s byte -> %s (token: %s)", self.token[:6], scope.get("path", "?"),
                 rng, st["sent"], st["total"] if st["total"] is not None else "?", result, after)
