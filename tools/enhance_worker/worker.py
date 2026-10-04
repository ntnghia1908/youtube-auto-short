#!/usr/bin/env python3
"""Enhance worker (CP13.1a, ADR `docs/decisions/CP13.1-enhance-worker-contract.md` E3/E4/E7/E8).

Script doc lap, chay tren may Windows co GPU (hoac `--device cpu` de thu tren VM).
Khong thuoc package `auto_short`. Dependency: Python 3.11, torch, numpy,
opencv-python-headless, ffmpeg/ffprobe (NVENC neu co). HTTP bang `urllib`.

Vong lap: lease -> tai nguon (Range + sha256) -> moi doan con thieu:
may-run (E7) -> enhance (luong doc khung + batch tren GPU) -> ma hoa NVENC /
libx264 -> luu dia + file trang thai -> upload (luong rieng, backoff) -> het
doan thi xoa nguon. Khoi dong lai: doc `state.json`, lam tiep.

  python worker.py --config config.json            # chay nen (vong lap)
  python worker.py --config config.json --self-test
  python worker.py --config config.json --once --device cpu --max-segments 2

Ma thoat: 0 binh thuong, 1 loi, 3 token sai / khong cau hinh duoc (wrapper cho lau hon roi chay lai).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction
from pathlib import Path

__version__ = "2"  # 2: gui kem so lieu GPU (gpu_stats, CP8.28)

sys.path.insert(0, str(Path(__file__).resolve().parent))  # srvgg.py canh worker.py
EXIT_OK, EXIT_ERROR, EXIT_AUTH = 0, 1, 3

log = logging.getLogger("enhance_worker")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DONE = object()

DEFAULTS = {
    "server_url": "http://127.0.0.1:18080",
    "worker_name": "worker",
    "token": "",
    "yield_to_ollama": False,
    "work_dir": "work",
    "models_dir": "models",
    "log_file": "",
    "max_disk_gb": 100.0,
    "batch_size": 4,
    "device": "auto",          # auto | cuda | cpu
    "cuda_device": 0,
    "cpu_threads": 0,          # 0 = mac dinh cua torch
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "encoder": "auto",         # auto | h264_nvenc | libx264
    "nvenc_cq": 21,
    "x264_crf": 20,
    "idle_seconds": 60,        # 204: khong co viec
    "not_found_seconds": 300,  # 404: VM chua co API
    "error_seconds": 30,       # loi mang khi xin lease
    "may_run_seconds": 30,     # E7
    "heartbeat_seconds": 60,
    "http_timeout": 30,
    "upload_backoff_seconds": 5,
    "upload_backoff_max_seconds": 120,
    "drain_seconds": 30,
    "auth_retry_seconds": 600,  # 401: nghi roi doc lai config (token) va thu lai
}


class AuthError(Exception):
    """401: token sai (dung han, khong thu lai)."""


class LeaseLost(Exception):
    """409: lease khong con hieu luc / config_hash khac."""


class NetError(Exception):
    """Mat ket noi, timeout, 5xx."""


class HttpError(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class NotFound(HttpError):
    pass


class Aborted(Exception):
    pass


# ---------------------------------------------------------------------------
# Tien ich
# ---------------------------------------------------------------------------


def parse_fps(v) -> Fraction:
    """fps trong lease: chuoi 'a/b' hoac so (ADR chua ghi kieu)."""
    if isinstance(v, str) and "/" in v:
        a, b = v.split("/", 1)
        return Fraction(int(a), int(b))
    f = Fraction(str(v))
    for ntsc in (Fraction(24000, 1001), Fraction(30000, 1001), Fraction(60000, 1001)):  # 23.976 / 29.97 / 59.94
        if abs(float(f - ntsc)) < 0.006:
            return ntsc
    return f.limit_denominator(1001)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def seg_name(n: int) -> str:
    return f"seg_{n:05d}.mp4"


def seg_range(n: int, seg_frames: int, frames: int) -> tuple[int, int]:
    """(khung dau, so khung) cua doan n; doan cuoi co the ngan hon."""
    start = n * seg_frames
    return start, min(seg_frames, frames - start)


def total_segments(frames: int, seg_frames: int) -> int:
    return math.ceil(frames / seg_frames)


def out_size(src_w: int, src_h: int, pre_h: int, out_h: int, scale: int = 4) -> tuple[int, int, int, int]:
    """(pre_w, pre_h, out_w, out_h) theo cong thuc cua `enhance_bench_win.py`."""
    if pre_h > 0 and pre_h != src_h:
        pre_w = int(round(src_w * pre_h / src_h / 2) * 2)
    else:
        pre_w, pre_h = src_w, src_h
    uw, uh = pre_w * scale, pre_h * scale
    if out_h > 0 and uh != out_h:
        ow = int(round(uw * out_h / uh / 2) * 2)
        return pre_w, pre_h, ow, out_h
    return pre_w, pre_h, uw, uh


def utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_config(path: str | None, overrides: dict | None = None) -> dict:
    cfg = dict(DEFAULTS)
    base = Path.cwd()
    if path:
        p = Path(path)
        with open(p, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
        base = p.resolve().parent
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    cfg["token"] = os.environ.get("ENHANCE_WORKER_TOKEN") or cfg["token"]
    for k in ("work_dir", "models_dir"):
        pp = Path(cfg[k])
        cfg[k] = str(pp if pp.is_absolute() else base / pp)
    if not cfg["log_file"]:
        cfg["log_file"] = str(base / "logs" / "worker.log")
    return cfg


def setup_logging(cfg: dict, console: bool = True) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        Path(cfg["log_file"]).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            cfg["log_file"], maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError as e:
        print(f"Khong ghi duoc log file {cfg['log_file']}: {e}", file=sys.stderr)
    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        log.addHandler(sh)


# ---------------------------------------------------------------------------
# HTTP (urllib)
# ---------------------------------------------------------------------------


class Api:
    def __init__(self, base_url: str, token: str, timeout: float = 30):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _req(self, method, path, data=None, headers=None):
        h = {"Authorization": f"Bearer {self.token}"}
        if headers:
            h.update(headers)
        return urllib.request.Request(self.base + path, data=data, method=method, headers=h)

    def _open(self, req):
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.status == 401:
                raise AuthError("HTTP 401 (token sai hoac chua duoc VM cap)") from None
            if e.status == 409:
                raise LeaseLost(body[:200] or "HTTP 409") from None
            if e.status == 404:
                raise NotFound(404, body) from None
            if e.status >= 500:
                raise NetError(f"HTTP {e.status}") from None
            raise HttpError(e.status, body) from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise NetError(str(getattr(e, "reason", e))) from None
        except Exception as e:  # http.client.HTTPException ...
            raise NetError(f"{type(e).__name__}: {e}") from None

    def call(self, method, path, json_body=None, data=None, headers=None):
        """Tra (status, body bytes). 401/409/404/5xx/mang -> ngoai le."""
        hd = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode()
            hd["Content-Type"] = "application/json"
        with self._open(self._req(method, path, data, hd)) as r:
            try:
                return r.status, r.read()
            except Exception as e:
                raise NetError(f"{type(e).__name__}: {e}") from None

    def call_json(self, method, path, json_body=None):
        status, body = self.call(method, path, json_body=json_body)
        if status == 204 or not body:
            return status, None
        try:
            return status, json.loads(body)
        except ValueError:
            raise NetError("phan hoi khong phai JSON") from None

    def put_file(self, path, file_path: Path, sha: str):
        size = file_path.stat().st_size
        with open(file_path, "rb") as f:
            return self.call("PUT", path, data=f, headers={
                "X-Sha256": sha, "Content-Length": str(size),
                "Content-Type": "video/mp4"})

    def download(self, path, dest: Path, stop: threading.Event | None = None) -> None:
        """Tai (tiep) vao `dest` (file .part) bang Range."""
        offset = dest.stat().st_size if dest.exists() else 0
        hd = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            r = self._open(self._req("GET", path, headers=hd))
        except HttpError as e:
            if e.status == 416 and offset:
                return  # da du
            raise
        with r:
            if offset and r.status != 206:
                offset = 0  # server bo qua Range -> tai lai tu dau
            with open(dest, "r+b" if offset else "wb") as f:
                f.seek(offset)
                while True:
                    if stop is not None and stop.is_set():
                        raise Aborted("stop")
                    try:
                        chunk = r.read(1 << 20)
                    except Exception as e:
                        raise NetError(f"{type(e).__name__}: {e}") from None
                    if not chunk:
                        break
                    f.write(chunk)


# ---------------------------------------------------------------------------
# Trang thai cuc bo
# ---------------------------------------------------------------------------


class State:
    """work_dir/state.json: lease hien tai + trang thai tung doan (ghi nguyen tu)."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {"version": 1, "lease": None, "source_ok": False, "segments": {}}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                log.warning("state.json hong, bo qua: %s", path)

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    @property
    def lease(self):
        return self.data["lease"]

    def reset(self, lease=None):
        with self.lock:
            self.data.update(lease=lease, source_ok=False, segments={})
            self.save()

    def set_seg(self, n: int, state: str, sha: str = "", size: int = 0):
        with self.lock:
            self.data["segments"][str(n)] = {"state": state, "sha256": sha, "size": size}
            self.save()

    def drop_seg(self, n: int):
        with self.lock:
            self.data["segments"].pop(str(n), None)
            self.save()

    def seg(self, n: int):
        with self.lock:
            return self.data["segments"].get(str(n))

    def count(self, state: str | None = None) -> int:
        with self.lock:
            return sum(1 for s in self.data["segments"].values() if state is None or s["state"] == state)

    def next_pending(self):
        with self.lock:
            ns = sorted(int(k) for k, s in self.data["segments"].items() if s["state"] == "encoded")
            return ns[0] if ns else None


