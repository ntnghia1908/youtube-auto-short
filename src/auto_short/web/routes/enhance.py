"""Enhance routes extracted from the app factory."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, StrictBool

from ...enhance.state import EnhanceError
from ...enhance.tokens import authenticate as enhance_authenticate
from ..context import WebContext, SOURCE_TYPES


class EnhanceLeaseIn(BaseModel):
    worker: str | None = Field(default=None, max_length=80)
    gpu: str | None = Field(default=None, max_length=80)
    gpu_stats: Any = None  # CP8.28: optional ``nvidia-smi`` numbers (an old worker never sends them)
    capabilities: Any = None  # CP13.4: optional, e.g. ``["face:gfpgan_v1.4"]`` (an old worker never sends it)


class EnhanceBeatIn(BaseModel):
    progress: Any = None
    gpu_stats: Any = None  # CP8.28


class EnhanceReleaseIn(BaseModel):
    reason: Any = None


class EnhancePauseIn(BaseModel):
    paused: StrictBool


_LEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    async def _worker(request: Request) -> str:
        name = enhance_authenticate(ctx.tokens, request.headers.get("authorization"))
        if name is None:
            raise HTTPException(status_code=401, detail="token enhance sai hoặc thiếu")
        return name

    def _lease_id_ok(lease_id: str) -> bool:
        return bool(_LEASE_ID_RE.match(lease_id))

    @router.post("/api/enhance/lease")
    def api_enhance_lease(body: EnhanceLeaseIn, name: str = Depends(_worker)):
        """E3: the next video for the worker ``{episode_id, lease_id, expires_at, source_url, ...}`` or 204."""
        info = ctx.svc.lease(name, body.worker, body.gpu, body.gpu_stats, body.capabilities)
        return Response(status_code=204) if info is None else JSONResponse(info)

    @router.get("/api/enhance/may-run")
    def api_enhance_may_run(worker: str | None = None, gpu_stats: str | None = None,
                            name: str = Depends(_worker)):
        """E7: ``{run, reason, preempt}`` for the worker (``preempt`` = stop mid-segment, FIX-enhance-yield; the token name decides; ``worker`` is only a display label).
        ``gpu_stats`` (CP8.28, optional): the worker's ``nvidia-smi`` numbers as compact JSON (ignored when unusable)."""
        stats = None
        if gpu_stats and len(gpu_stats) <= 1000:
            try:
                stats = json.loads(gpu_stats)
            except ValueError:
                stats = None
        ctx.svc.ping(name, worker[:80] if worker else None, stats)
        run, reason, preempt = ctx.svc.may_run_info(name)
        return {"run": run, "reason": reason, "preempt": preempt}

    @router.get("/api/enhance/status")
    def api_enhance_status():
        """E8 / E10: read-only status for the UI (web cookie, not a worker route)."""
        return ctx.svc.status()

    @router.get("/api/enhance/{lease_id}/source")
    def api_enhance_source(lease_id: str, name: str = Depends(_worker)):
        """E3: the source video (``Range`` supported)."""
        if not _lease_id_ok(lease_id):
            return JSONResponse({"detail": "lease không hợp lệ"}, status_code=409)
        try:
            path = ctx.svc.source_path(name, lease_id)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        return FileResponse(path, media_type=SOURCE_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                            headers={"Cache-Control": "no-store"})

    @router.put("/api/enhance/{lease_id}/seg/{n}")
    async def api_enhance_put(lease_id: str, n: int, request: Request, name: str = Depends(_worker)):
        """E3: one enhanced segment (mp4 body, header ``X-Sha256``): checked, stored (idempotent), renews the lease."""
        if not _lease_id_ok(lease_id) or not 0 <= n <= 99999:
            return JSONResponse({"detail": "lease / đoạn không hợp lệ"}, status_code=400)
        limit = ctx.config.enhance.max_segment_mb * 2 ** 20
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > limit:
            return JSONResponse({"detail": f"đoạn lớn hơn {ctx.config.enhance.max_segment_mb} MB"}, status_code=413)
        try:
            put_ctx = await asyncio.to_thread(ctx.svc.check_put, name, lease_id, n)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        try:
            digest, size = hashlib.sha256(), 0
            with open(put_ctx.tmp, "wb") as fh:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        return JSONResponse({"detail": f"đoạn lớn hơn {ctx.config.enhance.max_segment_mb} MB"},
                                            status_code=413)
                    digest.update(chunk)
                    await asyncio.to_thread(fh.write, chunk)
            result = await asyncio.to_thread(ctx.svc.accept, put_ctx, request.headers.get("x-sha256"), digest.hexdigest())
            return result
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        finally:
            put_ctx.cleanup()  # no-op after a successful rename

    @router.post("/api/enhance/{lease_id}/heartbeat")
    def api_enhance_heartbeat(lease_id: str, body: EnhanceBeatIn, name: str = Depends(_worker)):
        if not _lease_id_ok(lease_id):
            return JSONResponse({"detail": "lease không hợp lệ"}, status_code=409)
        try:
            return ctx.svc.heartbeat(name, lease_id, body.progress, body.gpu_stats)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)

    @router.post("/api/enhance/{lease_id}/release")
    def api_enhance_release(lease_id: str, body: EnhanceReleaseIn, name: str = Depends(_worker)):
        if not _lease_id_ok(lease_id):
            return JSONResponse({"detail": "lease không hợp lệ"}, status_code=409)
        try:
            return ctx.svc.release(name, lease_id, body.reason)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)

    @router.post("/api/enhance-pause")
    def api_enhance_pause(body: EnhancePauseIn):
        """E7 "Tạm dừng enhance" (global): every worker's ``may-run`` answers ``run: false``; no new lease."""
        ctx.svc.set_paused(body.paused)
        return ctx.svc.status()

    return router
