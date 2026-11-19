"""SCH1 O8: one in-memory device authorization session per allowlisted token."""
from __future__ import annotations

import re
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ...publish import PublishError, youtube
from ...workspace import read_json_dict
from ..context import WebContext


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()
    sessions = {}
    lock = threading.Lock()

    def target(stem):
        # Never turn a route parameter into a filesystem path.
        path = youtube.token_paths().get(stem) if re.fullmatch(r"[A-Za-z0-9_-]+", stem) else None
        if path is None:
            raise HTTPException(status_code=404, detail="không có token này")
        return path

    def view(entry):
        # Whitelist fields: credentials/device_code/token contents remain private.
        session = entry.get("device", {})
        return JSONResponse(dict(status=entry["status"], message=entry.get("message", ""),
                                 **{key: session[key] for key in ("verification_url", "user_code", "expires_in")
                                    if key in session}), headers={"Cache-Control": "no-store"})

    def run(entry, path):
        try:
            youtube.poll_device(entry["device"], path)
        except Exception:
            # Transport/OS exception text may contain credentials or local paths.
            state, message = "error", "Không lấy được token; mã hết hạn hoặc bị từ chối. Hãy thử lại."
        else:
            state, message = "done", "Đã lấy token mới"
        with lock:
            entry.update(status=state, message=message)

    @router.post("/api/youtube-tokens/{stem}/auth")
    def start(stem: str):
        path = target(stem)
        with lock:
            previous = sessions.get(stem)
            if previous and previous["status"] == "waiting":
                return view(previous)
            token = read_json_dict(path) or {}
            client = token.get("client_path")
            if not isinstance(client, str) or not client.strip():
                raise HTTPException(status_code=422, detail="token thiếu client_path; chạy auth CLI một lần")
            try:
                device = youtube.start_device(client)
            except (PublishError, OSError, ValueError):
                message = "Không bắt đầu được đăng nhập YouTube; hãy thử lại"
                return JSONResponse({"status": "error", "message": message, "detail": message},
                                    status_code=502, headers={"Cache-Control": "no-store"})
            entry = dict(status="waiting", device=device)
            sessions[stem] = entry
            try:
                threading.Thread(target=run, args=(entry, path), daemon=True, name="youtube-auth").start()
            except RuntimeError:
                entry.update(status="error", message="Không bắt đầu được đăng nhập; hãy thử lại")
            return view(entry)

    @router.get("/api/youtube-tokens/{stem}/auth")
    def status(stem: str):
        target(stem)
        with lock:
            entry = sessions.get(stem)
            if entry is None:
                raise HTTPException(status_code=404, detail="chưa có phiên đăng nhập")
            return view(entry)

    return router
