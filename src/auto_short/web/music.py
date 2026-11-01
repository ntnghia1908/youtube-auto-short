"""AUD2 authenticated per-video music jobs and local artifacts."""
from __future__ import annotations

import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse, JSONResponse

from ..compilation import CID_RE, store
from ..hashing import sha256_file
from ..packaging import PackageError, assets, music
from ..packaging.episode import _no_symlinks
from ..render.intro import clip_record, offset
from ..render.stage import RenderError
from ..review import content_disposition
from ..store.client import StoreError
from ..store.shorts import borrow_short
from . import episodes as ep
from .jobs import KIND_MUSIC, RENDER, JobFailed, Step
from .urls import valid_playlist_id
from .playlists import PlaylistError
from .theme_plan import MissingPlan, BrokenArtifact


@dataclass(frozen=True)
class Source:
    location: Path | ep.StoredShort
    folder: Path
    stem: str
    name: str
    description: str
    intro_offset: float

    def sha(self):
        return self.location.sha256 if isinstance(self.location, ep.StoredShort) else (
            sha256_file(_no_symlinks(self.location)) if self.location.is_file() else "")


class Conflict(PackageError):
    pass


class MusicTarget:
    def __init__(self, work):
        self.work = work

    def __call__(self, job):
        job.stage = "music"
        self.work(job)
        job.stages.append(dict(stage="music", ran=True))
        job.stage = None

    def lane_steps(self):
        return [Step(RENDER, self)]

    def spec(self):
        return {}  # a restart needs a fresh request, never recreates a music target


