"""Post corrections routes extracted from the app factory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...post import corrections as post_corrections
from ..context import WebContext

log = logging.getLogger("auto_short")


class CorrectionIn(BaseModel):
    """CP8.18 D5 ``POST /api/post-corrections``: a hand-added rule."""

    model_config = {"populate_by_name": True}
    from_: str = Field(alias="from", max_length=500)
    to: str = Field(max_length=500)


class CorrectionEditIn(BaseModel):
    """CP8.18 D5 ``PUT /api/post-corrections/{id}``: any subset of ``status`` / ``from`` / ``to``."""

    model_config = {"populate_by_name": True}
    status: Literal["proposed", "approved", "rejected"] | None = None
    from_: str | None = Field(default=None, alias="from", max_length=500)
    to: str | None = Field(default=None, max_length=500)


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _corr_load() -> dict | JSONResponse:
        try:
            return post_corrections.load(ctx.config.post.corrections_path)
        except post_corrections.CorrectionsError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    def _corr_apply(rule: dict) -> dict:
        return post_corrections.apply_rule_to_posts(Path(ctx.config.workspace.dir), rule, ctx.post_lock, ctx.post_now())

    @router.get("/api/post-corrections")
    def api_corrections():
        with ctx.post_lock:
            try:
                doc, error = post_corrections.load(ctx.config.post.corrections_path), None
            except post_corrections.CorrectionsError as exc:
                doc, error = post_corrections.empty_doc(), str(exc)
        return {"rules": doc["rules"], "stats": post_corrections.stats(ctx.config.post.corrections_path),
                "error": error}

    @router.post("/api/post-corrections")
    def api_corrections_add(body: CorrectionIn):
        now = ctx.post_now()
        with ctx.post_lock:
            doc = _corr_load()
            if isinstance(doc, JSONResponse):
                return doc
            try:
                src, dst = post_corrections.validate_phrases(body.from_, body.to)
                rule = {"id": post_corrections.next_rule_id(doc), "from": src, "to": dst,
                        "status": post_corrections.APPROVED, "count": 0, "examples": [], "created_at": now,
                        "updated_at": now}
                post_corrections.check_unique_approved(doc, rule)
                doc["rules"].append(rule)
                post_corrections.save(ctx.config.post.corrections_path, doc)
            except post_corrections.CorrectionsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        applied = _corr_apply(rule)
        log.info("web: luật sửa lỗi %s thêm tay: %s", rule["id"], applied)
        return {"rule": rule, "applied": applied}

    @router.put("/api/post-corrections/{rule_id}")
    def api_corrections_edit(rule_id: str, body: CorrectionEditIn):
        now = ctx.post_now()
        with ctx.post_lock:
            doc = _corr_load()
            if isinstance(doc, JSONResponse):
                return doc
            rule = post_corrections.find_rule(doc, rule_id)
            if rule is None:
                return JSONResponse({"detail": "không có luật này"}, status_code=404)
            given = body.model_fields_set & {"status", "from_", "to"}
            if not given:
                return JSONResponse({"detail": "cần ít nhất một trong: status, from, to"}, status_code=422)
            try:
                src, dst = post_corrections.validate_phrases(
                    body.from_ if "from_" in given else rule["from"], body.to if "to" in given else rule["to"])
                status = body.status if body.status is not None else rule["status"]
                new = {**rule, "from": src, "to": dst, "status": status, "updated_at": now}
                post_corrections.check_unique_approved(doc, new)
                doc["rules"] = [new if r["id"] == rule_id else r for r in doc["rules"]]
                post_corrections.save(ctx.config.post.corrections_path, doc)
            except post_corrections.CorrectionsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        out: dict = {"rule": new}
        if new["status"] == post_corrections.APPROVED and rule["status"] != post_corrections.APPROVED:
            out["applied"] = _corr_apply(new)
            log.info("web: luật sửa lỗi %s đã duyệt: %s", rule_id, out["applied"])
        return out

    @router.delete("/api/post-corrections/{rule_id}")
    def api_corrections_delete(rule_id: str):
        with ctx.post_lock:
            doc = _corr_load()
            if isinstance(doc, JSONResponse):
                return doc
            if post_corrections.find_rule(doc, rule_id) is None:
                return JSONResponse({"detail": "không có luật này"}, status_code=404)
            doc["rules"] = [r for r in doc["rules"] if r["id"] != rule_id]
            try:
                post_corrections.save(ctx.config.post.corrections_path, doc)
            except post_corrections.CorrectionsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        return {"deleted": rule_id}

    return router
