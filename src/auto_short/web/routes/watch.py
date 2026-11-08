"""Authenticated watch-room API; one independent room per app factory invocation."""

import json
import logging
import math
import re
import threading
import time
import unicodedata
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from .. import episodes as ep
from ..context import WebContext
from ..listen import clip_metadata
from ..watch_party import WatchConflict, WatchRoom

log = logging.getLogger("auto_short.web.watch")
LOG_TYPES = {"pause_hidden", "retry_ok", "retry_blocked", "seek_skipped_hidden", "stalled", "waiting", "visibility",
             "retry_gave_up", "pip_enter", "pip_leave", "pip_unsupported"}


def _log_batch(raw: bytes) -> dict:
    """Validate one small diagnostic batch; strip control characters before logging."""
    def clean(value):
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError("chuỗi không hợp lệ")
        return "".join(c for c in value if not unicodedata.category(c).startswith("C")
                       and unicodedata.category(c) not in ("Zl", "Zp"))

    body = json.loads(raw)
    if not isinstance(body, dict) or set(body) != {"client", "page", "events"}:
        raise ValueError("lô sự kiện không hợp lệ")
    client, page, events = clean(body["client"]), clean(body["page"]), body["events"]
    if not client or page not in ("watch", "listen") or not isinstance(events, list) or not 1 <= len(events) <= 20:
        raise ValueError("client / page / events không hợp lệ")
    cleaned = []
    for event in events:
        if not isinstance(event, dict) or "type" not in event or set(event) - {"type", "t", "drift", "err", "hidden"}:
            raise ValueError("sự kiện không hợp lệ")
        item = {"type": clean(event["type"])}
        if item["type"] not in LOG_TYPES:
            raise ValueError("type không hợp lệ")
        for key in ("t", "drift"):
            if key in event:
                value = event[key]
                if type(value) not in (int, float) or not math.isfinite(value) or (key == "t" and value < 0):
                    raise ValueError(f"{key} không hợp lệ")
                item[key] = value
        if "err" in event:
            item["err"] = clean(event["err"])
        if "hidden" in event:
            if type(event["hidden"]) is not bool:
                raise ValueError("hidden không hợp lệ")
            item["hidden"] = event["hidden"]
        cleaned.append(item)
    return {"client": client, "page": page, "events": cleaned}


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()
    room = WatchRoom()
    log_times, log_lock = {}, threading.Lock()

    @router.post("/api/watch/log")
    async def log_watch(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 2048:
                return JSONResponse({"detail": "lô sự kiện tối đa 2 KB"}, status_code=422)
            raw.extend(chunk)
        try:
            batch = _log_batch(bytes(raw))
        except (ValueError, TypeError, OverflowError, UnicodeError):
            return JSONResponse({"detail": "lô sự kiện không hợp lệ"}, status_code=422)
        now = time.monotonic()
        with log_lock:
            for client in list(log_times):
                if now - log_times[client] >= 5:
                    del log_times[client]
            if batch["client"] in log_times:
                return JSONResponse({"detail": "tối đa 1 lô / 5 giây / client"}, status_code=429)
            log_times[batch["client"]] = now
        for event in batch["events"]:
            log.info("player %s", json.dumps({"client": batch["client"], "page": batch["page"], **event},
                                             ensure_ascii=False, separators=(",", ":")))
        return JSONResponse({"ok": True})

    def decorate(state, have=None):
        # Derive fresh metadata on every response, including rooms set by old browser tabs.
        state["fav"] = None
        state["code"] = None
        metadata = {}
        # The queue is only sent (and decorated) when the client's cached copy is stale.
        send_queue = have != state["queue_version"]
        for entry in (state["queue"] if send_queue else state["queue"][state["index"]:state["index"] + 1]):
            match = re.fullmatch(r"/files/([^/]+)/([^/]+)\.mp4", urlsplit(entry["url"]).path)
            if not match:
                continue
            eid, clip = match.groups()
            if not ep.valid_episode_id(eid) or not ep.valid_clip_id(clip):
                continue
            if eid not in metadata:
                metadata[eid] = clip_metadata(ctx.config, eid)
            entry.update(metadata[eid].get(clip, {}))
        if state["queue"]:
            current = state["queue"][state["index"]]
            state.update({key: value for key, value in current.items() if key not in ("url", "title")})
            state["title"] = current["title"]
        match = re.fullmatch(r"/files/([^/]+)/([^/]+)\.mp4", urlsplit(state["video_url"] or "").path)
        if match:
            episode_id, clip = match.groups()
            if ep.valid_episode_id(episode_id) and ep.valid_clip_id(clip):
                favorites = ctx.compilations.episode_favorites(episode_id)
                if favorites is not None:
                    state["fav"] = dict(playlist_id=favorites["playlist_id"], episode_id=episode_id,
                                        clip=clip, favorite=clip in favorites["clips"])
        if not send_queue:
            del state["queue"]
        return state

    def have_version(body):
        value = body.get("queue_version")
        return value if isinstance(value, str) else None

    def call(client, action, have=None, **data):
        try:
            state = room.snapshot(client) if action is None else room.command(client, action, **data)
            return JSONResponse(decorate(state, have), headers={"Cache-Control": "no-store"})
        except WatchConflict as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @router.get("/api/watch")
    def get_watch(client: str | None = None, queue_version: str | None = None):
        return call(client, None, queue_version)

    @router.post("/api/watch")
    def update_watch(body: dict = Body(...)):
        data = {k: v for k, v in body.items() if k not in ("client", "action", "self", "queue_version")}
        action = body.get("action")
        return call(body.get("client"), action if isinstance(action, str) else "", have_version(body), **data)

    @router.post("/api/watch/leave")
    def leave_watch(body: dict = Body(...)):
        return call(body.get("client"), "leave", have_version(body))

    @router.delete("/api/watch")
    def end_watch(body: dict = Body(...)):
        return call(body.get("client"), "end", have_version(body))

    return router
