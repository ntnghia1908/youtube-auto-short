"""Authenticated watch-room API; one independent room per app factory invocation."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse, JSONResponse

from ...store.client import StoreClient, StoreError, StoreUnavailable
from .. import episodes as ep
from ..context import WebContext
from ..watch_audio import AudioCache, WatchAudioError
from ..watch_party import WatchConflict, WatchRoom


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()
    room = WatchRoom()
    audio_cache = AudioCache(Path(ctx.config.workspace.dir) / "_watch_audio")

    def decorate(state):
        # Derive fresh metadata on every response, including rooms set by old browser tabs.
        state["fav"] = None
        match = re.fullmatch(r"/files/([^/]+)/([^/]+)\.mp4", urlsplit(state["video_url"] or "").path)
        if match:
            episode_id, clip = match.groups()
            if ep.valid_episode_id(episode_id) and ep.valid_clip_id(clip):
                favorites = ctx.compilations.episode_favorites(episode_id)
                if favorites is not None:
                    state["fav"] = dict(playlist_id=favorites["playlist_id"], episode_id=episode_id,
                                        clip=clip, favorite=clip in favorites["clips"])
        return state

    def call(client, action, **data):
        try:
            state = room.snapshot(client) if action is None else room.command(client, action, **data)
            return JSONResponse(decorate(state), headers={"Cache-Control": "no-store"})
        except WatchConflict as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.get("/api/watch")
    def get_watch(client: str | None = None):
        return call(client, None)

    @router.post("/api/watch")
    def update_watch(body: dict = Body(...)):
        data = {k: v for k, v in body.items() if k not in ("client", "action", "self")}
        action = body.get("action")
        return call(body.get("client"), action if isinstance(action, str) else "", **data)

    @router.post("/api/watch/leave")
    def leave_watch(body: dict = Body(...)):
        return call(body.get("client"), "leave")

    @router.delete("/api/watch")
    def end_watch(body: dict = Body(...)):
        return call(body.get("client"), "end")

    @router.get("/api/watch/audio/{episode_id}/{clip}")
    def get_audio(episode_id: str, clip: str):
        if not ep.valid_episode_id(episode_id) or not ep.valid_clip_id(clip):
            return JSONResponse({"detail": "không có video này"}, status_code=404)
        source = next((p for cid, p, _ in ep.short_locations(ctx.config, episode_id) or [] if cid == clip), None)
        if source is None:
            return JSONResponse({"detail": "không có video này"}, status_code=404)
        fetch = None
        if isinstance(source, ep.StoredShort):
            if not ctx.config.store.enabled:
                return JSONResponse({"detail": "3090 đang tắt"}, status_code=503)
            sha = source.sha256

            def fetch(dest):
                client = StoreClient.from_config(ctx.config.store)
                if not client.available():
                    raise StoreUnavailable("3090 đang tắt")
                client.fetch(source.episode_id, "short", dest, source.sha256, clip=source.clip)

            local = None
        else:
            local = source
            manifest = ep.render_manifest(ctx.config, episode_id) or {}
            sha = next((s.get("sha256") for s in manifest.get("shorts", []) if s.get("clip_id") == clip), None)
        try:
            path = audio_cache.get(sha, local, fetch=fetch)
        except (StoreError, WatchAudioError, OSError):
            return JSONResponse({"detail": "Không chuẩn bị được tiếng; thử lại khi nguồn / kho sẵn sàng"}, status_code=503)
        return FileResponse(path, media_type="audio/mp4", headers={"Cache-Control": "private, no-cache"})

    return router
