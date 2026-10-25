"""Playlists routes extracted from the app factory."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

from ... import khaithi
from ...compilation import CID_RE as CID_RE, CompilationError, Item
from ...enhance import state as enh_state
from ...review import backup as review_backup
from ...enhance.state import EnhanceError
from ...post import doc as post_doc, stage as post_stage, store as post_store
from ...render import full as render_full
from ..context import WebContext, RANGE_SIZE, KINDS
from .. import episodes as ep, playlists as playlists_mod
from ..jobs import KIND_PIPELINE, KIND_POST, KIND_VERTICAL, post_compose_target
from ..playlists import PlaylistError
from ..urls import valid_playlist_id
from .models import PublishedIn

log = logging.getLogger("auto_short")


class ResumeAllIn(BaseModel):
    """CP13.2 H2 "Chạy tiếp cả bộ": khai thị minutes (absent = ``[khaithi]`` defaults); checked in the handler."""

    min_minutes: Any = None
    max_minutes: Any = None
    vertical: bool = False  # CP8.35 D2: also the vertical full-episode version of each episode


class HashtagsIn(BaseModel):
    hashtags: list[str] = Field(max_length=100)


class SeriesIn(BaseModel):
    series: Any = None  # CP8.11 D7: checked by the store (string, 1-100 chars after normalization) -> 422


class DocIn(BaseModel):
    url: Any = None  # CP8.19 D1: the lecture-document link, or null to remove it (checked by the store -> 422)
    videos_per_page: Any = None  # CP8.24 P1: videos per text page (integer 1..10); absent / null keeps the stored one


class FavoriteIn(BaseModel):
    episode_id: str = Field(max_length=128)
    clip: str = Field(max_length=64)
    favorite: StrictBool


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _jobs_by_episode() -> dict[str, dict]:
        out = {}
        for job in ctx.runner.jobs():
            latest = ctx.runner.latest(job.episode_id)
            if latest is job:
                out[job.episode_id] = ctx.job_view(job, logs=False)
        return out

    @router.get("/api/playlists")
    def api_playlists():
        jobs = _jobs_by_episode()
        return {"playlists": [ctx.playlists.summary(d, jobs) for d in ctx.playlists.all()]}

    def _download_fields(e: dict) -> None:
        """CP8.31 D3: zip (``all.zip`` with both Shorts and khai thị, else the ``shorts.zip`` of the kind present) and
        ``.docx`` url + name of one playlist entry; the key is absent / None when there is nothing to download."""
        vid = e.get("video_id")
        e["zip_url"] = e["zip_name"] = e["posts_docx_url"] = e["posts_docx_name"] = None
        e["posts_count"] = e["posts_total"] = e["posts_posted"] = 0  # CP8.31 A2 (Bài x/y)
        if not vid or not e.get("available"):
            return
        kid = e.get("khaithi_episode_id")
        shorts, kts = (e.get("shorts") or 0) > 0, kid is not None and (e.get("khaithi_videos") or 0) > 0
        found = ep.all_zip(ctx.config, vid) if shorts and kts else None
        if found is not None:
            e["zip_url"], e["zip_name"] = f"/files/{vid}/all.zip", found[1]
        elif shorts:
            e["zip_url"], e["zip_name"] = f"/files/{vid}/shorts.zip", ep.zip_download_name(ctx.config, vid)
        elif kts:
            e["zip_url"], e["zip_name"] = f"/files/{kid}/shorts.zip", ep.zip_download_name(ctx.config, kid)
        stats = [ctx.post_stats(x) for x in (vid, kid) if x is not None]
        e["posts_count"] = sum(n for n, _, _ in stats)
        e["posts_posted"] = sum(x for _, x, _ in stats)
        e["posts_total"] = sum(r for _, _, r in stats)
        if e["posts_count"]:
            e["posts_docx_url"] = f"/files/{vid}/posts.docx"
            e["posts_docx_name"] = ctx.docx_name_of(vid)

    def _vertical_status(vid: str, e: dict) -> tuple[str, str | None]:
        """CP8.32 V3: ``("todo", None)`` when "Tạo bản dọc cả bộ" would queue this entry, else ``("skip", reason)``."""
        if not e.get("available"):
            return "skip", "tập không khả dụng"
        if e.get("state") not in (playlists_mod.RENDERED, playlists_mod.COMPLETE):
            return "skip", "chưa xong Short"
        src = ep.hd_source(ctx.config, vid)
        on_store = False
        if src is None and review_backup.view(ctx.config, vid)["released"]:
            if not ctx.config.store.enabled:
                return "skip", enh_state.RELEASED_MESSAGE
            on_store = True  # HD2a: the vertical job borrows the HD from the 3090 store
        if src is None and not on_store:
            return "skip", f"không có bản HD / video gốc < {ctx.config.enhance.min_height}p"
        if render_full.current(ctx.config, vid):
            return "skip", "đã có bản dọc"
        job = ctx.runner.latest_vertical(vid)
        if job is not None and job.active:
            return "skip", "đang chờ / đang tạo bản dọc"
        return "todo", None

    def _vertical_fields(e: dict) -> None:
        """CP8.32: per-entry vertical status of the bộ kinh page (the icon of a ready file, the count of "cả bộ")."""
        vid = e.get("video_id")
        e["vertical"] = None
        if not vid:
            return
        status, reason = _vertical_status(vid, e)
        waiting = ctx.auto_vertical_waiting(vid)  # CP8.35 D6
        if waiting and status != "todo":
            reason = "sẽ tạo khi có HD"
        src = ep.hd_source(ctx.config, vid)
        ready = render_full.ready_file(ctx.config, vid) if render_full.current(ctx.config, vid) else None
        vjob = ctx.runner.latest_vertical(vid)
        e["vertical"] = {"status": status, "reason": reason, "active": vjob is not None and vjob.active,
                         "auto_waiting": waiting, "fetch": src is not None and src.kind == enh_state.SRC_ARCHIVED,
                         "ready": ready is not None,
                         "url": f"/api/episodes/{vid}/vertical" if ready is not None else None,
                         "name": ep.video_download_name(ctx.config, vid, "Doc") if ready is not None else None}

    def _posts_ranges(playlist_id: str, entries: list[dict]) -> list[dict]:
        """CP8.31 A1: fixed ranges of ``RANGE_SIZE`` episode numbers (1-10, 11-20, ...) that hold at least one post,
        plus "Tập chưa rõ số" for unnumbered episodes."""
        buckets: dict[int | None, dict] = {}
        for e in entries:
            if not e.get("posts_count"):
                continue
            n = e.get("episode")
            key = (int(n) - 1) // RANGE_SIZE if isinstance(n, str) and n.isdigit() and int(n) >= 1 else None
            b = buckets.setdefault(key, {"episodes": 0, "posts": 0})
            b["episodes"] += 1
            b["posts"] += e["posts_count"]
        out = []
        base = f"/files/playlists/{playlist_id}/posts.docx"
        for key in sorted(k for k in buckets if k is not None):
            lo, hi = key * RANGE_SIZE + 1, (key + 1) * RANGE_SIZE
            out.append({"from": lo, "to": hi, "label": f"Tập {lo}–{hi}", **buckets[key], "url": f"{base}?from={lo}&to={hi}"})
        if None in buckets:
            out.append({"from": None, "to": None, "label": "Tập chưa rõ số", **buckets[None], "url": f"{base}?other=1"})
        return out

    @router.get("/api/playlists/{playlist_id}")
    def api_playlist(playlist_id: str):
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        view = ctx.playlists.view(doc, _jobs_by_episode())
        view["gpu"] = ctx.runner.gpu_status()  # FIX-ollama-wait O7
        view["youtube"] = ctx.runner.youtube_status()  # FIX-youtube-botcheck-wait Y3
        for e in view["entries"]:  # CP8.26
            e["priority"] = bool(e.get("video_id")) and ctx.runner.priority.marked(e["video_id"])
            # CP8.27 H2: download icon of the finished HD video
            if e.get("video_id") and ep.hd_file(ctx.config, e["video_id"]) is not None:  # CP8.32: also the original >= 720p
                e["hd_url"] = f"/api/episodes/{e['video_id']}/source-hd"
                e["hd_name"] = ep.hd_download_name(ctx.config, e["video_id"])
            if e.get("video_id"):  # HD1 G3: the HD / vertical files were moved to an external machine
                bk = review_backup.view(ctx.config, e["video_id"])
                e["hd_released"], e["hd_released_at"] = bk["released"], bk["released_at"]
            _vertical_fields(e)  # CP8.32 V3
            _download_fields(e)  # CP8.31 D3
        view["priority_count"] = sum(1 for e in view["entries"] if e["priority"])
        view["vertical_active"] = sum(1 for e in view["entries"] if (e.get("vertical") or {}).get("active"))  # CP8.32 V4
        view["posts_ranges"] = _posts_ranges(playlist_id, view["entries"])
        view["favorites_count"] = ctx.compilations.favorites_count(playlist_id)  # CP8.33 G9
        kc = ctx.config.khaithi  # CP8.9 A2.2: defaults of the kind bar ("Khai thị [min]–[max] phút")
        view["khaithi_defaults"] = {"min_minutes": kc.default_min_minutes, "max_minutes": kc.default_max_minutes,
                                    "max_minutes_limit": kc.max_minutes_limit}
        return view

    def _bulk_result(playlist_id: str, items: list[dict], episodes: int) -> dict:
        errors = [{"episode_id": i["episode_id"], "detail": i["error"]} for i in items if "error" in i]
        return {"playlist_id": playlist_id, "episodes": episodes,
                "queued": sum(1 for i in items if i.get("created")), "errors": errors}

    @router.post("/api/playlists/{playlist_id}/prepare")
    def api_playlist_prepare(playlist_id: str):
        """H2 "Chuẩn bị + HD": a prepare-only job (:class:`PipelineTarget` ``prepare_only``) for every not yet processed
        entry, in episode order. No khai thị job, no AI / render; the video asks for HD after its download."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        view = ctx.playlists.view(doc, _jobs_by_episode())
        todo = ctx.by_episode_order([e for e in view["entries"] if e["state"] == playlists_mod.NEW and e.get("video_id")])
        items: list[dict] = []
        for e in todo:
            items += ctx.queue_video(e["video_id"], ["short"], None, None, None, None, prepare_only=True)
        out = _bulk_result(playlist_id, items, len(todo))
        log.info("web: playlist %s chuẩn bị + HD: %d tập, queued %d, %d lỗi", playlist_id, len(todo), out["queued"],
                 len(out["errors"]))
        return JSONResponse(out, status_code=202 if out["queued"] else 200)

    @router.post("/api/playlists/{playlist_id}/resume-prepared")
    def api_playlist_resume_prepared(playlist_id: str, body: ResumeAllIn | None = None):
        """H2 "Chạy tiếp cả bộ": every prepared entry (episode order) runs AI → render for the Short and the khai thị."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        body = body or ResumeAllIn()
        kc = ctx.config.khaithi
        try:
            lo, hi = khaithi.check_minutes(kc.default_min_minutes if body.min_minutes is None else body.min_minutes,
                                           kc.default_max_minutes if body.max_minutes is None else body.max_minutes,
                                           kc.max_minutes_limit)
        except khaithi.KhaithiError as exc:
            return JSONResponse({"detail": exc.vi}, status_code=422)
        view = ctx.playlists.view(doc, _jobs_by_episode())
        todo = ctx.by_episode_order([e for e in view["entries"] if e["state"] == playlists_mod.PREPARED])
        items: list[dict] = []
        for e in todo:
            kinds = [k for k in KINDS if k in (e.get("resume_kinds") or ["short"])]
            items += ctx.queue_video(e["video_id"], kinds, lo if khaithi.KIND in kinds else None,
                                  hi if khaithi.KIND in kinds else None, None, None,
                                  vertical_wish=body.vertical)
        out = _bulk_result(playlist_id, items, len(todo))
        log.info("web: playlist %s chạy tiếp cả bộ: %d tập, queued %d, %d lỗi", playlist_id, len(todo), out["queued"],
                 len(out["errors"]))
        return JSONResponse(out, status_code=202 if out["queued"] else 200)

    @router.post("/api/playlists/{playlist_id}/priority")
    def api_playlist_priority(playlist_id: str, body: PublishedIn):
        """CP8.26 P1 "Ưu tiên cả bộ" / "Bỏ ưu tiên cả bộ": mark (episode order) / unmark every video of the bộ kinh that
        still has work to do (not unavailable, deleted or complete); unmark clears all of its videos."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        view = ctx.playlists.view(doc, _jobs_by_episode())
        entries = [e for e in view["entries"] if e.get("video_id")]
        if body.value:
            todo = ctx.by_episode_order([e for e in entries if e["state"] not in (
                playlists_mod.UNAVAILABLE, playlists_mod.DELETED) and not e.get("complete")])
            changed = ctx.runner.priority.mark([e["video_id"] for e in todo])
        else:
            changed = ctx.runner.priority.unmark([e["video_id"] for e in entries])
        log.info("web: playlist %s ưu tiên %s: %d tập đổi", playlist_id, body.value, len(changed))
        return {"playlist_id": playlist_id, "priority": body.value, "changed": len(changed)}

    @router.post("/api/playlists/{playlist_id}/refresh")
    def api_playlist_refresh(playlist_id: str):
        if ctx.playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc, added = ctx.playlists.refresh(playlist_id)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        return {"playlist_id": playlist_id, "count": len(doc["entries"]), "added": added}

    @router.put("/api/playlists/{playlist_id}/hashtags")
    def api_playlist_hashtags(playlist_id: str, body: HashtagsIn):
        """Per-bộ kinh hashtags (full ordered list); no job, allowed while jobs run."""
        if ctx.playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc = ctx.playlists.set_hashtags(playlist_id, body.hashtags)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        tags, custom = ctx.playlists.effective_hashtags(doc)
        return {"playlist_id": playlist_id, "hashtags": tags, "hashtags_custom": custom}

    @router.delete("/api/playlists/{playlist_id}/hashtags")
    def api_playlist_hashtags_reset(playlist_id: str):
        if ctx.playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc = ctx.playlists.set_hashtags(playlist_id, None)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        tags, custom = ctx.playlists.effective_hashtags(doc)
        return {"playlist_id": playlist_id, "hashtags": tags, "hashtags_custom": custom}

    def _series_response(playlist_id: str, value) -> JSONResponse | dict:
        if ctx.playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc = ctx.playlists.set_series(playlist_id, value)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        series = ctx.playlists.series_view(doc)["series"]
        log.info("web: playlist %s series %s", playlist_id, repr(series) if series else "removed")
        return {"playlist_id": playlist_id, "series": series, "series_custom": series is not None}

    @router.put("/api/playlists/{playlist_id}/series")
    def api_playlist_series(playlist_id: str, body: SeriesIn):
        """CP8.11 D7: "Tên bộ kinh" (header fallback when no title pattern matches); no job, allowed while jobs
        run."""
        if body.series is None:
            return JSONResponse({"detail": "tên bộ kinh phải là chuỗi"}, status_code=422)
        return _series_response(playlist_id, body.series)

    @router.delete("/api/playlists/{playlist_id}/series")
    def api_playlist_series_reset(playlist_id: str):
        return _series_response(playlist_id, None)

    def _doc_check(doc: dict) -> dict | None:
        """CP8.19 D1: match of the first episode of the bộ kinh that already has a transcript (None when none)."""
        prepare = ctx.doc_prepare or post_doc.prepare
        root = Path(ctx.config.workspace.dir)
        for e in doc["entries"]:
            vid = e.get("video_id")
            if not vid or not (root / vid / "transcript.json").is_file():
                continue
            found = post_doc.lookup(root, vid)
            if found is None:
                continue
            base = {"episode_id": vid, "episode": found[1]}
            try:
                segments = json.loads((root / vid / "transcript.json").read_text(encoding="utf-8")).get("segments")
                text = prepare(vid, root, [s for s in segments or [] if isinstance(s, dict)])
            except (post_doc.DocError, OSError, ValueError, AttributeError) as exc:
                log.warning("web: văn bản gốc [%s]: %s", vid, exc)
                return {**base, "match": None, "ok": False, "error": str(exc)}
            if text is None:
                continue
            return {**base, "match": text.match, "ok": text.usable}
        return None

    def _recompose_for_doc(doc: dict) -> int:
        """CP8.19 D7: queue a ``post`` job per episode (Short + khai thị) of the bộ kinh that has ``posts.json``, for
        its unposted ``ai`` / ``raw`` posts; returns how many episodes were queued."""
        queued = 0
        for e in doc["entries"]:
            vid = e.get("video_id")
            if not vid:
                continue
            ids = [vid]
            try:
                kid = khaithi.episode_id_for(vid)
                if (Path(ctx.config.workspace.dir) / kid).is_dir():
                    ids.append(kid)
            except khaithi.KhaithiError:
                pass
            for eid in ids:
                if not ctx.posts_path(eid).is_file():
                    continue
                order = {cid for cid, _ in post_stage.rendered_clip_ids(ctx.config, eid)}
                with ctx.post_lock:
                    try:
                        posts = post_store.read_posts(ctx.posts_path(eid), eid)["posts"]
                    except post_store.PostsError:
                        continue
                clips = [p["clip_id"] for p in posts if p["origin"] in (post_store.AI, post_store.RAW)
                         and p["posted_at"] is None and p["clip_id"] in order]
                if not clips:
                    continue
                with ctx.submit_lock:
                    current = ctx.runner.latest(eid)
                    if current is not None and current.active and current.kind == KIND_PIPELINE:
                        log.info("web: văn bản gốc: bỏ qua soạn lại [%s]: đang chạy pipeline", eid)
                        continue
                    ctx.runner.submit(eid, KIND_POST, post_compose_target(ctx.config, clips, compose=ctx.post_compose,
                                                                      preflight=ctx.post_preflight, lock=ctx.post_lock))
                queued += 1
        return queued

    @router.put("/api/playlists/{playlist_id}/doc")
    def api_playlist_doc(playlist_id: str, body: DocIn):
        """CP8.19 D1: link of the bộ kinh's lecture document (``{"url": link | null}``); 422 for a link that is not
        ``https://ph.tinhtong.vn/Home/<Code>?d=<Code>_<n>.html``. A new link downloads one episode to report
        ``check`` and queues the recompose of unposted ``ai`` / ``raw`` posts (D7: ``queued`` episodes)."""
        if ctx.playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        if "url" not in body.model_fields_set:
            return JSONResponse({"detail": "thiếu url (link hoặc null để xóa)"}, status_code=422)
        try:
            doc = ctx.playlists.set_doc_url(playlist_id, body.url, body.videos_per_page)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        url = playlists_mod.stored_doc_url(doc)
        check, queued = None, 0
        if url is not None:
            check = _doc_check(doc)
            queued = _recompose_for_doc(doc)
        log.info("web: playlist %s văn bản gốc %s (queued %d)", playlist_id, url or "removed", queued)
        return {"playlist_id": playlist_id, "doc_url": url, "check": check, "queued": queued,
                "doc_videos_per_page": post_doc.stored_videos_per_page(doc.get("doc_videos_per_page"))}

    @router.post("/api/playlists/{playlist_id}/hashtags/preview")
    def api_playlist_hashtags_preview(playlist_id: str, body: HashtagsIn):
        """Copy text of the playlist's longest processed title (or a 60-char sample) with these tags."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            return ctx.playlists.preview(doc, body.hashtags)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.delete("/api/playlists/{playlist_id}")
    def api_playlist_delete(playlist_id: str):
        """Only the stored list; processed episodes stay (L1)."""
        if not valid_playlist_id(playlist_id) or not ctx.playlists.remove(playlist_id):
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        log.info("web: playlist %s removed (episodes kept)", playlist_id)
        return {"deleted": playlist_id}

    @router.post("/api/playlists/{playlist_id}/enhance-redo")
    def api_playlist_enhance_redo(playlist_id: str):
        """CP13.4 G3 "Enhance lại cả bộ": every video of the bộ kinh whose HD source was made with another configuration
        is queued again (episode order); the others are skipped."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        view = ctx.playlists.view(doc, _jobs_by_episode())
        todo = ctx.by_episode_order([e for e in view["entries"] if e.get("video_id") and (e.get("hd") or {}).get("old_config")
                                  and e["hd"]["state"] == "done"])
        redone, errors = 0, []
        for e in todo:
            try:
                ctx.svc.redo(e["video_id"])
                redone += 1
            except EnhanceError as exc:
                errors.append({"episode_id": e["video_id"], "detail": str(exc)})
        log.info("web: playlist %s enhance lại: %d / %d tập, %d lỗi", playlist_id, redone, len(todo), len(errors))
        return {"playlist_id": playlist_id, "episodes": len(todo), "queued": redone, "errors": errors}

    @router.post("/api/playlists/{playlist_id}/vertical")
    def api_playlist_vertical(playlist_id: str):
        """CP8.32 V3 "Tạo bản dọc cả bộ": a vertical job (episode order) for every episode whose Shorts are done, that has
        an effective HD source (V1 / V2) and no current vertical file or pending vertical job; the others are skipped
        with a reason. The vertical jobs start after every other job of their lane (JobRunner order)."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        view = ctx.playlists.view(doc, _jobs_by_episode())
        entries = ctx.by_episode_order([e for e in view["entries"] if e.get("video_id")])
        queued, skipped, errors = [], [], []
        for e in entries:
            vid = e["video_id"]
            status, reason = _vertical_status(vid, e)
            if status != "todo":
                skipped.append({"episode_id": vid, "reason": reason})
                continue
            with ctx.submit_lock:
                restoring = ctx.restore_job(vid)
                if restoring is not None and restoring.active:
                    skipped.append({"episode_id": vid, "reason": "đang khôi phục nguồn"})
                    continue
                try:
                    job, created = ctx.runner.submit(vid, KIND_VERTICAL, ctx.vertical_target(vid))
                except Exception as exc:  # a broken workspace must not stop the others
                    errors.append({"episode_id": vid, "detail": str(exc)})
                    continue
            (queued if created else skipped).append(vid if created else {"episode_id": vid, "reason": "đang có việc bản dọc"})
        log.info("web: playlist %s bản dọc cả bộ: queued %d, bỏ qua %d, %d lỗi", playlist_id, len(queued), len(skipped),
                 len(errors))
        return JSONResponse({"playlist_id": playlist_id, "episodes": len(entries), "queued": len(queued),
                             "queued_ids": queued, "skipped": skipped, "errors": errors},
                            status_code=202 if queued else 200)

    @router.post("/api/playlists/{playlist_id}/vertical/cancel")
    def api_playlist_vertical_cancel(playlist_id: str):
        """CP8.32 V4 "Hủy bản dọc cả bộ": cancel every queued / running vertical job of the bộ kinh's videos (and only
        those); 409 when there is none."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        ids = {e["video_id"] for e in doc["entries"] if e.get("video_id")}
        cancelled = ctx.runner.cancel_vertical(ids)
        log.info("web: playlist %s hủy bản dọc: %d job", playlist_id, len(cancelled))
        if not cancelled:
            return JSONResponse({"detail": "bộ kinh này không có bản dọc đang chờ / đang chạy"}, status_code=409)
        return {"playlist_id": playlist_id, "cancelled": len(cancelled), "ids": sorted(j.episode_id for j in cancelled)}

    def _compilation_playlist(playlist_id: str):
        doc = ctx.playlist_or_404(playlist_id)
        return doc if doc is not None else JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)

    @router.post("/api/playlists/{playlist_id}/favorites")
    def api_favorite(playlist_id: str, body: FavoriteIn):
        doc = _compilation_playlist(playlist_id)
        if isinstance(doc, JSONResponse):
            return doc
        if not ep.valid_episode_id(body.episode_id) or not ep.valid_clip_id(body.clip):
            return JSONResponse({"detail": "khai thị không hợp lệ"}, status_code=400)
        try:
            items = ctx.compilations.set_favorite(playlist_id, doc, Item(body.episode_id, body.clip), body.favorite)
        except CompilationError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        ctx.storage.invalidate()  # CP8.33 G11: the heart changes what the storage tab may recommend
        return {"playlist_id": playlist_id, "episode_id": body.episode_id, "clip": body.clip,
                "favorite": body.favorite, "count": len(items)}

    @router.get("/api/playlists/{playlist_id}/compilations")
    def api_compilations(playlist_id: str):
        doc = _compilation_playlist(playlist_id)
        if isinstance(doc, JSONResponse):
            return doc
        return ctx.compilations.view(playlist_id, doc)

    @router.post("/api/playlists/{playlist_id}/compilations")
    def api_compilation_create(playlist_id: str, body: dict = Body(...)):
        doc = _compilation_playlist(playlist_id)
        if isinstance(doc, JSONResponse):
            return doc
        try:
            view, created = ctx.compilations.submit(playlist_id, doc, body)
        except CompilationError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse({"cid": view["cid"], "created": created, "compilation": view}, status_code=202 if created else 200)

    @router.delete("/api/playlists/{playlist_id}/compilations/{cid}")
    def api_compilation_delete(playlist_id: str, cid: str):
        if ctx.playlist_or_404(playlist_id) is None or not CID_RE.match(cid):
            return JSONResponse({"detail": "không có video ghép này"}, status_code=404)
        result = ctx.compilations.delete(playlist_id, cid)
        if result == "busy":
            return JSONResponse({"detail": "video ghép đang chờ / đang ghép; xóa sau khi xong"}, status_code=409)
        if result == "missing":
            return JSONResponse({"detail": "không có video ghép này"}, status_code=404)
        return {"deleted": cid}

    return router
