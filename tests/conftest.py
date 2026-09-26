import shutil
import subprocess
from pathlib import Path

import pytest

from auto_short.config import Config, IngestConfig, WorkspaceConfig


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
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), ingest=IngestConfig())


@pytest.fixture
def config_file(tmp_path) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(f'[workspace]\ndir = "{(tmp_path / "work").as_posix()}"\n', encoding="utf-8")
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
