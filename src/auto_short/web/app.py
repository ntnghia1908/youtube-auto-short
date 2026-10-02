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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool

from .. import khaithi
from ..config import Config
from ..pipeline import PIPELINE_STAGES, PreflightError, ollama_preflight, run_pipeline
from ..post import corrections as post_corrections
from ..post import fetch as post_fetch
from ..post import images as post_images
from ..post import logic as post_logic
from ..post import source as post_source
from ..post import stage as post_stage
from ..post import store as post_store
from ..post import validate as post_validate
from ..render import run_render
from ..review import (ArchivedError, EpisodeNotFound, ReviewError, TitlePreview, archive_source, content_disposition,
                      list_tombstones, mark_downloaded, remove_tombstone,
                      delete_episode, is_archived, list_titles, preview_title, reject_archived_clip, reject_clip,
                      reset_title, restore_clip, set_alternative, set_published, set_title)
from ..review import shorts as review_shorts
from ..review.names import hashtags as review_hashtags
from . import episodes as ep
from .auth import COOKIE_NAME, SessionSigner, load_or_create_secret
from .storage import BLOCK_MESSAGE, StorageCache
from .jobs import (KIND_ADD, KIND_PIPELINE, KIND_POST, KIND_POST_SEARCH, KIND_RENDER, POST_IMAGES_KEY, JobRunner,
                   add_short_target, image_search_target, pipeline_target, post_compose_target, render_target)
from .playlists import LIST_TIMEOUT, PlaylistError, PlaylistStore, ytdlp_list
from .urls import ASK, PLAYLIST, UrlError, canonical_url, classify_url, valid_playlist_id

log = logging.getLogger("auto_short")

STATIC_DIR = Path(__file__).parent / "static"
LOGIN_DELAY = 1.0  # seconds to wait after a wrong password
# Reachable without a session: the login page and its stylesheet only.
PUBLIC_PATHS = {"/login", "/static/style.css"}
MAX_FIELD = 100
ZIP_CHUNK = 1 << 20
KINDS = ("short", "khaithi")  # CP8.9 A1.1, in job order


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


class PreviewIn(BaseModel):
    text: str = Field(max_length=1000)


class PublishedIn(BaseModel):
    value: StrictBool  # JSON true / false only


class HashtagsIn(BaseModel):
    hashtags: list[str] = Field(max_length=100)


class SeriesIn(BaseModel):
    series: Any = None  # CP8.11 D7: checked by the store (string, 1-100 chars after normalization) -> 422


class TitleIn(BaseModel):
    """Exactly one action: ``set`` (manual text), ``alternative`` (1-based AI alternative) or ``reset: true``."""

    set: str | None = Field(default=None, max_length=1000)
    alternative: int | None = None
    reset: bool = False


SEGMENT_ID = Field(default=None, max_length=32)
SOURCE_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
                ".mov": "video/quicktime"}


class CutPreviewIn(BaseModel):
    """CP9 C7: range of caption lines ``start_segment`` .. ``end_segment`` + nudges (s, ±0.2 steps, ≤ ±2.0);
    ``clip_id`` = the Short being edited (its current range is the base), absent = a new Short."""

    clip_id: str | None = Field(default=None, max_length=32)
    start_segment: str = Field(max_length=32)
    end_segment: str = Field(max_length=32)
    start_nudge: Any = 0
    end_nudge: Any = 0


class CutIn(BaseModel):
    """``{start_segment, end_segment, start_nudge, end_nudge}`` or ``{reset: true}`` ("Về như AI chọn")."""

    start_segment: str | None = SEGMENT_ID
    end_segment: str | None = SEGMENT_ID
    start_nudge: Any = 0
    end_nudge: Any = 0
    reset: bool = False


class AddIn(BaseModel):
    """A new Short: ``{candidate_id}`` (remaining AI proposal) or ``{start_segment, end_segment[, nudges]}``."""

    candidate_id: str | None = Field(default=None, max_length=32)
    start_segment: str | None = SEGMENT_ID
    end_segment: str | None = SEGMENT_ID
    start_nudge: Any = 0
    end_nudge: Any = 0


class PostComposeIn(BaseModel):
    """CP8.15 P9: ``{"clips": [...]}`` (1-based clip ids) or ``{"clips": "all"}`` ("Soạn bài cho mọi Short")."""

    clips: Any = None


class PostEditIn(BaseModel):
    """CP8.15 P9 ``PUT``: any non-empty subset of ``paragraphs`` / ``image`` / ``link``."""

    paragraphs: list[str] | None = Field(default=None, max_length=200)
    image: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=2000)


class CorrectionIn(BaseModel):
    """CP8.18 D5 ``POST /api/post-corrections``: a hand-added rule."""

    model_config = {"populate_by_name": True}
    from_: str = Field(alias="from", max_length=500)
    to: str = Field(max_length=500)


class CorrectionEditIn(BaseModel):
    """CP8.18 D5 ``PUT /api/post-corrections/{id}``: any subset of ``status`` / ``from`` / ``to``."""

    model_config = {"populate_by_name": True}
    status: Literal["proposed", "approved", "rejected"] | None = None
    from_: str | None = Field(default=None, alias="from", max_length=500)
    to: str | None = Field(default=None, max_length=500)


