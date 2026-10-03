"""Helpers for the CP13.1b enhance tests: a low-resolution YouTube-like episode with a real (tiny) source, segments of
the right size made with ffmpeg, a config with small enhance parameters."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from auto_short.config import Config, EnhanceConfig, RenderConfig, WebConfig, WorkspaceConfig
from auto_short.enhance import state as st
from auto_short.hashing import fingerprint
from auto_short.workspace import DONE, Workspace

T1 = "a" * 40  # worker tokens (>= 32 characters)
T2 = "b" * 40
FPS, SRC_W, SRC_H, FRAMES = 25, 320, 240, 90  # 3.6 s: with 25-frame segments -> 25, 25, 25, 15
SEG = 25
OUT_W, OUT_H = 640, 480  # pre_height 0, x4 -> 1280x960, out_height 480


def enhance_cfg(tmp_path: Path, *, enabled: bool = True, **kw) -> Config:
    enh = EnhanceConfig(enabled=enabled, pre_height=0, out_height=OUT_H, segment_seconds=1, lease_hours=48,
                        **kw)
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast"),
                  web=WebConfig(session_days=30), enhance=enh)


def make_clip(path: Path, *, w: int, h: int, frames: int, fps: int = FPS, audio: bool = False,
              seed: int = 1) -> Path:
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={440 + seed}:sample_rate=48000"]
    cmd += ["-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-ac", "2", "-shortest"]
    else:
        cmd += ["-an"]
    subprocess.run(cmd + [str(path)], check=True)
    return path


def make_segment(path: Path, n: int, *, frames: int | None = None, w: int = OUT_W, h: int = OUT_H) -> bytes:
    """A valid segment ``n`` (right frame count / size) for the helper source; returns its bytes."""
    want = frames if frames is not None else min(SEG, FRAMES - n * SEG)
    make_clip(path, w=w, h=h, frames=want, seed=n)
    return path.read_bytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_yt_episode(cfg: Config, eid: str = "vid00000001", *, height: int = SRC_H, with_enhance: bool = True,
                    template: Path | None = None, kind: str = "youtube", ingest_only: bool = False) -> Workspace:
    """A workspace holding a downloaded low-resolution source (``source.mp4``) + manifest + metadata.json. With
    ``ingest_only`` only the ingest stage is ``done`` (the decision point of E1)."""
    ws = Workspace(Path(cfg.workspace.dir), eid)
    ws.dir.mkdir(parents=True, exist_ok=True)
    src = ws.dir / "source.mp4"
    if template is not None:
        shutil.copy2(template, src)
    else:
        make_clip(src, w=SRC_W * height // SRC_H, h=height, frames=FRAMES, audio=True)
    fp = fingerprint(src)
    info = st.probe_video(src)
    (ws.dir / "metadata.json").write_text(json.dumps({
        "schema_version": 1, "episode_id": eid, "title": "Địa Tạng", "duration": info["duration"],
        "width": info["width"], "height": info["height"], "fps": FPS}), encoding="utf-8")
    manifest = ws.new_manifest({"kind": kind, "uri": f"https://youtu.be/{eid}", "path": "source.mp4",
                                "sha256": fp.sha256, "size": fp.size, "mtime_ns": fp.mtime_ns})
    stages = ("ingest",) if ingest_only else ("ingest", "transcript", "analysis", "selection", "titling")
    for stage in stages:
        manifest["stages"][stage] = {"status": DONE, "artifacts": [], "inputs": [], "config_hash": "x",
                                     "started_at": "2026-10-03T00:00:00Z", "finished_at": "2026-10-03T00:01:00Z",
                                     "error": None}
    ws.save_manifest(manifest)
    if with_enhance:
        st.decide(cfg, eid)
    return ws
