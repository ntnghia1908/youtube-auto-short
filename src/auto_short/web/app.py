"""FastAPI app factory (W2, W4, W6, W7). Contract: docs/decisions/CP8.3-web-contract.md."""

from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import Config
from ..pipeline import PIPELINE_STAGES, PreflightError, ollama_preflight, run_pipeline
from . import episodes as ep
from .auth import COOKIE_NAME, SessionSigner, load_or_create_secret
from .jobs import KIND_PIPELINE, JobRunner, pipeline_target
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


def _zip_stream(episode_id: str, files: list[tuple[str, Path]]):
    sink = _ZipSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as zf:
        for clip_id, path in files:
            info = zipfile.ZipInfo.from_file(path, f"{episode_id}_{clip_id}.mp4")
            info.compress_type = zipfile.ZIP_STORED
            with path.open("rb") as src, zf.open(info, "w") as dst:
                while chunk := src.read(ZIP_CHUNK):
                    dst.write(chunk)
                    yield sink.drain()
            yield sink.drain()
    yield sink.drain()


def create_app(config: Config, password: str, *, runner: JobRunner | None = None,
               preflight: Callable[[Config], None] | None = ollama_preflight,
               pipeline: Callable = run_pipeline, secret: bytes | None = None) -> FastAPI:
    """``preflight`` / ``pipeline`` are injectable for tests (defaults: CP8 ``ollama_preflight`` /
    ``run_pipeline``)."""
    runner = runner or JobRunner()
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
        if preflight is not None:
            try:
                preflight(config)
            except PreflightError as exc:
                return JSONResponse({"detail": f"ollama preflight: {exc}"}, status_code=503)
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
                    "stages": [], "header": None, "shorts": [], "rendered": 0, "zip_url": None}
        view["job"] = _job_view(job)
        return view

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
                _zip_stream(episode_id, items), media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{episode_id}_shorts.zip"',
                         "Cache-Control": "no-store"})
        clip_id = name[:-4] if name.endswith(".mp4") else ""
        if not ep.valid_clip_id(clip_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        path = ep.short_file(config, episode_id, clip_id)
        if path is None:
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        headers = {"Cache-Control": "private, no-cache"}
        if download is not None:
            return FileResponse(path, media_type="video/mp4", filename=f"{episode_id}_{clip_id}.mp4",
                                headers=headers)
        return FileResponse(path, media_type="video/mp4", headers=headers)

    return app
