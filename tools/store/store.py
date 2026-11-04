"""Loopback-only HD2 store. Python 3.11+, standard library, no project imports."""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}(?:\.kt)?")
SERIES_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
# Clip id rule: src/auto_short/web/episodes.py _CLIP_ID_RE, plus the .mp4 suffix.
CLIP = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\.mp4")
SHA256 = re.compile(r"[a-fA-F0-9]{64}")
COLUMNS = ("tap", "loai", "file", "video_id", "tieu_de")
KINDS = {"HD": "hd", "Doc": "vertical", "Goc": "source"}
MAX_BODY = 20 * 1024**3
CHUNK = 1024 * 1024
REVISION = re.compile(r" \(r[0-9]+\)(?=\.mp4$)")
HD_NAME = re.compile(r"^\[(HD|HD Mobile|HD Dọc)\] (.+) - Tập ([0-9]+)\.mp4$")
DEFAULT_SPEAKER = "PS. Tịnh Không"
MEDIA_DIRS = ("HD", "HD Mobile", "Goc", "Hinh", "Short", "KhaiThi")


def subdir(kind: str, name: str) -> Path:
    """Fixed directory names; only the numeric episode is derived from the filename."""
    if name.endswith(".jpg"):
        return Path("Hinh")
    if kind == "short":
        category = "KhaiThi" if name.startswith("[KhaiThi] ") else "Short"
        episode = re.search(r" - Tập ([0-9]+)(?= - |\.mp4$| \(r[0-9]+\)\.mp4$)", name)
        return Path(category) / (f"Tap {int(episode[1]):02d}" if episode else "Khac")
    return Path({"hd": "HD", "vertical": "HD Mobile", "source": "Goc"}[kind])


def media_path(folder: Path, kind: str, name: str, *, existing: bool = True) -> Path:
    """Find media in the new layout first, then the flat legacy tree; otherwise its new path."""
    validate_name(name[:-4] + ".mp4" if name.endswith(".jpg") else name)
    parent = no_links(folder / subdir(kind, name))
    if parent.exists() and not parent.is_dir():
        raise StoreError(400, "Media directory must be a directory")
    target = inside(parent, name)
    # Validate both locations even when the new file exists.
    legacy = inside(folder, name)
    return legacy if existing and not target.exists() and legacy.exists() else target


def media_kind(name: str) -> str | None:
    """Recognize files safe to reorganize; unknown files stay where they are."""
    tag = re.match(r"^\[(HD|HD Mobile|HD Dọc|Goc|Short|KhaiThi)\] ", name)
    if tag is None or not name.endswith((".mp4", ".jpg")):
        return None
    validate_name(name[:-4] + ".mp4")
    return {"HD": "hd", "HD Mobile": "vertical", "HD Dọc": "vertical",
            "Goc": "source", "Short": "short", "KhaiThi": "short"}[tag[1]]


def hd_name(name: str, speaker: str = DEFAULT_SPEAKER) -> str:
    """Derive the current HD name from its filename, never from optional CSV fields."""
    match = HD_NAME.fullmatch(REVISION.sub("", name))
    if match is None:
        raise StoreError(400, "HD file name must contain a series and episode number")
    tag, title, number = match.groups()
    if "tịnh không" not in title.casefold() and not title.endswith(" - " + speaker):
        title += " - " + speaker
    return validate_name(f"[{tag}] {title} - Tập {number}.mp4")


def vertical_key(name: str) -> str:
    # Same convention as PUB2: the optional segment before 'Tập' is the speaker.
    return re.sub(r" - .+? - Tập (?=[0-9]+\.mp4$)", " - Tập ", REVISION.sub("", name))


