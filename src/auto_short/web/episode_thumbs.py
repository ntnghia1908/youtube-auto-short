"""Authenticated episode thumbnail grid, render jobs and verified downloads (PKG2)."""
from __future__ import annotations

import io
import hashlib
import re
import threading
import zipfile
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, StrictStr

from ..packaging import PackageError, cover, cover_suggest, episode, khaithi_thumbs
from ..review.names import clean_part, content_disposition, short_code, truncate_utf8
from ..titling.logic import TitlingError
from ..render.stage import RenderError
from ..render.text import TextError
from .jobs import RENDER, JobFailed, Step
from .theme_plan import job_view, response, safe

KIND = "episode_thumbs"


def render_key(pid):
    return f"episode_thumbs:{pid}"


class Unavailable(Exception):
    pass


class ThumbnailTarget:
    def __init__(self, service, pid):
        self.service, self.pid = service, pid

    def __call__(self, job):
        job.stage = KIND
        def progress(result):
            job.summary = f"Đã dựng {result['built']}, dùng lại {result['reused']}, bỏ qua {len(result['skipped'])} tập"
            kt = result.get("khaithi")
            if kt:
                job.summary += f"; khai thị: {kt['built']} ảnh mới, {kt['reused']} ảnh dùng lại"
                if kt["skipped"]:
                    job.summary += "; " + "; ".join(sorted({safe(e["reason"]) for e in kt["skipped"]}))
        try:
            self.result = episode.build_playlist(self.service.config, self.pid, run=self.service.media_runner,
                                                  progress=progress)
        except (PackageError, OSError, ValueError, KeyError, TypeError) as exc:
            raise JobFailed(safe(str(exc))) from exc
        job.stage = None

    def lane_steps(self):
        return [Step(RENDER, self)]

    def spec(self):
        return dict(playlist_id=self.pid)


