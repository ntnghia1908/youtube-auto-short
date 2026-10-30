"""THUMB2: two KT thumbnails for favourites compilations and approved theme revisions."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import theme_plan
from ..compilation import store
from ..compilation.spec import CID_RE
from ..hashing import sha256_file
from ..render.text import TextError, nfc
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PackageError, cover, episode, khaithi_thumbs as kt, record, thumbnail

LABEL = "TUYỂN TẬP KHAI THỊ"
MISSING_COVER = "Bộ kinh chưa có ảnh bìa khai thị"
FILE_NAME = episode.FILE_NAME


@dataclass(frozen=True)
class Source:
    playlist_id: str
    identity: str
    folder: Path
    title: str
    fields: dict


_HONORIFICS = ("hòa thượng", "hoà thượng", "ht.", "ht", "pháp sư", "lão pháp sư")


def _name(text):
    text = " ".join(nfc(text).casefold().replace(".", ". ").split())
    for honorific in sorted(_HONORIFICS, key=len, reverse=True):
        if text.startswith(honorific + " "):
            return text[len(honorific) + 1:].strip()
    return text


def thumb_title(title, speaker):
    """Drop a leading "<speaker> - " (e.g. "Hòa Thượng Tịnh Không - …"): the speaker line already shows it."""
    head, sep, rest = nfc(title).partition(" - ")
    if sep and rest.strip() and _name(head) and _name(head) == _name(speaker):
        return rest.strip()
    return title


def _source(config, pid, identity, folder, title, clips):
    if not isinstance(clips, list) or not clips or not isinstance(clips[0], dict):
        raise PackageError("video ghép không có đoạn đầu hợp lệ")
    ident = clips[0].get("episode_id")
    if not isinstance(ident, str):
        raise PackageError("tập của đoạn đầu không hợp lệ")
    fields = kt.display_fields(config, pid, episode.header(config, ident.removesuffix(".kt")))
    if title is not None and not isinstance(title, str):
        raise PackageError("tiêu đề video ghép không hợp lệ")
    return Source(pid, identity, episode._no_symlinks(folder), nfc(thumb_title(title or "", fields["speaker"])), fields)


def favorite(config, pid, cid, *, pending=False):
    episode.playlist(config, pid)
    if not isinstance(cid, str) or not CID_RE.fullmatch(cid):
        raise PackageError("id video ghép không hợp lệ")
    folder = episode._no_symlinks(store.directory(config.render.output_dir, pid))
    episode._no_symlinks(folder / f"{cid}.json")
    doc = store.read_doc(folder, cid)
    if not doc or doc.get("playlist_id") != pid or not pending and (doc.get("status") != store.DONE
            or not episode._no_symlinks(store.video_path(folder, cid)).is_file()):
        raise PackageError("video ghép chưa sẵn sàng")
    return _source(config, pid, cid, folder / "thumbs" / cid, doc.get("title"), doc.get("items"))


def intro_image(config, source, shape, *, run=None, current=None):
    """Build the very same THUMB2 images at assembly time, with its usual identity/cache."""
    try:
        build(config, source, run=run, current=current)
        return source.folder / read(source)["files"][shape]["file"]
    except PackageError as exc:
        if MISSING_COVER in str(exc):
            raise PackageError(f"{exc} — /playlists/{source.playlist_id}/thumbs") from exc
        raise


def intro_current(config, source, shape, doc, path, *, verify=True):
    """A video is current only while the image used for its prefix is still the current THUMB2 image."""
    from ..render.intro import metadata

    try:
        files = valid_files(config, source)
        image = source.folder / files[shape]["file"]
        return doc.get("intro") == metadata(image) and path.is_file() \
            and (not verify or doc.get("sha256") == sha256_file(path))
    except (PackageError, OSError, ValueError, KeyError, TypeError, TextError):
        return False


def enqueue_intro_rebuild(config, runner, playlist_ids, *, compilations, theme_plans):
    """D-KTI2-5/6 on the live runner: VLT, Cảm Ứng Thiên, Thập Thiện, then optional Địa Tạng.

    Existing KTI1 marks/jobs retain precedence. Queue existing videos first (both shapes), then Shorts;
    the first ten Short episodes per configured start are marked by the shared KTI1 selector.
    This selects rendered artifacts only; it neither creates plans nor calls AI/downloaders.
    """
    from ..web.jobs import KIND_COMPILATION, compilation_key
    from ..web.theme_plan import render_key

    pids = list(dict.fromkeys(playlist_ids))
    for pid in pids:
        episode.playlist(config, pid)
    pending_kt = [j.episode_id for j in runner.jobs() if j.active and j.episode_id.endswith(".kt")
                  and kt.intro_context(config, j.episode_id) is not None]
    runner.priority.mark(pending_kt)
    queued, skipped = [], []

    def videos(pid, *, prioritize):
        if kt.start_episode(config, pid) is None:
            return
        folder = store.directory(config.render.output_dir, pid)
        for doc in sorted(store.list_docs(folder), key=lambda d: d["cid"]):
            cid = doc["cid"]
            if not store.video_path(folder, cid).is_file():
                continue
            key = compilation_key(pid, cid)
            if compilations.intro_current(pid, doc):
                skipped.append(key)
                continue
            target = compilations.rebuild(key, doc)
            if target is None:
                skipped.append(key)
                continue
            if prioritize:
                runner.priority.mark([key])
            _, created = runner.submit(key, KIND_COMPILATION, target)
            (queued if created else skipped).append(key)
        for plan in theme_plans.plans(pid):
            if plan.get("check", {}).get("state") != "approved":
                continue
            ident = plan["plan_id"]
            path = folder / "theme" / f"{ident}-r{plan['revision']}.mp4"
            if not path.is_file():
                continue
            key = render_key(pid, ident)
            doc = read_json_dict(path.with_suffix(".json")) or {}
            if intro_current(config, theme(config, pid, ident), "landscape", doc, path):
                skipped.append(key)
                continue
            if prioritize:
                runner.priority.mark([key])
            _, created = theme_plans.render(pid, ident)
            (queued if created else skipped).append(key)

    for pid in pids[:3]:
        videos(pid, prioritize=True)
    shorts, khaithi = {}, {}
    for pid in pids[:3]:
        shorts[pid] = kt.enqueue_intro_rebuild(config, runner, pid, 1, 999999999,
                                               prioritize_first_ten=True, short=True)
    for pid in pids[3:]:
        videos(pid, prioritize=False)
        shorts[pid] = kt.enqueue_intro_rebuild(config, runner, pid, 1, 999999999, short=True)
        khaithi[pid] = kt.enqueue_intro_rebuild(config, runner, pid, 1, 999999999)
    return dict(queued=queued, skipped=skipped, shorts=shorts, khaithi=khaithi)


def theme(config, pid, plan_id):
    episode.playlist(config, pid)
    if not isinstance(plan_id, str) or not record.PLAN_ID.fullmatch(plan_id):
        raise PackageError("id kế hoạch không hợp lệ")
    episode._no_symlinks(store.directory(config.render.output_dir, pid) / theme_plan.PLANS_DIR / f"{plan_id}.json")
    plan = theme_plan.approved_plan(config, pid, plan_id)
    folder = record.directory(config.render.output_dir, pid, plan_id, plan["revision"])
    return _source(config, pid, f"{plan_id}-r{plan['revision']}", folder, plan.get("title"), plan.get("clips"))


def _inputs(config, source):
    covers = cover.current(config, source.playlist_id)
    if any("kt_" + shape not in covers for shape in thumbnail.EPISODE_SIZES):
        raise PackageError(MISSING_COVER)
    items = kt.portraits(config)
    portrait, digest, facing = kt.choose_portrait(items, source.fields["episode"])
    keys = {}
    for shape in thumbnail.EPISODE_SIZES:
        entry = covers["kt_" + shape]
        # Validate both frames before staging anything, even if an old sidecar claims a cache hit.
        kt.layout(source.title, source.fields, entry["box"], label=LABEL, series_line=source.fields["series"])
        keys[shape] = kt.cache_key(source.title, source.fields["episode"], entry, shape,
            portrait_sha256=digest, portrait_library=[sha for _, sha, _ in items],
            speaker=source.fields["speaker"], series=source.fields["series"],
            hflip=shape == "landscape" and facing == "left", label=LABEL, series_line=source.fields["series"])
    return covers, portrait, facing, keys


def read(source):
    path = episode._no_symlinks(source.folder / "thumbs.json")
    doc = read_json_dict(path)
    if doc is None:
        if path.exists():
            raise PackageError("hồ sơ thumbnail video ghép không hợp lệ")
        return None
    try:
        if doc.get("schema_version") != 1 or doc["playlist_id"] != source.playlist_id \
                or doc["identity"] != source.identity or set(doc["files"]) != set(thumbnail.EPISODE_SIZES):
            raise PackageError("hồ sơ thumbnail video ghép không hợp lệ")
        for shape, entry in doc["files"].items():
            if entry["file"] != f"{shape}-{entry['key']}.jpg" or not FILE_NAME.fullmatch(entry["file"]) \
                    or not record.SHA.fullmatch(entry["sha256"]):
                raise PackageError("file thumbnail video ghép không hợp lệ")
    except (KeyError, TypeError, AttributeError) as exc:
        raise PackageError("hồ sơ thumbnail video ghép không hợp lệ") from exc
    return doc


def valid_files(config, source):
    doc = read(source)
    _, _, _, keys = _inputs(config, source)
    return {shape: entry for shape, entry in (doc or {}).get("files", {}).items()
            if thumbnail.reusable(source.folder, entry, keys[shape], file_pattern=FILE_NAME)
            and episode._no_symlinks(source.folder / entry["file"])}


def build(config, source, *, run=None, current=None):
    covers, portrait, facing, keys = _inputs(config, source)
    folder = episode._no_symlinks(source.folder)
    old = read(source) or {}
    files, staged = {}, []
    counts = dict(built=0, reused=0)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".comp-thumbs-", dir=folder) as tmp:
        for shape in thumbnail.EPISODE_SIZES:
            key = keys[shape]
            previous = old.get("files", {}).get(shape)
            if thumbnail.reusable(folder, previous, key, file_pattern=FILE_NAME):
                files[shape] = previous
                counts["reused"] += 1
                continue
            work = Path(tmp) / shape
            work.mkdir()
            entry = covers["kt_" + shape]
            name = f"{shape}-{key}.jpg"
            image = kt.draw(work, source.title, source.fields, entry, shape,
                episode._no_symlinks(cover.directory(config, source.playlist_id) / entry["file"]), name,
                portrait=portrait, facing=facing, label=LABEL, series_line=source.fields["series"], run=run)
            files[shape] = dict(file=name, key=key, sha256=sha256_file(image))
            staged.append((image, episode._no_symlinks(folder / name)))
            counts["built"] += 1
        # A queued / running job may outlive a title edit, cover install or plan revision change.
        latest = current() if current else source
        if latest != source or _inputs(config, latest)[3] != keys:
            raise PackageError("đầu vào thumbnail đã đổi; hãy dựng lại")
        for image, destination in staged:
            os.replace(image, destination)
        if staged or files != old.get("files"):
            atomic_write_json(episode._no_symlinks(folder / "thumbs.json"), dict(schema_version=1,
                playlist_id=source.playlist_id, identity=source.identity, files=files, updated_at=utc_now()))
    keep = {entry["file"] for entry in files.values()}
    for path in folder.iterdir():
        if FILE_NAME.fullmatch(path.name) and path.name not in keep:
            episode._no_symlinks(path).unlink()
    return counts