class StoreError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def no_links(path: Path) -> Path:
    """Check every existing ancestor, including Windows junctions/reparse points."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise StoreError(400, "Symlinks/reparse points are not allowed")
    return path


def inside(folder: Path, name: str) -> Path:
    folder = no_links(folder)
    path = no_links(folder / name)
    if not path.resolve().is_relative_to(folder.resolve()):
        raise StoreError(400, "Path outside series folder")
    if path.exists() and not path.is_file():
        raise StoreError(400, "Expected a regular file")
    return path


def validate_name(name: str) -> str:
    # Also reject Windows ADS, device names, and characters invalid on NTFS.
    if (not name or ".." in name or any(c in name for c in '/\\:<>"|?*')
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or not name.endswith(".mp4") or name.endswith((" ", "."))
            or re.match(r"(?i)^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)", name)):
        raise StoreError(400, "Invalid mp4 file name")
    return name


def validate_identity(video_id: str, kind: str, clip: str | None = None) -> None:
    if (not VIDEO_ID.fullmatch(video_id) or kind not in (*KINDS.values(), "short")
            or (kind == "short" and (not isinstance(clip, str) or not CLIP.fullmatch(clip)))
            or (kind != "short" and clip is not None)):
        raise StoreError(400, "Invalid video_id/kind")


def parse_range(value: str, size: int) -> tuple[int, int]:
    """Return inclusive byte bounds; only one HTTP byte range is supported."""
    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", value)
    if not match or not any(match.groups()) or size <= 0:
        raise StoreError(416, "Invalid range")
    first, last = match.groups()
    try:
        if not first:
            length = int(last)
            if length <= 0:
                raise ValueError
            return max(0, size - length), size - 1
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
        if start >= size or start > end:
            raise ValueError
        return start, end
    except ValueError:
        raise StoreError(416, "Unsatisfiable range") from None


def load_config(config_file: Path) -> dict:
    base = no_links(config_file).parent
    with config_file.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise StoreError(400, "Config must be an object")
    port = config.get("port", 18090)
    if type(port) is not int or not 1 <= port <= 65535:
        raise StoreError(400, "Invalid port")
    for key in ("root", "token_file"):
        value = config.get(key, "token.txt" if key == "token_file" else None)
        if not isinstance(value, str) or not value.strip():
            raise StoreError(400, f"Invalid {key}")
        config[key] = no_links(base / value)
    series = config.get("series", {})
    if not isinstance(series, dict):
        raise StoreError(400, "Invalid series mapping")
    config["series"] = {}
    for ident, folder in series.items():
        if not SERIES_ID.fullmatch(ident) or not isinstance(folder, str) or not folder.strip():
            raise StoreError(400, "Invalid series mapping")
        config["series"][ident] = no_links(base / folder)
    config["port"] = port
    return config


class Store:
    def __init__(self, config: dict):
        self.config = config
        self.root = no_links(config["root"])
        self.token = no_links(config["token_file"]).read_text(encoding="utf-8-sig").strip().encode()
        if not self.token or any(c in self.token for c in (b"\r", b"\n")):
            raise StoreError(400, "Token file must contain one nonempty token")
        for folder in (self.root, *config["series"].values()):
            if not no_links(folder).is_dir():
                raise StoreError(400, "Configured folder does not exist")
        self._cache = {}
        self._lock = threading.RLock()
        # Serialize PUTs, including metadata publication; readers need not wait for the upload.
        self._put_lock = threading.Lock()

    def authorized(self, header: str) -> bool:
        return header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), self.token)

    def folders(self) -> dict[str, Path]:
        result = dict(self.config["series"])
        for folder in no_links(self.root).iterdir():
            if SERIES_ID.fullmatch(folder.name) and folder.name not in result:
                if no_links(folder).is_dir():
                    result[folder.name] = folder
        return result

    def _rows(self, folder: Path) -> list[dict]:
        # The current backup template writes danh-sach.csv; index.csv takes precedence.
        paths = [inside(folder, name) for name in ("danh-sach.csv", "index.csv", "SHA256SUMS.txt", "index-short.csv")]
        signature = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)
        cached = self._cache.get(folder)
        if cached and cached[0] == signature:
            return cached[1]
        sums = {}
        if paths[2].exists():
            with paths[2].open(encoding="utf-8-sig") as stream:
                for line in stream:
                    sha, sep, name = line.rstrip("\r\n").partition("  ")
                    if sep and SHA256.fullmatch(sha):
                        sums[name] = sha.lower()
        rows = {}
        for index in paths[:2]:
            if not index.exists():
                continue
            with index.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if not {"video_id", "loai", "file"}.issubset(reader.fieldnames or []):
                    raise StoreError(400, "Invalid CSV columns")
                for row in reader:
                    ident, kind, name = row["video_id"], KINDS.get(row["loai"]), row["file"]
                    if not ident or not VIDEO_ID.fullmatch(ident) or not kind or not name:
                        continue
                    try:
                        validate_name(name)
                    except StoreError:
                        continue
                    if name in sums:
                        rows[ident, kind] = dict(video_id=ident, kind=kind, file=name, sha256=sums[name])
        if paths[3].exists():
            with paths[3].open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if not {"video_id", "clip", "file"}.issubset(reader.fieldnames or []):
                    raise StoreError(400, "Invalid Short CSV columns")
                for row in reader:
                    ident, clip, name = row["video_id"], row["clip"], row["file"]
                    try:
                        validate_identity(ident, "short", clip)
                        validate_name(name)
                    except (StoreError, TypeError):
                        continue
                    if name in sums:
                        rows[ident, "short", clip] = dict(video_id=ident, kind="short", clip=clip,
                                                         file=name, sha256=sums[name])
        result = list(rows.values())
        self._cache[folder] = (signature, result)
        return result

    def index(self) -> list[dict]:
        with self._lock:
            entries = {}
            for series, folder in sorted(self.folders().items()):
                for row in self._rows(folder):
                    path = media_path(folder, row["kind"], row["file"])
                    if path.is_file():
                        key = (row["video_id"], row["kind"], row.get("clip", ""))
                        if key in entries:
                            raise StoreError(409, "Duplicate video_id/kind across series")
                        entries[key] = dict(row, series=series, size=path.stat().st_size)
            return [entries[key] for key in sorted(entries)]

    def lookup(self, video_id: str, kind: str, clip: str | None = None) -> tuple[dict, Path]:
        validate_identity(video_id, kind, clip)
        if kind != "short":
            for row in self.index():
                if (row["video_id"], row["kind"]) == (video_id, kind):
                    return row, media_path(self.folders()[row["series"]], kind, row["file"])
            raise StoreError(404, "Unknown file")
        # Read cached catalogues, stat only the requested identity (thousands of Shorts per series).
        found = []
        with self._lock:
            for series, folder in self.folders().items():
                for row in self._rows(folder):
                    if (row["video_id"], row["kind"], row.get("clip")) == (video_id, kind, clip):
                        path = media_path(folder, kind, row["file"])
                        if path.is_file():
                            found.append((dict(row, series=series, size=path.stat().st_size), path))
        if len(found) > 1:
            raise StoreError(409, "Duplicate identity across series")
        if found:
            return found[0]
        raise StoreError(404, "Unknown file")

    def _metadata(self, folder: Path, kind: str = "hd") -> tuple[Path, Path, list[str]]:
        index = inside(folder, "index-short.csv" if kind == "short" else "index.csv")
        sums = inside(folder, "SHA256SUMS.txt")
        columns = ("video_id", "clip", "file") if kind == "short" else COLUMNS
        fields = list(columns)
        source = index
        if kind != "short" and (not source.exists() or not source.stat().st_size):
            source = inside(folder, "danh-sach.csv")
        if source.exists() and source.stat().st_size:
            with source.open(encoding="utf-8-sig", newline="") as stream:
                fields = next(csv.reader(stream))
            if not set(columns).issubset(fields):
                raise StoreError(400, "Invalid CSV columns for append")
        return index, sums, fields

    def _publish(self, folder: Path, video_id: str, kind: str, name: str, sha: str,
                 clip: str | None = None) -> None:
        """Preserve the backup Export-Csv column order, including existing optional columns."""
        index, sums, fields = self._metadata(folder, kind)
        row = dict.fromkeys(fields, "")
        row.update(video_id=video_id, file=name)
        if kind == "short":
            row["clip"] = clip
        else:
            row["loai"] = next(label for label, value in KINDS.items() if value == kind)
        # A backup file might lack its final newline. Keep the appended record separate.
        for path in (sums, index):
            if path.exists() and path.stat().st_size:
                with path.open("rb+") as stream:
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        stream.write(b"\r\n")
        with sums.open("a", encoding="utf-8", newline="") as stream:
            stream.write(f"{sha}  {name}\r\n")
            stream.flush()
            os.fsync(stream.fileno())
        if kind == "short":
            # One current row per clip; old media and checksum lines remain archival copies.
            rows = []
            if index.exists() and index.stat().st_size:
                with index.open(encoding="utf-8-sig", newline="") as stream:
                    rows = [r for r in csv.DictReader(stream)
                            if (r["video_id"], r["clip"]) != (video_id, clip)]
            rows.append(row)
            temp = index.with_name(index.name + ".part")
            owned_temp = False
            try:
                with temp.open("x", encoding="utf-8", newline="") as stream:
                    owned_temp = True
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, index)
            finally:
                if owned_temp:
                    temp.unlink(missing_ok=True)
            self._cache.pop(folder, None)
            return
        needs_header = not index.exists() or not index.stat().st_size
        with index.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            if needs_header:
                writer.writeheader()
            writer.writerow(row)
        self._cache.pop(folder, None)

    def _archive_plan(self, folder: Path, paths: list[Path]) -> list[tuple[Path, Path]]:
        """Reserve unique names in _cu without overwriting any previous archive."""
        archive = no_links(folder / "_cu")
        if archive.exists() and not archive.is_dir():
            raise StoreError(409, "Archive must be a directory")
        moves, reserved = [], set()
        for path in sorted(set(paths)):
            if not no_links(path).resolve().is_relative_to(no_links(folder).resolve()):
                raise StoreError(400, "Path outside series folder")
            inside(path.parent, path.name)
            target = inside(archive, path.name)
            revision = 2
            while target.exists() or target in reserved:
                target = inside(archive, f"{path.stem} (r{revision}).mp4")
                revision += 1
            reserved.add(target)
            moves.append((path, target))
        return moves

    def _media_files(self, folder: Path) -> list[Path]:
        """Check the tree without following links; refuse pending uploads before any move."""
        def fail(error):
            raise error

        media = []
        for base, dirs, files in os.walk(no_links(folder), onerror=fail):
            parent = no_links(Path(base))
            for name in dirs:
                no_links(parent / name)
            for name in files:
                path = inside(parent, name)
                if name.endswith(".part"):
                    raise StoreError(409, "Partial files exist in series")
                relative = path.relative_to(folder)
                if len(relative.parts) == 1 or relative.parts[0] in MEDIA_DIRS:
                    if name.endswith((".mp4", ".jpg")):
                        media.append(path)
        return media

    def reorganize(self, series: str, *, apply: bool = False) -> tuple[list[tuple[Path, Path]], list[Path]]:
        """Preflight every selected series before moving anything, including for 'all'."""
        if series != "all" and not SERIES_ID.fullmatch(series):
            raise StoreError(400, "Invalid series")
        with self._put_lock, self._lock:
            folders = self.folders()
            if series != "all":
                if series not in folders:
                    raise StoreError(404, "Unknown series")
                folders = {series: folders[series]}
            moves, unknown, reserved = [], [], set()
            metadata = {"index.csv", "index-short.csv", "danh-sach.csv", "SHA256SUMS.txt", "backup-log.txt"}
            for folder in folders.values():
                self._media_files(folder)
                for path in sorted(folder.iterdir()):
                    if path.name.startswith("_cu") or path.name in metadata or path.is_dir():
                        continue
                    source = inside(folder, path.name)
                    kind = media_kind(path.name)
                    if kind is None:
                        unknown.append(source)
                        continue
                    target = media_path(folder, kind, path.name, existing=False)
                    if target.exists() or target in reserved:
                        raise StoreError(409, f"Reorganize destination already exists: {source} -> {target}")
                    reserved.add(target)
                    moves.append((source, target))
                inside(folder, "backup-log.txt")
            if apply:
                for source, target in moves:
                    no_links(target.parent).mkdir(parents=True, exist_ok=True)
                    inside(source.parent, source.name).rename(inside(target.parent, target.name))
                    # Log each completed move, without changing the media catalogues.
                    with inside(source.parent, "backup-log.txt").open("a", encoding="utf-8") as log:
                        log.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} reorganize: "
                                  f"{source.name} -> {target.relative_to(source.parent)}\n")
                for folder in folders.values():
                    self._cache.pop(folder, None)
            return moves, unknown

    def rename_vertical(self, series: str, *, apply: bool = False,
                        speaker: str = DEFAULT_SPEAKER,
                        format: str = "{tag} {title} - Tập {episode}.mp4") -> list[dict]:
        """Plan HD + vertical renames, append catalogue records and archive older media."""
        if not SERIES_ID.fullmatch(series):
            raise StoreError(400, "Invalid series")
        with self._put_lock, self._lock:
            folder = self.folders().get(series)
            if folder is None:
                raise StoreError(404, "Unknown series")
            media = [p for p in self._media_files(folder) if p.suffix == ".mp4"]
            rows = self._rows(folder)
            self._metadata(folder)
            # Retain historical identity attribution even if a previous file used another title.
            history = {}
            for filename in ("danh-sach.csv", "index.csv"):
                index = inside(folder, filename)
                if index.exists():
                    with index.open(encoding="utf-8-sig", newline="") as stream:
                        for row in csv.DictReader(stream):
                            history[row["file"]] = (row["video_id"], KINDS.get(row["loai"]))
            current = {r["file"] for r in rows}
            planned, targets, archived = [], set(), set()
            for row in rows:
                if row["kind"] not in ("hd", "vertical"):
                    continue
                old = media_path(folder, row["kind"], row["file"])
                if not old.is_file():
                    raise StoreError(409, "Current HD file is missing")
                canonical = HD_NAME.fullmatch(hd_name(row["file"], speaker))
                tag, title, number = canonical.groups()
                name = validate_name(format.format(tag=f"[{tag}]", title=title, episode=number))
                # A custom format must keep the recognized HD identity and naming convention.
                if name != hd_name(name, speaker) or vertical_key(name) != vertical_key(row["file"]):
                    raise StoreError(400, "Format must preserve the HD series, tag and episode")
                dest = media_path(folder, row["kind"], name)
                if name in targets or (name != row["file"] and name in current):
                    raise StoreError(409, "Rename target belongs to another current file")
                targets.add(name)
                key = (row["video_id"], row["kind"])
                older = [p for p in media if p.name not in current and
                         (history.get(p.name) == key or
                          (p.name not in history and vertical_key(p.name) == vertical_key(row["file"])))]
                if archived.intersection(older):
                    raise StoreError(409, "Ambiguous archival identity")
                if dest.exists() and dest != old and dest not in older:
                    raise StoreError(409, "Rename destination already exists")
                archived.update(older)
                planned.append(dict(row, old=row["file"], file=name, archive=[p.name for p in older]))
            moves = self._archive_plan(folder, list(archived))
            if apply:
                for source, target in moves:
                    target.parent.mkdir(exist_ok=True)
                    source.rename(target)
                for row in planned:
                    if row["old"] != row["file"]:
                        old = media_path(folder, row["kind"], row["old"])
                        dest = media_path(folder, row["kind"], row["file"])
                        no_links(dest.parent).mkdir(parents=True, exist_ok=True)
                        old.rename(dest)
                        self._publish(folder, row["video_id"], row["kind"], row["file"], row["sha256"])
            return planned

    def _replaced_metadata(self, folder: Path, video_id: str, name: str, sha: str, size: int) -> None:
        index = inside(folder, "index.csv" if (folder / "index.csv").exists() else "danh-sach.csv")
        sums = inside(folder, "SHA256SUMS.txt")
        with index.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            if row.get("video_id") == video_id and row.get("file") == name:
                for key, value in (("sha256", sha), ("size", str(size))):
                    if key in fields:
                        row[key] = value
        checksums = sums.read_text(encoding="utf-8-sig").splitlines() if sums.exists() else []
        checksums = [line for line in checksums if line[66:].lstrip(" *") != name]
        checksums.append(f"{sha}  {name}")
        for path in (sums, index):
            temp = path.with_name(path.name + ".replace.part")
            owned = False
            try:
                with temp.open("x", encoding="utf-8", newline="") as stream:
                    owned = True
                    if path == index:
                        writer = csv.DictWriter(stream, fieldnames=fields)
                        writer.writeheader()
                        writer.writerows(rows)
                    else:
                        stream.write("\r\n".join(checksums) + "\r\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, path)
            finally:
                if owned:
                    temp.unlink(missing_ok=True)
        self._cache.pop(folder, None)

    def put(self, video_id: str, kind: str, series: str, name: str,
            sha: str, stream, length: int, clip: str | None = None,
            replace_sha: str | None = None) -> int:
        """Stream exactly Content-Length bytes. Return 201 (created) or 200 (same file)."""
        validate_identity(video_id, kind, clip)
        validate_name(name)
        if not SERIES_ID.fullmatch(series) or not SHA256.fullmatch(sha):
            raise StoreError(400, "Invalid series/sha256")
        if length < 0 or length > MAX_BODY:
            raise StoreError(413, "Body exceeds 20 GiB limit")
        sha = sha.lower()
        if replace_sha is not None and (kind != "hd" or not SHA256.fullmatch(replace_sha)):
            raise StoreError(400, "Replacement requires hd and a valid current sha256")
        replace_sha = replace_sha.lower() if replace_sha is not None else None
        with self._put_lock:
            folder = no_links(self.config["series"].get(series, self.root / series))
            folder.mkdir(parents=True, exist_ok=True)
            dest = media_path(folder, kind, name)
            part = inside(dest.parent, name + ".part")
            with self._lock:
                entries = self.index()
                current = None
                for row in entries:
                    same_key = (row["video_id"], row["kind"], row.get("clip")) == (video_id, kind, clip)
                    same_path = media_path(self.folders()[row["series"]], row["kind"], row["file"]) == dest
                    if same_key and replace_sha is not None:
                        if not same_path or row["sha256"] != replace_sha:
                            raise StoreError(409, "Replacement sha256 or path does not match")
                        current = row
                        continue
                    if same_key and kind in ("short", "vertical"):
                        base = REVISION.sub("", row["file"])
                        matches = (vertical_key(name) == vertical_key(row["file"])) if kind == "vertical" else name in (base, row["file"])
                        if row["series"] != series or not matches:
                            raise StoreError(409, "Identity already has a different file")
                        current = row
                        continue
                    if same_key and (not same_path or row["sha256"] != sha):
                        raise StoreError(409, "Identity already has a different file")
                    if same_path and not same_key:
                        raise StoreError(409, "File belongs to another identity")
                # Validate metadata before creating a file.
                self._rows(folder)
                self._metadata(folder, kind)
                if replace_sha is not None and current is None:
                    raise StoreError(409, "Replacement requires an existing HD")
                if current is not None and replace_sha is None:
                    if current["sha256"] == sha:
                        name = current["file"]
                        dest = media_path(folder, kind, name)
                        part = inside(dest.parent, name + ".part")
                    elif kind == "vertical":
                        incoming = HD_NAME.fullmatch(REVISION.sub("", name))
                        # Prefer the sender's explicit speaker; legacy senders retain the current label.
                        candidate = name if incoming and " - " in incoming[2] else current["file"]
                        parsed = HD_NAME.fullmatch(REVISION.sub("", candidate))
                        speaker = (parsed[2].rsplit(" - ", 1)[1] if parsed and " - " in parsed[2]
                                   else self.config.get("speaker_label", DEFAULT_SPEAKER))
                        name = hd_name(candidate, speaker)
                        dest = media_path(folder, kind, name)
                        part = inside(dest.parent, name + ".part")
                    else:
                        base = REVISION.sub("", current["file"])
                        revision = 2
                        while True:
                            name = f"{base[:-4]} (r{revision}).mp4"
                            dest = media_path(folder, kind, name)
                            part = inside(dest.parent, name + ".part")
                            if not dest.exists() and not part.exists():
                                break
                            revision += 1
            replacing_vertical = kind == "vertical" and current is not None and current["sha256"] != sha
            archive_moves = self._archive_plan(folder, [media_path(folder, kind, current["file"])]) if replacing_vertical else []
            if replacing_vertical and dest.exists() and dest.name != current["file"]:
                raise StoreError(409, "Vertical destination already exists")
            if replacing_vertical:
                dest = media_path(folder, kind, name, existing=False)
                part = inside(dest.parent, name + ".part")
            if dest.exists() and not replacing_vertical:
                with dest.open("rb") as existing:
                    actual = hashlib.file_digest(existing, "sha256").hexdigest()
                if replace_sha is not None and actual != replace_sha:
                    raise StoreError(409, "Replacement sha256 does not match existing bytes")
                if replace_sha is None and actual != sha:
                    raise StoreError(409, "Existing file has a different sha256")
                if not any((r["video_id"], r["kind"], r.get("clip")) == (video_id, kind, clip) for r in entries):
                    with self._lock:
                        self._publish(folder, video_id, kind, name, sha, clip)
                if replace_sha is None:
                    return 200
            elif replace_sha is not None:
                raise StoreError(409, "Replacement file disappeared")
            # Refuse legacy partials too; a new upload must not silently abandon them.
            legacy_part = inside(folder, name + ".part")
            if legacy_part.exists() and legacy_part != part:
                raise StoreError(409, "Partial file already exists")
            no_links(dest.parent).mkdir(parents=True, exist_ok=True)
            owned_part = False
            try:
                # Exclusive creation refuses stale/foreign .part files rather than overwriting them.
                try:
                    output = part.open("xb")
                    owned_part = True
                except FileExistsError:
                    raise StoreError(409, "Partial file already exists") from None
                with output:
                    digest = hashlib.sha256()
                    remaining = length
                    while remaining:
                        block = stream.read(min(remaining, CHUNK))
                        if not block:
                            raise StoreError(400, "Incomplete request body")
                        output.write(block)
                        digest.update(block)
                        remaining -= len(block)
                    if digest.hexdigest() != sha:
                        raise StoreError(422, "SHA256 mismatch")
                    output.flush()
                    os.fsync(output.fileno())
                # Recheck immediately before the atomic rename and metadata writes.
                with self._lock:
                    inside(dest.parent, name)
                    inside(part.parent, part.name)
                    if replace_sha is not None:
                        with dest.open("rb") as existing:
                            actual = hashlib.file_digest(existing, "sha256").hexdigest()
                        if actual != replace_sha:
                            raise StoreError(409, "Replacement file changed during upload")
                    elif dest.exists() and not (replacing_vertical and dest.name == current["file"]):
                        raise StoreError(409, "Destination appeared during upload")
                    for source, target in archive_moves:
                        no_links(target.parent).mkdir(exist_ok=True)
                        inside(target.parent, target.name)
                        if target.exists():
                            raise StoreError(409, "Archive destination appeared during upload")
                        inside(source.parent, source.name).rename(target)
                    try:
                        os.replace(part, dest)
                    except OSError:
                        for source, target in reversed(archive_moves):
                            target.rename(source)
                        raise
                    if replace_sha is not None:
                        self._replaced_metadata(folder, video_id, name, sha, length)
                    else:
                        self._publish(folder, video_id, kind, name, sha, clip)
                return 200 if replace_sha is not None else 201
            finally:
                # Only clean up a part created by this request.
                if owned_part and part.exists():
                    inside(part.parent, part.name).unlink()


class StoreHandler(BaseHTTPRequestHandler):
    server_version = "AutoShortStore/1"

    def log_message(self, format, *args):
        # Never log headers, raw request targets or exception text (may contain credentials).
        pass

    def log_request(self, code="-", size="-"):
        method = self.command if self.command in {"GET", "HEAD", "PUT", "POST", "DELETE"} else "OTHER"
        print(f"store request: {method} {code}", file=sys.stderr)

    def _reply(self, status: int, body=b"", headers=None):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self):
        store = self.server.store
        try:
            auth = self.headers.get_all("Authorization", [])
            if len(auth) != 1 or not store.authorized(auth[0]):
                self._reply(401, b'{"error":"Unauthorized"}', {"WWW-Authenticate": "Bearer"})
                return
            target = urlsplit(self.path)
            path = unquote(target.path, errors="strict")
            if path == "/index" and self.command == "GET":
                self._reply(200, json.dumps(store.index(), ensure_ascii=False).encode())
                return
            parts = path.split("/")
            if len(parts) not in (4, 5) or parts[:2] != ["", "files"]:
                raise StoreError(404, "Unknown endpoint")
            video_id, kind = parts[2:4]
            clip = parts[4] if len(parts) == 5 else None
            validate_identity(video_id, kind, clip)
            if self.command == "PUT":
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding"):
                    raise StoreError(400, "Transfer-Encoding is not supported")
                if not lengths:
                    raise StoreError(411, "Content-Length required")
                if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
                    raise StoreError(400, "Invalid Content-Length")
                query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
                if set(query) != {"series", "name"} or any(len(v) != 1 for v in query.values()):
                    raise StoreError(400, "series and name required exactly once")
                shas = self.headers.get_all("X-Sha256", [])
                if len(shas) != 1:
                    raise StoreError(400, "X-Sha256 required exactly once")
                replacements = self.headers.get_all("X-Replace-Sha256", [])
                if len(replacements) > 1:
                    raise StoreError(400, "X-Replace-Sha256 must occur at most once")
                status = store.put(video_id, kind, query["series"][0], query["name"][0],
                                   shas[0], self.rfile, int(lengths[0]), clip,
                                   replacements[0] if replacements else None)
                self._reply(status)
                return
            if self.command not in ("GET", "HEAD"):
                raise StoreError(404, "Unknown endpoint")
            row, path = store.lookup(video_id, kind, clip)
            with path.open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                start, end = 0, size - 1
                ranges = self.headers.get_all("Range", []) if self.command == "GET" else []
                if ranges:
                    try:
                        if len(ranges) != 1:
                            raise StoreError(416, "Multiple ranges are not supported")
                        start, end = parse_range(ranges[0], size)
                    except StoreError:
                        self._reply(416, headers={"Content-Range": f"bytes */{size}", "X-Sha256": row["sha256"]})
                        return
                self.send_response(206 if ranges else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("X-Sha256", row["sha256"])
                if ranges:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if self.command == "GET":
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        block = stream.read(min(remaining, CHUNK))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
        except StoreError as exc:
            self._reply(exc.status, json.dumps({"error": str(exc)}).encode())
        except FileNotFoundError:
            self._reply(404, b'{"error":"File not found"}')
        except (ValueError, UnicodeError, csv.Error):
            self._reply(400, b'{"error":"Invalid request or index"}')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self._reply(500, b'{"error":"Store I/O error"}')

    do_GET = do_HEAD = do_PUT = do_POST = do_DELETE = _handle


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--self-test", action="store_true", help="Validate config/token/folders/index without binding a socket")
    commands = parser.add_subparsers(dest="command")
    rename = commands.add_parser("rename-vertical", help="Rename current HD/vertical files; dry run unless --apply")
    rename.add_argument("--series", required=True)
    rename.add_argument("--speaker-label", default=DEFAULT_SPEAKER)
    rename.add_argument("--format", default="{tag} {title} - Tập {episode}.mp4",
                        help="Filename template: {tag}, {title} (including speaker), {episode}")
    rename.add_argument("--apply", action="store_true")
    reorganize = commands.add_parser("reorganize", help="Move media into type/episode folders; dry run unless --apply")
    reorganize.add_argument("--series", required=True, help="Configured series id or all")
    reorganize.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = Store(load_config(args.config))
        if args.command == "reorganize":
            print("Apply" if args.apply else "Dry run")
            try:
                moves, unknown = store.reorganize(args.series, apply=args.apply)
            except StoreError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            for source, target in moves:
                print(f"{source} -> {target}")
            for path in unknown:
                print(f"Unknown (unchanged): {path}")
            print(f"{len(moves)} file(s) {'moved' if args.apply else 'to move'}")
            return 0
        if args.command == "rename-vertical":
            rows = store.rename_vertical(args.series, apply=args.apply, speaker=args.speaker_label, format=args.format)
            print("Apply" if args.apply else "Dry run")
            print("Kind\tOld\tNew\tArchive")
            for row in rows:
                print(f"{row['kind']}\t{row['old']}\t{row['file']}\t{', '.join(row['archive'])}")
            return 0
        entries = store.index()
        if args.self_test:
            print(f"Self-test OK: {len(store.folders())} series, {len(entries)} files "
                  f"(hd={sum(r['kind'] == 'hd' for r in entries)}, "
                  f"vertical={sum(r['kind'] == 'vertical' for r in entries)})")
            return 0
        with ThreadingHTTPServer(("127.0.0.1", store.config["port"]), StoreHandler) as server:
            server.store = store
            print(f"Store listening on 127.0.0.1:{store.config['port']}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, IndexError, StoreError, csv.Error):
        # Config/OS exception strings may include private paths or input; keep output generic.
        print("Store check failed: inspect config, token, folders and CSV/SHA256SUMS files", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
