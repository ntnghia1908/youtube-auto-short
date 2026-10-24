"""Status routes extracted from the app factory."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...post import images as post_images, kept
from ...review import list_tombstones, remove_tombstone
from ...workspace import WorkspaceError
from .. import downloads as dl_mod
from .. import episodes as ep
from .. import monitor as monitor_mod
from ..context import WebContext
from .models import PublishedIn


class QueuePauseIn(BaseModel):
    mode: Literal["now", "after"] = "after"  # CP8.22 Q1


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/kept-posts")
    def api_kept_posts():
        with ctx.post_lock:
            episodes = kept.list_kept(ctx.config)
        for episode in episodes:
            for entry in episode["posts"]:
                entry["image_missing"] = entry["image"] is not None \
                    and post_images.resolve(ctx.config.post.image_dir, entry["image"]) is None
        return {"episodes": episodes}

    @router.post("/api/kept-posts/{episode_id}/{clip_id}/posted")
    def api_kept_posted(episode_id: str, clip_id: str, body: PublishedIn, index: int | None = None):
        try:
            with ctx.post_lock:
                entry = kept.set_posted(ctx.config, episode_id, clip_id, body.value, index=index)
        except WorkspaceError:
            entry = None
        except (kept.KeptPostsError, OSError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=500)
        if entry is None:
            return JSONResponse({"detail": "không có bài giữ lại này"}, status_code=404)
        return {"clip_id": clip_id, "posted": entry["posted_at"] is not None, "posted_at": entry["posted_at"]}

    @router.delete("/api/kept-posts/{episode_id}")
    def api_kept_remove(episode_id: str):
        try:
            with ctx.post_lock:
                removed = kept.remove(ctx.config, episode_id)
        except WorkspaceError:
            removed = False
        except OSError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=500)
        if not removed:
            return JSONResponse({"detail": "không có bài giữ lại của tập này"}, status_code=404)
        return {"removed": episode_id}

    @router.get("/api/deleted")
    def api_deleted():
        """Tombstones of deleted single episodes (not in a stored bộ kinh, no workspace now)."""
        in_playlists = ctx.playlists.video_ids()
        return {"episodes": [d for d in list_tombstones(ctx.config) if d["episode_id"] not in in_playlists]}

    @router.delete("/api/deleted/{episode_id}")
    def api_deleted_remove(episode_id: str):
        """"Xóa khỏi lịch sử": removes the tombstone only."""
        if not ep.valid_episode_id(episode_id) or not remove_tombstone(ctx.config, episode_id):
            return JSONResponse({"detail": "không có trong lịch sử"}, status_code=404)
        ctx.playlists.invalidate(episode_id)
        return {"removed": episode_id}

    @router.get("/api/ui")
    def api_ui():
        """CP8.21 D5: UI flags (``[web] show_advanced``: "Sửa đầu/cuối" and "Từ điển sửa lỗi" buttons)."""
        return {"advanced": bool(ctx.config.web.show_advanced)}

    @router.get("/api/downloads/{token}")
    def api_download_progress(token: str):
        """CP8.34 D3: ``{state: sending | done | aborted, bytes_sent, bytes_total}`` of a ``?dl=<token>`` download."""
        found = ctx.download_table.get(token) if dl_mod.TOKEN_RE.match(token) else None
        if found is None:
            return JSONResponse({"detail": "không có lượt tải này"}, status_code=404)
        return JSONResponse(found, headers={"Cache-Control": "no-store"})

    @router.get("/api/queue")
    def api_queue():
        """CP8.22 Q1: ``{paused, mode, running, pending}`` of the job queue (top bar of every page)."""
        return ctx.runner.queue_state()

    @router.post("/api/queue/pause")
    def api_queue_pause(body: QueuePauseIn):
        return ctx.runner.pause(body.mode)

    @router.post("/api/queue/resume")
    def api_queue_resume():
        return ctx.runner.resume()

    @router.get("/api/monitor/queue")
    def api_monitor_queue(limit: int = 20):
        """M1: running job per lane (episode, step, elapsed, progress), jobs waiting for HD / GPU / YouTube, and the
        pending jobs of every lane in the order they will start (first ``limit`` per lane, default 20)."""
        limit = max(1, min(limit, 500))
        data = ctx.runner.monitor_queue(limit)
        labels: dict[str, dict] = {}

        def decorate(entry: dict, job=None) -> dict:
            eid = entry["episode_id"]
            entry["episode"] = labels.setdefault(eid, monitor_mod.episode_label(ctx.config, eid))
            if job is not None and entry.get("stage") == "render":
                entry["progress"] = monitor_mod.render_progress(ctx.config, job.logs, eid)
            return entry

        for lane, info in data["lanes"].items():
            for run in info["running_all"]:  # CP8.29: the prepare lane may run several (``running`` = the first)
                decorate(run, ctx.runner.job(run["id"]))
            for e in info["pending"]:
                decorate(e)
        for e in data["waiting"]:
            decorate(e)
        return data

    @router.get("/api/monitor/system")
    def api_monitor_system():
        """M2: CPU % (total + per core), load, RAM, disk of ``work/``, top processes (with the job they belong to
        when known), about one hour of history (``[t, cpu %, ram %, load1]``)."""
        return ctx.sampler.snapshot()

    @router.get("/api/monitor/ollama")
    def api_monitor_ollama():
        """M3: models Ollama has loaded (``/api/ps``), connection state, the job of the ``ai`` lane."""
        out = ctx.ollama_view.get()
        out["gpu"] = ctx.runner.gpu_status()
        ai = ctx.runner.running().get("ai")
        out["job"] = {"id": ai.id, "kind": ai.kind, "stage": ai.stage,
                      "episode": monitor_mod.episode_label(ctx.config, ai.episode_id)} if ai is not None else None
        return out

    @router.get("/api/monitor/gpu")
    def api_monitor_gpu():
        """M4: the enhance workers' GPU numbers (None = "chưa có số liệu GPU") and what each one is enhancing."""
        st = ctx.svc.status()
        now = ctx.svc.clock()  # the same clock the worker registry stamps last_seen with
        return {"enabled": st["enabled"], "paused": st["paused"], "now": now,
                "workers": monitor_mod.gpu_workers(st["workers"], sorted(ctx.tokens), now,
                                                   lambda eid: monitor_mod.episode_label(ctx.config, eid))}

    @router.get("/api/storage")
    def api_storage():
        """S1 + S2 + S4: disks, episode sizes, caches, recommendations, warning (cached up to 30 s)."""
        active = {j.episode_id for j in ctx.runner.jobs() if j.active}
        return ctx.storage.report(active)

    @router.get("/api/storage/status")
    def api_storage_status():
        """S4 banner on every page: free space, ``warn``, ``block`` (not cached)."""
        return ctx.storage.status()

    return router
