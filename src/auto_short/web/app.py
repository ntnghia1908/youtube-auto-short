"""FastAPI app factory (W2, W4, W6, W7). Contract: docs/decisions/CP8.3-web-contract.md."""

from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import shutil
import threading
import time
import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool

from ..config import Config
from ..pipeline import PIPELINE_STAGES, PreflightError, ollama_preflight, run_pipeline
from ..render import run_render
from ..review import (ArchivedError, EpisodeNotFound, ReviewError, TitlePreview, archive_source, content_disposition,
                      delete_episode, is_archived, preview_title, reject_archived_clip, reject_clip, reset_title,
                      restore_clip, set_alternative, set_published, set_title)
from . import episodes as ep
from .auth import COOKIE_NAME, SessionSigner, load_or_create_secret
from .storage import StorageCache
from .jobs import KIND_PIPELINE, KIND_RENDER, JobRunner, pipeline_target, render_target
from .urls import UrlError, parse_youtube_url

log = logging.getLogger("auto_short")

STATIC_DIR = Path(__file__).parent / "static"
LOGIN_DELAY = 1.0  # seconds to wait after a wrong password
# Reachable without a session: the login page and its stylesheet only.
PUBLIC_PATHS = {"/login", "/static/style.css"}
MAX_FIELD = 100
ZIP_CHUNK = 1 << 20


class SubmitIn(BaseModel):
    url: str = Field(max_length=2000)
    series: str | None = Field(default=None, max_length=MAX_FIELD)
    episode: str | None = Field(default=None, max_length=MAX_FIELD)


class PreviewIn(BaseModel):
    text: str = Field(max_length=1000)


class PublishedIn(BaseModel):
    value: StrictBool  # JSON true / false only


class TitleIn(BaseModel):
    """Exactly one action: ``set`` (manual text), ``alternative`` (1-based AI alternative) or ``reset: true``."""

    set: str | None = Field(default=None, max_length=1000)
    alternative: int | None = None
    reset: bool = False


def _preview_dict(p: TitlePreview | None) -> dict | None:
    if p is None:
        return None
    return {"clip_id": p.clip_id, "title": p.title, "origin": p.origin, "display_lines": list(p.display_lines),
            "font_size": p.font_size, "panel_height": p.panel_height, "chars": len(p.title)}


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _safe_next(value: str | None) -> str:
    """Only same-site absolute paths (no ``//host`` or backslash tricks)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value \
            or any(ord(c) < 32 for c in value):
        return "/"
    return value


def _login_page(days: int, error: str | None = None, next_path: str = "/", status: int = 200) -> HTMLResponse:
    page = (STATIC_DIR / "login.html").read_text(encoding="utf-8").replace("{{days}}", str(days))
    page = page.replace("{{next}}", html.escape(next_path, quote=True))
    page = page.replace("{{error}}", f'<p class="error">{html.escape(error)}</p>' if error else "")
    return HTMLResponse(page, status_code=status)


class _ZipSink(io.RawIOBase):
    """Write-only, non-seekable buffer: ``zipfile`` then writes data descriptors and we stream as we go."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        self._buf += b
        self._pos += len(b)
        return len(b)

    def tell(self) -> int:
        return self._pos

    def drain(self) -> bytes:
        data, self._buf = bytes(self._buf), bytearray()
        return data


def _zip_stream(files: list[tuple[str, Path, str]]):
    """Entries named like the single downloads (X1); non-ASCII names get the zip UTF-8 flag (bit 11)."""
    sink = _ZipSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as zf:
        for _clip_id, path, name in files:
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_STORED
            with path.open("rb") as src, zf.open(info, "w") as dst:
                while chunk := src.read(ZIP_CHUNK):
                    dst.write(chunk)
                    yield sink.drain()
            yield sink.drain()
    yield sink.drain()