class PostImageSearchIn(BaseModel):
    url: str = Field(max_length=2000)


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
               clock: Callable[[], float] = time.time, playlist_lister: Callable = ytdlp_list,
               playlist_timeout: float = LIST_TIMEOUT, titler: Callable | None = None,
               post_compose: Callable | None = None,
               post_preflight: Callable[[Config], None] | None = post_stage.preflight,
               post_search: Callable | None = None) -> FastAPI:
    """``preflight`` / ``pipeline`` / ``render`` are injectable for tests (defaults: CP8 ``ollama_preflight`` /
    ``run_pipeline``, CP7/CP8.2 ``run_render``); so are ``disk_usage`` (``shutil.disk_usage``) and ``clock`` (epoch
    seconds, ages of the storage recommendations) for CP8.6; ``playlist_lister`` (yt-dlp flat listing) and
    ``playlist_timeout`` for CP8.7; ``titler`` (AI title of an added Short, default
    :func:`auto_short.titling.added.title_added`) for CP9; ``post_compose`` / ``post_preflight`` (default
    :func:`auto_short.post.stage.compose_posts` / ``.preflight``) and ``post_search`` (default
    :func:`auto_short.post.fetch.search_images`) for CP8.15."""
    runner = runner or JobRunner(config.web.queue_mode)
    storage = StorageCache(config, disk_usage=disk_usage, clock=clock)
    playlists = PlaylistStore(config, lister=playlist_lister, timeout=playlist_timeout)
    # Serialises "no active job for the episode?" + review.json write + job submit (W5: no title write while a
    # pipeline / render job of the episode is queued or running).
    submit_lock = threading.Lock()
    publish_lock = threading.Lock()  # publish.json read-modify-write (no job check: allowed while a job runs)
    post_lock = threading.Lock()  # posts.json read-modify-write (CP8.15 P7: allowed even while a job runs)
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
    app.state.playlists = playlists
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

    @app.get("/episodes/{episode_id}/posts")
    async def episode_posts_page(episode_id: str):
        """CP8.16 R1: tab "Bài đăng" of a video (same HTML for the Short episode and its khai thị episode)."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return FileResponse(STATIC_DIR / "posts.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- API ---------------------------------------------------------------------------------------

    def _job_view(job, *, logs: bool = True) -> dict | None:
        if job is None:
            return None
        out = job.to_dict(logs=logs)
        out["queue_position"] = runner.queue_position(job)  # CP8.10: in the queue of the lane it waits for
        return out

    @app.get("/api/episodes")
    def api_list():
        items = ep.list_episodes(config)
        known = {i["id"] for i in items}
        for job in runner.jobs():  # queued jobs whose workspace does not exist yet
            if job.active and job.episode_id not in known:
                known.add(job.episode_id)
                items.insert(0, {**ep.kind_fields(config, job.episode_id), "id": job.episode_id, "title": None,
                                 "stages_done": 0, "stages_total": len(PIPELINE_STAGES), "running": None,
                                 "failed": None, "shorts": 0})
        in_playlists = playlists.video_ids()
        for item in items:
            job = runner.latest(item["id"])
            item["job"] = _job_view(job, logs=False)
            item.setdefault("published", 0)
            item.setdefault("complete", False)
            item["publish_group"] = ep.publish_group(item)
            # CP8.7: home page "Tập lẻ" = not in a bộ kinh; CP8.9 K8: a khai thị episode follows its base video
            item["in_playlist"] = (item.get("base_episode_id") or item["id"]) in in_playlists
        return {"episodes": items, "gpu": runner.gpu_status()}  # FIX-ollama-wait O7

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

    @app.post("/api/episodes")
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
            kc = config.khaithi
            try:
                lo, hi = khaithi.check_minutes(
                    kc.default_min_minutes if body.min_minutes is None else body.min_minutes,
                    kc.default_max_minutes if body.max_minutes is None else body.max_minutes, kc.max_minutes_limit)
            except khaithi.KhaithiError as exc:
                return JSONResponse({"detail": exc.vi}, status_code=422)
        video_id, url = parsed.video_id, canonical_url(parsed.video_id)
        series, episode = _clean(body.series), _clean(body.episode)

        # W4 per kind on its own episode (A1.1): duplicate job, archived (CP8.6 S3), low disk (CP8.6 S4)
        items: list[dict] = []
        for kind in kinds:
            eid = video_id if kind == "short" else khaithi.episode_id_for(video_id)
            item: dict = {"kind": kind, "episode_id": eid}
            current = runner.latest(eid)
            if current is not None and current.active:
                item.update(created=False, job=current)
            elif is_archived(Path(config.workspace.dir) / eid):
                item.update(error=str(ArchivedError(eid)), status=409)
            elif storage.status()["block"]:
                item.update(error=BLOCK_MESSAGE, status=507)
            items.append(item)
        todo = [i for i in items if "job" not in i and "error" not in i]
        # FIX-ollama-wait O4: no Ollama preflight here - the ai lane checks it and waits for the GPU
        with submit_lock:
            for i in todo:  # Short first, then khai thị (K5 reuses the Short's source + transcript)
                current = runner.latest(i["episode_id"])
                if current is not None and current.active:
                    i.update(created=False, job=current)
                    continue
                if i["kind"] == khaithi.KIND:
                    try:  # written just before its job is queued; changed minutes -> re-run from analysis
                        _, changed = khaithi.prepare(config, video_id, lo, hi)
                    except khaithi.KhaithiError as exc:
                        i.update(error=exc.vi, status=409)
                        continue
                    log.info("web: khai thi %s %d-%d minutes (%s)", i["episode_id"], lo, hi,
                             "parameters changed" if changed else "parameters unchanged")
                job, created = runner.submit(
                    i["episode_id"], KIND_PIPELINE,
                    pipeline_target(url, config, series=series, episode=episode, pipeline=pipeline,
                                    preflight=preflight,
                                    episode_id=i["episode_id"] if i["kind"] == khaithi.KIND else None,
                                    disk_blocked=storage.block_message))
                i.update(created=created, job=job)
        playlists.invalidate(video_id)
        storage.invalidate()
        out = [{k: (_job_view(v) if k == "job" else v) for k, v in i.items()} for i in items]
        ok = [i for i in out if "error" not in i]
        if not ok:
            return JSONResponse({"detail": out[0]["error"], "kind": "video", "episodes": out},
                                status_code=out[0]["status"])
        first = ok[0]  # UI before A1: created / episode_id / job of the first accepted episode
        return JSONResponse({"kind": "video", "episodes": out, "created": first["created"],
                             "episode_id": first["episode_id"], "job": first["job"]},
                            status_code=202 if any(i.get("created") for i in ok) else 200)

    # --- playlists (CP8.7) ---------------------------------------------------------------------------

    def _import_playlist(playlist_id: str) -> JSONResponse:
        try:
            doc, created = playlists.add(playlist_id)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)
        log.info("web: playlist %s %s (%d entries)", playlist_id, "imported" if created else "already stored",
                 len(doc["entries"]))
        return JSONResponse({"kind": PLAYLIST, "created": created, "playlist_id": playlist_id,
                             "title": doc.get("title"), "count": len(doc["entries"])},
                            status_code=201 if created else 200)

    def _jobs_by_episode() -> dict[str, dict]:
        out = {}
        for job in runner.jobs():
            latest = runner.latest(job.episode_id)
            if latest is job:
                out[job.episode_id] = _job_view(job, logs=False)
        return out

    def _playlist_or_404(playlist_id: str):
        if not valid_playlist_id(playlist_id):
            return None
        try:
            return playlists.load(playlist_id)
        except PlaylistError:
            return None

    @app.get("/api/deleted")
    def api_deleted():
        """Tombstones of deleted single episodes (not in a stored bộ kinh, no workspace now)."""
        in_playlists = playlists.video_ids()
        return {"episodes": [d for d in list_tombstones(config) if d["episode_id"] not in in_playlists]}

    @app.delete("/api/deleted/{episode_id}")
    def api_deleted_remove(episode_id: str):
        """"Xóa khỏi lịch sử": removes the tombstone only."""
        if not ep.valid_episode_id(episode_id) or not remove_tombstone(config, episode_id):
            return JSONResponse({"detail": "không có trong lịch sử"}, status_code=404)
        playlists.invalidate(episode_id)
        return {"removed": episode_id}

    @app.get("/playlists/{playlist_id}")
    async def playlist_page(playlist_id: str):
        if not valid_playlist_id(playlist_id):
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        return FileResponse(STATIC_DIR / "playlist.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/playlists")
    def api_playlists():
        jobs = _jobs_by_episode()
        return {"playlists": [playlists.summary(d, jobs) for d in playlists.all()]}

    @app.get("/api/playlists/{playlist_id}")
    def api_playlist(playlist_id: str):
        doc = _playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        view = playlists.view(doc, _jobs_by_episode())
        view["gpu"] = runner.gpu_status()  # FIX-ollama-wait O7
        kc = config.khaithi  # CP8.9 A2.2: defaults of the kind bar ("Khai thị [min]–[max] phút")
        view["khaithi_defaults"] = {"min_minutes": kc.default_min_minutes, "max_minutes": kc.default_max_minutes,
                                    "max_minutes_limit": kc.max_minutes_limit}
        return view

    @app.post("/api/playlists/{playlist_id}/refresh")
    def api_playlist_refresh(playlist_id: str):
        if _playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc, added = playlists.refresh(playlist_id)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        return {"playlist_id": playlist_id, "count": len(doc["entries"]), "added": added}

    @app.put("/api/playlists/{playlist_id}/hashtags")
    def api_playlist_hashtags(playlist_id: str, body: HashtagsIn):
        """Per-bộ kinh hashtags (full ordered list); no job, allowed while jobs run."""
        if _playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc = playlists.set_hashtags(playlist_id, body.hashtags)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        tags, custom = playlists.effective_hashtags(doc)
        return {"playlist_id": playlist_id, "hashtags": tags, "hashtags_custom": custom}

    @app.delete("/api/playlists/{playlist_id}/hashtags")
    def api_playlist_hashtags_reset(playlist_id: str):
        if _playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc = playlists.set_hashtags(playlist_id, None)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        tags, custom = playlists.effective_hashtags(doc)
        return {"playlist_id": playlist_id, "hashtags": tags, "hashtags_custom": custom}

    def _series_response(playlist_id: str, value) -> JSONResponse | dict:
        if _playlist_or_404(playlist_id) is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            doc = playlists.set_series(playlist_id, value)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except FileNotFoundError:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        series = playlists.series_view(doc)["series"]
        log.info("web: playlist %s series %s", playlist_id, repr(series) if series else "removed")
        return {"playlist_id": playlist_id, "series": series, "series_custom": series is not None}

    @app.put("/api/playlists/{playlist_id}/series")
    def api_playlist_series(playlist_id: str, body: SeriesIn):
        """CP8.11 D7: "Tên bộ kinh" (header fallback when no title pattern matches); no job, allowed while jobs
        run."""
        if body.series is None:
            return JSONResponse({"detail": "tên bộ kinh phải là chuỗi"}, status_code=422)
        return _series_response(playlist_id, body.series)

    @app.delete("/api/playlists/{playlist_id}/series")
    def api_playlist_series_reset(playlist_id: str):
        return _series_response(playlist_id, None)

    @app.post("/api/playlists/{playlist_id}/hashtags/preview")
    def api_playlist_hashtags_preview(playlist_id: str, body: HashtagsIn):
        """Copy text of the playlist's longest processed title (or a 60-char sample) with these tags."""
        doc = _playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        try:
            return playlists.preview(doc, body.hashtags)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.delete("/api/playlists/{playlist_id}")
    def api_playlist_delete(playlist_id: str):
        """Only the stored list; processed episodes stay (L1)."""
        if not valid_playlist_id(playlist_id) or not playlists.remove(playlist_id):
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        log.info("web: playlist %s removed (episodes kept)", playlist_id)
        return {"deleted": playlist_id}

    @app.get("/api/episodes/{episode_id}")
    def api_episode(episode_id: str):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        kf = ep.kind_fields(config, episode_id)
        # CP8.9 K8: a khai thị episode copies with the hashtags of the bộ kinh of its base video
        view = ep.episode_view(config, episode_id,
                               hashtags=playlists.hashtags_for(kf["base_episode_id"] or episode_id))
        job = runner.latest(episode_id)
        if view is None:
            if job is None:
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            view = {**kf, "id": episode_id, "title": None, "channel": None, "duration": None, "source_url": None,
                    "stages": [], "header": None, "shorts": [], "rendered": 0, "deleted": 0, "published": 0,
                    "zip_url": None, "zip_name": None, "zip_all_url": None, "zip_all_name": None,
                    "archived": None}
        view["job"] = _job_view(job)
        view["gpu"] = runner.gpu_status()  # FIX-ollama-wait O7
        view["post_job"] = _job_view(runner.latest_post(episode_id))  # CP8.16 R3 (job stays the episode's own job)
        if job is not None and job.active and job.kind in (KIND_RENDER, KIND_ADD):
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

    # --- CP9: cut points + added Shorts ---------------------------------------------------------------

    def _episode_or_404(episode_id: str) -> JSONResponse | None:
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return None

    def _busy(episode_id: str) -> JSONResponse | None:
        current = runner.latest(episode_id)
        if current is not None and current.active:
            return JSONResponse({"detail": "episode đang có job chạy/đợi; thử lại sau khi job xong",
                                 "job": _job_view(current)}, status_code=409)
        return None

    @app.get("/api/episodes/{episode_id}/transcript")
    def api_transcript(episode_id: str):
        """C7: caption lines + the current range of every Short (read-only, allowed while a job runs)."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        try:
            return review_shorts.transcript_view(episode_id, config)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/episodes/{episode_id}/proposals")
    def api_proposals(episode_id: str):
        """C7: AI proposals not selected (overlapped / over_limit / ineligible) that map to a candidate."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        try:
            return review_shorts.list_proposals(episode_id, config)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.post("/api/episodes/{episode_id}/cut/preview")
    def api_cut_preview(episode_id: str, body: CutPreviewIn):
        """C7: range + duration + C4 error / warnings of lines + nudges; nothing written, allowed during a job."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        if body.clip_id is not None and not ep.valid_clip_id(body.clip_id):
            return JSONResponse({"detail": "không có Short này"}, status_code=404)
        try:
            return review_shorts.preview_cut(episode_id, config, clip_id=body.clip_id,
                                             start_segment=body.start_segment, end_segment=body.end_segment,
                                             start_nudge=body.start_nudge, end_nudge=body.end_nudge)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/cut")
    def api_cut(episode_id: str, clip_id: str, body: CutIn):
        """C7: save the cut points of one Short (or ``reset``) + render job for it; 409 while a job runs or when
        the source video was cleaned up; 422 invalid range (review.json unchanged)."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        has_range = body.start_segment is not None and body.end_segment is not None
        if body.reset == has_range or (not has_range and (body.start_segment or body.end_segment)):
            return JSONResponse({"detail": "cần start_segment + end_segment, hoặc reset: true"}, status_code=422)
        with submit_lock:
            if (busy := _busy(episode_id)) is not None:
                return busy
            try:
                if body.reset:
                    preview = review_shorts.reset_cut(episode_id, config, clip_id)
                else:
                    preview = review_shorts.set_cut(episode_id, config, clip_id, start_segment=body.start_segment,
                                                    end_segment=body.end_segment, start_nudge=body.start_nudge,
                                                    end_nudge=body.end_nudge)
            except ArchivedError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render),
                                   clip_ids=[clip_id])
        log.info("web: cut %s [%s]: %s %.3f-%.3f (%.1f s) -> render job %s", clip_id, episode_id,
                 "reset" if body.reset else "set", preview["start"], preview["end"], preview["duration"], job.id)
        return JSONResponse({"preview": preview, "job": _job_view(job)}, status_code=202)

    @app.post("/api/episodes/{episode_id}/shorts")
    def api_add_short(episode_id: str, body: AddIn):
        """C7: add a Short (C1) -> job: AI title (lane ai, C6) then render. 409 while a job runs / archived;
        503 Ollama preflight (W4); 422 invalid range or proposal (nothing written)."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        if (busy := _busy(episode_id)) is not None:
            return busy
        if is_archived(Path(config.workspace.dir) / episode_id):
            return JSONResponse({"detail": str(ArchivedError(episode_id))}, status_code=409)
        if preflight is not None:
            try:
                preflight(config)
            except PreflightError as exc:
                return JSONResponse({"detail": f"ollama preflight: {exc}"}, status_code=503)
        with submit_lock:
            if (busy := _busy(episode_id)) is not None:
                return busy
            try:
                added = review_shorts.add_short(episode_id, config, candidate_id=body.candidate_id,
                                                start_segment=body.start_segment, end_segment=body.end_segment,
                                                start_nudge=body.start_nudge, end_nudge=body.end_nudge)
            except ArchivedError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_ADD,
                                   add_short_target(config, added.clip_id, render=render, preflight=preflight,
                                                    titler=titler),
                                   clip_ids=[added.clip_id])
        log.info("web: added Short %s [%s] %.3f-%.3f (%.1f s, %s) -> job %s", added.clip_id, episode_id,
                 added.preview["start"], added.preview["end"], added.preview["duration"],
                 body.candidate_id or "transcript", job.id)
        return JSONResponse({"clip_id": added.clip_id, "preview": added.preview, "job": _job_view(job)},
                            status_code=202)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/published")
    def api_short_published(episode_id: str, clip_id: str, body: PublishedIn):
        """X4: tick / untick "Đã đăng" — user state only: no job, allowed while a job runs, render not stale."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        with publish_lock:
            try:
                result = set_published(episode_id, config, clip_id, body.value)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        playlists.invalidate(episode_id)
        storage.invalidate()
        return result

    # --- CP8.15: community post text ------------------------------------------------------------------------

    def _auto_post(job) -> None:
        """CP8.16 R2a: an episode job that ran the render step has ended (done / failed) → queue the ``auto``
        compose job of the episode when R4 selects at least one Short (empty set = no job)."""
        eid = job.episode_id
        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, eid)]
        if not order:
            return
        try:
            ep_src = post_source.load(eid, config)
            with post_lock:
                doc = post_store.read_posts(_posts_path(eid), eid)
        except (post_source.PostSourceError, post_store.PostsError):
            return
        if not post_stage.auto_clips(ep_src, doc, order):
            return
        posted, created = runner.submit(eid, KIND_POST,
                                        post_compose_target(config, "auto", compose=post_compose,
                                                            preflight=post_preflight, lock=post_lock))
        log.info("web: tự soạn bài [%s] sau job %s -> job %s%s", eid, job.id, posted.id,
                 "" if created else " (đã có)")

    runner.on_finished = _auto_post

    def _post_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _posts_path(episode_id: str) -> Path:
        return Path(config.workspace.dir) / episode_id / post_store.POSTS_NAME

    def _post_header_fields(episode_id: str) -> dict | None:
        try:
            doc = json.loads((Path(config.workspace.dir) / episode_id / "titles.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        fields = (doc.get("header") or {}).get("fields")
        return fields if isinstance(fields, dict) else None

    def _post_series_and_tags(episode_id: str) -> tuple[str | None, tuple[str, ...]]:
        """Like ``episode_view``'s per-Short hashtags (CP8.7/CP8.8): custom bộ kinh hashtags, else ``#<series>`` +
        ``[web] hashtags``."""
        kf = ep.kind_fields(config, episode_id)
        custom = playlists.hashtags_for(kf["base_episode_id"] or episode_id)
        if custom is not None:
            return None, tuple(custom)
        fields = _post_header_fields(episode_id)
        return (fields.get("series") if fields else None), tuple(config.web.hashtags)

    def _post_image_sources() -> dict[str, str]:
        try:
            lines = (config.post.image_dir / "sources.tsv").read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        out = {}
        for line in lines:
            name, _, url = line.partition("\t")
            if name and url:
                out[name] = url
        return out

    def _post_entry_view(entry: dict, *, ep_src, title: str | None, header_fields: dict | None,
                         hashtags_list: list[str]) -> dict:
        stale = post_stage.compute_stale(ep_src, entry) if ep_src is not None else True
        image = entry["image"]
        image_missing = image is not None and post_images.resolve(config.post.image_dir, image) is None
        text = post_logic.compose_copy_text(title=title, paragraphs=entry["paragraphs"], header_fields=header_fields,
                                            link=entry["link"], hashtags=hashtags_list)
        # P3 amendment: "ít dấu câu" label (Q4) — an "ai" post whose punctuation is too sparse to be useful,
        # even though the projection matched the source words well enough to not fall back to "raw".
        low_punctuation = entry["origin"] == post_store.AI \
            and post_validate.marks_per_100_words(entry["paragraphs"]) < 4
        return {"clip_id": entry["clip_id"], "paragraphs": list(entry["paragraphs"]), "origin": entry["origin"],
                "stale": stale, "image": image, "image_missing": image_missing, "link": entry["link"],
                "posted": entry["posted_at"] is not None, "posted_at": entry["posted_at"], "text": text,
                "chars": len(text), "low_punctuation": low_punctuation}

    @app.get("/api/episodes/{episode_id}/posts")
    def api_posts(episode_id: str):
        """P7/P9: every stored post of the episode (read-only, allowed while a job runs); ``post_error`` when
        ``posts.json`` is broken (not overwritten)."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        with post_lock:
            try:
                doc = post_store.read_posts(_posts_path(episode_id), episode_id)
                post_error = None
            except post_store.PostsError as exc:
                doc, post_error = post_store.empty_posts(episode_id), str(exc)
        try:
            ep_src = post_source.load(episode_id, config)
        except post_source.PostSourceError:
            ep_src = None
        titles_by_clip: dict[str, str | None] = {}
        try:
            titles_by_clip = {c["clip_id"]: c["title"] for c in list_titles(episode_id, config)["clips"]}
        except ReviewError:
            pass
        header_fields = _post_header_fields(episode_id)
        series, tags = _post_series_and_tags(episode_id)
        hashtags_list = review_hashtags(series, tags)
        posts = [_post_entry_view(e, ep_src=ep_src, title=titles_by_clip.get(e["clip_id"]),
                                  header_fields=header_fields, hashtags_list=hashtags_list) for e in doc["posts"]]
        return {"posts": posts, "post_error": post_error}

    def _post_clips(body: PostComposeIn) -> "list[str] | str | JSONResponse":
        raw = body.clips
        if raw in ("all", "auto"):  # "auto": CP8.16 R4
            return raw
        if not isinstance(raw, list) or not raw or not all(isinstance(c, str) and ep.valid_clip_id(c) for c in raw):
            return JSONResponse({"detail": 'clips phải là "all", "auto" hoặc một danh sách clip_id không rỗng'},
                                status_code=422)
        return raw

    @app.post("/api/episodes/{episode_id}/posts")
    def api_posts_compose(episode_id: str, body: PostComposeIn):
        """P1 (CP8.16 R3): soạn / soạn lại bài (lane ai) -> 202 job (job soạn bài đang đợi -> trả job đó); 409 khi
        episode đang có job ``pipeline`` (không còn 503 Ollama, FIX-ollama-wait O4). Không bị khóa bởi job render / add."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        clips = _post_clips(body)
        if isinstance(clips, JSONResponse):
            return clips
        with submit_lock:  # FIX-ollama-wait O4: no preflight in the request; the ai lane waits for the GPU
            current = runner.latest(episode_id)
            if current is not None and current.active and current.kind == KIND_PIPELINE:
                return JSONResponse({"detail": "episode đang chạy pipeline; soạn bài sau khi job xong",
                                     "job": _job_view(current)}, status_code=409)
            job, _created = runner.submit(episode_id, KIND_POST,
                                          post_compose_target(config, clips, compose=post_compose,
                                                              preflight=post_preflight, lock=post_lock))
        log.info("web: soạn bài %s [%s] -> job %s", clips if isinstance(clips, str) else ",".join(clips), episode_id,
                 job.id)
        return JSONResponse({"job": _job_view(job)}, status_code=202)

    def _learn_corrections(episode_id: str, clip: str, old: list[str], new: list[str], now: str) -> int | None:
        """CP8.18 D2/D6 (caller holds ``post_lock``): log the edit and record the proposals; any dictionary / IO
        failure is a warning and ``None``, never a failure of the post save."""
        path = config.post.corrections_path
        try:
            proposals, words, changed = post_corrections.extract(old, new)
            post_corrections.append_edit_log(path, at=now, episode_id=episode_id, clip_id=clip, words=words,
                                             changed_words=changed)
            if not proposals:
                return 0
            cdoc = post_corrections.load(path)
            post_corrections.record(cdoc, proposals, episode_id, clip, now)
            post_corrections.save(path, cdoc)
            return len(proposals)
        except (post_corrections.CorrectionsError, OSError) as exc:
            log.warning("web: từ điển sửa lỗi: %s", exc)
            return None

    @app.put("/api/episodes/{episode_id}/posts/{clip}")
    def api_posts_edit(episode_id: str, clip: str, body: PostEditIn):
        """P9: sửa tay ``paragraphs`` (-> ``origin: manual``) / đổi ``image`` / sửa ``link`` (P6); được cả khi job
        đang chạy (P7); cần đã có bài (bấm "Soạn bài" trước)."""
        if (bad := _check_clip(episode_id, clip)) is not None:
            return bad
        given = body.model_fields_set & {"paragraphs", "image", "link"}
        if not given:
            return JSONResponse({"detail": "cần ít nhất một trong: paragraphs, image, link"}, status_code=422)
        changes: dict = {}
        if "paragraphs" in given:
            paragraphs = body.paragraphs
            if not isinstance(paragraphs, list) or not paragraphs \
                    or not all(isinstance(p, str) and p.strip() for p in paragraphs):
                return JSONResponse({"detail": "paragraphs phải là mảng chuỗi không rỗng"}, status_code=422)
            changes["paragraphs"] = [p.strip() for p in paragraphs]
            changes["origin"] = post_store.MANUAL
        if "image" in given:
            if body.image is None or post_images.resolve(config.post.image_dir, body.image) is None:
                return JSONResponse({"detail": "không có ảnh này trong thư viện"}, status_code=404)
            changes["image"] = body.image
        if "link" in given:
            try:
                changes["link"] = post_logic.normalize_link(body.link)
            except post_logic.LinkError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, episode_id)]
        proposed: int | None = None
        with post_lock:
            try:
                doc = post_store.read_posts(_posts_path(episode_id), episode_id)
                old_paragraphs = post_store.find(doc, clip)["paragraphs"] if post_store.find(doc, clip) else None
                now = _post_now()
                doc = post_store.with_fields(doc, order, clip, changes, now=now)
            except post_store.PostsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            post_store.write(_posts_path(episode_id), doc)
            if "paragraphs" in given and old_paragraphs is not None:
                proposed = _learn_corrections(episode_id, clip, old_paragraphs, changes["paragraphs"], now)
        entry = post_store.find(doc, clip)
        try:
            ep_src = post_source.load(episode_id, config)
        except post_source.PostSourceError:
            ep_src = None
        title = None
        try:
            title = next((c["title"] for c in list_titles(episode_id, config)["clips"] if c["clip_id"] == clip), None)
        except ReviewError:
            pass
        header_fields = _post_header_fields(episode_id)
        series, tags = _post_series_and_tags(episode_id)
        log.info("web: post %s [%s] sửa %s", clip, episode_id, ", ".join(sorted(given)))
        view = _post_entry_view(entry, ep_src=ep_src, title=title, header_fields=header_fields,
                                hashtags_list=review_hashtags(series, tags))
        if "paragraphs" in given:
            view["proposed"] = proposed  # CP8.18 D5 (null: the dictionary failed, the post was still saved)
        return view

    @app.post("/api/episodes/{episode_id}/posts/{clip}/posted")
    def api_posts_posted(episode_id: str, clip: str, body: PublishedIn):
        """P8: tick / untick "Đã đăng bài" — độc lập với "Đã đăng" Short (``publish.json``); được cả khi job
        đang chạy."""
        if (bad := _check_clip(episode_id, clip)) is not None:
            return bad
        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, episode_id)]
        with post_lock:
            try:
                doc = post_store.read_posts(_posts_path(episode_id), episode_id)
                doc = post_store.with_posted(doc, order, clip, body.value, now=_post_now())
            except post_store.PostsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            post_store.write(_posts_path(episode_id), doc)
        entry = post_store.find(doc, clip)
        log.info("web: post %s [%s] %s \"Đã đăng bài\"", clip, episode_id, "tick" if body.value else "untick")
        return {"clip_id": clip, "posted": entry["posted_at"] is not None, "posted_at": entry["posted_at"]}

    # --- CP8.18: post correction dictionary (D5) ------------------------------------------------------------

    def _corr_load() -> dict | JSONResponse:
        try:
            return post_corrections.load(config.post.corrections_path)
        except post_corrections.CorrectionsError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    def _corr_apply(rule: dict) -> dict:
        return post_corrections.apply_rule_to_posts(Path(config.workspace.dir), rule, post_lock, _post_now())

    @app.get("/api/post-corrections")
    def api_corrections():
        with post_lock:
            try:
                doc, error = post_corrections.load(config.post.corrections_path), None
            except post_corrections.CorrectionsError as exc:
                doc, error = post_corrections.empty_doc(), str(exc)
        return {"rules": doc["rules"], "stats": post_corrections.stats(config.post.corrections_path),
                "error": error}

    @app.post("/api/post-corrections")
    def api_corrections_add(body: CorrectionIn):
        now = _post_now()
        with post_lock:
            doc = _corr_load()
            if isinstance(doc, JSONResponse):
                return doc
            try:
                src, dst = post_corrections.validate_phrases(body.from_, body.to)
                nums = [int(r["id"][1:]) for r in doc["rules"] if r["id"][1:].isdigit()]
                rule = {"id": f"r{max(nums, default=0) + 1:04d}", "from": src, "to": dst,
                        "status": post_corrections.APPROVED, "count": 0, "examples": [], "created_at": now,
                        "updated_at": now}
                post_corrections.check_unique_approved(doc, rule)
                doc["rules"].append(rule)
                post_corrections.save(config.post.corrections_path, doc)
            except post_corrections.CorrectionsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        applied = _corr_apply(rule)
        log.info("web: luật sửa lỗi %s thêm tay: %s", rule["id"], applied)
        return {"rule": rule, "applied": applied}

    @app.put("/api/post-corrections/{rule_id}")
    def api_corrections_edit(rule_id: str, body: CorrectionEditIn):
        now = _post_now()
        with post_lock:
            doc = _corr_load()
            if isinstance(doc, JSONResponse):
                return doc
            rule = post_corrections.find_rule(doc, rule_id)
            if rule is None:
                return JSONResponse({"detail": "không có luật này"}, status_code=404)
            given = body.model_fields_set & {"status", "from_", "to"}
            if not given:
                return JSONResponse({"detail": "cần ít nhất một trong: status, from, to"}, status_code=422)
            try:
                src, dst = post_corrections.validate_phrases(
                    body.from_ if "from_" in given else rule["from"], body.to if "to" in given else rule["to"])
                status = body.status if body.status is not None else rule["status"]
                new = {**rule, "from": src, "to": dst, "status": status, "updated_at": now}
                post_corrections.check_unique_approved(doc, new)
                doc["rules"] = [new if r["id"] == rule_id else r for r in doc["rules"]]
                post_corrections.save(config.post.corrections_path, doc)
            except post_corrections.CorrectionsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        out: dict = {"rule": new}
        if new["status"] == post_corrections.APPROVED and rule["status"] != post_corrections.APPROVED:
            out["applied"] = _corr_apply(new)
            log.info("web: luật sửa lỗi %s đã duyệt: %s", rule_id, out["applied"])
        return out

    @app.delete("/api/post-corrections/{rule_id}")
    def api_corrections_delete(rule_id: str):
        with post_lock:
            doc = _corr_load()
            if isinstance(doc, JSONResponse):
                return doc
            if post_corrections.find_rule(doc, rule_id) is None:
                return JSONResponse({"detail": "không có luật này"}, status_code=404)
            doc["rules"] = [r for r in doc["rules"] if r["id"] != rule_id]
            try:
                post_corrections.save(config.post.corrections_path, doc)
            except post_corrections.CorrectionsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        return {"deleted": rule_id}

    # --- CP8.15: image library (P5, P5a, P5b) ---------------------------------------------------------------

    @app.get("/api/post-images")
    def api_post_images():
        infos = post_images.list_images(config.post.image_dir)
        used = post_images.usage_counts(Path(config.workspace.dir))
        sources = _post_image_sources()
        return {"images": [{"name": i.name, "width": i.width, "height": i.height, "bytes": i.bytes,
                            "used": used.get(i.name, 0), "source": sources.get(i.name)} for i in infos],
                "image_sources": list(config.post.image_sources)}

    @app.post("/api/post-images")
    async def api_post_images_upload(request: Request, name: str = ""):
        """P5a: raw body (``Content-Type: image/jpeg`` | ``image/png``), original name in ``?name=``."""
        if not name.strip():
            return JSONResponse({"detail": "cần tên ảnh gốc (?name=...)"}, status_code=422)
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > post_images.MAX_BYTES:
            return JSONResponse({"detail": f"ảnh lớn hơn {post_images.MAX_BYTES // (1024 * 1024)} MB"},
                                status_code=422)
        body = await request.body()
        if len(body) > post_images.MAX_BYTES:
            return JSONResponse({"detail": f"ảnh lớn hơn {post_images.MAX_BYTES // (1024 * 1024)} MB"},
                                status_code=422)
        try:
            img_name, duplicate = post_images.save_image(config.post.image_dir, body, original_name=name)
        except post_images.ImageError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        log.info("web: post-images: %s \"%s\" (%d bytes)%s", "upload" if not duplicate else "upload (trùng)",
                 img_name, len(body), "" if not duplicate else ", ảnh có sẵn")
        return JSONResponse({"image": img_name, "duplicate": duplicate}, status_code=200)

    @app.delete("/api/post-images/{name}")
    def api_post_images_delete(name: str):
        path = post_images.resolve(config.post.image_dir, name)
        if path is None:
            return JSONResponse({"detail": "không có ảnh này"}, status_code=404)
        used = post_images.usage_counts(Path(config.workspace.dir)).get(name, 0)
        post_images.delete_image(config.post.image_dir, name)
        log.info("web: post-images: xóa %s (đang dùng ở %d bài)", name, used)
        return {"used": used}

    @app.post("/api/post-images/search")
    def api_post_images_search(body: PostImageSearchIn):
        """P5b: tìm ảnh từ một link -> job nền (lane prepare, không cần Ollama); 409 khi đang tìm."""
        with submit_lock:
            current = runner.latest(POST_IMAGES_KEY)
            if current is not None and current.active:
                return JSONResponse({"detail": "đang tìm ảnh; đợi xong rồi tìm tiếp",
                                     "job": _job_view(current)}, status_code=409)
            job, _created = runner.submit(POST_IMAGES_KEY, KIND_POST_SEARCH,
                                          image_search_target(config, body.url, search=post_search))
        log.info("web: post-images: tìm ảnh %s -> job %s", body.url, job.id)
        return JSONResponse({"job": _job_view(job)}, status_code=202)

    @app.get("/api/post-images/search/{job_id}")
    def api_post_images_search_status(job_id: str):
        job = runner.job(job_id)
        if job is None or job.episode_id != POST_IMAGES_KEY:
            return JSONResponse({"detail": "không có job này"}, status_code=404)
        result = getattr(job.target, "result", None)
        found = len(result.added) + len(result.duplicate) if result is not None else 0
        return {"status": job.status, "found": found, "added": list(result.added) if result else [],
                "duplicate": list(result.duplicate) if result else [],
                "skipped": dict(result.skipped) if result else {}}

    @app.get("/files/post-images/{name}")
    def post_image_file(name: str, download: str | None = None):
        path = post_images.resolve(config.post.image_dir, name)
        if path is None:
            return JSONResponse({"detail": "không có ảnh này"}, status_code=404)
        headers = {"Cache-Control": "private, no-cache"}
        if download is not None:
            headers["Content-Disposition"] = content_disposition(name)
        return FileResponse(path, media_type=post_images.CONTENT_TYPES[Path(name).suffix.lower()], headers=headers)

    @app.delete("/api/episodes/{episode_id}")
    def api_episode_delete(episode_id: str):
        """X3: delete work/<id>/ and output/<id>/ (cannot be undone); 409 while a job of the episode is
        queued/running; unknown / invalid id -> 404."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with submit_lock:
            current = runner.latest(episode_id)
            if current is None or not current.active:
                current = runner.latest_post(episode_id)  # CP8.16 R3: a compose job also blocks the deletion
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
            playlists.invalidate(episode_id)
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

    def _mark_downloaded(episode_id: str, clip_ids: list[str]) -> None:
        """CP8.7 (bổ sung HUMAN LEAD 2026-09-27): a download ticks "Đã đăng" (current file); never blocks it."""
        with publish_lock:
            try:
                changed = mark_downloaded(episode_id, config, clip_ids)
            except (ReviewError, OSError) as exc:
                log.warning("web: download of %s [%s]: not marked as published: %s", ",".join(clip_ids),
                            episode_id, exc)
                return
        if changed:
            playlists.invalidate(episode_id)
            storage.invalidate()
            log.info("web: download marked %s [%s] as published", ",".join(changed), episode_id)

    # --- files -------------------------------------------------------------------------------------

    @app.get("/files/{episode_id}/{name}")
    def files(episode_id: str, name: str, download: str | None = None):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        if name == "shorts.zip":
            items = ep.short_files(config, episode_id)
            if not items:
                return JSONResponse({"detail": "chưa có Short nào"}, status_code=404)
            # CP8.17 D3: a zip never ticks "Đã đăng" (only the single "Tải về" of a Short does)
            return StreamingResponse(
                _zip_stream(items), media_type="application/zip",
                headers={"Content-Disposition": content_disposition(ep.zip_download_name(config, episode_id)),
                         "Cache-Control": "no-store"})
        if name == "all.zip":  # CP8.17 D5: Shorts/ + KhaiThị/ of one video in a single zip (no tick, D3)
            both = ep.all_zip(config, episode_id)
            if both is None:
                return JSONResponse({"detail": "cần có cả Short và khai thị đã dựng"}, status_code=404)
            items, zip_file_name = both
            return StreamingResponse(
                _zip_stream(items), media_type="application/zip",
                headers={"Content-Disposition": content_disposition(zip_file_name), "Cache-Control": "no-store"})
        if name == "source.mp4":  # CP9 C7: "Nghe thử" around a cut point (Range; never ticks, never a download)
            found_src = ep.source_file(config, episode_id)
            if found_src is None:
                return JSONResponse({"detail": "không có video nguồn"}, status_code=404)
            return FileResponse(found_src, media_type=SOURCE_TYPES.get(found_src.suffix.lower(),
                                                                       "application/octet-stream"),
                                headers={"Cache-Control": "private, no-cache"})
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
            _mark_downloaded(episode_id, [clip_id])  # plain playback (no download=1) never ticks
        return FileResponse(path, media_type="video/mp4", headers=headers)

    return app
