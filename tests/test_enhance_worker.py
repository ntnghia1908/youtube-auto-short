"""Tests CP13.1a: worker enhance (tools/enhance_worker) + fake server.

Worker chay nhu tien trinh con (`--device cpu`) bang Python co torch + numpy + opencv:
  - mac dinh: env conda `enhance-bench` (~/miniconda3/envs/enhance-bench);
  - ghi de bang `ENHANCE_WORKER_PYTHON=/duong/dan/python`.
Trong so: `ENHANCE_TEST_MODELS` (mac dinh ~/.cache/auto-short-cp13-test/models, can
`realesr-general-x4v3.pth`). Thieu Python-co-torch hoac trong so -> test tich hop SKIP
(phan khong can torch van chay trong env `auto-short`).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from fractions import Fraction
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "enhance_worker"
sys.path.insert(0, str(TOOLS))

import face as F  # noqa: E402
import fake_server  # noqa: E402
import worker as W  # noqa: E402

TOK = "test-token"
SEG = 20           # khung / doan; video 3 s x 25 fps = 75 khung -> 4 doan (doan cuoi 15 khung)
PARAMS = {"model": "realesr-general-x4v3", "denoise": 1.0, "pre_height": 32, "out_height": 96}


def _worker_python() -> str | None:
    cand = os.environ.get("ENHANCE_WORKER_PYTHON") or str(Path.home() / "miniconda3/envs/enhance-bench/bin/python")
    if not Path(cand).exists():
        return None
    r = subprocess.run([cand, "-c", "import torch, cv2, numpy"], capture_output=True)
    return cand if r.returncode == 0 else None


def _models_dir() -> Path | None:
    d = Path(os.environ.get("ENHANCE_TEST_MODELS") or Path.home() / ".cache/auto-short-cp13-test/models")
    return d if (d / "realesr-general-x4v3.pth").exists() else None


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg")
needs_torch = pytest.mark.skipif(_worker_python() is None or _models_dir() is None,
                                 reason="can Python co torch+cv2 (ENHANCE_WORKER_PYTHON) va trong so (ENHANCE_TEST_MODELS)")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("enh") / "tiny.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=25:duration=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10", str(p)], check=True)
    return p


@pytest.fixture
def server(tiny, tmp_path):
    made = []

    def make(**kw):
        s = fake_server.FakeServer(tiny, token=TOK, params=PARAMS, segment_frames=SEG,
                                   seg_dir=tmp_path / f"segs{len(made)}", **kw).start()
        made.append(s)
        return s

    yield make
    for s in made:
        s.stop()


class Run:
    """Mot worker (tien trinh con) voi thu muc rieng; giu work_dir / log giua cac lan chay."""

    def __init__(self, tmp: Path, srv, **cfg):
        self.dir = tmp / "wk"
        self.dir.mkdir(exist_ok=True)
        self.cfg = {"server_url": srv.url, "worker_name": "t", "token": TOK, "work_dir": "work",
                    "models_dir": str(_models_dir()), "device": "cpu", "cpu_threads": 4, "batch_size": 4,
                    "idle_seconds": 1, "not_found_seconds": 1, "may_run_seconds": 1, "error_seconds": 1,
                    "upload_backoff_seconds": 1, "upload_backoff_max_seconds": 2, "drain_seconds": 2,
                    "heartbeat_seconds": 30}
        self.cfg.update(cfg)
        self.procs = []

    def start(self, *args) -> subprocess.Popen:
        (self.dir / "config.json").write_text(json.dumps(self.cfg))
        env = dict(os.environ, OMP_NUM_THREADS="4", PYTHONUNBUFFERED="1")
        p = subprocess.Popen([_worker_python(), str(TOOLS / "worker.py"), "--config", str(self.dir / "config.json"), *args],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        self.procs.append(p)
        return p

    def finish(self, p, timeout=120) -> int:
        try:
            return p.wait(timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            pytest.fail("worker khong thoat dung han:\n" + self.log())

    def log(self) -> str:
        f = self.dir / "logs" / "worker.log"
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def state(self) -> dict:
        f = self.dir / "work" / "state.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def kill_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()


@pytest.fixture
def run(tmp_path, server):
    made = []

    def make(srv, **cfg):
        r = Run(tmp_path, srv, **cfg)
        made.append(r)
        return r

    yield make
    for r in made:
        r.kill_all()


def wait_for(cond, timeout=60, what="dieu kien"):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.1)
    pytest.fail(f"het gio cho {what}")


def count_frames(path: Path) -> tuple[int, int, int]:
    i = fake_server.probe("ffprobe", path)
    return i["frames"], i["w"], i["h"]


# --------------------------------------------------------------------------- khong can torch


def test_pure_helpers():
    assert W.parse_fps("30000/1001") == Fraction(30000, 1001)
    assert W.parse_fps(29.97) == Fraction(30000, 1001)
    assert W.parse_fps(25) == Fraction(25)
    assert W.seg_range(3, 20, 75) == (60, 15)
    assert W.total_segments(75, 20) == 4
    assert W.out_size(640, 480, 360, 1080) == (480, 360, 1440, 1080)
    assert W.out_size(352, 262, 0, 1080)[3] == 1080
    good = {"episode_id": "e1", "lease_id": "L1", "source_url": "/x", "source_sha256": "a", "source_size": 1, "fps": "25/1",
            "frames": 10, "segment_frames": 5, "params": dict(PARAMS), "config_hash": "c"}
    assert W.Worker.validate_lease(good) == ""
    assert "episode_id" in W.Worker.validate_lease({**good, "episode_id": "../x"})
    assert W.Worker.validate_lease({k: v for k, v in good.items() if k != "params"})


# --------------------------------------------------------------------------- CP13.4: buoc mat (ham gia, khong torch)


class FakeRestorer:
    """Thay FaceRestorer: moc mat = (x, 10) voi x = so thu tu khung (ma hoa o pixel [0,0]); 'phuc hoi' = ve o trang tai
    vi tri moc (de kiem 'dan lai dung cho')."""

    def __init__(self, no_face=()):
        self.det, self.restored, self.no_face = [], [], set(no_face)

    def landmarks(self, img):
        n = int(img[0, 0, 0])
        self.det.append(n)
        return None if n in self.no_face else __import__("numpy").array([[n, 10.0]] * 5, "float32")

    def restore_frames(self, frames, lms, batch=8):
        out = []
        for f, lm in zip(frames, lms):
            self.restored.append((int(f[0, 0, 0]), None if lm is None else float(lm[0][0])))
            g = f.copy()
            if lm is not None:
                g[int(lm[0][1]), 5, 1] = 255
            out.append(g)
        return out


def _frames(n):
    np = pytest.importorskip("numpy")
    fs = np.zeros((n, 20, 20, 3), "uint8")
    for i in range(n):
        fs[i, 0, 0, 0] = i
    return fs


def _run_stream(every, n, **kw):
    r = FakeRestorer(**kw)
    sp = F.SparseFace(r, every)
    out = []
    for f in _frames(n):
        out += sp.push(f)
    out += sp.flush()
    return r, out


def test_sparse_face_detects_every_n_and_interpolates_in_order():
    r, out = _run_stream(5, 13)
    assert len(out) == 13 and [int(o[0, 0, 0]) for o in out] == list(range(13))      # all frames, in order
    assert r.det == [0, 5, 10, 11, 12]                                               # keyframes + tail detected one by one
    # between keyframes 0 and 5 the landmark moves linearly (x = frame number here), restored in frame order
    assert [x for _, x in r.restored[:6]] == pytest.approx([0, 1, 2, 3, 4, 5])
    assert all(o[10, 5, 1] == 255 for o in out)                                      # the restored mark of every frame


def test_sparse_face_every_one_is_per_frame_and_missing_faces_fall_back():
    r, out = _run_stream(1, 6)
    assert r.det == list(range(6)) and len(out) == 6
    r, out = _run_stream(5, 11, no_face={5})                                         # no face at a keyframe
    assert len(out) == 11 and r.det == [0, 5, 1, 2, 3, 4, 10, 6, 7, 8, 9]  # in-between frames detected by themselves
    assert {n: x for n, x in r.restored}[3] == 3.0 and {n: x for n, x in r.restored}[5] is None
    r, out = _run_stream(5, 3)                                                       # shorter than N: all flushed
    assert len(out) == 3 and r.det == [0, 1, 2]


def test_face_stream_and_validate_lease_for_face():
    assert W.face_stream(None, {}) is None
    assert isinstance(W.face_stream(lambda f: f, {"face": "x"}), W._EachFrame)
    sp = W.face_stream(FakeRestorer(), {"face": F.FACE_MODEL, "face_detect_every": 4})
    assert isinstance(sp, F.SparseFace) and sp.every == 4
    good = {"episode_id": "e1", "lease_id": "L1", "source_url": "/x", "source_sha256": "a", "source_size": 1,
            "fps": "25/1", "frames": 10, "segment_frames": 5, "config_hash": "c",
            "params": {**PARAMS, "face": F.FACE_MODEL, "face_weight": 1.0}}
    assert W.Worker.validate_lease(good) == ""
    bad = {**good, "params": {**PARAMS, "face": "codeformer"}}
    assert "cap nhat worker" in W.Worker.validate_lease(bad)
    assert W.__version__ == "3" and F.CAPABILITY == "face:gfpgan_v1.4"


def test_worker_advertises_face_only_when_it_can_do_it(tmp_path, monkeypatch):
    cfg = W.load_config(None, {"models_dir": str(tmp_path)})
    w = W.Worker(cfg)
    monkeypatch.setattr(F, "support_problem", lambda d: "thieu goi")
    assert w.capabilities() == []
    monkeypatch.setattr(F, "support_problem", lambda d: "")
    assert w.capabilities() == ["face:gfpgan_v1.4"]
    w.cfg["face"] = "off"
    assert w.capabilities() == []
    monkeypatch.undo()
    assert F.support_problem(tmp_path)   # no package / no weights in an empty dir: a reason, never ''
    (tmp_path / "GFPGANv1.4.pth").write_bytes(b"x")
    assert "detection_Resnet50_Final.pth" in " ".join(F.missing_weights(tmp_path))


@needs_ffmpeg
def test_fake_server_auth_and_sha(server):
    s = server()
    api = W.Api(s.url, "bad")
    with pytest.raises(W.AuthError):
        api.call_json("POST", "/api/enhance/lease", {"worker": "t", "gpu": "x"})
    api = W.Api(s.url, TOK)
    _, lease = api.call_json("POST", "/api/enhance/lease", {"worker": "t", "gpu": "x"})
    assert lease["frames"] == 75 and lease["params"] == PARAMS
    with pytest.raises(W.HttpError) as ei:  # sha sai -> 400
        req = urllib.request.Request(s.url + f"/api/enhance/{lease['lease_id']}/seg/0", data=b"abc", method="PUT",
                                     headers={"Authorization": f"Bearer {TOK}", "X-Sha256": "0" * 64})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            raise W.HttpError(e.code) from None
    assert ei.value.status == 400


@needs_ffmpeg
def test_reader_is_frame_accurate(tiny):
    """Doan n = khung [n*L, (n+1)*L): khung dau doc bang -ss trung khung tham chieu (select)."""
    np = pytest.importorskip("numpy")
    import queue
    start, count = 40, 5
    q: queue.Queue = queue.Queue()
    W.read_frames("ffmpeg", tiny, start, count, Fraction(25), 64, 48, 64, 48, 2, q, threading.Event())
    got = []
    while True:
        it = q.get_nowait()
        if it is W._DONE:
            break
        got.extend(list(it))
    assert len(got) == count
    ref = subprocess.run(["ffmpeg", "-v", "error", "-i", str(tiny), "-vf", f"select='between(n,{start},{start + count - 1})'",
                          "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    refs = [np.frombuffer(ref[i * 64 * 48 * 3:(i + 1) * 64 * 48 * 3], np.uint8).reshape(48, 64, 3) for i in range(count)]
    for a, b in zip(got, refs):
        assert (a == b).all()


# --------------------------------------------------------------------------- tich hop (torch CPU)


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_full_episode(server, run, tmp_path):
    s = server()
    r = run(s)
    rc = r.finish(r.start("--once"))
    assert rc == 0, r.log()
    assert sorted(s.received) == [0, 1, 2, 3]
    assert all(c == 1 for c in s.put_counts.values()) and s.put_rejects == 0
    sizes = {n: count_frames(s.seg_dir / f"seg_{n:05d}.mp4") for n in range(4)}
    assert [sizes[n][0] for n in range(4)] == [20, 20, 20, 15]
    assert all(v[1:] == (126, 96) for v in sizes.values())  # tham so lay tu lease (pre 32 -> x4 -> 96)
    log = r.log()
    assert "frame-reader" in log and "batch<=4" in log           # AC4: luong doc + batch
    assert not (r.dir / "work" / "ep" / "ep1").exists()          # xoa nguon cuc bo khi xong
    assert r.state()["lease"] is None


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_offline_midway_then_reconnect(server, run):
    s = server()
    s.on_put = lambda n: threading.Thread(target=s.stop).start() if n == 0 else None
    r = run(s)
    p = r.start("--once")
    wait_for(lambda: len(s.received) == 1 and s.httpd is None, 30, "server dung sau doan 0")
    st = lambda: r.state().get("segments", {})  # noqa: E731
    wait_for(lambda: sum(1 for v in st().values() if v["state"] == "encoded") == 3, 90, "enhance tiep khi offline")
    assert "offline" in r.log()
    assert p.poll() is None
    s.start()                                                    # co mang lai (cung cong)
    assert r.finish(p) == 0, r.log()
    assert sorted(s.received) == [0, 1, 2, 3] and s.put_counts[0] == 1
    assert s.source_gets == 1                                    # khong tai lai nguon


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_restart_resumes_without_redo(server, run):
    s = server()
    r = run(s)
    assert r.finish(r.start("--once", "--max-segments", "2")) == 0, r.log()
    assert sorted(s.received) == [0, 1]
    assert r.state()["lease"]["lease_id"] == "L1"
    assert r.finish(r.start("--once")) == 0, r.log()
    assert sorted(s.received) == [0, 1, 2, 3]
    assert all(c == 1 for c in s.put_counts.values())            # khong upload lai
    assert s.source_gets == 1 and s.lease_calls == 1             # nguon + lease giu qua khoi dong lai
    second = r.log().split("tiep tuc viec dang do")[1]
    assert "doan 1/4 xong" not in second and "doan 3/4 xong" in second and "doan 4/4 xong" in second


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_restart_with_pending_uploads(server, run):
    s = server()
    s.on_put = lambda n: threading.Thread(target=s.stop).start() if n == 0 else None
    r = run(s)
    assert r.finish(r.start("--once", "--max-segments", "3")) == 0, r.log()   # offline: 3 doan encode, 1 upload
    assert sorted(s.received) == [0]
    s.start()
    assert r.finish(r.start("--once")) == 0, r.log()
    assert sorted(s.received) == [0, 1, 2, 3] and s.put_counts[0] == 1
    second = r.log().split("tiep tuc viec dang do")[1]
    assert "doan 2/4 xong" not in second and "doan 3/4 xong" not in second and "doan 4/4 xong" in second


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_may_run_false_pauses_after_current_segment(server, run):
    gate = {"open": False}
    s = server()
    s.may_run = lambda calls: calls == 1 or gate["open"]
    r = run(s)
    p = r.start("--once")
    wait_for(lambda: s.may_run_calls >= 5, 60, "worker hoi may-run theo chu ky")
    assert sorted(s.received) == [0]                             # dung sau doan hien tai
    assert p.poll() is None and "may-run: false" in r.log()
    gate["open"] = True
    assert r.finish(p) == 0, r.log()
    assert sorted(s.received) == [0, 1, 2, 3]


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_wrong_token_stops_with_log(server, run):
    s = server()
    r = run(s, token="sai-token")
    assert r.finish(r.start("--once")) == W.EXIT_AUTH
    assert "XAC THUC THAT BAI" in r.log() and "sai-token" not in r.log()


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_401_waits_and_rereads_config(server, run):
    """VM chua co API (login middleware tra 401) / token rong: worker khong thoat; sua token trong config -> tiep tuc."""
    s = server()
    s.api_401 = True
    r = run(s, token="", auth_retry_seconds=1)
    p = r.start()
    n401 = lambda: sum(1 for x in s.status_log if x[2] == 401)  # noqa: E731
    wait_for(lambda: n401() >= 2, 30, "2 lan 401")
    assert p.poll() is None and "VM tra 401" in r.log()
    s.api_401 = False
    r.cfg["token"] = TOK
    (r.dir / "config.json").write_text(json.dumps(r.cfg))      # khong restart worker
    wait_for(lambda: len(s.received) == 4, 120, "enhance xong sau khi sua token")
    p.send_signal(signal.SIGTERM)
    assert r.finish(p, 30) == 0
    assert TOK not in r.log()


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_404_keeps_polling(server, run):
    s = server()
    s.no_api = True
    r = run(s)
    p = r.start()
    wait_for(lambda: sum(1 for x in s.status_log if x[1] == "/api/enhance/lease" and x[2] == 404) >= 2, 30, "2 lan hoi lease 404")
    assert p.poll() is None
    p.send_signal(signal.SIGTERM)
    assert r.finish(p, 30) == 0
    assert "chua co API" in r.log()


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_lease_expired_abandons_and_continues(server, run):
    s = server()
    s.on_put = lambda n: s.expire_lease() if n == 0 else None
    r = run(s)
    assert r.finish(r.start("--once")) == 0, r.log()
    assert "bo viec" in r.log()
    assert s.lease_calls >= 2 and s.source_gets == 2             # lease moi, tai lai nguon
    assert sorted(s.received) == [0, 1, 2, 3] and s.put_counts[0] == 1   # doan da nhan duoc giu (done_segments)


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_source_download_resumes_with_range(server, run):
    s = server()
    s.cut_source_after = max(1, s.source_size // 2)
    r = run(s)
    assert r.finish(r.start("--once", "--max-segments", "1")) == 0, r.log()
    assert any(x.startswith("bytes=") and not x.startswith("bytes=0-") for x in s.range_requests)
    assert "tai nguon xong, sha256 khop" in r.log() and sorted(s.received) == [0]


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_self_test_reports_vm_states(server, run):
    s = server()
    r = run(s)
    (r.dir / "config.json").write_text(json.dumps(r.cfg))

    def self_test():
        return subprocess.run([_worker_python(), str(TOOLS / "worker.py"), "--config", str(r.dir / "config.json"),
                               "--self-test"], capture_output=True, text=True, timeout=120, cwd=r.dir)

    p = self_test()
    assert p.returncode == 0, p.stdout + p.stderr
    assert "SELF-TEST" in p.stdout and "API co san" in p.stdout
    s.no_api = True
    p = self_test()
    assert p.returncode == 0 and "chua co API enhance (404" in p.stdout
    s.no_api = False
    s.api_401 = True                                             # VM truoc CP13.1b: 401 cho moi /api/*
    r.cfg["token"] = ""
    (r.dir / "config.json").write_text(json.dumps(r.cfg))
    p = self_test()
    assert p.returncode == 0 and "reachable-unauthorized" in p.stdout and "chua co token" in p.stdout
    assert "SELF-TEST OK voi canh bao" in p.stdout and "FAIL" not in p.stdout
    r.cfg["token"] = "x"
    (r.dir / "config.json").write_text(json.dumps(r.cfg))
    p = self_test()
    assert p.returncode == 0 and "token sai hoac VM chua co API" in p.stdout
    s.api_401 = False
    s.stop()
    p = self_test()
    assert p.returncode == 0 and "khong noi duoc" in p.stdout


@needs_ffmpeg
@needs_torch
@pytest.mark.slow
def test_face_step_runs_on_every_frame_before_encoding(tiny, tmp_path):
    """CP13.4 AC1: Engine.run_segment applies the face step (fake restorer) to every frame, in order, after SRVGG and before
    the encoder: the marker it paints at a known place is in every encoded frame; sparse detection (every 3) detects
    only key frames and the number of frames out equals the number in."""
    script = tmp_path / "face_run.py"
    script.write_text("""
