"""Đọc Kinh routes (SR1 S6). Only ``fastapi`` + this package; auth is the host middleware."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from . import importer, markup
from .store import SutraConflict, SutraError, SutraNotFound, SutraStore

NO_CACHE = {"Cache-Control": "no-cache"}
MAX_JSON_BYTES = 3 * 1024 * 1024


def router(store: SutraStore, static_dir: Path) -> APIRouter:
    r = APIRouter()

    def guard(fn, *args):
        try:
            return fn(*args)
        except SutraNotFound as e:
            raise HTTPException(404, str(e)) from e
        except SutraConflict as e:
            raise HTTPException(409, str(e)) from e
        except SutraError as e:
            raise HTTPException(422, str(e)) from e

    async def read_body(request: Request, limit: int, what: str) -> bytes:
        """Raw body, capped: ``Content-Length`` pre-check, then the real length (CP8.15 P5a pattern)."""
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        too_big = HTTPException(413, f"{what} lớn hơn {limit // (1024 * 1024)} MB")
        if declared > limit:
            raise too_big
        body = await request.body()
        if len(body) > limit:
            raise too_big
        return body

    async def read_json(request: Request) -> dict:
        body = await read_body(request, MAX_JSON_BYTES, "nội dung gửi lên")
        try:
            doc = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise HTTPException(422, "nội dung gửi lên không phải JSON hợp lệ") from e
        if not isinstance(doc, dict):
            raise HTTPException(422, "nội dung gửi lên phải là đối tượng JSON")
        return doc

    def text_field(doc: dict) -> str:
        text = doc.get("text")
        if not isinstance(text, str):
            raise HTTPException(422, "thiếu văn bản kinh (text)")
        return text

    def markup_errors(e: markup.MarkupError) -> JSONResponse:
        return JSONResponse({"detail": str(e), "errors": e.to_json()}, status_code=400)

    @r.get("/sutras")
    async def library_page():
        return FileResponse(static_dir / "sutras.html", headers=NO_CACHE)

    # /sutras/new and /sutras/{slug}/edit are registered BEFORE /sutras/{slug}
    @r.get("/sutras/new")
    async def new_page():
        return FileResponse(static_dir / "sutra-edit.html", headers=NO_CACHE)

    @r.get("/sutras/{slug}/edit")
    async def edit_page(slug: str):
        if not store.exists(slug):
            raise HTTPException(404, "không có bộ kinh này")
        return FileResponse(static_dir / "sutra-edit.html", headers=NO_CACHE)

    @r.get("/sutras/{slug}")
    async def reader_page(slug: str):
        if not store.exists(slug):
            raise HTTPException(404, "không có bộ kinh này")
        return FileResponse(static_dir / "sutra.html", headers=NO_CACHE)

    @r.get("/api/sutras")
    def api_list():
        return store.list()

    @r.get("/api/sutras/{slug}")
    def api_get(slug: str):
        return guard(store.get, slug)

    @r.get("/api/sutras/{slug}/text")
    def api_text(slug: str):
        return guard(store.text, slug)

    @r.post("/api/sutras/import")
    async def api_import(request: Request, name: str = ""):
        """S5: raw body (``.txt`` / ``.docx``), original name in ``?name=``; returns the S2 text to edit."""
        if not name.strip():
            raise HTTPException(422, "cần tên file gốc (?name=...)")
        lower = name.strip().lower()
        if not lower.endswith(importer.EXTENSIONS):
            raise HTTPException(415, "chỉ nhận file .txt hoặc .docx")
        body = await read_body(request, importer.MAX_BYTES, "file")
        try:
            text, warnings = await run_in_threadpool(importer.import_file, name, body)
        except importer.ImportFileError as e:
            raise HTTPException(e.status, str(e)) from e
        return {"text": text, "warnings": warnings}

    @r.post("/api/sutras")
    async def api_create(request: Request, dry_run: int = 0):
        text = text_field(await read_json(request))
        try:
            if dry_run:
                return markup.parse(text).to_json()  # preview only: nothing is written
            slug = store.create(text)
        except markup.MarkupError as e:
            return markup_errors(e)
        except SutraError as e:
            raise HTTPException(422, str(e)) from e
        return JSONResponse({"slug": slug}, status_code=201)

    @r.put("/api/sutras/{slug}")
    async def api_update(slug: str, request: Request):
        doc = await read_json(request)
        text = text_field(doc)
        sha = doc.get("sha256")
        if not isinstance(sha, str) or not sha:
            raise HTTPException(422, "thiếu sha256 của bản đang sửa")
        try:
            return guard(store.update, slug, text, sha)
        except markup.MarkupError as e:
            return markup_errors(e)

    @r.delete("/api/sutras/{slug}")
    def api_delete(slug: str):
        guard(store.delete, slug)
        return {"deleted": slug}

    @r.post("/api/sutras/{slug}/recitations")
    def api_add(slug: str):
        return guard(store.add_recitation, slug)

    @r.delete("/api/sutras/{slug}/recitations/last")
    def api_undo(slug: str):
        return guard(store.undo_recitation, slug)

    return r