class Music:
    def __init__(self, config, runner, compilations, theme_plans, *, run=None):
        self.config, self.runner = config, runner
        self.compilations, self.theme_plans = compilations, theme_plans
        self.run = run
        self.lock = threading.RLock()

    @staticmethod
    def job_key(kind, owner, video):
        return f"music:{kind}:{owner}:{video}"

    def source(self, kind, owner, video):
        root = _no_symlinks(Path(self.config.render.output_dir))
        if kind == "clip":
            if not ep.valid_episode_id(owner) or not owner.endswith(".kt") or not ep.valid_clip_id(video):
                raise PackageError("không có clip khai thị này")
            if ep.kind_fields(self.config, owner)["kind"] != "khaithi":
                raise PackageError("chỉ clip khai thị mới có nhạc nền")
            folder = _no_symlinks(root / owner)
            _no_symlinks(folder / "render_manifest.json")
            _no_symlinks(folder / "store.json")
            _no_symlinks(folder / "shorts" / f"{video}.mp4")
            _no_symlinks(folder / "shorts" / f"{video}.intro.json")
            row = next((r for r in ep.short_locations(self.config, owner) or [] if r[0] == video), None)
            if row is None or row[1] is None:
                raise PackageError("clip khai thị chưa sẵn sàng")
            location = row[1]
            record = (next((s for s in (ep.render_manifest(self.config, owner) or {}).get("shorts", [])
                            if s.get("clip_id") == video), {}) if isinstance(location, ep.StoredShort)
                      else clip_record(location))
            result = Source(location, folder / "music", video, row[2], "", offset(record))
        elif kind == "compilation":
            if not valid_playlist_id(owner) or not CID_RE.fullmatch(video):
                raise PackageError("id video ghép không hợp lệ")
            folder = _no_symlinks(store.directory(root, owner))
            _no_symlinks(folder / f"{video}.json")
            path = _no_symlinks(folder / f"{video}.mp4")
            doc = store.read_doc(folder, video)
            if not doc or doc.get("status") != store.DONE:
                raise PackageError("video ghép chưa sẵn sàng")
            playlist = self.compilations.playlists.load(owner)
            if playlist is None:
                raise PackageError("không có bộ kinh này")
            tags = self.compilations.playlists.effective_hashtags(playlist)[0]
            description = self.compilations.compilation_view(doc, tags).get("description") or ""
            result = Source(path, folder / "music", video, doc.get("download_name") or path.name, description, offset(doc))
        elif kind == "theme":
            if not valid_playlist_id(owner) or not re.fullmatch(r"[a-z0-9]{8,32}", video):
                raise PackageError("id tuyển tập không hợp lệ")
            folder = _no_symlinks(store.directory(root, owner) / "theme")
            try:
                plan = self.theme_plans.find(owner, video)
            except (MissingPlan, BrokenArtifact) as exc:
                raise PackageError("tuyển tập không còn hợp lệ") from exc
            stem = f"{video}-r{plan['revision']}"
            path = _no_symlinks(folder / (stem + ".mp4"))
            _no_symlinks(path.with_suffix(".json"))
            output = self.theme_plans.output(owner, plan, verify=True)
            doc = output[1] if output else {}
            # Keep old renditions visible as stale while a changed plan has no current output.
            location = path if output else folder / (stem + "-unavailable.mp4")
            result = Source(location, folder / "music", stem, doc.get("download_name") or stem + ".mp4",
                            doc.get("description", ""), offset(doc))
        else:
            raise PackageError("loại video không hợp lệ")
        _no_symlinks(result.folder)
        return result

    def choices(self):
        rows = []
        _no_symlinks(self.config.packaging.asset_dir)
        for asset in assets.list_assets(self.config.packaging.asset_dir):
            if asset["kind"] != "music" or not asset["approved"]:
                continue
            try:
                assets.usable(self.config.packaging.asset_dir, asset["id"], kind="music")
            except (PackageError, OSError):
                continue
            rows.append({k: asset.get(k, "") for k in ("id", "title", "artist", "attribution")})
        return rows

    def docs(self, source, *, preview=False, kind=None, video=None):
        return music.records(source.folder, source.stem, preview=preview,
                             family_stem=video if kind == "theme" else None)

    def valid(self, source, doc):
        return music.current(source.folder, doc, source.sha(), self.config.packaging.asset_dir,
                             audio_bitrate=self.config.render.audio_bitrate)

    def view(self, kind, owner, video):
        source = self.source(kind, owner, video)
        base = f"/api/music/{kind}/{owner}/{video}"
        docs = self.docs(source, kind=kind, video=video)
        previews = self.docs(source, preview=True, kind=kind, video=video)
        doc = docs[0] if docs else None
        job = self.runner.latest(self.job_key(kind, owner, video))
        default = self.config.music
        result = dict(assets=self.choices(), defaults=dict(level_lu=default.default_level_lu,
                      fade_in=round(source.intro_offset or default.fade_in, 1), fade_out=default.fade_out,
                      loop_crossfade=default.loop_crossfade), job=job.to_dict(logs=False) if job else None,
                      state="none", previews=[])
        if doc:
            valid = self.valid(source, doc)
            result.update(state="ready" if valid else "stale", spec=doc.get("spec"))
            if valid:
                result.update(video_url=base + "/file?inline=1", download_url=base + "/file",
                              attribution=doc.get("attribution", ""),
                              description=music.attributed_description(source.description, doc.get("attribution", "")))
        if previews and self.valid(source, previews[0]):
            result["previews"] = [dict(url=base + f"/preview/{i}", start=p["start"], duration=p["duration"])
                                  for i, p in enumerate(previews[0]["previews"], 1)]
        return result

    def submit(self, kind, owner, video, spec, *, preview=False):
        with self.lock:
            source = self.source(kind, owner, video)
            spec = music.normalize(spec, source.intro_offset, self.config.music)
            key = self.job_key(kind, owner, video)
            active = self.runner.latest(key)
            if active and active.active:
                raise Conflict("video đang có job nhạc chạy/đợi")
            if spec is None:
                return None
            _no_symlinks(self.config.packaging.asset_dir)
            assets.usable(self.config.packaging.asset_dir, spec["asset_id"], kind="music")
            if not source.sha():
                raise PackageError("video nguồn chưa sẵn sàng")
            source.folder.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(source.folder).free < 3 * 1024 ** 3:
                raise PackageError("ổ đĩa cần còn ít nhất 3 GB để dựng nhạc")
            expected_sha = source.sha()

            def work(job):
                def check():
                    if job.cancel_requested:
                        raise KeyboardInterrupt
                    now = self.source(kind, owner, video)
                    if now.stem != source.stem or now.sha() != expected_sha:
                        raise PackageError("nguồn đã đổi trong khi dựng")
                try:
                    check()
                    with borrow_short(self.config, source.location, source.folder) as local:
                        intro_offset = offset(clip_record(local)) if kind == "clip" else source.intro_offset
                        if sha256_file(local) != expected_sha:
                            raise PackageError("nguồn mượn lệch sha256")
                        build = music.preview if preview else music.mix
                        build(local, intro_offset, spec, self.config.packaging.asset_dir, folder=source.folder,
                              stem=source.stem, defaults=self.config.music, audio_bitrate=self.config.render.audio_bitrate,
                              run=self.run, description=source.description, before_publish=check, publish_lock=self.lock,
                              family_stem=video if kind == "theme" else None)
                except StoreError as exc:
                    raise JobFailed("đang ở kho 3090, thử lại sau") from exc
                except (PackageError, RenderError, OSError, ValueError) as exc:
                    raise JobFailed(str(exc)) from exc
            job, created = self.runner.submit(key, KIND_MUSIC, MusicTarget(work))
            if not created:
                raise Conflict("video đang có job nhạc chạy/đợi")
            return job.to_dict(logs=False)

    def delete(self, kind, owner, video):
        with self.lock:
            key = self.job_key(kind, owner, video)
            job = self.runner.latest(key)
            if job and job.active:
                raise Conflict("hãy hủy job nhạc trước khi xóa")
            source = self.source(kind, owner, video)
            for preview in (False, True):
                for path in music.artifact_files(source.folder, source.stem, preview=preview,
                                                 family_stem=video if kind == "theme" else None):
                    _no_symlinks(path).unlink(missing_ok=True)
            return dict(deleted=True)


