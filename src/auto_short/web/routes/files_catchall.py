"""Files catchall routes extracted from the app factory."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ... import khaithi
from ...review import content_disposition
from .. import episodes as ep
from ..context import WebContext, SOURCE_TYPES

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


def _zip_stream(files: list[tuple[str, Path, str]]):
    """Entries named like the single downloads (X1); non-ASCII names get the zip UTF-8 flag (bit 11)."""
    sink = _ZipSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as zf:
        for _clip_id, path, name in files:
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

    @router.get("/files/{episode_id}/{name}")
    def files(episode_id: str, name: str, download: str | None = None, dl: str | None = None):
        return ctx.tracked(dl, _files_response(episode_id, name, download))

    def _files_response(episode_id: str, name: str, download: str | None) -> Response:
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        if name == "shorts.zip":
            items = ep.short_files(ctx.config, episode_id)
            if not items:
                return JSONResponse({"detail": "chưa có Short nào"}, status_code=404)
            # CP8.31 D1 (reverses CP8.17 D3): a zip ticks "Đã đăng" for every Short it contains (current file)
            ctx.mark_downloaded(episode_id, [cid for cid, _, _ in items])
            return StreamingResponse(
                _zip_stream(items), media_type="application/zip",
                headers={"Content-Disposition": content_disposition(ep.zip_download_name(ctx.config, episode_id)),
                         "Cache-Control": "no-store"})
        if name == "all.zip":  # CP8.17 D5: Shorts/ + KhaiThị/ of one video in a single zip (CP8.31 D1: ticks both)
            both = ep.all_zip(ctx.config, episode_id)
            if both is None:
                return JSONResponse({"detail": "cần có cả Short và khai thị đã dựng"}, status_code=404)
            items, zip_file_name = both
            vid = ep.hd_owner(episode_id)  # the Short episode; its khai thị is ``<vid>.kt``
            ctx.mark_downloaded(vid, [cid for cid, _, n in items if n.startswith("Shorts/")])
            ctx.mark_downloaded(vid + khaithi.SUFFIX, [cid for cid, _, n in items if n.startswith("KhaiThị/")])
            return StreamingResponse(
                _zip_stream(items), media_type="application/zip",
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
        found = ep.short_file(ctx.config, episode_id, clip_id)
        if found is None:
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        path, download_name = found
        headers = {"Cache-Control": "private, no-cache"}
        if download is not None:
            headers["Content-Disposition"] = content_disposition(download_name)
            ctx.mark_downloaded(episode_id, [clip_id])  # plain playback (no download=1) never ticks
        return FileResponse(path, media_type="video/mp4", headers=headers)

    return router
