"""CP11-R1: Shorts of one render run are encoded in parallel (``[render] jobs``); the planning stays sequential, so
the output is identical to ``jobs = 1``; a failing Short stops new encodes and reports the first failing clip."""

import json
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.hashing import config_hash, sha256_file
from auto_short.render import RenderError, run_render
from auto_short.render.stage import used_config
from render_helpers import CANDIDATES, CLIPS, EID, TITLES, make_render_episode, make_source, write_docs

pytestmark = pytest.mark.usefixtures("_ffmpeg")

# Four Shorts (k01-k04): k03/k04 are plain clips over the whole of candidate c00003.
CLIPS4 = CLIPS + [
    {"id": "k03", "candidate_id": "c00003", "source_start": 0.0, "source_end": 3.0, "source_duration": 3.0,
     "duration": 3.0, "head_cut": None},
    {"id": "k04", "candidate_id": "c00003", "source_start": 3.0, "source_end": 6.0, "source_duration": 3.0,
     "duration": 3.0, "head_cut": None},
]
TITLES4 = {**TITLES, "k03": "Ba là con số may mắn", "k04": "Bốn mùa đều có cái đẹp"}


@pytest.fixture(scope="session")
def _ffmpeg(_video_template):
    return None


@pytest.fixture(scope="session")
def source_template(tmp_path_factory, _ffmpeg) -> Path:
    return make_source(tmp_path_factory.mktemp("par") / "src.mp4")


def _cfg(tmp_path, jobs=1) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast", jobs=jobs))


@pytest.fixture
def ws(tmp_path, source_template):
    ws = make_render_episode(tmp_path / "work", source_template)
    write_docs(ws, clips=CLIPS4, titles=TITLES4)
    return ws


class Gate:
    """Runner double: runs ffmpeg for real, counts the ffmpeg commands running at the same time (sleeping a
    little to overlap them), optionally failing the ffmpeg of some clips."""

    def __init__(self, fail: dict[str, float] | None = None, delay: float = 0.3):
        self.fail = fail or {}  # clip id -> seconds to wait before failing
        self.delay = delay
        self.lock = threading.Lock()
        self.running = self.peak = 0
        self.started: list[str] = []

    def __call__(self, cmd):
        if cmd[0] != "ffmpeg":
            return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
        cid = Path(cmd[-1]).name.split(".")[1]
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
            self.started.append(cid)
        try:
            time.sleep(self.delay if cid not in self.fail else self.fail[cid])
            if cid in self.fail:
                return subprocess.CompletedProcess(cmd, 1, "", f"[fake] {cid} failed\n")
            return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
        finally:
            with self.lock:
                self.running -= 1


def _out(cfg):
    return (cfg.render.output_dir / EID).resolve()


def _snapshot(cfg):
    root = cfg.render.output_dir
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_concurrency_bounded_by_jobs(ws, tmp_path):
    gate = Gate()
    res = run_render(EID, _cfg(tmp_path, 3), run=gate)
    assert res.encoded == 4 and gate.peak == 3

    gate = Gate()
    run_render(EID, _cfg(tmp_path, 4), force=True, run=gate)
    assert gate.peak == 4


@pytest.mark.slow
def test_jobs_one_is_sequential(ws, tmp_path):
    gate = Gate(delay=0.05)
    run_render(EID, _cfg(tmp_path, 1), run=gate)
    assert gate.peak == 1 and gate.started == ["k01", "k02", "k03", "k04"]


def test_output_identical_to_jobs_one(ws, tmp_path):
    cfg1 = _cfg(tmp_path, 1)
    run_render(EID, cfg1)
    m1 = (_out(cfg1) / "render_manifest.json").read_bytes()
    shas1 = {p.name: sha256_file(p) for p in (_out(cfg1) / "shorts").glob("*.mp4")}
    assert len(shas1) == 4
    cfg4 = _cfg(tmp_path, 4)
    assert run_render(EID, cfg4, force=True).ran
    assert (_out(cfg4) / "render_manifest.json").read_bytes() == m1
    assert {p.name: sha256_file(p) for p in (_out(cfg4) / "shorts").glob("*.mp4")} == shas1
    assert {s["clip_id"]: s["sha256"] for s in json.loads(m1)["shorts"]} == \
        {k[:-4]: v for k, v in shas1.items()}
    assert [s["clip_id"] for s in json.loads(m1)["shorts"]] == ["k01", "k02", "k03", "k04"]


def test_failure_reports_first_clip_and_cleans(ws, tmp_path):
    cfg = _cfg(tmp_path, 2)
    run_render(EID, cfg)
    before = _snapshot(cfg)
    # k02 fails fast, k01 (slow) is still running; k03 fails too but k01/k02 come first in clip order.
    gate = Gate(fail={"k02": 0.05, "k01": 0.4, "k03": 0.0})
    with pytest.raises(RenderError, match=r"clip k01: ffmpeg failed: \[fake\] k01 failed"):
        run_render(EID, cfg, force=True, run=gate)
    assert "k03" not in gate.started and "k04" not in gate.started  # no encode starts after the first failure
    entry = json.loads(ws.manifest_path.read_text(encoding="utf-8"))["stages"]["render"]
    assert entry["status"] == "failed" and "clip k01: ffmpeg failed" in entry["error"]
    assert _snapshot(cfg) == before  # previous render intact, no .part left


def test_failure_without_previous_render_leaves_nothing(ws, tmp_path):
    cfg = _cfg(tmp_path, 4)
    with pytest.raises(RenderError, match="clip k03: ffmpeg failed"):
        run_render(EID, cfg, run=Gate(fail={"k03": 0.05}))
    root = cfg.render.output_dir
    assert not root.exists() or [p for p in root.rglob("*") if p.is_file()] == []


def test_reuse_with_jobs(ws, tmp_path):
    cfg = _cfg(tmp_path, 4)
    run_render(EID, cfg)
    gate = Gate(delay=0.01)
    res = run_render(EID, cfg, force=False, run=gate)
    assert not res.ran and gate.started == []
    # change one title: only k03 is encoded, the other three are reused (T5)
    write_docs(ws, clips=CLIPS4, titles={**TITLES4, "k03": "Ba là con số rất may mắn"})
    gate = Gate(delay=0.01)
    res = run_render(EID, cfg, run=gate)
    assert (res.encoded, res.reused) == (1, 3) and gate.started == ["k03"]


def test_jobs_does_not_change_config_hash_or_stale(ws, tmp_path):
    assert config_hash(used_config(replace(RenderConfig(), jobs=8), "f" * 64)) == \
        config_hash(used_config(RenderConfig(), "f" * 64))
    run_render(EID, _cfg(tmp_path, 1))
    gate = Gate()
    assert not run_render(EID, _cfg(tmp_path, 4), run=gate).ran and gate.started == []
