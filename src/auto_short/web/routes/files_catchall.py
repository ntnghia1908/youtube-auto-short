"""Files catchall routes extracted from the app factory."""

from __future__ import annotations

import hashlib
import io
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ... import khaithi
from ...review import content_disposition
from ...store.client import StoreClient, StoreMismatch, StoreRangeError, StoreUnavailable
from .. import episodes as ep
from ..context import WebContext, SOURCE_TYPES
from .episodes import _StoreResponse

ZIP_CHUNK = 1 << 20


class _ZipSink(io.RawIOBase):
    """Write-only, non-seekable buffer: ``zipfile`` then writes data descriptors and we stream as we go."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        self._buf += b
        self._pos += len(b)
        return len(b)

    def tell(self) -> int:
        return self._pos

    def drain(self) -> bytes:
        data, self._buf = bytes(self._buf), bytearray()
        return data


def _zip_stream(files: list[tuple[str, Path | ep.StoredShort, str]], *, client=None):
    """Entries named like the single downloads (X1); non-ASCII names get the zip UTF-8 flag (bit 11)."""
    sink = _ZipSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as zf:
        for _clip_id, path, name in files:
            if isinstance(path, ep.StoredShort):
                info = zipfile.ZipInfo(name, time.localtime(path.mtime_ns / 1_000_000_000)[:6])
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o100644 << 16
                info.file_size = path.size
                _status, _headers, stream = client.open_stream(path.episode_id, "short", clip=path.clip)
                digest, size = hashlib.sha256(), 0
                try:
                    with zf.open(info, "w") as dst:
                        for chunk in stream:
                            digest.update(chunk)
                            size += len(chunk)
                            dst.write(chunk)
                            yield sink.drain()
                        if size != path.size or digest.hexdigest() != path.sha256:
                            raise StoreMismatch("Short trên kho thiếu byte / khác sha256")
                finally:
                    stream.close()
                yield sink.drain()
                continue
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_STORED
            with path.open("rb") as src, zf.open(info, "w") as dst:
                while chunk := src.read(ZIP_CHUNK):
                    dst.write(chunk)
                    yield sink.drain()
            yield sink.drain()
    yield sink.drain()


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/archive/zips")
    def archive_zips():
        return ep.archive_zips(ctx.config)

    @router.get("/files/{episode_id}/{name}")
    def files(episode_id: str, name: str, download: str | None = None, dl: str | None = None,
              archive: str | None = None, request: Request = None):
        archive_mode = name == "all.zip" and archive == "1"
        response = _files_response(episode_id, name, download, archive_mode, request)
        return response if archive_mode else ctx.tracked(dl, response)

    def zip_body(items):
        if not any(isinstance(p, ep.StoredShort) for _, p, _ in items):
            return _zip_stream(items)
        client = StoreClient.from_config(ctx.config.store)
        if not ctx.config.store.enabled or not client.available():
            return JSONResponse({"detail": "3090 đang tắt"}, status_code=503)
        return _zip_stream(items, client=client)

    def _files_response(episode_id: str, name: str, download: str | None, archive: bool,
                        request: Request | None) -> Response:
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        if name == "shorts.zip":
            items = [(cid, p, n) for cid, p, n in ep.short_locations(ctx.config, episode_id) or [] if p is not None]
            if not items:
                return JSONResponse({"detail": "chưa có Short nào"}, status_code=404)
            body = zip_body(items)
            if isinstance(body, Response):
                return body
            # CP8.31 D1 (reverses CP8.17 D3): a zip ticks "Đã đăng" for every Short it contains (current file)
            ctx.mark_downloaded(episode_id, [cid for cid, _, _ in items])
            return StreamingResponse(
                body, media_type="application/zip",
                headers={"Content-Disposition": content_disposition(ep.zip_download_name(ctx.config, episode_id)),
                         "Cache-Control": "no-store"})
        if name == "all.zip":  # CP8.17 D5: Shorts/ + KhaiThị/ of one video in a single zip (CP8.31 D1: ticks both)
            both = ep.all_zip(ctx.config, episode_id)
            if both is None:
                return JSONResponse({"detail": "cần có cả Short và khai thị đã dựng"}, status_code=404)
            items, zip_file_name = both
            body = zip_body(items)
            if isinstance(body, Response):
                return body
            if not archive:  # ARC1: archival downloads neither publish nor track the zip.
                vid = ep.hd_owner(episode_id)  # the Short episode; its khai thị is ``<vid>.kt``
                ctx.mark_downloaded(vid, [cid for cid, _, n in items if n.startswith("Shorts/")])
                ctx.mark_downloaded(vid + khaithi.SUFFIX, [cid for cid, _, n in items if n.startswith("KhaiThị/")])
            return StreamingResponse(
                body, media_type="application/zip",
                headers={"Content-Disposition": content_disposition(zip_file_name), "Cache-Control": "no-store"})
        if name == "source.mp4":  # CP9 C7: "Nghe thử" around a cut point (Range; never ticks, never a download)
            found_src = ep.source_file(ctx.config, episode_id)
            if found_src is None:
                return JSONResponse({"detail": "không có video nguồn"}, status_code=404)
            return FileResponse(found_src, media_type=SOURCE_TYPES.get(found_src.suffix.lower(),
                                                                       "application/octet-stream"),
                                headers={"Cache-Control": "private, no-cache"})
        clip_id = name[:-4] if name.endswith(".mp4") else ""
        if not ep.valid_clip_id(clip_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        found = next(((p, n) for cid, p, n in ep.short_locations(ctx.config, episode_id) or []
                      if cid == clip_id and p is not None), None)
        if found is None:
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        path, download_name = found
        headers = {"Cache-Control": "private, no-cache"}
        if isinstance(path, ep.StoredShort):
            if not ctx.config.store.enabled:
                return JSONResponse({"detail": "3090 đang tắt"}, status_code=503)
            try:
                client = StoreClient.from_config(ctx.config.store)
                status, upstream, stream = client.open_stream(episode_id, "short",
                                                              request.headers.get("range") if request else None,
                                                              clip=path.clip)
            except StoreUnavailable:
                return JSONResponse({"detail": "3090 đang tắt"}, status_code=503)
            except StoreRangeError as exc:
                hdrs = {"Content-Range": exc.content_range} if exc.content_range is not None else {}
                return JSONResponse({"detail": "Range không hợp lệ"}, status_code=416, headers=hdrs)
            except StoreMismatch:
                return JSONResponse({"detail": "kho không có file này"}, status_code=404)
            headers.update({k: v for k, v in upstream.items()
                            if k.lower() in ("content-length", "content-range", "accept-ranges")})
            if download is not None:
                headers["Content-Disposition"] = content_disposition(download_name)
                try:
                    ctx.mark_downloaded(episode_id, [clip_id])
                except BaseException:
                    stream.close()
                    raise
            return _StoreResponse(stream, status_code=status, headers=headers)
        if download is not None:
            headers["Content-Disposition"] = content_disposition(download_name)
            ctx.mark_downloaded(episode_id, [clip_id])  # plain playback (no download=1) never ticks
        return FileResponse(path, media_type="video/mp4", headers=headers)

    return router
