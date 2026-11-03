"""Local, content-addressed asset library. No downloads or web imports."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

from ..hashing import sha256_file
from ..render.stage import _run, probe_media
from ..workspace import atomic_write_json
from . import PackageError

SHA = re.compile(r"[a-f0-9]{64}")
ASSET_FILE = re.compile(r"[a-f0-9]{64}\.[a-z0-9]{1,8}")
KINDS = ("image", "loop", "music")


def list_assets(asset_dir: Path) -> list[dict]:
    path = asset_dir / "library.json"
    if not path.exists():
        return []
    try:
        if path.is_symlink():
            raise PackageError("asset library must not be a symlink")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("assets"), list):
            raise PackageError("invalid asset library")
        seen = set()
        for a in doc["assets"]:
            if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not SHA.fullmatch(a["id"]) \
                    or a["id"] in seen or not isinstance(a.get("file"), str) \
                    or not ASSET_FILE.fullmatch(a["file"]) or not a["file"].startswith(a["id"] + ".") \
                    or a.get("kind") not in KINDS or not isinstance(a.get("approved"), bool) \
                    or not all(isinstance(a.get(k), str) for k in ("source", "license")) \
                    or not isinstance(a.get("tags"), list) or not all(isinstance(t, str) for t in a["tags"]) \
                    or not all(type(a.get(k)) in (int, float) and math.isfinite(a[k]) and a[k] >= 0
                               for k in ("width", "height", "duration")):
                raise PackageError("invalid asset entry")
            _metadata(a)
            seen.add(a["id"])
        return doc["assets"]
    except (OSError, ValueError, TypeError) as exc:
        raise PackageError("cannot read asset library") from exc


def _save(asset_dir, entries):
    atomic_write_json(asset_dir / "library.json", {"schema_version": 1, "assets": entries})


def add(asset_dir: Path, file: Path, *, kind: str, source: str, license: str = "", tags=(),
        title=None, artist=None, attribution=None, loop_end=None, run=None, expected_sha=None) -> dict:
    if kind not in KINDS or not source.strip():
        raise PackageError("asset needs a kind and source")
    metadata = _metadata(dict(title=title, artist=artist, attribution=attribution, loop_end=loop_end))
    ext = file.suffix.lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9]{1,8}", ext):
        raise PackageError("invalid asset extension")
    entries = list_assets(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".asset-", dir=asset_dir) as tmp:
        staged = Path(tmp) / ("media." + ext)
        shutil.copyfile(file, staged)
        digest = sha256_file(staged)
        if expected_sha is not None and digest != expected_sha:
            raise PackageError("music sha256 changed during import")
        existing = next((a for a in entries if a["id"] == digest), None)
        if existing is not None:
            return existing  # importing again cannot change provenance or approval
        info = probe_media(staged, run or _run)
        video = info["video"]
        if (kind in ("image", "loop") and video is None) or (kind == "music" and info["audio"] is None):
            raise PackageError("asset does not contain the required media stream")
        duration = info["duration"]
        if not math.isfinite(duration) or duration < 0 or (kind != "image" and duration <= 0):
            raise PackageError("invalid asset duration")
        entry = dict(id=digest, file=f"{digest}.{ext}", kind=kind, tags=list(tags), source=source.strip(),
                     license=license.strip(), approved=False, width=int(video["width"]) if video else 0,
                     height=int(video["height"]) if video else 0, duration=duration)
        if loop_end is not None and loop_end > duration:
            raise PackageError("loop_end exceeds asset duration")
        entry.update(metadata)
        os.replace(staged, asset_dir / entry["file"])
        _save(asset_dir, [*entries, entry])
        return entry


def usable(asset_dir: Path, ident: str, *, kind=None) -> tuple[dict, Path]:
    if not isinstance(ident, str) or not SHA.fullmatch(ident):
        raise PackageError("invalid asset id")
    entry = next((a for a in list_assets(asset_dir) if a["id"] == ident), None)
    if entry is None or not entry["approved"] or not entry["license"].strip() or not entry["source"].strip():
        raise PackageError("asset must be approved and have source + license")
    if kind is not None and entry["kind"] != kind:
        raise PackageError(f"asset must be {kind}")
    path = asset_dir / entry["file"]
    if path.is_symlink() or not path.is_file() or sha256_file(path) != ident:
        raise PackageError("asset file is missing or changed")
    return entry, path


def approve(asset_dir: Path, ident: str) -> dict:
    entries = list_assets(asset_dir)
    entry = next((a for a in entries if a["id"] == ident), None)
    if entry is None or not entry["license"].strip() or not entry["source"].strip():
        raise PackageError("asset needs source + license before approval")
    entry["approved"] = True
    usable_entry = asset_dir / entry["file"]
    if usable_entry.is_symlink() or sha256_file(usable_entry) != entry["id"]:
        raise PackageError("asset file changed")
    _save(asset_dir, entries)
    return entry


def import_post_images(config, *, license: str, run=None) -> list[dict]:
    if not license.strip():
        raise PackageError("import-post-images requires --license")
    # Reuse the post library's existing format/name validation, read only.
    from ..post.images import list_images
    folder = config.post.image_dir
    sources = {}
    if (folder / "sources.tsv").is_file():
        for line in (folder / "sources.tsv").read_text(encoding="utf-8").splitlines():
            name, _, source = line.partition("\t")
            if source.strip():
                sources[name] = source
    return [add(config.packaging.asset_dir, folder / image.name, kind="image", license=license, tags=[Path(image.name).stem],
                source=sources.get(image.name) or (folder / image.name).absolute().as_uri(), run=run)
            for image in list_images(folder)]


def _metadata(values):
    result = {}
    for key in ("title", "artist", "attribution"):
        value = values.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise PackageError(f"{key} must be text")
            result[key] = value.strip()
    end = values.get("loop_end")
    if end is not None:
        if type(end) not in (int, float) or not math.isfinite(end) or end <= 0:
            raise PackageError("loop_end must be a positive number")
        result["loop_end"] = float(end)
    return result


def unapprove(asset_dir: Path, ident: str) -> dict:
    entries = list_assets(asset_dir)
    entry = next((a for a in entries if a["id"] == ident), None)
    if entry is None:
        raise PackageError("unknown asset id")
    entry["approved"] = False
    _save(asset_dir, entries)
    return entry


def import_music(asset_dir: Path, manifest: Path, directory: Path, *, run=None) -> dict:
    """Refuse pending entries explicitly; preflight all verified files before importing any."""
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        tracks = doc["tracks"]
        if doc.get("schema_version") != 1 or not isinstance(tracks, list):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PackageError("invalid music manifest") from exc
    accepted, rejected = [], []
    for track in tracks:
        if not isinstance(track, dict):
            raise PackageError("invalid music track")
        if track.get("license_status") != "verified":
            rejected.append(dict(id=track.get("id"), reason="license pending / not verified"))
            continue
        name = track.get("filename")
        if not isinstance(name, str) or Path(name).name != name or "\\" in name or name in (".", ".."):
            raise PackageError("invalid music filename")
        path = directory / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise PackageError(f"missing music file: {name}")
        if sha256_file(path) != track.get("sha256"):
            raise PackageError(f"music sha256 mismatch: {name}")
        if not all(isinstance(track.get(k), str) and track[k].strip() for k in ("source", "license")):
            raise PackageError("verified music needs source + license")
        _metadata(track)
        accepted.append((track, path))
    imported = [add(asset_dir, path, kind="music", source=t["source"], license=t["license"],
                    tags=[t["id"]] if isinstance(t.get("id"), str) else [], run=run, expected_sha=t["sha256"],
                    **{k: t.get(k) for k in ("title", "artist", "attribution", "loop_end")})
                for t, path in accepted]
    return dict(imported=imported, rejected=rejected)
