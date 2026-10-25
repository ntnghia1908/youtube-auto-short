"""Episode viewing, publication, source and job routes."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from ... import khaithi
from ...compilation import CompilationError
from ...enhance import state as enh_state
from ...enhance.state import EnhanceError
from ...pipeline import PIPELINE_STAGES
from ...post import store as post_store
from ...render import full as render_full
from ...review import (
    ArchivedError, EpisodeNotFound, ReviewError, archive_source, content_disposition,
    delete_episode, is_archived, list_titles, set_published, set_watched, shorts as review_shorts,
)
from ...review import backup as review_backup
from ...review.archive import restore_parts
from ...review.names import hashtags as review_hashtags
from ...store.client import StoreClient, StoreMismatch, StoreUnavailable
from .. import episodes as ep
from ..context import WebContext, KIND_RESTORE_SOURCE, KINDS
from ..jobs import KIND_ADD, KIND_COMPILATION, KIND_RENDER, KIND_VERTICAL, render_target
from ..playlists import PlaylistError
from ..urls import ASK, PLAYLIST, UrlError, classify_url
from .models import PublishedIn

log = logging.getLogger("auto_short")
MAX_FIELD = 100


class SubmitIn(BaseModel):
    url: str = Field(max_length=2000)
    series: str | None = Field(default=None, max_length=MAX_FIELD)
    episode: str | None = Field(default=None, max_length=MAX_FIELD)
    # CP8.7 L2: for ``watch?v=…&list=…`` the user chooses the single video or the whole playlist
    mode: Literal["video", "playlist"] | None = None
    # CP8.9 A1.1: ["short", "khaithi"] (absent = both) + khai thị minutes; checked in the handler (Vietnamese 422)
    kinds: Any = None
    min_minutes: Any = None
    max_minutes: Any = None
    # CP8.35 D3: also make the vertical full-episode version once the Shorts and the best HD source are ready
    vertical: bool = False


class EnhanceSwitchIn(BaseModel):
    enabled: StrictBool


class BackupIn(BaseModel):
    kind: Literal["hd", "vertical"]
    sha256: str = Field(max_length=200)


class ReleaseIn(BaseModel):
    allow_no_vertical: StrictBool = False


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


class _StoreResponse(StreamingResponse):
    """Close the upstream socket even on disconnect, including before the first chunk was read."""

    def __init__(self, stream, *, status_code, headers):
        self.stream = stream

        async def chunks():
            while (chunk := await asyncio.to_thread(next, stream, None)) is not None:
                yield chunk

        super().__init__(chunks(), status_code=status_code, headers=headers, media_type="video/mp4")

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.stream.close()


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/episodes")
    def api_list():
        items = ep.list_episodes(ctx.config)
        known = {i["id"] for i in items}
        for job in ctx.runner.jobs():  # queued jobs whose workspace does not exist yet
            if job.active and job.episode_id not in known and job.kind != KIND_COMPILATION:
                known.add(job.episode_id)
                items.insert(0, {**ep.kind_fields(ctx.config, job.episode_id), "id": job.episode_id, "title": None,
                                 "stages_done": 0, "stages_total": len(PIPELINE_STAGES), "running": None,
                                 "failed": None, "shorts": 0})
        in_playlists = ctx.playlists.video_ids()
        for item in items:
            job = ctx.runner.latest(item["id"])
            item["job"] = ctx.job_view(job, logs=False)
            item["priority"] = ctx.runner.priority.marked(item["id"])  # CP8.26
            item.setdefault("published", 0)
            item.setdefault("complete", False)
            item["publish_group"] = ep.publish_group(item)
            # CP8.7: home page "Tập lẻ" = not in a bộ kinh; CP8.9 K8: a khai thị episode follows its base video
            item["in_playlist"] = (item.get("base_episode_id") or item["id"]) in in_playlists
        return {"episodes": items, "gpu": ctx.runner.gpu_status(), "youtube": ctx.runner.youtube_status(), "queue": ctx.runner.queue_state()}  # O7, CP8.22

    def _kinds(body: SubmitIn) -> list[str] | JSONResponse:
        """CP8.9 A1.1: ``kinds`` (absent = Short + khai thị), always in the order Short then khai thị."""
        raw = body.kinds
        if raw is None:
            kinds = list(KINDS)
        else:
            if not isinstance(raw, list) or not raw or not all(isinstance(k, str) and k in KINDS for k in raw):
                return JSONResponse({"detail": "kinds phải là danh sách không rỗng gồm \"short\" và / hoặc "
                                               "\"khaithi\""}, status_code=422)
            if len(set(raw)) != len(raw):
                return JSONResponse({"detail": "kinds bị trùng"}, status_code=422)
            kinds = [k for k in KINDS if k in raw]
        if khaithi.KIND not in kinds and (body.min_minutes is not None or body.max_minutes is not None):
            return JSONResponse({"detail": "Số phút chỉ dùng khi có video khai thị"}, status_code=422)
        return kinds

    @router.post("/api/episodes")
    def api_submit(body: SubmitIn):
        kinds = _kinds(body)
        if isinstance(kinds, JSONResponse):
            return kinds
        try:
            parsed = classify_url(body.url)
        except UrlError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if parsed.kind == ASK and body.mode is None:  # CP8.7 L2: the UI asks "tập lẻ" or "cả bộ kinh"
            return JSONResponse({"kind": ASK, "video_id": parsed.video_id, "playlist_id": parsed.playlist_id})
        if parsed.kind == PLAYLIST or (parsed.kind == ASK and body.mode == "playlist"):
            return _import_playlist(parsed.playlist_id)  # A1.3: kinds / minutes do not apply to a bộ kinh
        if body.mode == "playlist":
            return JSONResponse({"detail": "URL không có playlist"}, status_code=422)
        lo = hi = None
        if khaithi.KIND in kinds:  # K2 minutes (absent = [khaithi] defaults)
            kc = ctx.config.khaithi
            try:
                lo, hi = khaithi.check_minutes(
                    kc.default_min_minutes if body.min_minutes is None else body.min_minutes,
                    kc.default_max_minutes if body.max_minutes is None else body.max_minutes, kc.max_minutes_limit)
            except khaithi.KhaithiError as exc:
                return JSONResponse({"detail": exc.vi}, status_code=422)
        video_id = parsed.video_id
        series, episode = _clean(body.series), _clean(body.episode)
        items = ctx.queue_video(video_id, kinds, lo, hi, series, episode, vertical_wish=body.vertical)
        out = [{k: (ctx.job_view(v) if k == "job" else v) for k, v in i.items()} for i in items]
        ok = [i for i in out if "error" not in i]
        if not ok:
            return JSONResponse({"detail": out[0]["error"], "kind": "video", "episodes": out},
                                status_code=out[0]["status"])
        first = ok[0]  # UI before A1: created / episode_id / job of the first accepted episode
        return JSONResponse({"kind": "video", "episodes": out, "created": first["created"],
                             "episode_id": first["episode_id"], "job": first["job"]},
                            status_code=202 if any(i.get("created") for i in ok) else 200)

    def _import_playlist(playlist_id: str) -> JSONResponse:
        try:
            doc, created = ctx.playlists.add(playlist_id)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)
        log.info("web: playlist %s %s (%d entries)", playlist_id, "imported" if created else "already stored",
                 len(doc["entries"]))
        return JSONResponse({"kind": PLAYLIST, "created": created, "playlist_id": playlist_id,
                             "title": doc.get("title"), "count": len(doc["entries"])},
                            status_code=201 if created else 200)

    @router.get("/api/episodes/{episode_id}")
    def api_episode(episode_id: str):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        kf = ep.kind_fields(ctx.config, episode_id)
        # CP8.9 K8: a khai thị episode copies with the hashtags of the bộ kinh of its base video
        view = ep.episode_view(ctx.config, episode_id,
                               hashtags=ctx.playlists.hashtags_for(kf["base_episode_id"] or episode_id))
        job = ctx.runner.latest(episode_id)
        if view is None:
            if job is None:
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            view = {**kf, "id": episode_id, "title": None, "channel": None, "duration": None, "source_url": None,
                    "stages": [], "header": None, "shorts": [], "rendered": 0, "deleted": 0, "published": 0,
                    "zip_url": None, "zip_name": None, "zip_all_url": None, "zip_all_name": None,
                    "archived": None}
        view["job"] = ctx.job_view(job)
        rm = ep.render_manifest(ctx.config, episode_id) or {}
        rendered_ids = {s.get("clip_id") for s in rm.get("shorts", []) if s.get("status") == "rendered"}
        with ctx.post_lock:
            view["post_unticked"] = sum(1 for e in post_store.read_posts_quiet(ctx.posts_path(episode_id), episode_id)["posts"]
                                         if e["posted_at"] is None and e["clip_id"] in rendered_ids)
        view["restore_job"] = ctx.job_view(ctx.restore_job(episode_id))
        view["priority"] = ctx.runner.priority.marked(episode_id)  # CP8.26
        view["gpu"] = ctx.runner.gpu_status()  # FIX-ollama-wait O7
        view["youtube"] = ctx.runner.youtube_status()  # FIX-youtube-botcheck-wait Y3
        view["post_job"] = ctx.job_view(ctx.runner.latest_post(episode_id))  # CP8.16 R3 (job stays the episode's own job)
        view["enhance"] = _enhance_view(episode_id)  # CP13.1 E10
        view["hd_video"] = _hd_video_view(episode_id)  # CP8.27
        # CP8.33 G9 / G11: heart state of a khai thị episode (its bộ kinh + hearted clips), favourites that a delete loses
        fav = ctx.compilations.episode_favorites(episode_id)
        view["favorites"] = fav
        view["favorites_count"] = ctx.compilations.keep_count(episode_id)
        hearted = set(fav["clips"]) if fav else set()
        for short in view["shorts"]:
            short["favorite"] = short["clip_id"] in hearted
        if job is not None and job.active and job.kind in (KIND_RENDER, KIND_ADD):
            for short in view["shorts"]:
                short["rendering"] = short["clip_id"] in job.clip_ids
        return view

    def _size_or_none(path: Path | None) -> int | None:
        """A re-downloaded original can vanish between the view's checks (the vertical job cleans it up): no 500."""
        try:
            return path.stat().st_size if path is not None else None
        except OSError:
            return None

    def _hd_video_view(episode_id: str) -> dict | None:
        """CP8.27 H2 / H4 + CP8.32: the HD download (landscape) and the vertical full-episode file of the video, None
        while there is no effective HD source (``source``: ``hd`` | ``original`` | ``archived``; an archived original
        has no landscape download, ``url`` is None, and its vertical job downloads it again)."""
        src = ep.hd_source(ctx.config, episode_id)
        owner = ep.hd_owner(episode_id)
        backup = review_backup.view(ctx.config, owner)  # HD1 G3
        on_store = src is None and backup["released"] and ctx.config.store.enabled  # HD2a: the HD is on the 3090
        if src is None and not on_store:
            if backup["released"]:  # HD moved to an external machine: no HD / vertical link, only the fact
                return {"url": None, "name": None, "size": None, "source": "released", "vertical": None, **backup}
            return None
        hd = src.path if src is not None else None
        ready = render_full.ready_file(ctx.config, owner) if render_full.current(ctx.config, owner) else None
        job = ctx.runner.latest_vertical(owner)
        stored = render_full.on_store(ctx.config, owner)
        return {"url": f"/api/episodes/{episode_id}/source-hd" if hd is not None or on_store else None,
                "name": ep.hd_download_name(ctx.config, episode_id) if hd is not None or on_store else None,
                "size": _size_or_none(hd), "source": src.kind if src is not None else "released",
                **({"store": True} if on_store else {}),
                "vertical": {"ready": ready is not None or stored is not None,
                             "store": stored is not None,
                             "url": f"/api/episodes/{episode_id}/vertical",
                             "name": ep.video_download_name(ctx.config, episode_id, "Doc"),
                             "size": ready.stat().st_size if ready is not None else (stored or {}).get("size"),
                             "job": ctx.job_view(job, logs=False)}, **backup}

    @router.post("/api/episodes/{episode_id}/priority")
    def api_episode_priority(episode_id: str, body: PublishedIn):
        """CP8.26 P1 "Ưu tiên" / "Bỏ ưu tiên": the mark is per video (the Short and its khai thị episode share it)."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        if body.value:
            ctx.runner.priority.mark([episode_id])
        else:
            ctx.runner.priority.unmark([episode_id])
        return {"episode_id": episode_id, "priority": ctx.runner.priority.marked(episode_id)}

    @router.get("/api/episodes/{episode_id}/transcript")
    def api_transcript(episode_id: str):
        """C7: caption lines + the current range of every Short (read-only, allowed while a job runs)."""
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        try:
            return review_shorts.transcript_view(episode_id, ctx.config)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.get("/api/episodes/{episode_id}/proposals")
    def api_proposals(episode_id: str):
        """C7: AI proposals not selected (overlapped / over_limit / ineligible) that map to a candidate."""
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        try:
            return review_shorts.list_proposals(episode_id, ctx.config)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/published")
    def api_short_published(episode_id: str, clip_id: str, body: PublishedIn):
        """X4: tick / untick "Đã đăng" — user state only: no job, allowed while a job runs, render not stale."""
        if (bad := ctx.check_clip(episode_id, clip_id, error_response=JSONResponse)) is not None:
            return bad
        with ctx.publish_lock:
            try:
                result = set_published(episode_id, ctx.config, clip_id, body.value)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        ctx.playlists.invalidate(episode_id)
        ctx.storage.invalidate()
        return result

    @router.post("/api/episodes/{episode_id}/shorts/{clip_id}/watched")
    def api_short_watched(episode_id: str, clip_id: str, body: PublishedIn):
        """CP8.21 D4: tick / untick "Đã xem" (``watched.json``) — user state only: no job, allowed while a job runs,
        render not stale."""
        if (bad := ctx.check_clip(episode_id, clip_id, error_response=JSONResponse)) is not None:
            return bad
        with ctx.publish_lock:
            try:
                return set_watched(episode_id, ctx.config, clip_id, body.value)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.delete("/api/episodes/{episode_id}")
    def api_episode_delete(episode_id: str):
        """X3: delete work/<id>/ and output/<id>/ (cannot be undone); 409 while a job of the episode is
        queued/running; unknown / invalid id -> 404."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with ctx.submit_lock:
            ctx.runner.drop_parked(episode_id)  # CP13.1b: a job only waiting for its HD source does not block the deletion
            current = ctx.restore_job(episode_id)
            if current is None or not current.active:
                current = ctx.runner.latest(episode_id)
            if current is None or not current.active:
                current = ctx.runner.latest_post(episode_id)  # CP8.16 R3: a compose job also blocks the deletion
            if current is None or not current.active:
                current = ctx.runner.latest_enhance(episode_id)  # CP13.1b: so does the assembly of the HD source
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; xóa sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            try:  # CP8.33 G11: the hearted clips of a khai thị episode are kept; a failure here deletes nothing
                undo_keep = ctx.compilations.keep_favorites(episode_id)
            except CompilationError as exc:
                log.error("web: delete episode %s: %s", episode_id, exc)
                return JSONResponse({"detail": str(exc)}, status_code=500)
            try:
                # Snapshot P4 via the exact Posts-tab view, before its workspace disappears.
                # Hold post_lock through deletion so a concurrent manual edit cannot be lost.
                with ctx.post_lock:
                    try:
                        titles = {c["clip_id"]: c["title"] for c in list_titles(episode_id, ctx.config)["clips"]}
                    except ReviewError:
                        titles = {}
                    fields = ctx.post_header_fields(episode_id)
                    series, tags = ctx.post_series_and_tags(episode_id)
                    hashtags_list = review_hashtags(series, tags)

                    def copy_text(entry):
                        return ctx.post_entry_view(entry, ep_src=None, title=titles.get(entry["clip_id"]),
                                                   header_fields=fields, hashtags_list=hashtags_list)["text"]

                    removed = delete_episode(episode_id, ctx.config, copy_text=copy_text)
            except EpisodeNotFound:
                undo_keep()
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            except (ReviewError, OSError) as exc:
                undo_keep()
                log.error("web: delete episode %s failed: %s", episode_id, exc)
                return JSONResponse({"detail": f"không xóa được: {exc}"}, status_code=500)
            ctx.runner.forget(episode_id)
            ctx.storage.invalidate()
            ctx.playlists.invalidate(episode_id)
        log.warning("web: deleted episode %s (%s)", episode_id, ", ".join(str(p) for p in removed))
        return {"deleted": episode_id}

    def _enhance_view(episode_id: str) -> dict:
        view = ctx.svc.episode_view(episode_id)
        if view.get("exists"):
            rm = ep.render_manifest(ctx.config, episode_id)
            doc = enh_state.read(Path(ctx.config.workspace.dir) / episode_id) or {}
            view["rendered"] = rm is not None
            view["rendered_from_hd"] = bool(rm and doc.get("source_hd_sha256")
                                            and rm.get("source_sha256") == doc.get("source_hd_sha256"))
            view["can_rerender"] = bool(view.get("hd_ready") and rm is not None and not view["rendered_from_hd"])
            view["can_redo"] = bool(view.get("state") == "done" and view.get("hd_old_config"))  # CP13.4 G3
        job = ctx.runner.latest_enhance(episode_id)
        view["assembling_job"] = job.status if job is not None and job.active else None
        return view

    def _enhance_episode(episode_id: str) -> JSONResponse | None:
        if (bad := ctx.episode_or_404(episode_id, error_response=JSONResponse)) is not None:
            return bad
        if not (Path(ctx.config.workspace.dir) / episode_id / "manifest.json").is_file():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return None

    @router.post("/api/episodes/{episode_id}/enhance")
    def api_episode_enhance(episode_id: str, body: EnhanceSwitchIn):
        """E1 / E10 "Bật / Tắt enhance" (the whole video: Short + khai thị). Off while waiting for HD -> the render runs at
        once from the original source."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        try:
            doc = ctx.svc.set_wanted(episode_id, body.enabled)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        owner = doc.get("follows") or episode_id
        done = None
        if not body.enabled:
            done = {part: ctx.release_hd(part) for part in enh_state.video_parts(ctx.config, owner)}
        elif doc.get("state") == enh_state.ASSEMBLING:
            ctx.enhance_complete(owner)
        elif doc.get("state") == enh_state.DONE:
            ctx.hd_ready(owner)
        log.info("web: enhance %s [%s]%s", "on" if body.enabled else "off", episode_id,
                 f" -> {done}" if done else "")
        return {"enhance": _enhance_view(episode_id)}

    @router.post("/api/episodes/{episode_id}/enhance/render-original")
    def api_episode_render_original(episode_id: str):
        """E6 "Render bằng bản gốc": turn enhance off for the video and render now from the original source."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        if review_backup.view(ctx.config, episode_id)["released"]:  # HD1 G3: no silent fall-back to the original
            return JSONResponse({"detail": f"{enh_state.RELEASED_MESSAGE}: không render bằng bản gốc"},
                                status_code=409)
        try:
            doc = ctx.svc.set_wanted(episode_id, False)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        outcome = {part: ctx.release_hd(part, force_render=part == episode_id)
                   for part in enh_state.video_parts(ctx.config, doc.get("follows") or episode_id)}
        log.info("web: render bằng bản gốc [%s]: %s", episode_id, outcome)
        return {"enhance": _enhance_view(episode_id), "outcome": outcome}

    @router.post("/api/episodes/{episode_id}/enhance/redo")
    def api_episode_enhance_redo(episode_id: str):
        """CP13.4 G3 "Enhance lại": queue the video again with the current ``[enhance]`` configuration (the previous HD
        source stays in use until the new one is assembled; no render until then)."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        try:
            ctx.svc.redo(episode_id)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        log.info("web: enhance lại [%s]", episode_id)
        return {"enhance": _enhance_view(episode_id)}

    @router.post("/api/episodes/{episode_id}/vertical/cancel")
    def api_episode_vertical_cancel(episode_id: str):
        """CP8.32 V4: cancel the queued / running vertical job of this video (a ``.kt`` id means its video)."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        owner = ep.hd_owner(episode_id)
        cancelled = ctx.runner.cancel_vertical({owner})
        if not cancelled:
            return JSONResponse({"detail": "tập này không có bản dọc đang chờ / đang chạy"}, status_code=409)
        log.info("web: hủy bản dọc [%s]", owner)
        return {"episode_id": owner, "cancelled": len(cancelled)}

    @router.post("/api/episodes/{episode_id}/enhance/rerender")
    def api_episode_rerender_hd(episode_id: str):
        """E6 "Render lại bản HD" (Shorts already ticked "Đã đăng" were kept): render job from the HD source."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        view = _enhance_view(episode_id)
        if not view.get("hd_ready"):
            return JSONResponse({"detail": "chưa có bản HD"}, status_code=409)
        with ctx.submit_lock:
            if (busy := ctx.busy(episode_id, error_response=JSONResponse)) is not None:
                return busy
            if is_archived(Path(ctx.config.workspace.dir) / episode_id):
                return JSONResponse({"detail": str(ArchivedError(episode_id))}, status_code=409)
            job, _ = ctx.runner.submit(episode_id, KIND_RENDER, render_target(ctx.config, render=ctx.render))
        log.info("web: render lại bản HD [%s] -> job %s", episode_id, job.id)
        return JSONResponse({"job": ctx.job_view(job), "enhance": _enhance_view(episode_id)}, status_code=202)

    def _hd_or_404(episode_id: str, *, archived_ok: bool = False) -> tuple[Path | None, JSONResponse | None]:
        """The landscape file (``source_hd.mp4`` or, CP8.32 V1, the original >= 720p) or a 404. ``archived_ok`` (the
        vertical routes, V2): an archived original that can be fetched again also passes (the path is then None)."""
        if not ep.valid_episode_id(episode_id):
            return None, JSONResponse({"detail": "không có episode này"}, status_code=404)
        src = ep.hd_source(ctx.config, episode_id)
        if src is None and archived_ok and ctx.config.store.enabled \
                and review_backup.view(ctx.config, ep.hd_owner(episode_id))["released"]:
            return None, None  # HD2a: released, the vertical job borrows the HD from the 3090 store
        if src is None or (src.path is None and not archived_ok):
            return None, JSONResponse({"detail": "chưa có bản HD của video này"}, status_code=404)
        return src.path, None

    @router.get("/api/episodes/{episode_id}/source-hd")
    def api_episode_source_hd(episode_id: str, request: Request, dl: str | None = None):
        """H1: the landscape HD video (``source_hd.mp4``, no banner); Range supported (FileResponse). A download never
        ticks "Đã đăng" / "Đã xem" (H3)."""
        if ep.valid_episode_id(episode_id) and ctx.config.store.enabled \
                and review_backup.view(ctx.config, episode_id)["released"]:
            return ctx.tracked(dl, _store_download(episode_id, "hd", request,
                                                  ep.hd_download_name(ctx.config, episode_id)))
        hd, bad = _hd_or_404(episode_id)
        if bad is not None:
            return ctx.tracked(dl, bad)
        return ctx.tracked(dl, FileResponse(hd, media_type=mimetypes.guess_type(hd.name)[0] or "video/mp4", headers={
            "Content-Disposition": content_disposition(ep.hd_download_name(ctx.config, episode_id)),
            "Cache-Control": "private, no-cache"}))

    @router.get("/api/episodes/{episode_id}/vertical")
    def api_episode_vertical(episode_id: str, request: Request, dl: str | None = None):
        """H4: the vertical full-episode file, once made from the current HD source."""
        if ep.valid_episode_id(episode_id) and render_full.on_store(ctx.config, episode_id) is not None:
            return ctx.tracked(dl, _store_download(episode_id, "vertical", request,
                                                  ep.video_download_name(ctx.config, episode_id, "Doc")))
        _hd, bad = _hd_or_404(episode_id, archived_ok=True)
        if bad is not None:
            return ctx.tracked(dl, bad)
        owner = ep.hd_owner(episode_id)
        path = render_full.ready_file(ctx.config, owner) if render_full.current(ctx.config, owner) else None
        if path is None:
            return ctx.tracked(dl, JSONResponse({"detail": "chưa có bản dọc (bấm \"Tạo bản dọc\")"}, status_code=404))
        return ctx.tracked(dl, FileResponse(path, media_type="video/mp4", headers={
            "Content-Disposition": content_disposition(ep.video_download_name(ctx.config, episode_id, "Doc")),
            "Cache-Control": "private, no-cache"}))

    def _store_download(episode_id: str, kind: str, request: Request, name: str):
        try:
            client = StoreClient.from_config(ctx.config.store)
            status, upstream, stream = client.open_stream(ep.hd_owner(episode_id), kind, request.headers.get("range"))
        except StoreUnavailable:
            return JSONResponse({"detail": "3090 đang tắt"}, status_code=503)
        except StoreMismatch:
            return JSONResponse({"detail": "kho không có file này"}, status_code=404)
        headers = {k: v for k, v in upstream.items()
                   if k.lower() in ("content-length", "content-range", "accept-ranges")}
        headers.update({"Content-Disposition": content_disposition(name), "Cache-Control": "private, no-cache"})
        return _StoreResponse(stream, status_code=status, headers=headers)

    @router.post("/api/episodes/{episode_id}/vertical")
    def api_episode_vertical_make(episode_id: str):
        """H4 "Tạo bản dọc": queue a render-lane job (reuses the file when nothing changed); 404 without an HD source
        (CP8.32: ``source_hd.mp4`` or the original >= 720p; an archived original is downloaded again by the job)."""
        _hd, bad = _hd_or_404(episode_id, archived_ok=True)
        if bad is not None:
            return bad
        owner = ep.hd_owner(episode_id)
        with ctx.submit_lock:
            if render_full.on_store(ctx.config, owner) is not None:
                return {"job": None, "hd_video": _hd_video_view(episode_id)}
            restoring = ctx.restore_job(owner)
            if restoring is not None and restoring.active:
                return JSONResponse({"detail": "đang khôi phục nguồn; tạo bản dọc sau khi xong",
                                     "job": ctx.job_view(restoring)}, status_code=409)
            job, created = ctx.runner.submit(owner, KIND_VERTICAL, ctx.vertical_target(owner))
        log.info("web: bản dọc [%s] -> job %s%s", owner, job.id, "" if created else " (đã có)")
        return JSONResponse({"job": ctx.job_view(job, logs=False), "hd_video": _hd_video_view(episode_id)},
                            status_code=202 if created else 200)

    @router.post("/api/episodes/{episode_id}/restore-source")
    def api_restore_source(episode_id: str):
        if not ep.valid_episode_id(episode_id) or not (Path(ctx.config.workspace.dir) / episode_id).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        owner = ep.hd_owner(episode_id)
        with ctx.submit_lock:
            current = ctx.restore_job(owner)
            if current is not None and current.active:
                return JSONResponse({"job": ctx.job_view(current), "created": False}, status_code=200)
            if not is_archived(Path(ctx.config.workspace.dir) / episode_id):
                return JSONResponse({"detail": "tập chưa dọn video nguồn"}, status_code=409)
            busy = next((j for j in ctx.runner.jobs() if j.active and ep.hd_owner(j.episode_id) == owner), None)
            if busy is not None:
                return JSONResponse({"detail": "video đang có job chạy/đợi; khôi phục sau khi xong",
                                     "job": ctx.job_view(busy)}, status_code=409)
            try:
                restore_parts(episode_id, ctx.config)
            except (ReviewError, OSError) as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, created = ctx.runner.submit(owner, KIND_RESTORE_SOURCE, ctx.restore_target(episode_id))
        return JSONResponse({"job": ctx.job_view(job), "created": created}, status_code=202 if created else 200)

    @router.post("/api/episodes/{episode_id}/archive")
    def api_archive(episode_id: str):
        """S3: delete the downloaded source video, keep the Shorts; 409 while a job of the episode is
        queued/running; 422 local source / render not done; 404 unknown id."""
        if not ep.valid_episode_id(episode_id) or not (Path(ctx.config.workspace.dir) / episode_id).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with ctx.submit_lock:
            current = ctx.restore_job(episode_id)
            if current is None or not current.active:
                current = ctx.runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; dọn sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            try:
                result = archive_source(episode_id, ctx.config)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            ctx.storage.invalidate()
        log.warning("web: archived %s: removed %s (%d bytes)", episode_id, ", ".join(result.removed) or "-",
                    result.freed)
        return {"archived": episode_id, "changed": result.changed, "freed": result.freed, "removed": result.removed}

    def _backup_busy(owner: str):
        from ..app import backup_busy
        return backup_busy(ctx, owner)

    @router.post("/api/episodes/{episode_id}/backup")
    def api_backup_confirm(episode_id: str, body: BackupIn):
        """HD1 G1: record that the external copy exists; only the sha256 of the file the VM holds now is accepted.
        404 unknown id; 409 job running; 422 no file / sha mismatch."""
        if not ep.valid_episode_id(episode_id) or not (Path(ctx.config.workspace.dir) / enh_state.owner_for(ctx.config, episode_id)).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        owner = ep.hd_owner(episode_id)
        with ctx.submit_lock:
            if (busy := _backup_busy(owner)) is not None:
                return busy
            try:
                done = review_backup.confirm(ctx.config, episode_id, body.kind, body.sha256)
            except review_backup.BackupError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=exc.status)
        return {"confirmed": done}

    @router.post("/api/episodes/{episode_id}/release")
    def api_release(episode_id: str, body: ReleaseIn | None = None):
        """HD1 G2: delete source_hd.mp4 + full/vertical.mp4 of the video once both were confirmed. 404 unknown id; 409
        job / enhance lease running; 422 conditions unmet (nothing deleted)."""
        if not ep.valid_episode_id(episode_id) or not (Path(ctx.config.workspace.dir) / enh_state.owner_for(ctx.config, episode_id)).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        owner = ep.hd_owner(episode_id)
        with ctx.submit_lock:
            if (busy := _backup_busy(owner)) is not None:
                return busy
            try:
                result = review_backup.release(ctx.config, episode_id,
                                               allow_no_vertical=bool(body and body.allow_no_vertical))
            except review_backup.BackupError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=exc.status)
            ctx.storage.invalidate()
            ctx.playlists.invalidate(owner)
        return {"released": owner, "changed": result.changed, "freed": result.freed, "removed": result.removed}

    return router
