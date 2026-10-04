#!/usr/bin/env python3
"""Server gia hien thuc cac route E3 toi thieu (CP13.1a) - CHI de test / thu tay worker.

Khong thuoc san pham, khong dung that. Chi thu vien chuan + ffprobe.
Hien thuc theo ADR `docs/decisions/CP13.1-enhance-worker-contract.md` E3:
lease / source (Range) / may-run / PUT seg (kiem sha256, so khung, kich thuoc) / heartbeat / release.

  python fake_server.py --source sample.mp4 --token T --port 18999 --segment-frames 100
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import re
import subprocess
import tempfile
import threading
import time
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SEG_RE = re.compile(r"^/api/enhance/([A-Za-z0-9._-]+)/seg/(\d{1,6})$")
_LEASE_RE = re.compile(r"^/api/enhance/([A-Za-z0-9._-]+)/(source|heartbeat|release)$")


def _json_or_empty(raw: bytes) -> dict:
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def probe(ffprobe: str, path: Path) -> dict:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,nb_read_packets", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return {"w": int(s["width"]), "h": int(s["height"]), "fps": s["r_frame_rate"], "frames": int(s["nb_read_packets"])}


class FakeServer:
    def __init__(self, source: Path, token="tok", worker_token_name="w", episode_id="ep1",
                 params=None, segment_frames=20, port=0, ffprobe="ffprobe", max_segment_mb=200,
                 seg_dir: Path | None = None):
        self.source = Path(source)
        self.token = token
        self.episode_id = episode_id
        self.params = params or {"model": "realesr-general-x4v3", "denoise": 1.0, "pre_height": 360, "out_height": 1080}
        self.segment_frames = segment_frames
        self.ffprobe = ffprobe
        self.max_bytes = max_segment_mb * 2 ** 20
        info = probe(ffprobe, self.source)
        self.fps = info["fps"]
        self.frames = info["frames"]
        self.src_wh = (info["w"], info["h"])
        self.source_size = self.source.stat().st_size
        h = hashlib.sha256()
        with open(self.source, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        self.source_sha = h.hexdigest()
        self.seg_dir = Path(seg_dir) if seg_dir else Path(tempfile.mkdtemp(prefix="fake-enh-"))
        self.seg_dir.mkdir(parents=True, exist_ok=True)
        self.nseg = math.ceil(self.frames / segment_frames)
        self.port = port
        self.lock = threading.RLock()
        # trang thai quan sat duoc (test doc)
        self.received: dict[int, str] = {}
        self.put_counts: dict[int, int] = {}
        self.put_rejects = 0
        self.lease_calls = 0
        self.may_run_calls = 0
        self.source_gets = 0
        self.range_requests: list[str] = []
        self.heartbeats = 0
        self.lease_bodies: list[dict] = []   # CP8.28: than JSON cua POST lease / heartbeat (kiem gpu_stats)
        self.heartbeat_bodies: list[dict] = []
        self.may_run_queries: list[str] = []
        self.releases: list[str] = []
        self.status_log: list[tuple[str, str, int]] = []
        # dieu khien
        self.may_run = True            # bool hoac callable(calls:int)->bool
        self.no_api = False            # moi route /api/enhance/* -> 404
        self.api_401 = False           # nhu VM truoc CP13.1b: middleware dang nhap tra 401 cho moi /api/*
        self.cut_source_after: int | None = None  # dut ket noi sau N byte (mot lan)
        self.on_put = None             # callback(n) sau khi nhan doan
        self._lease_seq = 0
        self.lease_id: str | None = None
        self.lease_valid = False
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    # -- vong doi --
    def start(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer._handle(self, "GET")

            def do_POST(self):
                outer._handle(self, "POST")

            def do_PUT(self):
                outer._handle(self, "PUT")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def expire_lease(self):
        """Gia lap hang lease het han: moi lease_id hien tai -> 409."""
        with self.lock:
            self.lease_valid = False

    @property
    def complete(self):
        return len(self.received) >= self.nseg

    # -- xu ly --
    def _send(self, h, status, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if body:
            h.wfile.write(body)
        self.status_log.append((h.command, h.path.split("?")[0], status))

    def _auth_ok(self, h):
        got = h.headers.get("Authorization", "")
        return got.startswith("Bearer ") and hmac.compare_digest(got[7:].encode(), self.token.encode())

    def _handle(self, h, method):
        path = h.path.split("?")[0]
        if not path.startswith("/api/enhance/"):
            return self._send(h, 404, {"error": "not found"})
        # doc het than de giu ket noi keep-alive hop le
        length = int(h.headers.get("Content-Length") or 0)
        if self.api_401:
            if length:
                h.rfile.read(min(length, self.max_bytes))
            return self._send(h, 401, {"error": "login required"})
        if self.no_api:
            if length:
                h.rfile.read(min(length, self.max_bytes))
            return self._send(h, 404, {"error": "not found"})
        if not self._auth_ok(h):
            if length:
                h.rfile.read(min(length, self.max_bytes))
            return self._send(h, 401, {"error": "unauthorized"})
        with self.lock:
            return self._route(h, method, path, length)

    def _lease_ok(self, lid):
        return self.lease_valid and lid == self.lease_id

    def _route(self, h, method, path, length):
        query = h.path.partition("?")[2]
        if method == "POST" and path == "/api/enhance/lease":
            self.lease_bodies.append(_json_or_empty(h.rfile.read(length)))
            self.lease_calls += 1
            if self.complete:
                return self._send(h, 204)
            if not self.lease_valid:
                self._lease_seq += 1
                self.lease_id = f"L{self._lease_seq}"
                self.lease_valid = True
            return self._send(h, 200, {
                "episode_id": self.episode_id, "lease_id": self.lease_id,
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 48 * 3600)),
                "source_url": f"http://127.0.0.1:{self.port}/api/enhance/{self.lease_id}/source",
                "source_sha256": self.source_sha, "source_size": self.source_size,
                "fps": self.fps, "frames": self.frames, "segment_frames": self.segment_frames,
                "params": self.params, "config_hash": "cfg-test",
                "done_segments": sorted(self.received)})
        if method == "GET" and path == "/api/enhance/may-run":
            self.may_run_calls += 1
            self.may_run_queries.append(query)
            run = self.may_run(self.may_run_calls) if callable(self.may_run) else bool(self.may_run)
            return self._send(h, 200, {"run": run, "reason": "" if run else "ollama busy"})
        m = _SEG_RE.match(path)
        if method == "PUT" and m:
            return self._put_seg(h, m.group(1), int(m.group(2)), length)
        m = _LEASE_RE.match(path)
        if m:
            lid, what = m.groups()
            raw = h.rfile.read(length) if length else b""
            if not self._lease_ok(lid):
                return self._send(h, 409, {"error": "lease invalid"})
            if what == "source" and method == "GET":
                return self._source(h)
            if what == "heartbeat" and method == "POST":
                self.heartbeats += 1
                self.heartbeat_bodies.append(_json_or_empty(raw))
                return self._send(h, 200, {"ok": True})
            if what == "release" and method == "POST":
                self.releases.append(lid)
                self.lease_valid = False
                return self._send(h, 200, {"ok": True})
        return self._send(h, 404, {"error": "no route"})

    def _source(self, h):
        self.source_gets += 1
        rng = h.headers.get("Range")
        size = self.source_size
        start, end = 0, size - 1
        status = 200
        if rng:
            self.range_requests.append(rng)
            m = re.match(r"bytes=(\d+)-(\d*)$", rng)
            if not m or int(m.group(1)) >= size:
                return self._send(h, 416, b"", extra={"Content-Range": f"bytes */{size}"})
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            status = 206
        n = end - start + 1
        h.send_response(status)
        h.send_header("Content-Type", "video/mp4")
        h.send_header("Content-Length", str(n))
        h.send_header("Accept-Ranges", "bytes")
        if status == 206:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        h.end_headers()
        self.status_log.append(("GET", "source", status))
        with open(self.source, "rb") as f:
            f.seek(start)
            sent = 0
            while sent < n:
                chunk = f.read(min(1 << 16, n - sent))
                if not chunk:
                    break
                if self.cut_source_after is not None and sent + len(chunk) > self.cut_source_after:
                    part = chunk[: max(0, self.cut_source_after - sent)]
                    h.wfile.write(part)
                    h.wfile.flush()
                    self.cut_source_after = None
                    h.close_connection = True
                    h.connection.shutdown(2)
                    return
                h.wfile.write(chunk)
                sent += len(chunk)

    def _put_seg(self, h, lid, n, length):
        if length > self.max_bytes:
            return self._send(h, 413, {"error": "too large"})
        body = h.rfile.read(length)
        if not self._lease_ok(lid):
            return self._send(h, 409, {"error": "lease invalid"})
        if not 0 <= n < self.nseg:
            return self._send(h, 400, {"error": "bad n"})
        sha = hashlib.sha256(body).hexdigest()
        if sha != (h.headers.get("X-Sha256") or "").lower():
            self.put_rejects += 1
            return self._send(h, 400, {"error": "sha256 mismatch"})
        if n in self.received and self.received[n] == sha:
            self.put_counts[n] = self.put_counts.get(n, 0) + 1
            return self._send(h, 200, {"ok": True, "idempotent": True})
        start = n * self.segment_frames
        want = min(self.segment_frames, self.frames - start)
        tmp = self.seg_dir / f"seg_{n:05d}.mp4.tmp"
        tmp.write_bytes(body)
        try:
            info = probe(self.ffprobe, tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            self.put_rejects += 1
            return self._send(h, 400, {"error": "unreadable mp4"})
        pre_w, pre_h = self._expected_wh()
        if info["frames"] != want or info["h"] != pre_h or info["w"] != pre_w:
            tmp.unlink(missing_ok=True)
            self.put_rejects += 1
            return self._send(h, 400, {"error": f"frames/size mismatch {info}"})
        tmp.replace(self.seg_dir / f"seg_{n:05d}.mp4")
        self.received[n] = sha
        self.put_counts[n] = self.put_counts.get(n, 0) + 1
        self._send(h, 200, {"ok": True})
        if self.on_put:
            self.on_put(n)

    def _expected_wh(self):
        w, h = self.src_wh
        ph = int(self.params["pre_height"])
        pw = int(round(w * ph / h / 2) * 2) if ph > 0 and ph != h else w
        ph = ph if ph > 0 else h
        oh = int(self.params["out_height"])
        uh = ph * 4
        ow = int(round(pw * 4 * oh / uh / 2) * 2) if oh > 0 and uh != oh else pw * 4
        return ow, (oh if oh > 0 else uh)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True)
    ap.add_argument("--token", default="tok")
    ap.add_argument("--port", type=int, default=18999)
    ap.add_argument("--segment-frames", type=int, default=100)
    ap.add_argument("--pre-height", type=int, default=360)
    ap.add_argument("--out-height", type=int, default=1080)
    ap.add_argument("--seg-dir", default="")
    a = ap.parse_args()
    s = FakeServer(Path(a.source), token=a.token, port=a.port, segment_frames=a.segment_frames,
                   params={"model": "realesr-general-x4v3", "denoise": 1.0, "pre_height": a.pre_height,
                           "out_height": a.out_height}, seg_dir=Path(a.seg_dir) if a.seg_dir else None)
    s.start()
    print(f"fake server {s.url}: {s.frames} khung, {s.nseg} doan, doan luu o {s.seg_dir}", flush=True)
    try:
        while not s.complete:
            time.sleep(1)
        print("du doan", sorted(s.received), flush=True)
        time.sleep(2)
    except KeyboardInterrupt:
        pass
    s.stop()


if __name__ == "__main__":
    main()
