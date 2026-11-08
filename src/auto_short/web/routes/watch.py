"""Authenticated watch-room API; one independent room per app factory invocation."""

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from ..context import WebContext
from ..watch_party import WatchConflict, WatchRoom


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()
    room = WatchRoom()

    def call(client, action, **data):
        try:
            state = room.snapshot(client) if action is None else room.command(client, action, **data)
            return JSONResponse(state, headers={"Cache-Control": "no-store"})
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