# ---------------------------------------------------------------------------
# Enhance (torch) - doc khung o luong rieng + batch tren GPU
# ---------------------------------------------------------------------------


def ffprobe_size(ffprobe: str, path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return int(s["width"]), int(s["height"])


def _put(q: "queue.Queue", item, abort: threading.Event):
    while not abort.is_set():
        try:
            q.put(item, timeout=0.2)
            return True
        except queue.Full:
            pass
    return False


def read_frames(ffmpeg: str, src: Path, start: int, count: int, fps: Fraction, w: int, h: int,
                pre_w: int, pre_h: int, batch: int, q: "queue.Queue", abort: threading.Event) -> None:
    """Chay trong luong doc: giai ma frame-accurate [start, start+count), ha ve pre_h, gui batch (N,H,W,3 BGR uint8)."""
    import numpy as np
    cv2 = None
    if (pre_w, pre_h) != (w, h):
        import cv2  # noqa: F811
    cmd = [ffmpeg, "-v", "error", "-nostdin"]
    if start > 0:
        # -ss chinh xac theo khung: lui nua khung de khung `start` la khung dau tien co pts >= t
        t = Fraction(start) / fps - Fraction(1, 2) / fps
        cmd += ["-ss", f"{float(t):.6f}"]
    cmd += ["-i", str(src), "-map", "0:v:0", "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err)
    fsz = w * h * 3
    got = 0
    buf = []
    try:
        for _ in range(count):
            if abort.is_set():
                return
            raw = proc.stdout.read(fsz)
            if len(raw) < fsz:
                break
            fr = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
            if cv2 is not None:
                fr = cv2.resize(fr, (pre_w, pre_h), interpolation=cv2.INTER_AREA if pre_h < h else cv2.INTER_CUBIC)
            buf.append(fr)
            got += 1
            if len(buf) >= batch:
                if not _put(q, np.stack(buf), abort):
                    return
                buf = []
        if buf and not _put(q, np.stack(buf), abort):
            return
        if got != count:
            err.seek(0)
            raise RuntimeError(f"nguon chi doc duoc {got}/{count} khung: {err.read().decode('utf-8', 'replace')[-300:]}")
        _put(q, _DONE, abort)
    except BaseException as e:  # chuyen sang luong chinh
        _put(q, e, abort)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        err.close()


def build_encode_cmd(cfg: dict, encoder: str, w: int, h: int, fps: Fraction, out: Path) -> list[str]:
    cmd = [cfg["ffmpeg"], "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
           "-r", f"{fps.numerator}/{fps.denominator}", "-i", "-", "-an",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv",
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-color_range", "tv"]
    if encoder == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cfg["nvenc_cq"]),
                "-b:v", "0", "-profile:v", "high"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(cfg["x264_crf"]), "-profile:v", "high"]
    return cmd + ["-f", "mp4", str(out)]


def detect_encoder(cfg: dict) -> str:
    """NVENC neu chay duoc that su (khong chi co trong `-encoders`), nguoc lai libx264."""
    want = cfg["encoder"]
    if want == "libx264":
        return "libx264"
    try:
        r = subprocess.run(
            [cfg["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=25:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return "h264_nvenc"
        reason = (r.stderr or "").strip().splitlines()[-1:] or ["?"]
    except (OSError, subprocess.SubprocessError) as e:
        reason = [str(e)]
    log.warning("Khong dung duoc NVENC (%s) -> fallback libx264 (CPU, cham hon)", reason[0])
    if want == "h264_nvenc":
        log.warning("cau hinh encoder=h264_nvenc nhung NVENC khong chay duoc")
    return "libx264"


def gpu_name(cfg: dict, device: str) -> str:
    if device == "cpu":
        return "cpu"
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader", "-i",
                              str(cfg["cuda_device"])], capture_output=True, text=True, timeout=10).stdout
        name = out.strip().splitlines()[0].strip()
        if name:
            return name
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


GPU_STATS_QUERY = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
GPU_STATS_KEYS = ("name", "util_pct", "mem_used_mb", "mem_total_mb", "temp_c", "power_w")
GPU_STATS_TTL = 2.0  # giay: lan lay so lieu nvidia-smi gan nhat con dung duoc


def read_gpu_stats(cfg: dict, run=subprocess.run) -> dict | None:
    """CP8.28 M4: so lieu GPU tu `nvidia-smi` (ten, % GPU, VRAM dung / tong MB, nhiet do, cong suat) hoac None khi
    khong lay duoc (CPU, khong co nvidia-smi, loi, dau ra la). Moi loi deu bi bo qua: worker khong bao gio dung vi so lieu."""
    if cfg.get("device") == "cpu":
        return None
    try:
        r = run(["nvidia-smi", f"--query-gpu={GPU_STATS_QUERY}", "--format=csv,noheader,nounits", "-i",
                 str(cfg.get("cuda_device", 0))], capture_output=True, text=True, timeout=5)
        line = (r.stdout or "").strip().splitlines()[0]
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != len(GPU_STATS_KEYS) or not parts[0]:
            return None
        out: dict = {"name": parts[0][:80]}
        for key, raw in zip(GPU_STATS_KEYS[1:], parts[1:]):
            try:
                out[key] = round(float(raw), 1)
            except ValueError:  # "[N/A]" ..
                out[key] = None
        return out
    except Exception:
        return None


class Engine:
    """Giu mang tren GPU (hoac CPU), enhance mot doan: doc khung | batch GPU | ma hoa."""

    def __init__(self, cfg: dict, device: str | None = None):
        self.cfg = cfg
        if (device or cfg["device"]) != "cpu":
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(cfg["cuda_device"]))
        import torch
        self.torch = torch
        dev = device or cfg["device"]
        if dev == "auto":
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        if dev == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA khong kha dung (cai PyTorch ban CUDA; xem docs/guides/enhance-worker-windows.md)")
        self.dev = dev
        if dev == "cpu" and cfg["cpu_threads"]:
            torch.set_num_threads(int(cfg["cpu_threads"]))
        if dev == "cuda":
            torch.backends.cudnn.benchmark = True
        self.net = None
        self.net_key = None
        self.on_device = False
        self.encoder = detect_encoder(cfg)
        self.gpu = gpu_name(cfg, dev)

    def ensure(self, params: dict):
        from srvgg import MODEL_NAME, load_net
        if params.get("model") != MODEL_NAME:
            raise ValueError(f"model khong ho tro: {params.get('model')!r}")
        key = (params["model"], float(params.get("denoise", 1.0)))
        if self.net_key != key:
            t0 = time.time()
            net = load_net(Path(self.cfg["models_dir"]), key[1])
            self.net, self.net_key, self.on_device = net, key, False
            log.info("nap model %s denoise=%s (%.1fs)", key[0], key[1], time.time() - t0)
        if not self.on_device:
            if self.dev == "cuda":
                self.net = self.net.half()
            self.net = self.net.to(self.dev)
            self.on_device = True

    def release_vram(self):
        """E7: nhuong Ollama - giu trong so tren CPU, tra VRAM."""
        if self.dev != "cuda" or self.net is None or not self.on_device:
            return
        self.net = self.net.float().to("cpu")
        self.on_device = False
        self.torch.cuda.empty_cache()
        log.info("da giai phong VRAM (trong so giu tren CPU)")

    def _run_net(self, x):
        torch = self.torch
        try:
            return self.net(x)
        except torch.cuda.OutOfMemoryError:
            if x.shape[0] == 1:
                raise
            torch.cuda.empty_cache()
            h = x.shape[0] // 2
            log.warning("het VRAM voi batch %d -> chia doi", x.shape[0])
            return torch.cat([self._run_net(x[:h]), self._run_net(x[h:])], 0)

    def run_segment(self, src: Path, start: int, count: int, fps: Fraction, src_wh: tuple[int, int],
                    params: dict, out_path: Path, abort: threading.Event) -> dict:
        torch = self.torch
        import numpy as np
        import torch.nn.functional as F
        self.ensure(params)
        ext_abort = abort
        abort = threading.Event()  # noi bo: bao luong doc / ghi dung khi run_segment ket thuc / loi
        w, h = src_wh
        pre_w, pre_h, ow, oh = out_size(w, h, int(params["pre_height"]), int(params["out_height"]))
        batch = max(1, int(self.cfg["batch_size"]))
        rq: queue.Queue = queue.Queue(maxsize=3)
        wq: queue.Queue = queue.Queue(maxsize=3)
        stats = {"frames": 0, "batches": 0, "max_batch": 0, "reader_thread": "", "encoder": self.encoder}
        tmp = out_path.with_name(out_path.name + ".part")

        def reader():
            stats["reader_thread"] = threading.current_thread().name
            read_frames(self.cfg["ffmpeg"], src, start, count, fps, w, h, pre_w, pre_h, batch, rq, abort)

        def encode_proc(encoder):
            err = tempfile.TemporaryFile()
            p = subprocess.Popen(build_encode_cmd(self.cfg, encoder, ow, oh, fps, tmp),
                                 stdin=subprocess.PIPE, stderr=err)
            return p, err

        proc, err = encode_proc(self.encoder)
        werr: list = []

        def writer():
            try:
                while True:
                    try:
                        item = wq.get(timeout=0.2)
                    except queue.Empty:
                        if abort.is_set():
                            return
                        continue
                    if item is _DONE:
                        return
                    proc.stdin.write(memoryview(item))
            except BaseException as e:
                werr.append(e)
                while not abort.is_set():  # xa hang doi de luong chinh khong ket
                    try:
                        if wq.get(timeout=0.2) is _DONE:
                            break
                    except queue.Empty:
                        pass

        tr = threading.Thread(target=reader, name="frame-reader", daemon=True)
        tw = threading.Thread(target=writer, name="frame-writer", daemon=True)
        tr.start()
        tw.start()
        t0 = time.time()
        try:
            while True:
                if ext_abort.is_set():
                    raise Aborted("abort")
                try:
                    item = rq.get(timeout=0.2)
                except queue.Empty:
                    continue
                if item is _DONE:
                    break
                if isinstance(item, BaseException):
                    raise item
                n = item.shape[0]
                x = torch.from_numpy(item).to(self.dev)
                x = x.flip(-1).permute(0, 3, 1, 2).to(torch.float16 if self.dev == "cuda" else torch.float32).div_(255).contiguous()
                with torch.no_grad():
                    y = self._run_net(x).float()
                    if y.shape[2] != oh or y.shape[3] != ow:
                        y = F.interpolate(y, size=(oh, ow), mode="area" if y.shape[2] > oh else "bicubic",
                                          **({} if y.shape[2] > oh else {"align_corners": False}))
                    y = y.clamp_(0, 1).mul_(255).round_().to(torch.uint8)
                    y = y.permute(0, 2, 3, 1).flip(-1).contiguous().cpu().numpy()
                if werr:
                    raise RuntimeError(f"ghi ffmpeg loi: {werr[0]}")
                if not _put(wq, y, abort):
                    raise Aborted("abort")
                stats["frames"] += n
                stats["batches"] += 1
                stats["max_batch"] = max(stats["max_batch"], n)
            _put(wq, _DONE, abort)
            tw.join()
            if werr:
                raise RuntimeError(f"ghi ffmpeg loi: {werr[0]}")
            proc.stdin.close()
            rc = proc.wait()
            if rc != 0:
                err.seek(0)
                raise RuntimeError(f"ffmpeg ma hoa loi ({self.encoder}) rc={rc}: {err.read().decode('utf-8', 'replace')[-400:]}")
            if stats["frames"] != count:
                raise RuntimeError(f"so khung {stats['frames']} != {count}")
        except BaseException:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        finally:
            abort.set()
            proc.poll()
            tr.join(timeout=5)
            err.close()
        os.replace(tmp, out_path)
        stats["seconds"] = round(time.time() - t0, 2)
        stats["out_size"] = f"{ow}x{oh}"
        return stats


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class Worker:
    def __init__(self, cfg: dict, once=False, max_segments=0, stop: threading.Event | None = None,
                 engine: Engine | None = None, config_path: str | None = None, overrides: dict | None = None):
        self.cfg = cfg
        self.config_path = config_path
        self.overrides = overrides
        self.once = once
        self.max_segments = max_segments
        self.stop = stop or threading.Event()
        self.api = Api(cfg["server_url"], cfg["token"], cfg["http_timeout"])
        self.work = Path(cfg["work_dir"])
        self.state = State(self.work / "state.json")
        self.engine = engine
        self.lost = threading.Event()      # lease mat (409)
        self.halt = threading.Event()      # dung luong phu cua lease hien tai
        self._fatal: BaseException | None = None
        self.stats = {"encoded": 0, "uploaded": 0, "put_ok": 0}
        self._gpu = ""
        self._stats: tuple[float, dict | None] = (-1e9, None)

    # -- tien ich --
    def gpu_stats(self) -> dict | None:
        """CP8.28: so lieu GPU moi nhat (dem 2 s), None neu khong lay duoc."""
        now = time.monotonic()
        if now - self._stats[0] >= GPU_STATS_TTL:
            self._stats = (now, read_gpu_stats(self.cfg))
        return self._stats[1]

    def sleep(self, s: float) -> bool:
        """Ngu `s` giay; True neu bi dung."""
        return self.stop.wait(s)

    def ep_dir(self, lease) -> Path:
        return self.work / "ep" / lease["episode_id"]

    def disk_used(self) -> int:
        tot = 0
        base = self.work / "ep"
        if base.exists():
            for p in base.rglob("*"):
                try:
                    if p.is_file():
                        tot += p.stat().st_size
                except OSError:
                    pass
        return tot

    def get_engine(self) -> Engine:
        if self.engine is None:
            self.engine = Engine(self.cfg)
            log.info("thiet bi: %s (%s), encoder: %s, batch %s", self.engine.dev, self.engine.gpu,
                     self.engine.encoder, self.cfg["batch_size"])
        return self.engine

    def gpu_label(self) -> str:
        if not self._gpu:
            dev = self.cfg["device"]
            self._gpu = "cpu" if dev == "cpu" else gpu_name(self.cfg, dev)
        return self._gpu

    # -- vong lap chinh --
    def run(self) -> int:
        log.info("worker v%s '%s' -> %s (yield_to_ollama=%s)", __version__,
                 self.cfg["worker_name"], self.cfg["server_url"], self.cfg["yield_to_ollama"])
        while not self.stop.is_set():
            try:
                return self._loop()
            except AuthError as e:
                if self.once:
                    log.error("XAC THUC THAT BAI: %s. Kiem tra token trong config (VM cap, E8). Dung.", e)
                    return EXIT_AUTH
                wait = self.cfg["auth_retry_seconds"]
                log.warning("VM tra 401 (%s token; token sai, chua cap, hoac VM chua co API enhance) - "
                            "thu lai sau %ss (doc lai config)", "chua co" if not self.cfg["token"] else "co",
                            wait)
                if self.sleep(wait):
                    break
                self.reload_config()
        return EXIT_OK

    def reload_config(self):
        if not self.config_path:
            return
        try:
            new = load_config(self.config_path, self.overrides)
        except (OSError, ValueError) as e:
            log.warning("khong doc lai duoc config: %s", e)
            return
        self.cfg.update(new)
        self.api = Api(self.cfg["server_url"], self.cfg["token"], self.cfg["http_timeout"])

    def _loop(self) -> int:
        try:
            while not self.stop.is_set():
                lease = self.state.lease
                if lease is None:
                    lease = self.acquire_lease()
                    if lease is None:
                        if self.once:
                            return EXIT_OK
                        continue
                elif not self.resume_check(lease):
                    continue
                try:
                    res = self.work_lease(lease)
                except LeaseLost as e:
                    log.warning("lease %s mat (%s) -> bo viec, xin viec moi", lease["lease_id"], e)
                    self.abandon(lease)
                    continue
                except Aborted:
                    return EXIT_OK
                except RuntimeError as e:
                    log.error("viec %s that bai: %s", lease["lease_id"], e)
                    self.release(lease, str(e)[:200])
                    self.sleep(self.cfg["error_seconds"])
                    continue
                if res == "stopped":
                    return EXIT_OK
                if self.once:
                    return EXIT_OK
        except KeyboardInterrupt:
            pass
        return EXIT_OK

    def acquire_lease(self):
        try:
            body = {"worker": self.cfg["worker_name"], "gpu": self.gpu_label()}
            stats = self.gpu_stats()
            if stats:
                body["gpu_stats"] = stats  # CP8.28: truong tuy chon, VM cu bo qua
            status, data = self.api.call_json("POST", "/api/enhance/lease", body)
        except NotFound:
            log.warning("VM chua co API enhance (404; CP13.1b chua trien khai?) - hoi lai sau %ss",
                        self.cfg["not_found_seconds"])
            self.sleep(self.cfg["not_found_seconds"] if not self.once else 0)
            return None
        except NetError as e:
            log.warning("khong noi duoc VM (%s) - thu lai sau %ss", e, self.cfg["error_seconds"])
            self.sleep(self.cfg["error_seconds"] if not self.once else 0)
            return None
        except LeaseLost:
            self.sleep(self.cfg["error_seconds"])
            return None
        except HttpError as e:
            log.warning("xin lease loi: %s", e)
            self.sleep(self.cfg["error_seconds"])
            return None
        if status == 204 or not data:
            log.info("khong co viec (204) - hoi lai sau %ss", self.cfg["idle_seconds"])
            self.sleep(self.cfg["idle_seconds"] if not self.once else 0)
            return None
        err = self.validate_lease(data)
        if err:
            log.error("lease khong hop le: %s", err)
            if _ID_RE.match(str(data.get("lease_id", ""))):
                self.release_raw(data["lease_id"], f"lease khong hop le: {err}")
            self.sleep(self.cfg["error_seconds"])
            return None
        log.info("nhan viec: tap %s lease %s, %d khung, %d khung/doan, %d doan da co, params=%s",
                 data["episode_id"], data["lease_id"], data["frames"], data["segment_frames"],
                 len(data.get("done_segments") or []), data["params"])
        self.state.reset(data)
        for n in data.get("done_segments") or []:
            self.state.set_seg(int(n), "uploaded")
        return data

    @staticmethod
    def validate_lease(d: dict) -> str:
        for k in ("episode_id", "lease_id", "source_url", "source_sha256", "source_size", "fps",
                  "frames", "segment_frames", "params", "config_hash"):
            if k not in d:
                return f"thieu '{k}'"
        if not _ID_RE.match(str(d["episode_id"])) or not _ID_RE.match(str(d["lease_id"])):
            return "episode_id / lease_id sai dinh dang"
        p = d["params"]
        for k in ("model", "denoise", "pre_height", "out_height"):
            if k not in p:
                return f"thieu params.{k}"
        if int(d["frames"]) <= 0 or int(d["segment_frames"]) <= 0:
            return "frames / segment_frames phai > 0"
        return ""

    def resume_check(self, lease) -> bool:
        """Sau khoi dong lai: kiem lease con hieu luc (heartbeat). Mang loi -> cu lam tiep."""
        log.info("tiep tuc viec dang do: tap %s lease %s (%d doan xong/upload, %d cho upload)",
                 lease["episode_id"], lease["lease_id"], self.state.count("uploaded"), self.state.count("encoded"))
        try:
            self.heartbeat_once(lease)
        except LeaseLost:
            log.warning("lease %s khong con hieu luc -> bo viec", lease["lease_id"])
            self.abandon(lease)
            return False
        except NetError as e:
            log.warning("offline khi kiem lease (%s) - lam tiep tu trang thai", e)
        except (NotFound, HttpError) as e:
            log.warning("kiem lease: %s - lam tiep", e)
        return True

    def abandon(self, lease):
        shutil.rmtree(self.ep_dir(lease), ignore_errors=True)
        self.state.reset(None)
        self.lost.clear()

    def release_raw(self, lease_id, reason):
        try:
            self.api.call("POST", f"/api/enhance/{lease_id}/release", json_body={"reason": reason})
        except Exception as e:
            log.warning("release that bai: %s", e)

    def release(self, lease, reason):
        log.warning("tra viec %s: %s", lease["lease_id"], reason)
        self.release_raw(lease["lease_id"], reason)
        self.abandon(lease)

    # -- mot lease --
    def work_lease(self, lease) -> str:
        eid, lid = lease["episode_id"], lease["lease_id"]
        d = self.ep_dir(lease)
        d.mkdir(parents=True, exist_ok=True)
        params = lease["params"]
        frames, L = int(lease["frames"]), int(lease["segment_frames"])
        fps = parse_fps(lease["fps"])
        nseg = total_segments(frames, L)
        src = d / "source.mp4"
        # doan 'encoded' ma file mat -> lam lai
        for n in range(nseg):
            s = self.state.seg(n)
            if s and s["state"] == "encoded" and not (d / seg_name(n)).exists():
                self.state.drop_seg(n)
        if params.get("model") != "realesr-general-x4v3":
            self.release(lease, f"model khong ho tro: {params.get('model')}")
            return "released"

        if not self.ensure_source(lease, src):
            return "stopped" if self.stop.is_set() else "released"

        self.halt.clear()
        self.lost.clear()
        threads = [threading.Thread(target=self._uploader, args=(lease, d), name="uploader", daemon=True),
                   threading.Thread(target=self._heartbeat, args=(lease, nseg), name="heartbeat", daemon=True)]
        for t in threads:
            t.start()
        try:
            return self._segments_loop(lease, d, src, params, frames, L, fps, nseg)
        finally:
            self.halt.set()
            for t in threads:
                t.join(timeout=10)

    def _segments_loop(self, lease, d, src, params, frames, L, fps, nseg) -> str:
        eng = self.get_engine()
        wh = ffprobe_size(self.cfg["ffprobe"], src)
        done_this_run = 0
        fails: dict[int, int] = {}
        n = 0
        while n < nseg:
            self._check_stop_ok()
            s = self.state.seg(n)
            if s:
                n += 1
                continue
            if self.max_segments and done_this_run >= self.max_segments:
                break
            if not self.wait_may_run(eng):
                return "stopped"
            if not self.wait_disk(d):
                return "stopped"
            start, count = seg_range(n, L, frames)
            out = d / seg_name(n)
            abort = threading.Event()
            watcher = threading.Thread(target=self._watch_abort, args=(abort,), daemon=True)
            watcher.start()
            try:
                st = eng.run_segment(src, start, count, fps, wh, params, out, abort)
            except Aborted:
                abort.set()
                self._check_stop_ok()
                return "stopped"
            except (RuntimeError, ValueError, OSError) as e:
                abort.set()
                fails[n] = fails.get(n, 0) + 1
                log.error("doan %d loi (lan %d): %s", n, fails[n], e, exc_info=log.isEnabledFor(logging.DEBUG))
                if eng.encoder == "h264_nvenc" and "nvenc" in str(e).lower():
                    log.warning("NVENC loi -> chuyen libx264")
                    eng.encoder = "libx264"
                if fails[n] >= 3:
                    self.release(lease, f"doan {n} loi lien tiep: {str(e)[:150]}")
                    return "released"
                self.sleep(5)
                continue
            finally:
                abort.set()
            sha = sha256_file(out)
            self.state.set_seg(n, "encoded", sha, out.stat().st_size)
            self.stats["encoded"] += 1
            done_this_run += 1
            log.info("doan %d/%d xong: %d khung %s %.1fs (%.1f khung/s) batch<=%d luong doc=%s enc=%s",
                     n + 1, nseg, st["frames"], st["out_size"], st["seconds"],
                     st["frames"] / max(st["seconds"], 1e-6), st["max_batch"], st["reader_thread"], st["encoder"])
            n += 1
        # cho upload het
        limit = time.time() + (self.cfg["drain_seconds"] if self.max_segments and done_this_run >= self.max_segments else 10 ** 9)
        while self.state.count("encoded") > 0:
            self._check_stop_ok()
            if time.time() > limit:
                log.info("het thoi gian cho upload (%ss); ket thuc, doan con lai upload o lan chay sau", self.cfg["drain_seconds"])
                return "stopped"
            self.sleep(0.2)
        if self.max_segments and self.state.count("uploaded") < nseg:
            return "stopped"
        log.info("tap %s: da upload du %d doan -> xoa nguon cuc bo", lease["episode_id"], nseg)
        self.abandon(lease)
        return "done"

    def _check_stop_ok(self):
        """Nem LeaseLost/AuthError tu luong phu; dung -> Aborted duoc xu ly boi caller."""
        if self._fatal is not None:
            e, self._fatal = self._fatal, None
            raise e
        if self.lost.is_set():
            raise LeaseLost("lease khong con hieu luc")
        if self.stop.is_set():
            raise Aborted("stop")

    def _watch_abort(self, abort: threading.Event):
        while not abort.wait(0.2):
            if self.stop.is_set() or self.lost.is_set() or self._fatal is not None:
                abort.set()
                return

    # -- nguon --
    def ensure_source(self, lease, src: Path) -> bool:
        part = src.with_name("source.part")
        if self.state.data["source_ok"] and src.exists():
            return True
        size = int(lease["source_size"])
        if self.disk_used() + size > self.cfg["max_disk_gb"] * 2 ** 30:
            self.release(lease, "het dung luong toi da cua worker (max_disk_gb)")
            self.sleep(self.cfg["error_seconds"])
            return False
        path = urllib.parse.urlsplit(lease["source_url"])
        pq = path.path + (f"?{path.query}" if path.query else "")
        if not pq.startswith("/"):
            pq = f"/api/enhance/{lease['lease_id']}/source"
        bad = 0
        backoff = 2
        while not self.stop.is_set():
            try:
                log.info("tai nguon (%d MB, da co %d MB)", size >> 20, (part.stat().st_size if part.exists() else 0) >> 20)
                self.api.download(pq, part, self.stop)
                got = part.stat().st_size
                if got < size:
                    raise NetError(f"moi nhan {got}/{size} byte")
                if got != size or sha256_file(part) != lease["source_sha256"]:
                    bad += 1
                    log.error("nguon sai kich thuoc / sha256 (lan %d)", bad)
                    part.unlink(missing_ok=True)
                    if bad >= 3:
                        self.release(lease, "nguon tai ve sai sha256")
                        return False
                    continue
                os.replace(part, src)
                self.state.data["source_ok"] = True
                self.state.save()
                log.info("tai nguon xong, sha256 khop")
                return True
            except Aborted:
                return False
            except NetError as e:
                log.warning("tai nguon dut (%s) - tiep tuc sau %ss (Range)", e, backoff)
                if self.sleep(backoff):
                    return False
                backoff = min(backoff * 2, 60)
            except LeaseLost:
                raise
            except HttpError as e:
                log.error("tai nguon loi: %s", e)
                self.release(lease, f"tai nguon loi {e.status}")
                return False
        return False

    # -- E7 --
    def wait_may_run(self, eng) -> bool:
        paused_logged = False
        while not self.stop.is_set():
            self._check_stop_ok()
            try:
                query = {"worker": self.cfg["worker_name"]}
                stats = self.gpu_stats()
                if stats:
                    query["gpu_stats"] = json.dumps(stats, separators=(",", ":"))  # CP8.28: VM cu bo qua
                _, data = self.api.call_json("GET", "/api/enhance/may-run?" + urllib.parse.urlencode(query))
            except (NetError, HttpError) as e:  # offline / VM khong tra loi -> cu lam (E4 offline)
                log.debug("may-run khong hoi duoc (%s) - coi nhu run=true", e)
                return True
            if data is None or data.get("run", True):
                if paused_logged:
                    log.info("may-run: tiep tuc")
                return True
            if not paused_logged:
                log.info("may-run: false (%s) - tam dung, hoi lai moi %ss", data.get("reason", ""), self.cfg["may_run_seconds"])
                paused_logged = True
                if self.cfg["yield_to_ollama"]:
                    eng.release_vram()
            self.sleep(self.cfg["may_run_seconds"])
        return False

    def wait_disk(self, d: Path) -> bool:
        limit = self.cfg["max_disk_gb"] * 2 ** 30
        warned = False
        while self.disk_used() > limit:
            if not warned:
                log.warning("dung luong lam viec vuot %.0f GB (doan cho upload) - tam dung enhance", self.cfg["max_disk_gb"])
                warned = True
            self._check_stop_ok()
            self.sleep(5)
        return not self.stop.is_set()

    # -- luong phu --
    def heartbeat_once(self, lease):
        body = {"progress": {
            "segments_uploaded": self.state.count("uploaded"), "segments_encoded": self.state.count("encoded"),
            "segments_total": total_segments(int(lease["frames"]), int(lease["segment_frames"]))}}
        stats = self.gpu_stats()
        if stats:
            body["gpu_stats"] = stats  # CP8.28: truong tuy chon, VM cu bo qua
        _, data = self.api.call_json("POST", f"/api/enhance/{lease['lease_id']}/heartbeat", body)
        if isinstance(data, dict) and data.get("expires_at"):
            lease["expires_at"] = data["expires_at"]

    def _heartbeat(self, lease, nseg):
        while not self.halt.wait(self.cfg["heartbeat_seconds"]):
            try:
                self.heartbeat_once(lease)
            except LeaseLost:
                self.lost.set()
                return
            except AuthError as e:
                self._fatal = e
                return
            except (NetError, HttpError) as e:
                log.debug("heartbeat: %s", e)

    def _uploader(self, lease, d: Path):
        backoff = self.cfg["upload_backoff_seconds"]
        offline = False
        tries: dict[int, int] = {}
        while not self.halt.is_set():
            n = self.state.next_pending()
            if n is None:
                self.halt.wait(0.2)
                continue
            f = d / seg_name(n)
            s = self.state.seg(n)
            try:
                status, _ = self.api.put_file(f"/api/enhance/{lease['lease_id']}/seg/{n}", f, s["sha256"])
            except NetError as e:
                if not offline:
                    log.warning("upload doan %d that bai (%s) - offline, enhance van tiep tuc; thu lai moi %ss+", n, e, backoff)
                offline = True
                self.halt.wait(backoff)
                backoff = min(backoff * 2, self.cfg["upload_backoff_max_seconds"])
                continue
            except LeaseLost as e:
                log.warning("upload doan %d: lease mat (%s)", n, e)
                self.lost.set()
                return
            except AuthError as e:
                self._fatal = e
                return
            except HttpError as e:
                tries[n] = tries.get(n, 0) + 1
                log.error("upload doan %d bi VM tu choi: %s (lan %d)", n, e, tries[n])
                if tries[n] >= 3:
                    self._fatal = RuntimeError(f"VM tu choi doan {n} nhieu lan: {e}")
                    return
                f.unlink(missing_ok=True)
                self.state.drop_seg(n)  # enhance lai doan nay
                continue
            if offline:
                log.info("co ket noi lai - upload tiep")
            offline = False
            backoff = self.cfg["upload_backoff_seconds"]
            self.state.set_seg(n, "uploaded", s["sha256"], s["size"])
            f.unlink(missing_ok=True)
            self.stats["uploaded"] += 1
            self.stats["put_ok"] += 1
            log.info("da upload doan %d (HTTP %d, %d MB)", n, status, s["size"] >> 20)


# ---------------------------------------------------------------------------
# --self-test
# ---------------------------------------------------------------------------


def self_test(cfg: dict) -> int:
    ok, warn_list, fail = [], [], []
    out = lambda tag, msg: print(f"[{tag}] {msg}", flush=True)  # noqa: E731
    out("INFO", f"enhance worker v{__version__} '{cfg['worker_name']}' (yield_to_ollama={cfg['yield_to_ollama']})")

    # ffmpeg
    try:
        subprocess.run([cfg["ffmpeg"], "-version"], capture_output=True, check=True)
        subprocess.run([cfg["ffprobe"], "-version"], capture_output=True, check=True)
        out(" OK ", "ffmpeg + ffprobe chay duoc")
    except (OSError, subprocess.SubprocessError) as e:
        fail.append("ffmpeg")
        out("FAIL", f"khong chay duoc ffmpeg/ffprobe ({e})")

    eng = None
    try:
        eng = Engine(cfg)
        if eng.dev == "cuda":
            p = eng.torch.cuda.get_device_properties(0)
            out(" OK ", f"GPU {p.name}, VRAM {p.total_memory / 2 ** 30:.1f} GB, torch {eng.torch.__version__} CUDA {eng.torch.version.cuda}")
        else:
            out("WARN" if cfg["device"] != "cpu" else " OK ", f"chay tren CPU (torch {eng.torch.__version__})")
            if cfg["device"] != "cpu":
                warn_list.append("cpu")
    except Exception as e:
        fail.append("gpu")
        out("FAIL", f"GPU / torch: {e}")

    if eng is not None and "ffmpeg" not in fail:
        if eng.encoder == "h264_nvenc":
            out(" OK ", "NVENC (h264_nvenc) dung duoc")
        else:
            warn_list.append("nvenc")
            out("WARN", "khong co NVENC -> se dung libx264 (CPU, cham hon)")
        # enhance mot doan mau
        try:
            with tempfile.TemporaryDirectory() as td:
                sample, outp = Path(td) / "s.mp4", Path(td) / "o.mp4"
                subprocess.run([cfg["ffmpeg"], "-v", "error", "-y", "-f", "lavfi", "-i",
                                "testsrc=size=320x240:rate=25:duration=0.6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                str(sample)], check=True)
                params = {"model": "realesr-general-x4v3", "denoise": 1.0, "pre_height": 240, "out_height": 480}
                if not (Path(cfg["models_dir"]) / "realesr-general-x4v3.pth").exists():
                    raise FileNotFoundError(f"thieu trong so: {Path(cfg['models_dir']) / 'realesr-general-x4v3.pth'}")
                st = eng.run_segment(sample, 0, 15, Fraction(25), (320, 240), params, outp, threading.Event())
                w, h = ffprobe_size(cfg["ffprobe"], outp)
                out(" OK ", f"enhance mau: {st['frames']} khung -> {w}x{h} trong {st['seconds']}s "
                           f"(batch<={st['max_batch']}, luong doc={st['reader_thread']})")
        except Exception as e:
            fail.append("enhance")
            out("FAIL", f"enhance doan mau: {e}")

    # VM
    api = Api(cfg["server_url"], cfg["token"], 10)
    vm = "?"
    try:
        _, data = api.call_json("GET", "/api/enhance/may-run?" + urllib.parse.urlencode({"worker": cfg["worker_name"]}))
        vm = f"API co san (may-run: run={data.get('run') if isinstance(data, dict) else '?'})"
        out(" OK ", f"VM: {vm}")
    except NotFound:
        vm = "ket noi duoc, VM chua co API enhance (404 - binh thuong truoc CP13.1b)"
        out(" OK ", f"VM: {vm}")
    except AuthError:
        reach = "reachable-unauthorized"
        if not cfg["token"]:
            vm = f"{reach}: VM tra 401: chua co token (VM cap o CP13.1b) - tunnel OK"
        else:
            vm = f"{reach}: VM tra 401: token sai hoac VM chua co API enhance (CP13.1b) - tunnel OK"
        warn_list.append("vm")
        out("WARN", f"VM: {vm}")
    except NetError as e:
        vm = f"khong noi duoc ({e}) - kiem tra tunnel {cfg['server_url']}"
        warn_list.append("vm")
        out("WARN", f"VM: {vm}")
    except HttpError as e:
        vm = f"phan hoi la: {e}"
        warn_list.append("vm")
        out("WARN", f"VM: {vm}")

    verdict = "FAIL" if fail else ("OK voi canh bao" if warn_list else "OK")
    print(f"SELF-TEST {verdict}: gpu={eng.gpu if eng else '?'} encoder={eng.encoder if eng else '?'} vm={vm}"
          + (f" loi={','.join(fail)}" if fail else ""), flush=True)
    return EXIT_ERROR if fail else EXIT_OK


# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Enhance worker (CP13.1a)")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--once", action="store_true", help="lam xong mot viec roi thoat (hoac thoat neu khong co viec)")
    ap.add_argument("--max-segments", type=int, default=0, help="thoat sau khi enhance N doan (giu trang thai)")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default=None)
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config, {"device": a.device})
    except (OSError, ValueError) as e:
        print(f"Khong doc duoc config {a.config}: {e}", file=sys.stderr)
        return EXIT_AUTH
    setup_logging(cfg, console=not a.self_test)
    if a.self_test:
        return self_test(cfg)
    stop = threading.Event()

    def _sig(signum, _frame):
        log.info("nhan tin hieu %s - dung sau doan hien tai", signum)
        stop.set()

    for s in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, s):
            try:
                signal.signal(getattr(signal, s), _sig)
            except (ValueError, OSError):
                pass
    try:
        return Worker(cfg, once=a.once, max_segments=a.max_segments, stop=stop,
                      config_path=a.config, overrides={"device": a.device}).run()
    except Exception:
        log.exception("worker loi khong xu ly duoc")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
