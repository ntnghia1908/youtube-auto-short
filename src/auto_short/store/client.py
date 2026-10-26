"""HD2a: HTTP client (urllib, stdlib) of the 3090 store (tools/store/store.py; protocol in that file).

``GET /index``, ``HEAD|GET /files/<video_id>/<kind>`` (``Range``, header ``X-Sha256``), ``Authorization: Bearer``. The
token comes from the env ``AUTO_SHORT_STORE_TOKEN`` and is never logged or put in an error text."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from ..config import StoreConfig

TOKEN_ENV = "AUTO_SHORT_STORE_TOKEN"
KINDS = ("hd", "vertical", "source")
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CHUNK = 1024 * 1024


class StoreError(Exception):
    """Base of every store failure that is not a bug: the job should wait ("đợi 3090"), not fail."""


class StoreUnavailable(StoreError):
    """No token, unreachable, timed out, 401 or any other HTTP / network error."""


class StoreMismatch(StoreError):
    """The store has no such file, or its bytes / sha256 differ from the expected one."""


class StoreRangeError(StoreMismatch):
    """HD2b G5: an unsatisfiable Range, distinct from a missing file for web downloads."""

    def __init__(self, content_range: str | None = None):
        super().__init__("kho trả Range không hợp lệ")
        self.content_range = content_range


class StoreClient:
    def __init__(self, url: str, token: str | None, timeout: float = 30.0):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    @classmethod
    def from_config(cls, cfg: StoreConfig, env=None) -> "StoreClient":
        token = (os.environ if env is None else env).get(TOKEN_ENV)
        return cls(cfg.url, token.strip() if token else None, cfg.timeout_seconds)

    def _open(self, path: str, *, method: str = "GET", headers: dict | None = None, data=None):
        if not self.token:
            raise StoreUnavailable(f"thiếu token kho (env {TOKEN_ENV})")
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", **(headers or {})})
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            content_range = exc.headers.get("Content-Range") if exc.headers else None
            exc.close()
            if exc.code == 404:
                raise StoreMismatch(f"kho không có file {path}") from None
            if exc.code == 416:
                raise StoreRangeError(content_range) from None
            if method == "PUT" and exc.code in (400, 409, 413, 422):
                raise StoreMismatch(f"kho từ chối file (HTTP {exc.code})") from None
            raise StoreUnavailable(f"kho trả HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:  # includes timeouts / connection refused
            raise StoreUnavailable(f"không kết nối được kho: {type(exc).__name__}") from None

    @staticmethod
    def _path(video_id: str, kind: str) -> str:
        if kind not in KINDS or not _ID.fullmatch(video_id):
            raise StoreMismatch(f"video_id/kind không hợp lệ: {video_id!r}/{kind!r}")
        return f"/files/{video_id}/{kind}"

    def available(self) -> bool:
        """Does the store answer (with our token)?"""
        try:
            with self._open("/index"):
                return True
        except StoreError:
            return False

    def index(self) -> list[dict]:
        with self._open("/index") as resp:
            try:
                data = json.loads(resp.read().decode("utf-8"))
            except (OSError, ValueError) as exc:
                raise StoreUnavailable("kho trả index không đọc được") from exc
        if not isinstance(data, list):
            raise StoreUnavailable("kho trả index không đúng dạng")
        return data

    def head(self, video_id: str, kind: str) -> dict:
        """``{"size": int, "sha256": str}`` of the stored file (StoreMismatch when the store has none)."""
        with self._open(self._path(video_id, kind), method="HEAD") as resp:
            sha = (resp.headers.get("X-Sha256") or "").lower()
            try:
                size = int(resp.headers.get("Content-Length") or "")
            except ValueError:
                raise StoreUnavailable("kho không trả Content-Length") from None
        if not _SHA.fullmatch(sha):
            raise StoreUnavailable("kho không trả X-Sha256 hợp lệ")
        return {"size": size, "sha256": sha}

    def put(self, video_id: str, kind: str, series: str, name: str, path: Path, sha256: str) -> None:
        """Stream the file without buffering it in RAM. A failed upload is retried in full by the caller."""
        route = self._path(video_id, kind)
        want = (sha256 or "").lower()
        if not _SHA.fullmatch(want):
            raise StoreMismatch("sha256 gửi lên không hợp lệ")
        if not isinstance(series, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", series) is None:
            raise StoreMismatch("series gửi lên không hợp lệ")
        try:
            size = Path(path).stat().st_size
            try:
                existing = self.head(video_id, kind)
            except StoreMismatch:
                existing = None
            if existing is not None:
                if existing["sha256"] != want or existing["size"] != size:
                    raise StoreMismatch("kho đã có file khác sha256 / kích thước")
                return
            route += "?" + urlencode({"series": series, "name": name})
            with Path(path).open("rb") as stream:
                headers = {"Content-Length": str(os.fstat(stream.fileno()).st_size), "X-Sha256": want,
                           "Content-Type": "application/octet-stream"}
                with self._open(route, method="PUT", headers=headers, data=stream) as resp:
                    if resp.status not in (200, 201):
                        raise StoreUnavailable(f"kho trả HTTP {resp.status} khi gửi file")
        except (OSError, http.client.HTTPException) as exc:
            raise StoreUnavailable(f"không gửi được file lên kho: {type(exc).__name__}") from None

    def open_stream(self, video_id: str, kind: str, range_header: str | None = None):
        """HD2b G5: (status, public headers, closable chunk iterator); never buffer the full file."""
        resp = self._open(self._path(video_id, kind), headers={"Range": range_header} if range_header else {})
        if resp.status not in (200, 206):
            resp.close()
            raise StoreUnavailable("kho trả trạng thái tải không hợp lệ")
        headers = {name: resp.headers[name] for name in ("Content-Length", "Content-Range", "Accept-Ranges")
                   if resp.headers.get(name) is not None}

        class Chunks:
            def __iter__(self):
                return self

            def __next__(self):
                try:
                    chunk = resp.read(_CHUNK)
                    if chunk:
                        return chunk
                except (OSError, http.client.HTTPException):
                    self.close()
                    raise StoreUnavailable("đứt kết nối khi tải từ 3090") from None
                self.close()
                raise StopIteration

            def close(self):
                resp.close()

        return resp.status, headers, Chunks()

    def fetch(self, video_id: str, kind: str, dest: Path, sha256: str) -> Path:
        """Download to ``dest`` (through ``dest + ".part"``, resumed with ``Range`` when a part exists), verify that the
        bytes hash to ``sha256`` (and that the store announces it), then rename atomically. Wrong sha256 deletes the
        part and raises :class:`StoreMismatch`; network errors keep the part and raise :class:`StoreUnavailable`."""
        want = (sha256 or "").lower()
        if not _SHA.fullmatch(want):
            raise StoreMismatch("sha256 mong đợi không hợp lệ")
        dest = Path(dest)
        part = dest.with_name(dest.name + ".part")
        info = self.head(video_id, kind)
        if info["sha256"] != want:
            raise StoreMismatch("kho có file khác (sha256 không khớp bản đã giải phóng)")
        size = info["size"]
        have = part.stat().st_size if part.is_file() else 0
        if have > size:
            part.unlink()
            have = 0
        if have < size or size == 0:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with self._open(self._path(video_id, kind), headers=headers) as resp:
                if have and resp.status != 206:  # the server ignored Range: start again
                    have = 0
                try:
                    with part.open("ab" if have else "wb") as out:
                        while chunk := resp.read(_CHUNK):
                            out.write(chunk)
                except Exception as exc:  # reset / timeout / IncompleteRead: the part stays for the next try
                    raise StoreUnavailable(f"đứt kết nối khi tải: {type(exc).__name__}") from None
        got = part.stat().st_size
        if got < size:
            raise StoreUnavailable("tải chưa đủ byte, sẽ thử tiếp")
        digest = hashlib.sha256()
        with part.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
        if digest.hexdigest() != want:
            part.unlink(missing_ok=True)
            raise StoreMismatch("sha256 file tải về không khớp")
        os.replace(part, dest)
        return dest
