"""TC-WEB1: read-only preview of the TC1 thematic index (docs/tasks/TC-WEB1-theme-index-preview.md).

Two GET routes behind the existing auth middleware. Every request re-runs TC1 ``build_index(write=False)`` with a
client that refuses generation, so a cache hit is re-validated by TC1 and a miss is reported as ``ai_error``.
No write, no network, no media route. Absolute server paths are never returned.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from .. import theme_index as tc1
from ..config import Config
from ..selection.client import ChatError
from ..workspace import utc_now
from .playlists import PlaylistError, PlaylistStore
from .urls import valid_playlist_id

MARKER = ".theme_index_preview.json"  # written by scripts/theme_index_preview_fixture.py in the scratch workspace
GENERATION_DISABLED = "generation-disabled: preview không sinh metadata; chưa có index hợp lệ cho dữ liệu hiện tại"
HIDDEN = "[đã ẩn đường dẫn]"
SCHEMA_VERSION = 1
STATUSES = ("indexed", "eligible", "ineligible", "ai_error")
_ABS = re.compile(r"(?<![\w.])(?:/[^\s'\"“”:;,()<>\[\]]+)+")


class RefusingClient:
    """TC1 ``ChatClient`` that never reaches a model: any generation request fails with a fixed reason."""

    def chat(self, **_kwargs):
        raise ChatError(GENERATION_DISABLED)


def redact(text: str) -> str:
    return _ABS.sub(HIDDEN, text)


def _redact_deep(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_deep(v) for v in value]
    if isinstance(value, dict):
        return {redact(k) if isinstance(k, str) else k: _redact_deep(v) for k, v in value.items()}
    return value


def _relative(config: Config, raw: object) -> str | None:
    """Reference relative to the workspace / output root; anything else is hidden."""
    if not isinstance(raw, str):
        return None
    path = Path(raw)
    for root in (Path(config.workspace.dir), Path(config.render.output_dir)):
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return None


# Extractive TC1 content: returned verbatim (changing it would change its meaning). Everything else is redacted.
VERBATIM = ("evidence", "metadata")


def project_record(config: Config, record: dict) -> dict:
    """HTTP view of one TC1 record: all fields kept (evidence, metadata, provenance, uncertainty); every other string
    (reason, favorite, identity, inputs, ...) is redacted of absolute paths, and the source path becomes a reference."""
    out = {k: (v if k in VERBATIM else _redact_deep(v)) for k, v in record.items()}
    ref = record.get("source_reference")
    if isinstance(ref, dict):
        rel = _relative(config, ref.get("path"))
        ref = {k: _redact_deep(v) for k, v in ref.items() if k != "path"}
        ref["reference"] = rel if rel is not None else HIDDEN
        ref["path_hidden"] = rel is None
        out["source_reference"] = ref
    return out


def preview(config: Config, playlist_id: str) -> dict:
    result = tc1.build_index(config, playlist_id, write=False, client=RefusingClient())
    records = [project_record(config, r) for r in result["records"]]
    counts = {s: 0 for s in STATUSES}
    for r in records:
        counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
    synthetic = (Path(config.workspace.dir) / MARKER).is_file()
    return {"schema_version": SCHEMA_VERSION, "playlist_id": playlist_id, "checked_at": utc_now(),
            "data_mode": "synthetic_preview" if synthetic else "unmarked", "generation_enabled": False,
            "counts": counts, "total": len(records), "records": records}


def register(app: FastAPI, config: Config, playlists: PlaylistStore, static_dir: Path) -> None:
    def not_found():
        return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)

    def exists(playlist_id: str):
        """True / False, or a 422 response when the playlist artifact is unreadable."""
        if not valid_playlist_id(playlist_id):
            return False
        try:
            return playlists.load(playlist_id) is not None
        except PlaylistError:
            return JSONResponse({"detail": "dữ liệu bộ kinh không hợp lệ"}, status_code=422)

    def checked(playlist_id: str):
        """None when the playlist is usable, else the 404 / 422 response."""
        found = exists(playlist_id)
        if isinstance(found, JSONResponse):
            return found
        return None if found else not_found()

    @app.get("/playlists/{playlist_id}/theme-index")
    def theme_index_page(playlist_id: str):
        error = checked(playlist_id)
        if error is not None:
            return error
        return FileResponse(static_dir / "theme_index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/playlists/{playlist_id}/theme-index")
    def theme_index_api(playlist_id: str):
        error = checked(playlist_id)
        if error is not None:
            return error
        try:
            return JSONResponse(preview(config, playlist_id), headers={"Cache-Control": "no-store"})
        except tc1.IndexError:
            return JSONResponse({"detail": "dữ liệu yêu thích / bộ kinh không hợp lệ; không thể kiểm tra"},
                                status_code=422, headers={"Cache-Control": "no-store"})
