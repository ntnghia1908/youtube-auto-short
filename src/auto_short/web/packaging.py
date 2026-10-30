"""THUMB2 authenticated compilation thumbnails; former package/variant routes are retired."""
from __future__ import annotations

import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from .. import theme_index, theme_plan
from ..packaging import PackageError, compilation_thumbs as thumbs, episode, record
from ..render.stage import RenderError
from ..render.text import TextError
from ..review.names import clean_part, content_disposition, truncate_utf8
from ..titling.logic import TitlingError
from .jobs import RENDER, JobFailed, Step
from .theme_plan import BrokenArtifact, MissingPlan, job_view, response, safe

KIND = "compilation_thumbs"


def render_key(pid, kind, ident):
    return f"compilation-thumbs:{pid}:{kind}:{ident}"


class Unavailable(Exception):
    pass


class ThumbnailTarget:
    def __init__(self, service, pid, kind, ident, source):
        self.service, self.pid, self.kind, self.ident = service, pid, kind, ident
        self.source = source

    def __call__(self, job):
        job.stage = KIND
        try:
            def current():
                return self.service.source(self.pid, self.kind, self.ident, verify=True)
            if current() != self.source:
                raise PackageError("video ghép đã đổi; hãy dựng lại")
            result = thumbs.build(self.service.config, self.source, run=self.service.media_runner, current=current)
        except (PackageError, TextError, RenderError, TitlingError, theme_plan.PlanError,
                theme_index.IndexError, MissingPlan, BrokenArtifact, OSError, ValueError, KeyError, TypeError) as exc:
            raise JobFailed(safe(str(exc))) from exc
        job.stage = None
        job.summary = f"Đã dựng {result['built']} ảnh, dùng lại {result['reused']} ảnh"

    def lane_steps(self):
        return [Step(RENDER, self)]

    def spec(self):
        return dict(playlist_id=self.pid, kind=self.kind, identity=self.ident)


class Packages:
    def __init__(self, plans, *, media_runner=None):
        self.plans, self.config, self.runner = plans, plans.config, plans.runner
        self.media_runner = media_runner
        self.lock = threading.RLock()

    def source(self, pid, kind, ident, *, verify=False):
        if kind == "favorites":
            return thumbs.favorite(self.config, pid, ident)
        if kind != "theme" or not record.PLAN_ID.fullmatch(ident):
            raise MissingPlan()
        source = thumbs.theme(self.config, pid, ident)
        plan = self.plans.find(pid, ident)
        # Keep the original rendered video / metadata download contract; no package approval.
        episode._no_symlinks(source.folder.parent.parent / (source.identity + ".mp4"))
        episode._no_symlinks(source.folder.parent.parent / (source.identity + ".json"))
        if self.plans.output(pid, plan, verify=verify) is None:
            raise PackageError("video tuyển tập chưa sẵn sàng; hãy ghép lại")
        return source

    def view(self, pid, kind, ident, base):
        source = self.source(pid, kind, ident)
        doc = thumbs.read(source)
        reason, files = None, {}
        try:
            files = thumbs.valid_files(self.config, source)
        except (PackageError, TextError, TitlingError) as exc:
            reason = str(exc)
        state = "ready" if len(files) == 2 else "stale" if doc else "empty"
        if state == "stale" and not reason:
            reason = "Thumbnail cũ — đầu vào đã đổi, dựng lại"
        result = safe(dict(state=state, reason=reason, files=files,
                           job=job_view(self.runner.latest(render_key(pid, kind, ident)))))
        result["cover_url"] = f"/playlists/{pid}/thumbs"
        for entry in result["files"].values():
            url = base + "/" + entry["file"]
            entry.update(preview_url=url + "?inline=1", download_url=url)
        return result

    def render(self, pid, kind, ident):
        key = render_key(pid, kind, ident)
        job = self.runner.latest(key)
        if job is not None and job.active:
            raise Unavailable("đang dựng thumbnail video này; chờ hoàn tất")
        source = self.source(pid, kind, ident, verify=True)
        thumbs.valid_files(self.config, source)  # reject missing covers / invalid text before queuing
        job, created = self.runner.submit(key, KIND, ThumbnailTarget(self, pid, kind, ident, source))
        if not created:
            raise Unavailable("đang dựng thumbnail video này; chờ hoàn tất")
        return response(dict(job=job_view(job), created=True), 202)

    def download(self, pid, kind, ident, name, inline):
        if not thumbs.FILE_NAME.fullmatch(name):
            raise MissingPlan()
        source = self.source(pid, kind, ident)
        files = thumbs.valid_files(self.config, source)
        shape = next((s for s, entry in files.items() if entry["file"] == name), None)
        if shape is None:
            raise MissingPlan()
        headers = {"Cache-Control": "no-store"}
        if inline != 1:
            title = truncate_utf8(clean_part(source.title), 100) or source.identity
            headers["Content-Disposition"] = content_disposition(f"{title}_{shape}.jpg")
        return FileResponse(episode._no_symlinks(source.folder / name), media_type="image/jpeg", headers=headers)


def register(app: FastAPI, service: Packages):
    def invoke(pid, action, *, write=False):
        error = service.plans.checked(pid)
        if error is not None:
            return error
        try:
            if write:
                with service.lock:
                    return action()
            return action()
        except MissingPlan:
            return response({"detail": "không có video hoặc thumbnail này"}, 404)
        except Unavailable as exc:
            return response({"detail": str(exc)}, 409)
        except (PackageError, TextError, TitlingError) as exc:
            return response({"detail": str(exc)}, 400)
        except (BrokenArtifact, theme_plan.PlanError, theme_index.IndexError, OSError, ValueError, KeyError, TypeError):
            return response({"detail": "dữ liệu video ghép không hợp lệ"}, 422)

    def routes(kind, base):
        @app.get(base)
        def get(pid: str, ident: str):
            url = base.replace("{pid}", pid).replace("{ident}", ident)
            return invoke(pid, lambda: JSONResponse(service.view(pid, kind, ident, url), headers={"Cache-Control": "no-store"}))

        @app.post(base)
        def build(pid: str, ident: str):
            return invoke(pid, lambda: service.render(pid, kind, ident), write=True)

        @app.get(base + "/{name}")
        def download(pid: str, ident: str, name: str, inline: int = 0):
            return invoke(pid, lambda: service.download(pid, kind, ident, name, inline))

    routes("favorites", "/api/playlists/{pid}/compilations/{ident}/thumbs")
    routes("theme", "/api/playlists/{pid}/theme-plans/{ident}/thumbs")
