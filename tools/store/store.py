"""Loopback-only HD2 store. Python 3.11+, standard library, no project imports."""
from __future__ import annotations

import argparse
import csv
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
SHA256 = re.compile(r"[a-fA-F0-9]{64}")
COLUMNS = ("tap", "loai", "file", "video_id", "tieu_de")
KINDS = {"HD": "hd", "Doc": "vertical", "Goc": "source"}
MAX_BODY = 20 * 1024**3
CHUNK = 1024 * 1024


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


def validate_identity(video_id: str, kind: str) -> None:
    if not VIDEO_ID.fullmatch(video_id) or kind not in KINDS.values():
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
        paths = [inside(folder, name) for name in ("danh-sach.csv", "index.csv", "SHA256SUMS.txt")]
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
        result = list(rows.values())
        self._cache[folder] = (signature, result)
        return result

    def index(self) -> list[dict]:
        with self._lock:
            entries = {}
            for series, folder in sorted(self.folders().items()):
                for row in self._rows(folder):
                    path = inside(folder, row["file"])
                    if path.is_file():
                        key = (row["video_id"], row["kind"])
                        if key in entries:
                            raise StoreError(409, "Duplicate video_id/kind across series")
                        entries[key] = dict(row, series=series, size=path.stat().st_size)
            return [entries[key] for key in sorted(entries)]

    def lookup(self, video_id: str, kind: str) -> tuple[dict, Path]:
        validate_identity(video_id, kind)
        for row in self.index():
            if (row["video_id"], row["kind"]) == (video_id, kind):
                return row, inside(self.folders()[row["series"]], row["file"])
        raise StoreError(404, "Unknown file")

    def _metadata(self, folder: Path) -> tuple[Path, Path, list[str]]:
        index = inside(folder, "index.csv")
        sums = inside(folder, "SHA256SUMS.txt")
        fields = list(COLUMNS)
        if index.exists() and index.stat().st_size:
            with index.open(encoding="utf-8-sig", newline="") as stream:
                fields = next(csv.reader(stream))
            if not set(COLUMNS).issubset(fields):
                raise StoreError(400, "Invalid CSV columns for append")
        return index, sums, fields

    def _publish(self, folder: Path, video_id: str, kind: str, name: str, sha: str) -> None:
        """Preserve the backup Export-Csv column order, including existing optional columns."""
        index, sums, fields = self._metadata(folder)
        row = dict.fromkeys(fields, "")
        row.update(video_id=video_id, loai=next(label for label, value in KINDS.items() if value == kind), file=name)
        # A backup file might lack its final newline. Keep the appended record separate.
        for path in (sums, index):
            if path.exists() and path.stat().st_size:
                with path.open("rb+") as stream:
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        stream.write(b"\r\n")
        with sums.open("a", encoding="utf-8", newline="") as stream:
            stream.write(f"{sha}  {name}\r\n")
        needs_header = not index.exists() or not index.stat().st_size
        with index.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            if needs_header:
                writer.writeheader()
            writer.writerow(row)
        self._cache.pop(folder, None)

    def put(self, video_id: str, kind: str, series: str, name: str,
            sha: str, stream, length: int) -> int:
        """Stream exactly Content-Length bytes. Return 201 (created) or 200 (same file)."""
        validate_identity(video_id, kind)
        validate_name(name)
        if not SERIES_ID.fullmatch(series) or not SHA256.fullmatch(sha):
            raise StoreError(400, "Invalid series/sha256")
        if length < 0 or length > MAX_BODY:
            raise StoreError(413, "Body exceeds 20 GiB limit")
        sha = sha.lower()
        with self._put_lock:
            folder = no_links(self.config["series"].get(series, self.root / series))
            folder.mkdir(parents=True, exist_ok=True)
            dest = inside(folder, name)
            part = inside(folder, name + ".part")
            with self._lock:
                entries = self.index()
                for row in entries:
                    same_key = (row["video_id"], row["kind"]) == (video_id, kind)
                    same_path = inside(self.folders()[row["series"]], row["file"]) == dest
                    if same_key and (not same_path or row["sha256"] != sha):
                        raise StoreError(409, "Identity already has a different file")
                    if same_path and not same_key:
                        raise StoreError(409, "File belongs to another identity")
                # Validate metadata before creating a file.
                self._rows(folder)
                self._metadata(folder)
            if dest.exists():
                with dest.open("rb") as existing:
                    actual = hashlib.file_digest(existing, "sha256").hexdigest()
                if actual != sha:
                    raise StoreError(409, "Existing file has a different sha256")
                if not any((r["video_id"], r["kind"]) == (video_id, kind) for r in entries):
                    with self._lock:
                        self._publish(folder, video_id, kind, name, sha)
                return 200
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
                    inside(folder, name)
                    inside(folder, name + ".part")
                    if dest.exists():
                        raise StoreError(409, "Destination appeared during upload")
                    os.replace(part, dest)
                    self._publish(folder, video_id, kind, name, sha)
                return 201
            finally:
                # Only clean up a part created by this request.
                if owned_part and part.exists():
                    inside(folder, name + ".part").unlink()


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
            if len(parts) != 4 or parts[:2] != ["", "files"]:
                raise StoreError(404, "Unknown endpoint")
            video_id, kind = parts[2:]
            validate_identity(video_id, kind)
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
                status = store.put(video_id, kind, query["series"][0], query["name"][0],
                                   shas[0], self.rfile, int(lengths[0]))
                self._reply(status)
                return
            if self.command not in ("GET", "HEAD"):
                raise StoreError(404, "Unknown endpoint")
            row, path = store.lookup(video_id, kind)
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
    args = parser.parse_args(argv)
    try:
        store = Store(load_config(args.config))
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
    except (OSError, ValueError, StoreError, csv.Error):
        # Config/OS exception strings may include private paths or input; keep output generic.
        print("Store check failed: inspect config, token, folders and CSV/SHA256SUMS files", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
