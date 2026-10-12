"""Đọc Kinh routes (SR1 S6, read / count part). Only ``fastapi`` + this package; auth is the host middleware."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .store import SutraConflict, SutraError, SutraNotFound, SutraStore

NO_CACHE = {"Cache-Control": "no-cache"}


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

    @r.get("/sutras")
    async def library_page():
        return FileResponse(static_dir / "sutras.html", headers=NO_CACHE)

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

    @r.post("/api/sutras/{slug}/recitations")
    def api_add(slug: str):
        return guard(store.add_recitation, slug)

    @r.delete("/api/sutras/{slug}/recitations/last")
    def api_undo(slug: str):
        return guard(store.undo_recitation, slug)

    return r
