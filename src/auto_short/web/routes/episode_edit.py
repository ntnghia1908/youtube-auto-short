"""Episode title, cut, Short and community-post editing routes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...pipeline import PreflightError
from ...post import (
    corrections as post_corrections, images as post_images, logic as post_logic,
    source as post_source, stage as post_stage, store as post_store,
)
from ...review import (
    ReviewError, TitlePreview, is_archived, list_titles, preview_title,
    reject_archived_clip, reject_clip, reset_title, restore_clip, set_alternative, set_title,
    shorts as review_shorts,
)
from ...review.names import hashtags as review_hashtags
from ...review.archive import restore_parts
from .. import episodes as ep
from ..context import WebContext, KIND_RESTORE_SOURCE
from ..jobs import KIND_ADD, KIND_PIPELINE, KIND_POST, KIND_RENDER, add_short_target, post_compose_target, render_target
from .models import PublishedIn

log = logging.getLogger("auto_short")


class PreviewIn(BaseModel):
    text: str = Field(max_length=1000)


class TitleIn(BaseModel):
    """Exactly one action: ``set`` (manual text), ``alternative`` (1-based AI alternative) or ``reset: true``."""

    set: str | None = Field(default=None, max_length=1000)
    alternative: int | None = None
    reset: bool = False


SEGMENT_ID = Field(default=None, max_length=32)


class CutPreviewIn(BaseModel):
    """CP9 C7: range of caption lines ``start_segment`` .. ``end_segment`` + nudges (s, ±0.2 steps, ≤ ±2.0);
    ``clip_id`` = the Short being edited (its current range is the base), absent = a new Short."""

    clip_id: str | None = Field(default=None, max_length=32)
    start_segment: str = Field(max_length=32)
    end_segment: str = Field(max_length=32)
    start_nudge: Any = 0
    end_nudge: Any = 0


class CutIn(BaseModel):
    """``{start_segment, end_segment, start_nudge, end_nudge}`` or ``{reset: true}`` ("Về như AI chọn")."""

    start_segment: str | None = SEGMENT_ID
    end_segment: str | None = SEGMENT_ID
    start_nudge: Any = 0
    end_nudge: Any = 0
    reset: bool = False


class AddIn(BaseModel):
    """A new Short: ``{candidate_id}`` (remaining AI proposal) or ``{start_segment, end_segment[, nudges]}``."""

    candidate_id: str | None = Field(default=None, max_length=32)
    start_segment: str | None = SEGMENT_ID
    end_segment: str | None = SEGMENT_ID
    start_nudge: Any = 0
    end_nudge: Any = 0


class PostComposeIn(BaseModel):
    """CP8.15 P9: ``{"clips": [...]}`` (1-based clip ids) or ``{"clips": "all"}`` ("Soạn bài cho mọi Short")."""

    clips: Any = None


class PostEditIn(BaseModel):
    """CP8.15 P9 ``PUT``: any non-empty subset of ``paragraphs`` / ``image`` / ``link``."""

    paragraphs: list[str] | None = Field(default=None, max_length=200)
    image: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=2000)


def _preview_dict(p: TitlePreview | None) -> dict | None:
    if p is None:
        return None
    return {"clip_id": p.clip_id, "title": p.title, "origin": p.origin, "display_lines": list(p.display_lines),
            "font_size": p.font_size, "panel_height": p.panel_height, "chars": len(p.title)}


def validate_restore_edit(config, edit: dict) -> None:
    """Read-only validation before reserving a restore; mutations revalidate after restoration."""
    eid, clip, action, payload = (edit[k] for k in ("episode_id", "clip_id", "action", "payload"))
    if action in ("title", "restore"):
        titles = list_titles(eid, config)
        entry = next((c for c in titles["clips"] if c["clip_id"] == clip), None)
        if entry is None:
            raise ReviewError("không có Short này")
        if action == "title":
            body = TitleIn(**payload)
            if (body.set is not None) + (body.alternative is not None) + bool(body.reset) != 1:
                raise ReviewError("cần đúng một trong: set, alternative, reset")
            if body.set is not None:
                preview_title(eid, config, clip, body.set)
            elif body.alternative is not None:
                alt = next((a for a in entry["alternatives"] if a["n"] == body.alternative), None)
                if alt is None:
                    raise ReviewError("không có phương án tiêu đề này")
                preview_title(eid, config, clip, alt["title"])
        return
    if action == "cut":
        body = CutIn(**payload)
        has_range = body.start_segment is not None and body.end_segment is not None
        if body.reset == has_range or (not has_range and (body.start_segment or body.end_segment)):
            raise ReviewError("cần start_segment + end_segment, hoặc reset: true")
        if body.reset:
            context = review_shorts._context(eid, config)
            review_shorts._clip_key(context, clip)
            start, end = context.original(clip)
            result = review_shorts.C.evaluate(context.rng, review_shorts.C.ms(start), review_shorts.C.ms(end))
            error = result.error
        else:
            error = review_shorts.preview_cut(eid, config, clip_id=clip,
                **body.model_dump(exclude={"reset"}))["error"]
    elif action == "add":
        body = AddIn(**payload)
        if (body.candidate_id is None) == (body.start_segment is None or body.end_segment is None):
            raise ReviewError("cần candidate_id hoặc start_segment + end_segment")
        if body.candidate_id is not None:
            proposal = next((p for p in review_shorts.list_proposals(eid, config)["proposals"]
                             if p["candidate_id"] == body.candidate_id), None)
            if proposal is None:
                raise ReviewError("không có đề xuất AI này")
            error = proposal["error"]
        else:
            error = review_shorts.preview_cut(eid, config, clip_id=None,
                **body.model_dump(exclude={"candidate_id"}))["error"]
    else:
        raise ReviewError("thao tác sau khôi phục không hợp lệ")
    if error:
        raise ReviewError(f"đoạn không hợp lệ: {error}")


def apply_restore_edit(ctx: WebContext, edit: dict):
    """Use the same review functions and job targets as the normal editing routes."""
    eid, clip, action, payload = (edit[k] for k in ("episode_id", "clip_id", "action", "payload"))
    if action == "title":
        body = TitleIn(**payload)
        if body.set is not None:
            set_title(eid, ctx.config, clip, body.set)
        elif body.alternative is not None:
            set_alternative(eid, ctx.config, clip, body.alternative)
        else:
            reset_title(eid, ctx.config, clip)
    elif action == "restore":
        restore_clip(eid, ctx.config, clip)
    elif action == "cut":
        body = CutIn(**payload)
        if body.reset:
            review_shorts.reset_cut(eid, ctx.config, clip)
        else:
            review_shorts.set_cut(eid, ctx.config, clip, **body.model_dump(exclude={"reset"}))
    elif action == "add":
        added = review_shorts.add_short(eid, ctx.config, **AddIn(**payload).model_dump())
        return added.clip_id, add_short_target(ctx.config, added.clip_id, render=ctx.render,
                                               preflight=ctx.preflight, titler=ctx.titler)
    else:
        raise ReviewError("thao tác sau khôi phục không hợp lệ")
    return clip, render_target(ctx.config, render=ctx.render)


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _defer_edit(eid, action, clip=None, body=None):
        """Caller holds submit_lock: share one restore reservation across both episode parts."""
        current = ctx.restore_job(eid)
        restoring = current is not None and current.active
        if not restoring and not is_archived(Path(ctx.config.workspace.dir) / eid):
            return None
        owner = ep.hd_owner(eid)
        busy = next((j for j in ctx.runner.jobs() if j.active and ep.hd_owner(j.episode_id) == owner
                     and j is not current), None)
        if busy is not None or (restoring and not current.target.accepting_edits):
            return JSONResponse({"detail": "video đang có job chạy/đợi; thử lại sau khi xong",
                                 "job": ctx.job_view(busy or current)}, status_code=409)
        edit = {"episode_id": eid, "action": action, "clip_id": clip,
                "payload": body.model_dump() if body is not None else {}}
        try:
            validate_restore_edit(ctx.config, edit)
            if not restoring:
                restore_parts(eid, ctx.config)
        except (ReviewError, OSError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if restoring:
            # Persist the appended request using the runner's existing queue serialization lock.
            with ctx.runner._lock:
                current.target.edits.append(edit)
                ctx.runner._save_locked()
            job = current
        else:
            job, _ = ctx.runner.submit(owner, KIND_RESTORE_SOURCE, ctx.restore_target(eid, edits=[edit]))
        return JSONResponse({"queued": "restore", "job": ctx.job_view(job)}, status_code=202)

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/title/preview")
    def api_title_preview(episode_id: str, clip_id: str, body: PreviewIn):
        if (bad := ctx.check_clip(episode_id, clip_id, error_response=JSONResponse)) is not None:
            return bad
        try:
            return _preview_dict(preview_title(episode_id, ctx.config, clip_id, body.text))
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/title")
    def api_title(episode_id: str, clip_id: str, body: TitleIn):
        if (bad := ctx.check_clip(episode_id, clip_id, error_response=JSONResponse)) is not None:
            return bad
        actions = (body.set is not None) + (body.alternative is not None) + bool(body.reset)
        if actions != 1:
            return JSONResponse({"detail": "cần đúng một trong: set, alternative, reset"}, status_code=422)
        with ctx.submit_lock:
            if (deferred := _defer_edit(episode_id, "title", clip_id, body)) is not None:
                return deferred
            current = ctx.runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; sửa title sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            try:
                if body.set is not None:
                    preview = set_title(episode_id, ctx.config, clip_id, body.set)
                elif body.alternative is not None:
                    preview = set_alternative(episode_id, ctx.config, clip_id, body.alternative)
                else:
                    preview = reset_title(episode_id, ctx.config, clip_id)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = ctx.runner.submit(episode_id, KIND_RENDER, render_target(ctx.config, render=ctx.render),
                                   clip_ids=[clip_id])
        log.info("web: title %s [%s]: %s -> render job %s", clip_id, episode_id,
                 f"{preview.origin} {preview.title!r}" if preview else "reset (untitled)", job.id)
        return JSONResponse({"preview": _preview_dict(preview), "job": ctx.job_view(job)}, status_code=202)

    def _review_render(episode_id: str, clip_id: str, action: Callable, what: str) -> JSONResponse:
        """CP8.5 X2: delete / restore one Short = write review.json + render job, same rules as a title write
        (409 while a job of the episode is queued/running, all under the submit lock)."""
        if (bad := ctx.check_clip(episode_id, clip_id, error_response=JSONResponse)) is not None:
            return bad
        with ctx.submit_lock:
            if action is restore_clip and (deferred := _defer_edit(episode_id, "restore", clip_id)) is not None:
                return deferred
            current = ctx.runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; thử lại sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            archived = is_archived(Path(ctx.config.workspace.dir) / episode_id)
            try:
                if archived and action is reject_clip:
                    # CP8.6 S3: no render possible; the deletion is applied to the last render directly.
                    changed = reject_archived_clip(episode_id, ctx.config, clip_id)
                    ctx.storage.invalidate()
                    log.info("web: %s %s [%s] (archived, no render)", what, clip_id, episode_id)
                    return JSONResponse({"changed": changed, "job": None})
                changed = action(episode_id, ctx.config, clip_id)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = ctx.runner.submit(episode_id, KIND_RENDER, render_target(ctx.config, render=ctx.render),
                                   clip_ids=[clip_id])
        log.info("web: %s %s [%s]%s -> render job %s", what, clip_id, episode_id, "" if changed else " (no change)",
                 job.id)
        return JSONResponse({"changed": changed, "job": ctx.job_view(job)}, status_code=202)

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/delete")
    def api_short_delete(episode_id: str, clip_id: str):
        response = _review_render(episode_id, clip_id, reject_clip, "delete Short")
        if response.status_code < 300:
            ctx.compilations.drop_hearts(episode_id, clip_id)  # CP8.33 G11 (c): a hand-deleted khai thị loses its heart
        return response

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/restore")
    def api_short_restore(episode_id: str, clip_id: str):
        return _review_render(episode_id, clip_id, restore_clip, "restore Short")

    @router.post("/api/episodes/{episode_id}/cut/preview")
    def api_cut_preview(episode_id: str, body: CutPreviewIn):
        """C7: range + duration + C4 error / warnings of lines + nudges; nothing written, allowed during a job."""
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        if body.clip_id is not None and not ep.valid_clip_id(body.clip_id):
            return JSONResponse({"detail": "không có Short này"}, status_code=404)
        try:
            return review_shorts.preview_cut(episode_id, ctx.config, clip_id=body.clip_id,
                                             start_segment=body.start_segment, end_segment=body.end_segment,
                                             start_nudge=body.start_nudge, end_nudge=body.end_nudge)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/cut")
    def api_cut(episode_id: str, clip_id: str, body: CutIn):
        """C7: save the cut points of one Short (or ``reset``) + render job for it; 409 while a job runs or when
        the source video was cleaned up; 422 invalid range (review.json unchanged)."""
        if (bad := ctx.check_clip(episode_id, clip_id, error_response=JSONResponse)) is not None:
            return bad
        has_range = body.start_segment is not None and body.end_segment is not None
        if body.reset == has_range or (not has_range and (body.start_segment or body.end_segment)):
            return JSONResponse({"detail": "cần start_segment + end_segment, hoặc reset: true"}, status_code=422)
        with ctx.submit_lock:
            if (deferred := _defer_edit(episode_id, "cut", clip_id, body)) is not None:
                return deferred
            if (busy := ctx.busy(episode_id, error_response=JSONResponse)) is not None:
                return busy
            try:
                if body.reset:
                    preview = review_shorts.reset_cut(episode_id, ctx.config, clip_id)
                else:
                    preview = review_shorts.set_cut(episode_id, ctx.config, clip_id, start_segment=body.start_segment,
                                                    end_segment=body.end_segment, start_nudge=body.start_nudge,
                                                    end_nudge=body.end_nudge)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = ctx.runner.submit(episode_id, KIND_RENDER, render_target(ctx.config, render=ctx.render),
                                   clip_ids=[clip_id])
        log.info("web: cut %s [%s]: %s %.3f-%.3f (%.1f s) -> render job %s", clip_id, episode_id,
                 "reset" if body.reset else "set", preview["start"], preview["end"], preview["duration"], job.id)
        return JSONResponse({"preview": preview, "job": ctx.job_view(job)}, status_code=202)

    @router.post("/api/episodes/{episode_id}/shorts")
    def api_add_short(episode_id: str, body: AddIn):
        """C7: add a Short (C1) -> job: AI title (lane ai, C6) then render. 409 while a job runs / archived;
        503 Ollama preflight (W4); 422 invalid range or proposal (nothing written)."""
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        with ctx.submit_lock:
            if (deferred := _defer_edit(episode_id, "add", body=body)) is not None:
                return deferred
            if (busy := ctx.busy(episode_id, error_response=JSONResponse)) is not None:
                return busy
        if ctx.preflight is not None:
            try:
                ctx.preflight(ctx.config)
            except PreflightError as exc:
                return JSONResponse({"detail": f"ollama preflight: {exc}"}, status_code=503)
        with ctx.submit_lock:
            if (deferred := _defer_edit(episode_id, "add", body=body)) is not None:
                return deferred
            if (busy := ctx.busy(episode_id, error_response=JSONResponse)) is not None:
                return busy
            try:
                added = review_shorts.add_short(episode_id, ctx.config, candidate_id=body.candidate_id,
                                                start_segment=body.start_segment, end_segment=body.end_segment,
                                                start_nudge=body.start_nudge, end_nudge=body.end_nudge)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = ctx.runner.submit(episode_id, KIND_ADD,
                                   add_short_target(ctx.config, added.clip_id, render=ctx.render, preflight=ctx.preflight,
                                                    titler=ctx.titler),
                                   clip_ids=[added.clip_id])
        log.info("web: added Short %s [%s] %.3f-%.3f (%.1f s, %s) -> job %s", added.clip_id, episode_id,
                 added.preview["start"], added.preview["end"], added.preview["duration"],
                 body.candidate_id or "transcript", job.id)
        return JSONResponse({"clip_id": added.clip_id, "preview": added.preview, "job": ctx.job_view(job)},
                            status_code=202)

    @router.get("/api/episodes/{episode_id}/posts")
    def api_posts(episode_id: str):
        """P7/P9: every stored post of the episode (read-only, allowed while a job runs); ``post_error`` when
        ``posts.json`` is broken (not overwritten)."""
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        with ctx.post_lock:
            try:
                doc = post_store.read_posts(ctx.posts_path(episode_id), episode_id)
                post_error = None
            except post_store.PostsError as exc:
                doc, post_error = post_store.empty_posts(episode_id), str(exc)
        try:
            ep_src = post_source.load(episode_id, ctx.config)
        except post_source.PostSourceError:
            ep_src = None
        titles_by_clip: dict[str, str | None] = {}
        try:
            titles_by_clip = {c["clip_id"]: c["title"] for c in list_titles(episode_id, ctx.config)["clips"]}
        except ReviewError:
            pass
        header_fields = ctx.post_header_fields(episode_id)
        series, tags = ctx.post_series_and_tags(episode_id)
        hashtags_list = review_hashtags(series, tags)
        posts = [ctx.post_entry_view(e, ep_src=ep_src, title=titles_by_clip.get(e["clip_id"]),
                                  header_fields=header_fields, hashtags_list=hashtags_list) for e in doc["posts"]]
        return {"posts": posts, "post_error": post_error}

    def _post_clips(body: PostComposeIn) -> "list[str] | str | JSONResponse":
        raw = body.clips
        if raw in ("all", "auto"):  # "auto": CP8.16 R4
            return raw
        if not isinstance(raw, list) or not raw or not all(isinstance(c, str) and ep.valid_clip_id(c) for c in raw):
            return JSONResponse({"detail": 'clips phải là "all", "auto" hoặc một danh sách clip_id không rỗng'},
                                status_code=422)
        return raw

    @router.post("/api/episodes/{episode_id}/posts")
    def api_posts_compose(episode_id: str, body: PostComposeIn):
        """P1 (CP8.16 R3): soạn / soạn lại bài (lane ai) -> 202 job (job soạn bài đang đợi -> trả job đó); 409 khi
        episode đang có job ``pipeline`` (không còn 503 Ollama, FIX-ollama-wait O4). Không bị khóa bởi job render / add."""
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        clips = _post_clips(body)
        if isinstance(clips, JSONResponse):
            return clips
        with ctx.submit_lock:  # FIX-ollama-wait O4: no preflight in the request; the ai lane waits for the GPU
            current = ctx.runner.latest(episode_id)
            if current is not None and current.active and current.kind == KIND_PIPELINE:
                return JSONResponse({"detail": "episode đang chạy pipeline; soạn bài sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            job, _created = ctx.runner.submit(episode_id, KIND_POST,
                                          post_compose_target(ctx.config, clips, compose=ctx.post_compose,
                                                              preflight=ctx.post_preflight, lock=ctx.post_lock))
        log.info("web: soạn bài %s [%s] -> job %s", clips if isinstance(clips, str) else ",".join(clips), episode_id,
                 job.id)
        return JSONResponse({"job": ctx.job_view(job)}, status_code=202)

    def _learn_corrections(episode_id: str, clip: str, old: list[str], new: list[str], now: str) -> int | None:
        """CP8.18 D2/D6 (caller holds ``post_lock``): log the edit and record the proposals; any dictionary / IO
        failure is a warning and ``None``, never a failure of the post save."""
        path = ctx.config.post.corrections_path
        try:
            proposals, words, changed = post_corrections.extract(old, new)
            post_corrections.append_edit_log(path, at=now, episode_id=episode_id, clip_id=clip, words=words,
                                             changed_words=changed)
            if not proposals:
                return 0
            cdoc = post_corrections.load(path)
            post_corrections.record(cdoc, proposals, episode_id, clip, now)
            post_corrections.save(path, cdoc)
            return len(proposals)
        except (post_corrections.CorrectionsError, OSError) as exc:
            log.warning("web: từ điển sửa lỗi: %s", exc)
            return None

    @router.put("/api/episodes/{episode_id}/posts/{clip}")
    def api_posts_edit(episode_id: str, clip: str, body: PostEditIn):
        """P9: sửa tay ``paragraphs`` (-> ``origin: manual``) / đổi ``image`` / sửa ``link`` (P6); được cả khi job
        đang chạy (P7); cần đã có bài (bấm "Soạn bài" trước)."""
        if (bad := ctx.check_clip(episode_id, clip, error_response=JSONResponse)) is not None:
            return bad
        given = body.model_fields_set & {"paragraphs", "image", "link"}
        if not given:
            return JSONResponse({"detail": "cần ít nhất một trong: paragraphs, image, link"}, status_code=422)
        changes: dict = {}
        if "paragraphs" in given:
            paragraphs = body.paragraphs
            if not isinstance(paragraphs, list) or not paragraphs \
                    or not all(isinstance(p, str) and p.strip() for p in paragraphs):
                return JSONResponse({"detail": "paragraphs phải là mảng chuỗi không rỗng"}, status_code=422)
            changes["paragraphs"] = [p.strip() for p in paragraphs]
            changes["origin"] = post_store.MANUAL
        if "image" in given:
            if body.image is None or post_images.resolve(ctx.config.post.image_dir, body.image) is None:
                return JSONResponse({"detail": "không có ảnh này trong thư viện"}, status_code=404)
            changes["image"] = body.image
        if "link" in given:
            try:
                changes["link"] = post_logic.normalize_link(body.link)
            except post_logic.LinkError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        order = [cid for cid, _ in post_stage.rendered_clip_ids(ctx.config, episode_id)]
        proposed: int | None = None
        with ctx.post_lock:
            try:
                doc = post_store.read_posts(ctx.posts_path(episode_id), episode_id)
                old_paragraphs = post_store.find(doc, clip)["paragraphs"] if post_store.find(doc, clip) else None
                now = ctx.post_now()
                doc = post_store.with_fields(doc, order, clip, changes, now=now)
            except post_store.PostsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            post_store.write(ctx.posts_path(episode_id), doc)
            if "paragraphs" in given and old_paragraphs is not None:
                proposed = _learn_corrections(episode_id, clip, old_paragraphs, changes["paragraphs"], now)
        entry = post_store.find(doc, clip)
        try:
            ep_src = post_source.load(episode_id, ctx.config)
        except post_source.PostSourceError:
            ep_src = None
        title = None
        try:
            title = next((c["title"] for c in list_titles(episode_id, ctx.config)["clips"] if c["clip_id"] == clip), None)
        except ReviewError:
            pass
        header_fields = ctx.post_header_fields(episode_id)
        series, tags = ctx.post_series_and_tags(episode_id)
        log.info("web: post %s [%s] sửa %s", clip, episode_id, ", ".join(sorted(given)))
        view = ctx.post_entry_view(entry, ep_src=ep_src, title=title, header_fields=header_fields,
                                hashtags_list=review_hashtags(series, tags))
        if "paragraphs" in given:
            view["proposed"] = proposed  # CP8.18 D5 (null: the dictionary failed, the post was still saved)
        return view

    @router.post("/api/episodes/{episode_id}/posts/{clip}/posted")
    def api_posts_posted(episode_id: str, clip: str, body: PublishedIn):
        """P8: tick / untick "Đã đăng bài" — độc lập với "Đã đăng" Short (``publish.json``); được cả khi job
        đang chạy."""
        if (bad := ctx.check_clip(episode_id, clip, error_response=JSONResponse)) is not None:
            return bad
        order = [cid for cid, _ in post_stage.rendered_clip_ids(ctx.config, episode_id)]
        with ctx.post_lock:
            try:
                doc = post_store.read_posts(ctx.posts_path(episode_id), episode_id)
                doc = post_store.with_posted(doc, order, clip, body.value, now=ctx.post_now())
            except post_store.PostsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            post_store.write(ctx.posts_path(episode_id), doc)
        entry = post_store.find(doc, clip)
        log.info("web: post %s [%s] %s \"Đã đăng bài\"", clip, episode_id, "tick" if body.value else "untick")
        return {"clip_id": clip, "posted": entry["posted_at"] is not None, "posted_at": entry["posted_at"]}

    return router
