"""Authenticated episode thumbnail grid, render jobs and verified downloads (PKG2)."""
from __future__ import annotations

import io
import base64
import hashlib
import re
import threading
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, StrictStr

from ..packaging import PackageError, assets, episode
from ..review.names import clean_part, content_disposition, truncate_utf8
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
    def __init__(self, plans, *, media_runner=None):
        self.plans, self.config, self.runner = plans, plans.config, plans.runner
        self.media_runner = media_runner
        self.lock = threading.RLock()

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

    def save_settings(self, pid, settings):
        self.mutable(pid)
        return episode.write_settings(self.config, pid, settings)

    def preview(self, pid, settings=None):
        self.mutable(pid)
        files = episode.preview(self.config, pid, settings=settings, run=self.media_runner)
        return {"files": {shape: {"preview_url": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")}
                          for shape, data in files.items()}}

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
                fields, _, _, _ = episode.context(self.config, ident, settings)
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

    def view(self, pid):
        doc = episode.playlist(self.config, pid)
        images = episode.images(self.config)
        images.sort(key=lambda a: (0, int(a["tags"][0]), a["id"]) if a["tags"] and a["tags"][0].isdecimal()
                    else (1, 0, a["id"]))
        images = safe(images)
        for number, asset in enumerate(images, 1):
            asset.update(number=asset["tags"][0] if asset["tags"] else number, preview_url=f"/files/playlists/{pid}/thumbs/assets/{asset['id']}")
        return dict(playlist_id=pid, series=safe(doc.get("series") or doc.get("title") or pid),
                    episodes=self.rows(pid), assets=images, settings=safe(episode.read_settings(self.config, pid)),
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
        filename = (truncate_utf8(clean_part(series or pid), 80) or pid) + "_Thumbnail.zip"
        return content.getvalue(), filename


class SettingsIn(BaseModel):
    style: Literal["A", "B", "C"] = "A"
    asset_id: StrictStr | None = Field(default=None, max_length=64)
    focus_x: float = Field(default=0.5, ge=0, le=1, strict=True)
    title_lines: list[StrictStr] = Field(min_length=1, max_length=3)
    credit: StrictStr = Field(default="", max_length=60)


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
        except Unavailable as exc:
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

    @app.get("/api/playlists/{pid}/thumbs/settings")
    def settings(pid: str):
        return invoke(pid, lambda: response(episode.read_settings(service.config, pid)))

    @app.put("/api/playlists/{pid}/thumbs/settings")
    def edit(pid: str, body: SettingsIn):
        return invoke(pid, lambda: response(service.save_settings(pid, body.model_dump())), write=True)

    @app.post("/api/playlists/{pid}/thumbs/preview")
    def preview(pid: str, body: SettingsIn | None = None):
        return invoke(pid, lambda: JSONResponse(service.preview(pid, body.model_dump() if body else None),
                                               headers={"Cache-Control": "no-store"}), write=True)

    @app.get("/files/playlists/{pid}/thumbs/assets/{asset_id}")
    def asset_image(pid: str, asset_id: str):
        def action():
            _, path = assets.usable(service.config.packaging.asset_dir, asset_id, kind="image")
            return FileResponse(path, headers={"Cache-Control": "no-store"})
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
