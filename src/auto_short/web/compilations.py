"""CP8.33: web side of the khai thị compilations: favourites (G9), the usable khai thị of a bộ kinh (G1), building a
spec from a request (G2, G10), the job body (G5) and the views of the Yêu thích page (G6). The ffmpeg work and the
stored files live in ``auto_short.compilation``; the routes in ``web/app.py`` only call this module.

Canonical contract: docs/tasks/CP8.33-khaithi-compilation.md.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from .. import compilation as comp
from .. import khaithi
from ..compilation import CompilationError, Item, store
from ..config import Config
from ..hashing import sha256_file
from ..packaging import PackageError, compilation_thumbs, khaithi_thumbs
from ..review.names import short_code
from ..render.intro import clip_record, offset, metadata as intro_metadata
from ..render.stage import RenderError
from ..render.text import TextError
from ..workspace import atomic_write_json
from ..store.shorts import borrow_short, fetch_released
from ..store.client import StoreError
from . import episodes as ep
from .jobs import KIND_COMPILATION, CompilationTarget, JobFailed, JobRunner, compilation_key
from .playlists import PlaylistStore
from .urls import valid_playlist_id

log = logging.getLogger("auto_short")

MAX_BODY_ITEMS = 500


def by_episode_order(entries: list[dict]) -> list[dict]:
    """CP13.2 H2 / CP8.33 G1: episode number order (the numbered first), then playlist order."""
    def key(e: dict):
        n = e.get("episode")
        return (0, int(n), e["index"]) if isinstance(n, str) and n.isdigit() else (1, 0, e["index"])
    return sorted(entries, key=key)


@dataclass(frozen=True)
class Clip:
    """A rendered, not deleted Short or khai thị clip of a bộ kinh (G1, Amendment 2)."""

    item: Item
    rank: tuple  # G1 order: (position of the episode in the bộ kinh, 0 Short / 1 khai thị, clip number)
    label: str  # episode label ("29"), as in the download names
    number: int  # 1-based position in the render manifest (``S<NN>`` / ``KT<NN>``)
    total: int  # clips in the render manifest (width of ``NN``)
    title: str | None
    manifest_duration: float | None
    path: Path | ep.StoredShort
    kept: bool = False  # G11: the file is the kept copy of a deleted episode's favourite
    kind: str = "khaithi"  # "short" | "khaithi" (decided by the episode id: ``<id>`` / ``<id>.kt``)

    @property
    def code(self) -> str:
        return short_code(self.label, self.number, self.total, khaithi=self.kind == "khaithi")


def kind_of(episode_id: str) -> str:
    """Amendment 2: a khai thị episode is ``<video_id>.kt`` (CP8.9 K8), every other episode is a Short episode."""
    return "khaithi" if episode_id.endswith(khaithi.SUFFIX) else "short"


def base_of(episode_id: str) -> str:
    return episode_id.removesuffix(khaithi.SUFFIX)


class Compilations:
    def __init__(self, config: Config, playlists: PlaylistStore, runner: JobRunner,
                 series_of: Callable[[dict], str | None], *, probe_runner: comp.Runner = comp.run_command):
        self.config, self.playlists, self.runner, self.series_of = config, playlists, runner, series_of
        self._probe_runner = probe_runner
        self._lock = threading.RLock()  # <cid>.json / favorites.json read-modify-write + "job exists?" decisions
        self._durations: dict[tuple[str, int, int], comp.MediaInfo] = {}

    # --- paths --------------------------------------------------------------------------------------------------

    def folder(self, playlist_id: str) -> Path:
        return store.directory(self.config.render.output_dir, playlist_id)

    def video_file(self, playlist_id: str, cid: str) -> Path | None:
        """The finished ``<cid>.mp4`` for the download route (G6), or None."""
        doc = store.read_doc(self.folder(playlist_id), cid) if valid_playlist_id(playlist_id) else None
        path = store.video_path(self.folder(playlist_id), cid)
        if doc is None or doc.get("status") != store.DONE or not path.is_file():
            return None
        return path

    # --- the khai thị clips of a bộ kinh (G1) ---------------------------------------------------------------------

    def clips(self, doc: dict) -> list[Clip]:
        """Every usable khai thị clip of the bộ kinh in G1 order (episode number, then ``KT`` number): the rendered,
        not deleted ones, and (G11) the kept copy of a favourite whose episode was deleted. A favourite with a kept
        file is always used through that file (the snapshot of what was hearted)."""
        out: dict[Item, Clip] = {}
        order: dict[str, int] = {}
        entries = by_episode_order([e for e in doc["entries"] if e.get("video_id") and e.get("available")])
        for pos, entry in enumerate(entries):
            order[entry["video_id"]] = pos
            try:
                parts = [(entry["video_id"], "short"), (khaithi.episode_id_for(entry["video_id"]), "khaithi")]
            except khaithi.KhaithiError:
                continue
            for part, (eid, kind) in enumerate(parts):
                kf = ep.kind_fields(self.config, eid)
                render = ep.render_manifest(self.config, eid)
                if kf["kind"] != kind or render is None:
                    continue
                files = {cid: path for cid, path, _ in ep.short_locations(self.config, eid) or [] if path is not None}
                label, shorts = ep.label(self.config, eid, kf), render.get("shorts") or []
                for n, s in enumerate(shorts, 1):
                    cid = s.get("clip_id") if isinstance(s, dict) else None
                    if cid in files:
                        d = s.get("duration")
                        item = Item(eid, cid)
                        out[item] = Clip(item, (pos, part, n), label, n, len(shorts),
                                         s.get("title") if isinstance(s.get("title"), str) else None,
                                         float(d) if isinstance(d, (int, float)) else None, files[cid], kind=kind)
        folder = self.folder(doc["playlist_id"])
        for fav in self.favorites(doc["playlist_id"]):
            path = store.kept_path(folder, fav)
            if path is None or not path.is_file():
                continue
            k = fav.kept
            base = base_of(fav.episode_id)
            tap = int(k["episode_number"]) if k["episode_number"].isdigit() else 999999
            pos = order.get(base, 1_000_000 + tap)
            out[Item(fav.episode_id, fav.clip)] = Clip(Item(fav.episode_id, fav.clip),
                                                       (pos, 1 if kind_of(fav.episode_id) == "khaithi" else 0, k["clip_number"]),
                                                       k["episode_number"], k["clip_number"], k["clip_total"],
                                                       k["title"], float(k["duration"]), path, kept=True,
                                                       kind=kind_of(fav.episode_id))
        return sorted(out.values(), key=lambda c: c.rank)

    def _info(self, path: Path) -> comp.MediaInfo:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        hit = self._durations.get(key)
        if hit is None:
            hit = comp.probe(path, self._probe_runner)
            if len(self._durations) > 2000:
                self._durations.clear()
            self._durations[key] = hit
        return hit

    def duration(self, clip: Clip) -> float:
        if isinstance(clip.path, ep.StoredShort):
            if clip.manifest_duration is None or clip.manifest_duration <= 0:
                raise CompilationError(f"{clip.code}: không biết thời lượng Short trên kho")
            return clip.manifest_duration
        info = self._info(clip.path)
        if not info.complete:
            raise CompilationError(f"{clip.code}: file thiếu video / audio")
        try:
            return info.duration - offset(clip_record(clip.path))
        except ValueError as exc:
            raise CompilationError(str(exc)) from exc

    def owns(self, doc: dict, episode_id: str) -> bool:
        """Does the Short / khai thị episode ``episode_id`` belong to a (available) entry of the bộ kinh?"""
        base = base_of(episode_id)
        return any(e.get("video_id") == base and e.get("available") for e in doc["entries"]) \
            and ep.kind_fields(self.config, episode_id)["kind"] == kind_of(episode_id)

    # --- favourites (G9) ------------------------------------------------------------------------------------------

    def favorites(self, playlist_id: str) -> list[Item]:
        try:
            return store.read_favorites(self.folder(playlist_id))
        except CompilationError:
            return []

    def favorites_count(self, playlist_id: str) -> int:
        return len(self.favorites(playlist_id))

    def set_favorite(self, playlist_id: str, doc: dict, item: Item, favorite: bool) -> list[Item]:
        """Idempotent heart on/off. A new favourite must be a rendered khai thị of this bộ kinh; one can always be
        removed (also a stale entry). The stored list stays in G1 order, stale entries last."""
        with self._lock:
            current = self.favorites(playlist_id)
            if favorite:
                if not self.owns(doc, item.episode_id):
                    raise CompilationError("khai thị không thuộc bộ kinh này")
                clips = self.clips(doc)
                if item not in {c.item for c in clips if not c.kept}:
                    raise CompilationError("khai thị chưa render hoặc đã xóa")
                if item not in current:
                    current.append(item)
                rank = {c.item: c.rank for c in clips}
                current.sort(key=lambda i: rank.get(i, (10**9, 0)))  # stable: stale entries keep their order, last
            else:
                folder = self.folder(playlist_id)
                for gone in (i for i in current if i == item):
                    store.remove_kept(folder, gone)  # G11: un-hearting a kept item deletes the kept file
                current = [i for i in current if i != item]
            store.write_favorites(self.folder(playlist_id), current)
            return current

    def episode_favorites(self, episode_id: str) -> dict | None:
        """For the episode page of a Short / khai thị episode: the bộ kinh it belongs to (the first stored one
        listing its base video) and the hearted clip ids; None when it belongs to none."""
        base = base_of(episode_id)
        for doc in self.playlists.all():
            if any(e.get("video_id") == base and e.get("available") for e in doc["entries"]):
                pid = doc["playlist_id"]
                return {"playlist_id": pid, "clips": [i.clip for i in self.favorites(pid) if i.episode_id == episode_id]}
        return None

    # --- views (G6) -------------------------------------------------------------------------------------------------

    def _clip_view(self, c: Clip, *, favorite: bool) -> dict:
        try:
            duration = self.duration(c)
        except CompilationError:
            duration = c.manifest_duration
        return {"episode_id": c.item.episode_id, "clip": c.item.clip, "tap": c.label, "number": c.number,
                "code": c.code, "kind": c.kind, "title": c.title, "duration": duration, "usable": duration is not None,
                "favorite": favorite, "kept": c.kept,
                "video_url": None if c.kept else f"/files/{c.item.episode_id}/{c.item.clip}.mp4"}

    def favorites_view(self, playlist_id: str, doc: dict) -> list[dict]:
        by_item = {c.item: c for c in self.clips(doc)}
        out = []
        for item in self.favorites(playlist_id):
            c = by_item.get(item)
            if c is None and item.kept is not None:  # G11: kept but the file is gone
                out.append({"episode_id": item.episode_id, "clip": item.clip, "tap": item.kept["episode_number"],
                            "number": item.kept["clip_number"], "kind": kind_of(item.episode_id),
                            "code": item.episode_id + "/" + item.clip,
                            "title": item.kept["title"], "duration": None, "usable": False, "favorite": True,
                            "kept": True, "video_url": None})
                continue
            if c is None:  # G9: deleted / not rendered any more / orphan -> shown dimmed, can only be un-hearted
                out.append({"episode_id": item.episode_id, "clip": item.clip, "tap": None, "number": None,
                            "kind": kind_of(item.episode_id),
                            "code": item.episode_id + "/" + item.clip, "title": None, "duration": None,
                            "usable": False, "favorite": True, "kept": False, "video_url": None})
            else:
                out.append(self._clip_view(c, favorite=True))
        return out

    def compilation_view(self, d: dict, tags: list[str]) -> dict:
        """One stored compilation with its live state: ``queued`` | ``running`` | ``done`` | ``failed``."""
        cid, pid = d["cid"], d["playlist_id"]
        job = self.runner.latest(compilation_key(pid, cid))
        state, error = d.get("status"), d.get("error")
        if job is not None and job.active:
            state, error = job.status, None
        elif state in (store.QUEUED, store.RUNNING):
            state, error = store.FAILED, "bị ngắt (khởi động lại hoặc hủy) — bấm tạo lại"
        elif state == store.DONE and not store.video_path(self.folder(pid), cid).is_file():
            state, error = store.FAILED, "file video không còn"
        elif state == store.DONE and not self.intro_current(pid, d, verify=False):
            state, error = store.FAILED, "Thumbnail intro đã đổi — cần ghép lại"
        done = state == store.DONE
        return {"cid": cid, "title": d.get("title"), "mode": d.get("mode"), "segments": len(d.get("items") or []),
                "repeat": d.get("repeat"), "duration": d.get("duration") if done else d.get("duration_estimate"),
                "state": state, "error": error, "created_at": d.get("created_at"), "size": d.get("size"),
                "download_name": d.get("download_name"),
                "download_url": f"/files/playlists/{pid}/compilations/{cid}.mp4" if done else None,
                "description": comp.meta.description(d.get("mode") or "concat", d.get("chapters") or [],
                                                     d.get("title"), tags) if done else None,
                "chapters": d.get("chapters") or [],
                **store.published_status(self.folder(pid), "compilation", cid)}

    def intro_current(self, pid: str, doc: dict, *, verify=True) -> bool:
        if khaithi_thumbs.start_episode(self.config, pid) is None:
            return True
        try:
            source = compilation_thumbs.favorite(self.config, pid, doc["cid"], pending=True)
            return compilation_thumbs.intro_current(self.config, source, "vertical", doc,
                                                     store.video_path(self.folder(pid), doc["cid"]), verify=verify)
        except (PackageError, OSError, ValueError, KeyError, TypeError, TextError):
            return False

    def view(self, playlist_id: str, doc: dict) -> dict:
        tags = self.playlists.effective_hashtags(doc)[0]
        with self._lock:
            docs = store.list_docs(self.folder(playlist_id))
            compilations = [self.compilation_view(d, tags) for d in docs]
        return {"playlist_id": playlist_id, "title": doc.get("title"), "series": self.series_of(doc),
                "max_minutes": self.config.compilation.max_minutes, "favorites": self.favorites_view(playlist_id, doc),
                "compilations": compilations}

    # --- request -> spec (G2, G10) -------------------------------------------------------------------------------------

    def _lookup(self, doc: dict) -> dict[Item, Clip]:
        return {c.item: c for c in self.clips(doc)}

    def _pick(self, by_item: dict[Item, Clip], raw: object) -> Clip:
        item = comp.item_from_json(raw)
        clip = by_item.get(item)
        if clip is None:
            raise CompilationError("khai thị không thuộc bộ kinh này, chưa render hoặc đã xóa")
        return clip

    def plan(self, playlist_id: str, doc: dict, body: dict) -> tuple[comp.Spec, list[Clip], dict]:
        """Validate ``body`` (G6 POST) and build the spec, the clips in playback order and a ``preview`` dict."""
        mode, limit = body.get("mode"), self.config.compilation.max_minutes
        if mode not in comp.MODES:
            raise CompilationError("mode phải là concat, loop hoặc auto")
        by_item = self._lookup(doc)
        if mode == "concat":
            raw = body.get("items")
            if not isinstance(raw, list) or len(raw) > MAX_BODY_ITEMS:
                raise CompilationError("items phải là danh sách khai thị")
            picked = sorted({c.item: c for c in (self._pick(by_item, r) for r in raw)}.values(), key=lambda c: c.rank)
            if len(picked) != len(raw):
                raise CompilationError("mục khai thị bị trùng")
            durations = {c.item: self.duration(c) for c in picked}
            spec = comp.build_concat([c.item for c in picked], durations, limit)
            return spec, picked, {"segments": len(picked), "duration": sum(durations.values())}
        if mode == "loop":
            clip = self._pick(by_item, body.get("item"))
            d = self.duration(clip)
            spec = comp.build_loop(clip.item, d, body.get("minutes"), limit)
            return spec, [clip] * spec.repeat, {"segments": spec.repeat, "repeat": spec.repeat,
                                               "duration": spec.repeat * d}
        kinds = body.get("kinds", ["short", "khaithi"])
        if not isinstance(kinds, list) or not kinds or not set(kinds) <= {"short", "khaithi"}:
            raise CompilationError("kinds phải là danh sách con của short, khaithi")
        usable = [c for c in (by_item.get(i) for i in self.favorites(playlist_id)) if c is not None
                  and c.kind in kinds]
        usable.sort(key=lambda c: c.rank)
        durations = {c.item: self.duration(c) for c in usable}
        spec, rounds = comp.build_auto([c.item for c in usable], durations, body.get("minutes"), limit)
        return spec, [by_item[i] for i in spec.items], {
            "segments": len(spec.items), "rounds": rounds, "duration": sum(durations[i] for i in spec.items)}

    def names(self, doc: dict, playlist_id: str, spec: comp.Spec, clips: list[Clip]) -> tuple[str, str | None]:
        """G7: (download name, title for the loop description)."""
        series = self.series_of(doc)
        fallback = doc.get("title") or playlist_id
        if spec.mode == "loop":
            c = clips[0]
            return comp.meta.loop_name(series, c.code, spec.repeat, fallback=fallback), c.title
        lo = min(clips, key=lambda c: c.rank)
        hi = max(clips, key=lambda c: c.rank)
        return comp.meta.concat_name(series, lo.label, hi.label, len(clips), kinds={c.kind for c in clips},
                                     fallback=fallback), None

    # --- submit / job / delete (G4, G5) -----------------------------------------------------------------------------------

    def submit(self, playlist_id: str, doc: dict, body: dict) -> tuple[dict, bool]:
        """Returns (view of the compilation, created). The same spec again -> the stored one, no new job (G4)."""
        spec, clips, preview = self.plan(playlist_id, doc, body)
        cid, folder = spec.cid, self.folder(playlist_id)
        name, title = self.names(doc, playlist_id, spec, clips)
        with self._lock:
            current = store.read_doc(folder, cid)
            key = compilation_key(playlist_id, cid)
            job = self.runner.latest(key)
            done = current is not None and current.get("status") == store.DONE and store.video_path(folder, cid).is_file() \
                and self.intro_current(playlist_id, current)
            if done or (job is not None and job.active):
                created = False
            else:
                new = store.new_doc(playlist_id, cid, spec.mode, spec.items, spec.repeat, download_name=name,
                                    title=title, duration_estimate=preview["duration"])
                store.write_doc(folder, new)
                target = self._target(playlist_id, spec)
                self.runner.submit(key, KIND_COMPILATION, target)
                created = True
            stored = store.read_doc(folder, cid)
        tags = self.playlists.effective_hashtags(doc)[0]
        out = self.compilation_view(stored, tags)
        out["preview"] = preview
        return out, created

    def spec_json(self, playlist_id: str, spec: comp.Spec) -> dict:
        return {"playlist_id": playlist_id, "cid": spec.cid, "mode": spec.mode,
                "items": [i.to_json() for i in spec.items], "repeat": spec.repeat}

    def _target(self, playlist_id: str, spec: comp.Spec) -> CompilationTarget:
        return CompilationTarget(self.spec_json(playlist_id, spec), lambda job: self._work(playlist_id, spec, job))

    def rebuild(self, key: str, saved: dict) -> CompilationTarget | None:
        """CP8.22 Q2: the target of a saved ``compilation`` job; None when it cannot be recreated."""
        try:
            pid, cid = saved["playlist_id"], saved["cid"]
            items = tuple(comp.item_from_json(i) for i in saved["items"])
            repeat, mode = saved["repeat"], saved["mode"]
            if mode not in comp.MODES or not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1 \
                    or not valid_playlist_id(pid) or not items or len(items) > comp.spec.MAX_ITEMS:
                return None
            spec = comp.Spec(mode, items, repeat)
            if spec.cid != cid or key != compilation_key(pid, cid):
                return None
            if store.read_doc(self.folder(pid), cid) is None:
                return None
        except (KeyError, TypeError, CompilationError):
            return None
        return self._target(pid, spec)

    def _update(self, playlist_id: str, cid: str, **fields) -> dict | None:
        with self._lock:
            d = store.read_doc(self.folder(playlist_id), cid)
            if d is None:
                return None
            d.update(fields)
            store.write_doc(self.folder(playlist_id), d)
            return d

    def _work(self, playlist_id: str, spec: comp.Spec, job) -> None:
        """The body of the ``compilation`` job: resolve the clips again (they may have changed since the request),
        join them, write ``<cid>.json``. A failure marks the file ``failed`` and leaves no temp file."""
        cid, folder = spec.cid, self.folder(playlist_id)
        if self._update(playlist_id, cid, status=store.RUNNING, error=None) is None:
            raise JobFailed("video ghép đã bị xóa")
        intro_required = khaithi_thumbs.start_episode(self.config, playlist_id) is not None
        published = False
        try:
            doc = self.playlists.load(playlist_id)
            if doc is None:
                raise CompilationError("bộ kinh không còn")
            by_item = self._lookup(doc)
            missing = [i for i in dict.fromkeys(spec.items) if i not in by_item]
            if missing:
                raise CompilationError(f"khai thị {missing[0].episode_id}/{missing[0].clip} không còn dùng được")
            clips = [by_item[i] for i in spec.items]
            enc = comp.Encode(crf=self.config.render.crf, preset=self.config.render.preset,
                              audio_bitrate=self.config.render.audio_bitrate, threads=self.config.render.threads)
            image = None
            if intro_required:
                current = lambda: compilation_thumbs.favorite(self.config, playlist_id, cid, pending=True)
                image = compilation_thumbs.intro_image(self.config, current(), "vertical", current=current,
                                                       run=self._probe_runner)
            with ExitStack() as stack:
                paths = {c.item: stack.enter_context(borrow_short(self.config, c.path, folder))
                         for c in dict((c.item, c) for c in clips).values()}
                done = comp.assemble([paths[c.item] for c in clips], store.video_path(folder, cid), enc,
                                     runner=self._probe_runner, **({"intro_image": image} if image else {}))
                published = True
            chapter_options = {"content_offset": done.content_offset} if image is not None else {}
            chapters = [] if spec.mode == "loop" else comp.meta.chapters([c.title or c.code for c in clips], done.parts,
                                                                        **chapter_options)
            extra = dict(intro=intro_metadata(image), content_offset=done.content_offset,
                         content_sha256=done.content_sha256,
                         sha256=sha256_file(store.video_path(folder, cid))) if image else {}
            self._update(playlist_id, cid, status=store.DONE, error=None, duration=round(done.duration, 3),
                         chapters=chapters, size=done.size, reencoded=done.reencoded, finished_at=store.now(), **extra)
        except (CompilationError, StoreError, OSError, PackageError, RenderError, TextError) as exc:
            self._update(playlist_id, cid, status=store.FAILED, error=str(exc))
            if not intro_required or published:
                store.video_path(folder, cid).unlink(missing_ok=True)
            raise JobFailed(str(exc)) from exc
        job.summary = f"{len(clips)} đoạn, {done.duration / 60:.1f} phút" + (" (encode lại)" if done.reencoded else "")

    def delete(self, playlist_id: str, cid: str) -> str:
        """``deleted`` | ``busy`` (a job is queued / running) | ``missing``."""
        with self._lock:
            job = self.runner.latest(compilation_key(playlist_id, cid))
            if job is not None and job.active:
                return "busy"
            return "deleted" if store.delete(self.folder(playlist_id), cid) else "missing"


    # --- G11: keep the hearted clips when their episode is deleted ----------------------------------------------------

    def _bound_playlists(self) -> list[tuple[str, Path]]:
        """(playlist id, folder) of every bộ kinh that has a ``favorites.json``."""
        root = Path(self.config.render.output_dir) / store.NAMESPACE
        if not root.is_dir():
            return []
        return [(p.name, p) for p in sorted(root.iterdir()) if p.is_dir() and (p / store.FAVORITES_NAME).is_file()]

    def keep_count(self, episode_id: str) -> int:
        """Hearted clips of ``episode_id`` over every bộ kinh (the delete confirmation)."""
        return sum(1 for pid, _ in self._bound_playlists() for i in self.favorites(pid)
                   if i.episode_id == episode_id and i.kept is None)

    def keep_favorites(self, episode_id: str) -> Callable[[], None]:
        """G11 (a): before the Short / khai thị episode ``episode_id`` is deleted, move each hearted clip that is currently
        rendered to ``<_compilations>/<pid>/kept/<episode_id>/<clip>.mp4`` and store its snapshot in
        ``favorites.json``. Raises :class:`CompilationError` (nothing changed) on any failure. Returns ``undo()``
        (used when the deletion itself fails)."""
        moved: list[tuple[Path, Path]] = []  # (original, kept)
        fetched: list[Path] = []  # store copies have no VM original to restore on undo
        written: list[tuple[Path, list[Item]]] = []  # (folder, previous favourites)

        def undo() -> None:
            for folder, before in reversed(written):
                try:
                    store.write_favorites(folder, before)
                except Exception:  # best effort
                    log.exception("compilation: không hoàn tác được favorites.json %s", folder)
            for src, dst in reversed(moved):
                try:
                    if not src.exists():
                        _move(dst, src)
                    else:
                        dst.unlink(missing_ok=True)
                except OSError:
                    log.exception("compilation: không hoàn tác được %s", dst)
            for dst in fetched:
                dst.unlink(missing_ok=True)
                dst.with_name(dst.name + ".part").unlink(missing_ok=True)

        try:
            hits = [(pid, folder, self.favorites(pid)) for pid, folder in self._bound_playlists()]
            hits = [(pid, folder, favs) for pid, folder, favs in hits
                    if any(i.episode_id == episode_id and i.kept is None for i in favs)]
            if not hits:
                return lambda: None
            render = ep.render_manifest(self.config, episode_id) or {}
            kf = ep.kind_fields(self.config, episode_id)
            label, shorts = ep.label(self.config, episode_id, kf), render.get("shorts") or []
            meta = {s["clip_id"]: (n, s) for n, s in enumerate(shorts, 1) if isinstance(s, dict) and "clip_id" in s}
            files = {cid: path for cid, path, _ in ep.short_locations(self.config, episode_id) or [] if path is not None}
            first: dict[str, Path] = {}  # clip -> the kept file of the first bộ kinh (later ones copy it)
            for pid, folder, favs in hits:
                new: list[Item] = []
                for fav in favs:
                    if fav.episode_id != episode_id or fav.kept is not None or fav.clip not in files:
                        new.append(fav)
                        continue
                    n, s = meta[fav.clip]
                    dst = folder / store.KEPT_DIR / episode_id / f"{fav.clip}.mp4"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if fav.clip in first:
                        moved.append((first[fav.clip], dst))  # undo: just remove this copy
                        shutil.copy2(first[fav.clip], dst)
                    else:
                        location = files[fav.clip]
                        if isinstance(location, ep.StoredShort):
                            fetched.append(dst)  # also remove an interrupted .part on failure
                            fetch_released(self.config, location, dst)
                        else:
                            _move(location, dst)
                            moved.append((location, dst))
                        first[fav.clip] = dst
                    try:
                        duration = self._info(dst).duration - offset(s)
                    except CompilationError:
                        duration = float(s.get("duration") or 0)
                    if s.get("intro"):
                        sidecar = dst.with_suffix(".intro.json")
                        fetched.append(sidecar)
                        atomic_write_json(sidecar, s)
                    snap = {"path": f"{store.KEPT_DIR}/{episode_id}/{fav.clip}.mp4",
                            "title": s.get("title") if isinstance(s.get("title"), str) else None,
                            "duration": round(duration, 3), "episode_number": label, "clip_number": n,
                            "clip_total": len(shorts), "saved_at": store.now()}
                    new.append(Item(fav.episode_id, fav.clip, snap))
                written.append((folder, favs))
                with self._lock:
                    store.write_favorites(folder, new)
        except Exception as exc:  # whatever went wrong: undo and refuse the deletion
            undo()
            raise CompilationError(f"không giữ lại được khai thị yêu thích: {exc}") from exc
        return undo

    def drop_hearts(self, episode_id: str, clip: str) -> int:
        """G11 (c): the clip was deleted by hand (CP8.5): remove its heart in every bộ kinh (no kept copy)."""
        n = 0
        for pid, folder in self._bound_playlists():
            with self._lock:
                favs = self.favorites(pid)
                keep = [i for i in favs if not (i.episode_id == episode_id and i.clip == clip and i.kept is None)]
                if len(keep) != len(favs):
                    store.write_favorites(folder, keep)
                    n += len(favs) - len(keep)
        return n


def _move(src: Path, dst: Path) -> None:
    """Rename; across devices copy to a temp name, verify the size, rename into place, then delete the source."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        return
    except OSError:
        pass
    tmp = dst.with_name(f".{dst.name}.part")
    try:
        shutil.copy2(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            raise OSError("kích thước file sau khi sao chép không khớp")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    src.unlink()
