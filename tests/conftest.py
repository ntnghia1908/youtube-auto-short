import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import AnalysisConfig, Config, IngestConfig, RenderConfig, WorkspaceConfig


def make_video(path: Path, seconds: int = 2, freq: int = 440) -> Path:
    """Synthetic H.264/AAC clip generated with ffmpeg lavfi sources."""
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="session")
def _video_template(tmp_path_factory) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    return make_video(tmp_path_factory.mktemp("media") / "template.mp4")


@pytest.fixture
def video(tmp_path, _video_template) -> Path:
    """A fresh copy of the synthetic clip, named like a real lecture file."""
    dst = tmp_path / "src" / "Bài Giảng Tập 9.mp4"
    dst.parent.mkdir()
    shutil.copy2(_video_template, dst)
    return dst


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), ingest=IngestConfig(),
                  analysis=AnalysisConfig(min_boundary_silence_floor=3.0),  # pre-CP8.23 rules (CP8.23 has its own tests)
                  render=replace(RenderConfig(), output_dir=tmp_path / "output"))


@pytest.fixture
def config_file(tmp_path) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(
        f'[workspace]\ndir = "{(tmp_path / "work").as_posix()}"\n'
        f'[render]\noutput_dir = "{(tmp_path / "output").as_posix()}"\n',
        encoding="utf-8",
    )
    return p


@pytest.fixture(autouse=True)
def _reset_cli_logging():
    """cli.main() installs its own handler; restore defaults so caplog keeps working."""
    import logging
    yield
    log = logging.getLogger("auto_short")
    for h in list(log.handlers):
        log.removeHandler(h)
    log.propagate = True
    log.setLevel(logging.NOTSET)


@pytest.fixture(autouse=True)
def _isolate_post_corrections(tmp_path_factory, monkeypatch):
    """CP8.18 D1: the default ``[post] corrections_path`` is under the home dir; no test may touch it."""
    import auto_short.config as config_mod
    path = tmp_path_factory.mktemp("post-corrections") / "post-corrections.json"
    monkeypatch.setattr(config_mod, "_default_corrections_path", lambda: path)


@pytest.fixture(autouse=True)
def _no_real_services(monkeypatch):
    """FIX-test-speed T2: no test may open a connection to the real Ollama (ports 11434 / 11437) or to a
    non-loopback host. Loopback fake servers on other ports (tests' own) stay allowed."""
    import socket
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(addr):
        if isinstance(addr, tuple) and len(addr) >= 2 and isinstance(addr[0], str):
            host, port = addr[0], addr[1]
            loopback = host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")
            if port in (11434, 11437) or (not loopback and host not in ("", "0.0.0.0")):
                raise AssertionError(f"test tried to reach a real service: {host}:{port} (inject a fake)")

    def guarded(self, addr):
        _check(addr)
        return real_connect(self, addr)

    def guarded_ex(self, addr):
        _check(addr)
        return real_connect_ex(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)