class EpisodeThumbs:
    codex_lock = threading.Lock()  # One Codex CLI job across all service instances.

    def __init__(self, plans, *, media_runner=None, codex_runner=None):
        self.plans, self.config, self.runner = plans, plans.config, plans.runner
        self.media_runner = media_runner
        self.lock = threading.RLock()
        self.codex_runner = codex_runner
        self.suggest_thread = None
        self.suggest_cancel = threading.Event()
        self.suggest_active = None
        cover_suggest.recover(self.config)

    def checked(self, pid):
        return self.plans.checked(pid)

    def mutable(self, pid):
        job = self.runner.latest(render_key(pid))
        if job is not None and job.active:
            raise Unavailable("đang dựng thumbnail; chờ hoàn tất")

    def render(self, pid):
        job = self.runner.latest(render_key(pid))
        if job is not None and job.active:
            return job, False
        return self.runner.submit(render_key(pid), KIND, ThumbnailTarget(self, pid))

    def suggest(self, pid, *, notes="", run_id=None, selected=None,
                parent_run=None, feedback=None, mode=None, reference=None):
        if not self.codex_lock.acquire(blocking=False):
            raise Unavailable("đang có một lượt Codex chạy; chờ hoàn tất hoặc hủy")
        try:
            self.mutable(pid)
            problem = cover_suggest.available(self.config)
            if problem:
                raise cover_suggest.MissingCodex(problem)
            if parent_run is not None:
                doc = cover_suggest.create_feedback(self.config, pid, parent_run, feedback, mode, reference)
            else:
                doc = (cover_suggest.select(self.config, pid, run_id, selected) if run_id else
                       cover_suggest.create(self.config, pid, notes))
            self.suggest_cancel = threading.Event()
            self.suggest_active = (pid, doc["run_id"])
            def work():
                try:
                    cover_suggest.execute(self.config, pid, doc["run_id"], runner=self.codex_runner,
                                          media_runner=self.media_runner, cancel=self.suggest_cancel)
                finally:
                    self.suggest_active = None
                    self.codex_lock.release()
            self.suggest_thread = threading.Thread(target=work, name="cover-suggest", daemon=True)
            self.suggest_thread.start()
            return doc
        except BaseException:
            self.codex_lock.release()
            raise

    def cancel(self, pid, run_id):
        doc = cover_suggest.state(self.config, pid, run_id)
        if self.suggest_active == (pid, run_id):
            self.suggest_cancel.set()
        return doc

    def install(self, pid, run_id):
        self.mutable(pid)
        if self.suggest_active:
            raise Unavailable("chờ lượt gợi ý hoàn tất")
        return cover_suggest.install(self.config, pid, run_id, run=self.media_runner)

    def suggestion_view(self, pid, run_id):
        doc = safe(cover_suggest.state(self.config, pid, run_id))
        prefix = f"/api/playlists/{pid}/thumbs/suggest/{run_id}/images/"
        for entry in doc["options"].values():
            entry["preview_url"] = prefix + entry["preview"]
        for entry in doc.get("previews", []):
            entry["preview_url"] = prefix + entry["file"]
        return doc

    def suggestion_image(self, pid, run_id, name):
        if not cover_suggest.IMAGE_NAME.fullmatch(name):
            raise PackageError("tên ảnh không hợp lệ")
        doc = cover_suggest.state(self.config, pid, run_id)
        allowed = set(doc["options"]) | set(doc["variants"])
        allowed.update(e["preview"] for e in doc["options"].values())
        allowed.update(e["file"] for e in doc.get("previews", []))
        if name not in allowed:
            raise PackageError("không có ảnh gợi ý này")
        path = episode._no_symlinks(cover_suggest.directory(self.config, pid, run_id) / name)
        if not path.is_file():
            raise PackageError("không có ảnh gợi ý này")
        return path

    def rows(self, pid):
        rows = []
        settings = episode.read_settings(self.config, pid)
        seen = set()
        for entry in episode.playlist(self.config, pid)["entries"]:
            ident = entry.get("video_id") if isinstance(entry, dict) else None
            if not isinstance(ident, str) or ident in seen:
                continue
            seen.add(ident)
            doc, files, reason = None, {}, None
            try:
                doc = episode.read(self.config, ident)
                fields = episode.context(self.config, ident, settings)[0]
                files = episode.valid_files(self.config, ident, doc, pid=pid)
                reason = (doc or {}).get("skipped_reason")
                if not files and reason is None:
                    reason = "chưa dựng hoặc đầu vào đã đổi — dựng lại"
            except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError) as exc:
                fields = {}
                reason = str(exc)
            row = safe(dict(video_id=ident, episode=fields.get("episode") or entry.get("episode"),
                            header=fields, asset_id=(doc or {}).get("asset_id"),
                            skipped_reason=reason, files=files))
            # safe() redacts absolute paths, so attach application URLs afterwards.
            for shape, file in row["files"].items():
                url = f"/files/episodes/{ident}/thumbs/{file['file']}"
                file.update(preview_url=url + "?inline=1", download_url=url)
            rows.append(row)
        return rows

    @staticmethod
    def progress(rows):
        """Aggregate for the page so the client does not count: files per shape, episodes without any file by reason."""
        reasons = {}
        for row in rows:
            if not row["files"]:
                reason = row["skipped_reason"] or "không rõ lý do"
                reasons[reason] = reasons.get(reason, 0) + 1
        return dict(total=len(rows), landscape=sum("landscape" in row["files"] for row in rows),
                    vertical=sum("vertical" in row["files"] for row in rows),
                    with_any=sum(bool(row["files"]) for row in rows), skipped=sum(reasons.values()),
                    skipped_by_reason=reasons)

    def view(self, pid):
        doc = episode.playlist(self.config, pid)
        rows = self.rows(pid)
        covers = cover.current(self.config, pid)
        cover_view = {shape: dict(sha256=entry["sha256"], preview_url=f"/api/playlists/{pid}/thumbs/covers/{shape}")
                      for shape, entry in covers.items()}
        folder = cover_suggest.directory(self.config, pid)
        runs = sorted((p for p in folder.iterdir() if cover_suggest.RUN_ID.fullmatch(p.name)
                       and not p.is_symlink() and p.is_dir()), key=lambda p: p.stat().st_mtime_ns, reverse=True) if folder.exists() else []
        latest = self.suggestion_view(pid, runs[0].name) if runs else None
        return dict(playlist_id=pid, series=safe(doc.get("series") or doc.get("title") or pid),
                    episodes=rows, progress=self.progress(rows), covers=cover_view, suggestion=latest,
                    codex_unavailable=cover_suggest.available(self.config),
                    job=job_view(self.runner.latest(render_key(pid))), zip_url=f"/files/playlists/{pid}/thumbs.zip")

    def archive(self, pid):
        content = io.BytesIO()
        series = episode.playlist(self.config, pid).get("series")
        names = set()
        with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_STORED) as archive:
            for row in self.rows(pid):
                if not row["files"]:
                    continue
                ident = row["video_id"]
                doc = episode.read(self.config, ident)
                for shape, entry in episode.valid_files(self.config, ident, doc, pid=pid).items():
                    number = int(doc["header"]["episode"])
                    name = f"T{number:03d}_{'ngang' if shape == 'landscape' else 'doc'}.jpg"
                    if name in names:
                        continue
                    # Read bytes and check again: never zip a file changed since the view audit.
                    try:
                        data = (episode.directory(self.config, ident) / entry["file"]).read_bytes()
                    except OSError:
                        continue
                    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                        continue
                    archive.writestr(name, data)
                    names.add(name)
                    series = series or doc["header"].get("series")
            for item in episode.playlist(self.config, pid)["entries"]:
                if not isinstance(item, dict) or not isinstance(item.get("video_id"), str):
                    continue
                ident = item["video_id"] + ".kt"
                for cid, files in khaithi_thumbs.valid_files(self.config, ident, pid=pid).items():
                    number = episode.header(self.config, ident[:-3])["episode"]
                    numbers = khaithi_thumbs.read(self.config, ident)["clip_numbers"]
                    code = short_code(number, numbers[cid], len(numbers), khaithi=True)
                    for shape, entry in files.items():
                        name = f"khai-thi/{code}_{shape}.jpg"
                        if name in names:
                            continue
                        try:
                            data = (episode._no_symlinks(khaithi_thumbs.directory(self.config, ident) / entry["file"])).read_bytes()
                        except (OSError, PackageError):
                            continue
                        if hashlib.sha256(data).hexdigest() == entry["sha256"]:
                            archive.writestr(name, data)
                            names.add(name)
        filename = (truncate_utf8(clean_part(series or pid), 80) or pid) + "_Thumbnail.zip"
        return content.getvalue(), filename