def router(service):
    routes = APIRouter()
    base = "/api/music/{kind}/{owner}/{video}"

    def invoke(action):
        try:
            return action()
        except Conflict as exc:
            return JSONResponse(dict(detail=str(exc)), status_code=409)
        except (PackageError, PlaylistError, OSError, ValueError, KeyError) as exc:
            return JSONResponse(dict(detail=str(exc)), status_code=422)

    @routes.get(base)
    def view(kind: str, owner: str, video: str):
        return invoke(lambda: service.view(kind, owner, video))

    @routes.post(base)
    def build(kind: str, owner: str, video: str, body: dict = Body(...)):
        return invoke(lambda: dict(job=service.submit(kind, owner, video, body)))

    @routes.post(base + "/preview")
    def preview(kind: str, owner: str, video: str, body: dict = Body(...)):
        return invoke(lambda: dict(job=service.submit(kind, owner, video, body, preview=True)))

    @routes.post(base + "/cancel")
    def cancel(kind: str, owner: str, video: str):
        def action():
            service.source(kind, owner, video)
            service.runner.cancel(KIND_MUSIC, [service.job_key(kind, owner, video)])
            return dict(cancelled=True)
        return invoke(action)

    @routes.delete(base)
    def delete(kind: str, owner: str, video: str):
        return invoke(lambda: service.delete(kind, owner, video))

    def file(kind, owner, video, index=None, inline=False):
        try:
            source = service.source(kind, owner, video)
            docs = service.docs(source, preview=index is not None, kind=kind, video=video)
            if not docs or not service.valid(source, docs[0]):
                return JSONResponse(dict(detail="bản nhạc cũ — dựng lại"), status_code=409)
            doc = docs[0]
            name = doc["file"] if index is None else doc["previews"][index - 1]["file"]
            path = _no_symlinks(source.folder / name)
            headers = {"Cache-Control": "no-store"}
            if index is None and not inline:
                headers["Content-Disposition"] = content_disposition(Path(source.name).stem + " (nhạc).mp4")
            return FileResponse(path, media_type="video/mp4" if index is None else "audio/mp4", headers=headers)
        except (PackageError, PlaylistError, OSError, ValueError, KeyError, IndexError):
            return JSONResponse(dict(detail="không có file nhạc này"), status_code=404)

    @routes.get(base + "/file")
    def download(kind: str, owner: str, video: str, inline: int = 0):
        return file(kind, owner, video, inline=inline == 1)

    @routes.get(base + "/preview/{index}")
    def preview_file(kind: str, owner: str, video: str, index: int):
        if index not in (1, 2):
            return JSONResponse(dict(detail="không có đoạn nghe thử này"), status_code=404)
        return file(kind, owner, video, index=index)

    return routes
