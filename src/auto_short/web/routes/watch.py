"""Authenticated watch-room API; one independent room per app factory invocation."""

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from .. import episodes as ep
from ..context import WebContext
from ..watch_party import WatchConflict, WatchRoom


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()
    room = WatchRoom()

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

    return router