class SuggestIn(BaseModel):
    notes: StrictStr = Field(default="", max_length=200)


class SelectIn(BaseModel):
    name: StrictStr = Field(max_length=40)


def register(app: FastAPI, service: EpisodeThumbs):
    @app.middleware("http")
    async def no_store(request: Request, call_next):
        result = await call_next(request)
        if re.fullmatch(r"/(?:api/playlists|files/playlists|files/episodes)/[^/]+/thumbs(?:[/.].*)?", request.url.path):
            result.headers["Cache-Control"] = "no-store"
        return result

    def invoke(pid, action, *, write=False):
        error = service.checked(pid)
        if error is not None:
            return error
        try:
            if write:
                with service.lock:
                    return action()
            return action()
        except cover_suggest.MissingCodex as exc:
            return response({"detail": str(exc)}, 503)
        except (Unavailable, cover_suggest.Busy) as exc:
            return response({"detail": str(exc)}, 409)
        except (PackageError, TextError, RenderError) as exc:
            return response({"detail": str(exc)}, 400)
        except (OSError, ValueError, KeyError, TypeError):
            return response({"detail": "dữ liệu thumbnail không hợp lệ"}, 422)

    def submitted(result):
        job, created = result
        return response(dict(job=job_view(job), created=created), 202 if created else 200)

    @app.get("/playlists/{pid}/thumbs")
    def page(pid: str):
        return invoke(pid, lambda: FileResponse(Path(__file__).parent / "static" / "thumbs.html",
                                               headers={"Cache-Control": "no-store"}))

    @app.get("/api/playlists/{pid}/thumbs")
    def get(pid: str):
        return invoke(pid, lambda: JSONResponse(service.view(pid), headers={"Cache-Control": "no-store"}))

    @app.post("/api/playlists/{pid}/thumbs")
    def build(pid: str):
        return invoke(pid, lambda: submitted(service.render(pid)), write=True)

    @app.post("/api/playlists/{pid}/thumbs/suggest")
    def suggest(pid: str, body: SuggestIn):
        return invoke(pid, lambda: response(service.suggest(pid, notes=body.notes), 202), write=True)

    @app.get("/api/playlists/{pid}/thumbs/suggest/{run_id}")
    def suggestion(pid: str, run_id: str):
        # suggestion_view redacts artifact data before attaching trusted application URLs.
        return invoke(pid, lambda: JSONResponse(service.suggestion_view(pid, run_id),
                                               headers={"Cache-Control": "no-store"}))

    @app.post("/api/playlists/{pid}/thumbs/suggest/{run_id}/select")
    def select(pid: str, run_id: str, body: SelectIn):
        return invoke(pid, lambda: response(service.suggest(pid, run_id=run_id, selected=body.name), 202), write=True)

    @app.post("/api/playlists/{pid}/thumbs/suggest/{run_id}/feedback")
    def feedback(pid: str, run_id: str, body: object = Body(default=None)):
        def action():
            if not isinstance(body, dict):
                raise PackageError("dữ liệu góp ý không hợp lệ")
            return response(service.suggest(pid, parent_run=run_id, feedback=body.get("feedback"),
                                            mode=body.get("mode"), reference=body.get("reference")), 202)
        return invoke(pid, action, write=True)

    @app.post("/api/playlists/{pid}/thumbs/suggest/{run_id}/cancel")
    def cancel(pid: str, run_id: str):
        return invoke(pid, lambda: response(service.cancel(pid, run_id)), write=True)

    @app.post("/api/playlists/{pid}/thumbs/suggest/{run_id}/install")
    def install(pid: str, run_id: str):
        return invoke(pid, lambda: response(service.install(pid, run_id)), write=True)

    @app.get("/api/playlists/{pid}/thumbs/suggest/{run_id}/images/{name}")
    def suggested_image(pid: str, run_id: str, name: str):
        return invoke(pid, lambda: FileResponse(service.suggestion_image(pid, run_id, name),
                                               headers={"Cache-Control": "no-store"}))

    @app.get("/api/playlists/{pid}/thumbs/covers/{shape}")
    def current_image(pid: str, shape: str):
        def action():
            entry = cover.current(service.config, pid).get(shape)
            if entry is None:
                return response({"detail": "chưa có ảnh bìa khổ này"}, 404)
            return FileResponse(episode._no_symlinks(cover.directory(service.config, pid) / entry["file"]),
                                headers={"Cache-Control": "no-store"})
        return invoke(pid, action)

    @app.get("/files/playlists/{pid}/thumbs.zip")
    def archive(pid: str):
        def action():
            data, name = service.archive(pid)
            return Response(data, media_type="application/zip", headers={"Cache-Control": "no-store",
                                                                        "Content-Disposition": content_disposition(name)})
        return invoke(pid, action)

    @app.get("/files/episodes/{video_id}/thumbs/{name}")
    def download(video_id: str, name: str, inline: int = 0):
        missing = lambda: response({"detail": "không có file này"}, 404)
        if video_id.endswith(".kt"):
            try:
                doc = khaithi_thumbs.read(service.config, video_id)
                for cid, files in khaithi_thumbs.valid_files(service.config, video_id).items():
                    for shape, entry in files.items():
                        if name in (entry["file"], f"{cid}-{shape}.jpg"):
                            numbers = doc["clip_numbers"]
                            code = short_code(doc["header"]["episode"], numbers[cid], len(numbers), khaithi=True)
                            filename = f"{code}_{shape}.jpg"
                            headers = {"Cache-Control": "no-store"}
                            if inline != 1:
                                headers["Content-Disposition"] = content_disposition(filename)
                            return FileResponse(episode._no_symlinks(khaithi_thumbs.directory(service.config, video_id) / entry["file"]),
                                                media_type="image/jpeg", headers=headers)
            except (PackageError, OSError, ValueError, KeyError, TypeError):
                pass
            return missing()
        if not episode.FILE_NAME.fullmatch(name) and name not in ("landscape.jpg", "vertical.jpg"):
            return missing()
        try:
            doc = episode.read(service.config, video_id)
            files = episode.valid_files(service.config, video_id, doc)
            selected = next(((shape, entry) for shape, entry in files.items()
                             if entry["file"] == name or name == shape + ".jpg"), None)
            if selected is None:
                return missing()
            shape, entry = selected
            filename = f"T{int(doc['header']['episode']):03d}_{'ngang' if shape == 'landscape' else 'doc'}.jpg"
            headers = {"Cache-Control": "no-store"}
            if inline != 1:
                headers["Content-Disposition"] = content_disposition(filename)
            return FileResponse(episode.directory(service.config, video_id) / entry["file"],
                                media_type="image/jpeg", headers=headers)
        except (PackageError, OSError, ValueError, KeyError, TypeError):
            return missing()