def create_app(config: Config, password: str, *, runner: JobRunner | None = None,
               preflight: Callable[[Config], None] | None = ollama_preflight,
               pipeline: Callable = run_pipeline, render: Callable = run_render,
               secret: bytes | None = None, disk_usage: Callable = shutil.disk_usage,
               clock: Callable[[], float] = time.time) -> FastAPI:
    """``preflight`` / ``pipeline`` / ``render`` are injectable for tests (defaults: CP8 ``ollama_preflight`` /
    ``run_pipeline``, CP7/CP8.2 ``run_render``); so are ``disk_usage`` (``shutil.disk_usage``) and ``clock`` (epoch
    seconds, ages of the storage recommendations) for CP8.6."""
    runner = runner or JobRunner()
    storage = StorageCache(config, disk_usage=disk_usage, clock=clock)
    # Serialises "no active job for the episode?" + review.json write + job submit (W5: no title write while a
    # pipeline / render job of the episode is queued or running).
    submit_lock = threading.Lock()
    publish_lock = threading.Lock()  # publish.json read-modify-write (no job check: allowed while a job runs)
    signer = SessionSigner(secret if secret is not None else load_or_create_secret(Path(config.workspace.dir)),
                           password, config.web.session_days)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runner.start()
        try:
            yield
        finally:
            await asyncio.to_thread(runner.stop)

    app = FastAPI(title="auto-short web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runner = runner
    app.state.storage = storage
    app.state.signer = signer

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path not in PUBLIC_PATHS and not signer.verify(request.cookies.get(COOKIE_NAME)):
            if path.startswith("/api/") or path.startswith("/files/") or request.method != "GET":
                response = JSONResponse({"detail": "chưa đăng nhập"}, status_code=401)
            else:
                target = path + (f"?{request.url.query}" if request.url.query else "")
                response = RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        else:
            response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # --- auth --------------------------------------------------------------------------------------

    @app.get("/login")
    async def login_form(request: Request, next: str = "/"):
        if signer.verify(request.cookies.get(COOKIE_NAME)):
            return RedirectResponse(_safe_next(next), status_code=303)
        return _login_page(config.web.session_days, next_path=_safe_next(next))

    @app.post("/login")
    async def login(request: Request):
        body = await request.body()
        if len(body) > 4096:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        is_json = request.headers.get("content-type", "").startswith("application/json")
        try:
            if is_json:
                data = json.loads(body or b"{}")
                password, next_path = str(data.get("password", "")), data.get("next")
            else:
                form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                password, next_path = (form.get("password") or [""])[0], (form.get("next") or [None])[0]
        except (ValueError, AttributeError):
            password, next_path = "", None
        next_path = _safe_next(next_path)
        if not signer.check_password(password):
            await asyncio.sleep(LOGIN_DELAY)
            log.warning("web: failed login from %s", request.client.host if request.client else "?")
            if is_json:
                return JSONResponse({"detail": "sai mật khẩu"}, status_code=401)
            return _login_page(config.web.session_days, "Sai mật khẩu.", next_path, status=401)
        response = (JSONResponse({"ok": True}) if is_json else RedirectResponse(next_path, status_code=303))
        response.set_cookie(COOKIE_NAME, signer.issue(), max_age=signer.max_age, httponly=True, samesite="lax",
                            path="/")
        log.info("web: login from %s", request.client.host if request.client else "?")
        return response

    @app.post("/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return response

    # --- pages -------------------------------------------------------------------------------------

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/episodes/{episode_id}")
    async def episode_page(episode_id: str):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return FileResponse(STATIC_DIR / "episode.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- API ---------------------------------------------------------------------------------------

    def _job_view(job) -> dict | None:
        if job is None:
            return None
        out = job.to_dict()
        out["queue_position"] = runner.queue_position(job)
        return out

    @app.get("/api/episodes")
    def api_list():
        items = ep.list_episodes(config)
        known = {i["id"] for i in items}
        for job in runner.jobs():  # queued jobs whose workspace does not exist yet
            if job.active and job.episode_id not in known:
                known.add(job.episode_id)
                items.insert(0, {"id": job.episode_id, "title": None, "stages_done": 0,
                                 "stages_total": len(PIPELINE_STAGES), "running": None, "failed": None,
                                 "shorts": 0})
        for item in items:
            job = runner.latest(item["id"])
            item["job"] = job.to_dict(logs=False) if job else None
            item.setdefault("published", 0)
            item["publish_group"] = ep.publish_group(item)
        return {"episodes": items}

    @app.post("/api/episodes")
    def api_submit(body: SubmitIn):
        try:
            video_id, url = parse_youtube_url(body.url)
        except UrlError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        series, episode = _clean(body.series), _clean(body.episode)
        current = runner.latest(video_id)
        if current is not None and current.active:
            return JSONResponse({"created": False, "episode_id": video_id, "job": _job_view(current)})
        if is_archived(Path(config.workspace.dir) / video_id):  # CP8.6 S3
            return JSONResponse({"detail": str(ArchivedError(video_id))}, status_code=409)
        if storage.status()["block"]:  # CP8.6 S4
            return JSONResponse({"detail": "Ổ đĩa server còn dưới 3 GB trống: không nhận video mới. "
                                           "Dọn bớt ở tab Bộ nhớ rồi thử lại."}, status_code=507)
        if preflight is not None:
            try:
                preflight(config)
            except PreflightError as exc:
                return JSONResponse({"detail": f"ollama preflight: {exc}"}, status_code=503)
        with submit_lock:
            job, created = runner.submit(video_id, KIND_PIPELINE,
                                         pipeline_target(url, config, series=series, episode=episode,
                                                         pipeline=pipeline, preflight=preflight))
        return JSONResponse({"created": created, "episode_id": video_id, "job": _job_view(job)},
                            status_code=202 if created else 200)

    @app.get("/api/episodes/{episode_id}")
    def api_episode(episode_id: str):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        view = ep.episode_view(config, episode_id)
        job = runner.latest(episode_id)
        if view is None:
            if job is None:
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            view = {"id": episode_id, "title": None, "channel": None, "duration": None, "source_url": None,
                    "stages": [], "header": None, "shorts": [], "rendered": 0, "deleted": 0, "published": 0,
                    "zip_url": None, "zip_name": None, "archived": None}
        view["job"] = _job_view(job)
        if job is not None and job.active and job.kind == KIND_RENDER:
            for short in view["shorts"]:
                short["rendering"] = short["clip_id"] in job.clip_ids
        return view

    def _check_clip(episode_id: str, clip_id: str) -> JSONResponse | None:
        if not ep.valid_episode_id(episode_id) or not ep.valid_clip_id(clip_id):
            return JSONResponse({"detail": "không có Short này"}, status_code=404)
        return None

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/title/preview")
    def api_title_preview(episode_id: str, clip_id: str, body: PreviewIn):
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        try:
            return _preview_dict(preview_title(episode_id, config, clip_id, body.text))
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/title")
    def api_title(episode_id: str, clip_id: str, body: TitleIn):
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        actions = (body.set is not None) + (body.alternative is not None) + bool(body.reset)
        if actions != 1:
            return JSONResponse({"detail": "cần đúng một trong: set, alternative, reset"}, status_code=422)
        with submit_lock:
            current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; sửa title sau khi job xong",
                                     "job": _job_view(current)}, status_code=409)
            try:
                if body.set is not None:
                    preview = set_title(episode_id, config, clip_id, body.set)
                elif body.alternative is not None:
                    preview = set_alternative(episode_id, config, clip_id, body.alternative)
                else:
                    preview = reset_title(episode_id, config, clip_id)
            except ArchivedError as exc:  # CP8.6 S3
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render),
                                   clip_ids=[clip_id])
        log.info("web: title %s [%s]: %s -> render job %s", clip_id, episode_id,
                 f"{preview.origin} {preview.title!r}" if preview else "reset (untitled)", job.id)
        return JSONResponse({"preview": _preview_dict(preview), "job": _job_view(job)}, status_code=202)

    def _review_render(episode_id: str, clip_id: str, action: Callable, what: str) -> JSONResponse:
        """CP8.5 X2: delete / restore one Short = write review.json + render job, same rules as a title write
        (409 while a job of the episode is queued/running, all under the submit lock)."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        with submit_lock:
            current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; thử lại sau khi job xong",
                                     "job": _job_view(current)}, status_code=409)
            archived = is_archived(Path(config.workspace.dir) / episode_id)
            try:
                if archived and action is reject_clip:
                    # CP8.6 S3: no render possible; the deletion is applied to the last render directly.
                    changed = reject_archived_clip(episode_id, config, clip_id)
                    storage.invalidate()
                    log.info("web: %s %s [%s] (archived, no render)", what, clip_id, episode_id)
                    return JSONResponse({"changed": changed, "job": None})
                changed = action(episode_id, config, clip_id)
            except ArchivedError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render),
                                   clip_ids=[clip_id])
        log.info("web: %s %s [%s]%s -> render job %s", what, clip_id, episode_id, "" if changed else " (no change)",
                 job.id)
        return JSONResponse({"changed": changed, "job": _job_view(job)}, status_code=202)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/delete")
    def api_short_delete(episode_id: str, clip_id: str):
        return _review_render(episode_id, clip_id, reject_clip, "delete Short")

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/restore")
    def api_short_restore(episode_id: str, clip_id: str):
        return _review_render(episode_id, clip_id, restore_clip, "restore Short")

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/published")
    def api_short_published(episode_id: str, clip_id: str, body: PublishedIn):
        """X4: tick / untick "Đã đăng" — user state only: no job, allowed while a job runs, render not stale."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        with publish_lock:
            try:
                return set_published(episode_id, config, clip_id, body.value)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.delete("/api/episodes/{episode_id}")
    def api_episode_delete(episode_id: str):
        """X3: delete work/<id>/ and output/<id>/ (cannot be undone); 409 while a job of the episode is
        queued/running; unknown / invalid id -> 404."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with submit_lock:
            current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; xóa sau khi job xong",
                                     "job": _job_view(current)}, status_code=409)
            try:
                removed = delete_episode(episode_id, config)
            except EpisodeNotFound:
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            except (ReviewError, OSError) as exc:
                log.error("web: delete episode %s failed: %s", episode_id, exc)
                return JSONResponse({"detail": f"không xóa được: {exc}"}, status_code=500)
            runner.forget(episode_id)
            storage.invalidate()
        log.warning("web: deleted episode %s (%s)", episode_id, ", ".join(str(p) for p in removed))
        return {"deleted": episode_id}

    # --- storage (CP8.6) ---------------------------------------------------------------------------

    @app.get("/storage")
    async def storage_page():
        return FileResponse(STATIC_DIR / "storage.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/storage")
    def api_storage():
        """S1 + S2 + S4: disks, episode sizes, caches, recommendations, warning (cached up to 30 s)."""
        active = {j.episode_id for j in runner.jobs() if j.active}
        return storage.report(active)

    @app.get("/api/storage/status")
    def api_storage_status():
        """S4 banner on every page: free space, ``warn``, ``block`` (not cached)."""
        return storage.status()

    @app.post("/api/episodes/{episode_id}/archive")
    def api_archive(episode_id: str):
        """S3: delete the downloaded source video, keep the Shorts; 409 while a job of the episode is
        queued/running; 422 local source / render not done; 404 unknown id."""
        if not ep.valid_episode_id(episode_id) or not (Path(config.workspace.dir) / episode_id).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with submit_lock:
            current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; dọn sau khi job xong",
                                     "job": _job_view(current)}, status_code=409)
            try:
                result = archive_source(episode_id, config)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            storage.invalidate()
        log.warning("web: archived %s: removed %s (%d bytes)", episode_id, ", ".join(result.removed) or "-",
                    result.freed)
        return {"archived": episode_id, "changed": result.changed, "freed": result.freed, "removed": result.removed}

    # --- files -------------------------------------------------------------------------------------

    @app.get("/files/{episode_id}/{name}")
    def files(episode_id: str, name: str, download: str | None = None):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        if name == "shorts.zip":
            items = ep.short_files(config, episode_id)
            if not items:
                return JSONResponse({"detail": "chưa có Short nào"}, status_code=404)
            return StreamingResponse(
                _zip_stream(items), media_type="application/zip",
                headers={"Content-Disposition": content_disposition(ep.zip_download_name(config, episode_id)),
                         "Cache-Control": "no-store"})
        clip_id = name[:-4] if name.endswith(".mp4") else ""
        if not ep.valid_clip_id(clip_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        found = ep.short_file(config, episode_id, clip_id)
        if found is None:
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        path, download_name = found
        headers = {"Cache-Control": "private, no-cache"}
        if download is not None:
            headers["Content-Disposition"] = content_disposition(download_name)
        return FileResponse(path, media_type="video/mp4", headers=headers)

    return app
