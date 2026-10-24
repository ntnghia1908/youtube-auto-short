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
            seen.add(a["id"])
        return doc["assets"]
    except (OSError, ValueError, TypeError) as exc:
        raise PackageError("cannot read asset library") from exc


def _save(asset_dir, entries):
    atomic_write_json(asset_dir / "library.json", {"schema_version": 1, "assets": entries})


def add(asset_dir: Path, file: Path, *, kind: str, source: str, license: str = "", tags=(), run=None) -> dict:
    if kind not in KINDS or not source.strip():
        raise PackageError("asset needs a kind and source")
    ext = file.suffix.lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9]{1,8}", ext):
        raise PackageError("invalid asset extension")
    entries = list_assets(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".asset-", dir=asset_dir) as tmp:
        staged = Path(tmp) / ("media." + ext)
        shutil.copyfile(file, staged)
        digest = sha256_file(staged)
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