import json, sys, threading
from fractions import Fraction
from pathlib import Path
import numpy as np
sys.path.insert(0, %r)
import worker as W
cfg = W.load_config(None, {"device": "cpu", "models_dir": %r, "cpu_threads": 4, "batch_size": 4, "encoder": "libx264"})
class Fake:
    def __init__(self): self.det, self.n = [], 0
    def landmarks(self, img):
        self.det.append(self.n); self.n += 1
        return np.array([[8.0, 8.0]] * 5, "float32")
    def restore_frames(self, frames, lms, batch=8):
        out = []
        for f, lm in zip(frames, lms):
            g = f.copy(); x, y = int(lm[0][0]), int(lm[0][1])
            g[y - 6:y + 6, x - 6:x + 6] = 255      # a white square centred on the landmark
            out.append(g)
        return out
eng = W.Engine(cfg)
fake = Fake()
eng.face_factory = lambda params: fake
params = dict(%r, face="gfpgan_v1.4", face_weight=1.0, face_detect_every=int(sys.argv[2]))
st = eng.run_segment(Path(sys.argv[1]), 0, 20, Fraction(25), (64, 48), params, Path(sys.argv[3]), threading.Event())
print(json.dumps({"stats": st, "det": fake.det}))
""" % (str(TOOLS), str(_models_dir()), PARAMS))
    for every in (1, 3):
        out = tmp_path / f"seg{every}.mp4"
        p = subprocess.run([_worker_python(), str(script), str(tiny), str(every), str(out)], capture_output=True, text=True,
                           timeout=180, env=dict(os.environ, OMP_NUM_THREADS="4"))
        assert p.returncode == 0, p.stderr[-800:]
        info = json.loads(p.stdout.strip().splitlines()[-1])
        assert info["stats"]["frames"] == 20 and info["stats"]["face"] == "gfpgan_v1.4"
        assert count_frames(out) == (20, 126, 96)
        assert len(info["det"]) == (20 if every == 1 else 8)               # 7 key frames (0, 3 .. 18) + the tail frame
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True).stdout
        np = pytest.importorskip("numpy")
        fr = np.frombuffer(raw, np.uint8).reshape(20, 96, 126)
        assert all(f[4:12, 4:12].mean() > 200 for f in fr)                 # marker in every frame, at the landmark
        assert fr[:, 40:90, 60:120].mean() < 200                           # and only there
