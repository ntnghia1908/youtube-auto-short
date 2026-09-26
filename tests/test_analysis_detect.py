"""Shot / silence detection: ffmpeg log parsers and the real ffmpeg analyzer (AC1)."""

import shutil
import subprocess

import pytest

from auto_short.analysis import AnalysisError
from auto_short.analysis.detect import (
    FfmpegAnalyzer,
    normalize_changes,
    normalize_silences,
    parse_showinfo,
    parse_silencedetect,
)
from analysis_helpers import SHOWINFO_LOG, SILENCEDETECT_LOG


def test_parse_showinfo_reads_frame_pts_only():
    assert parse_showinfo(SHOWINFO_LOG) == [21.3213, 47.9479, 3621.58]
    assert parse_showinfo("") == []


def test_normalize_changes_rounds_sorts_and_keeps_inside_duration():
    assert normalize_changes([47.9479, 21.3213, 21.32131, 0.0, 3622.001, 3700.0], 3622.001) == [21.321, 47.948]


def test_parse_silencedetect_merges_clamps_and_closes_at_duration():
    assert parse_silencedetect(SILENCEDETECT_LOG, 3622.001) == [
        (0.0, 0.5),  # negative start clamped
        (19.667, 22.875),
        (25.8, 30.925),  # 0.0002 s apart -> merged
        (65.148, 77.672),  # touching -> merged (12.5 s)
        (79.701, 80.565),
        (3620.55, 3622.001),  # unterminated -> ends at duration
    ]


def test_normalize_silences_gap_threshold():
    # < 0.05 s apart merges, >= 0.05 s does not.
    assert normalize_silences([(1.0, 2.0), (2.049, 3.0)], 10) == [(1.0, 3.0)]
    assert normalize_silences([(1.0, 2.0), (2.05, 3.0)], 10) == [(1.0, 2.0), (2.05, 3.0)]
    assert normalize_silences([(5.0, 6.0), (1.0, 2.0), (9.5, 12.0)], 10) == [(1.0, 2.0), (5.0, 6.0), (9.5, 10.0)]


@pytest.fixture(scope="module")
def two_shot_clip(tmp_path_factory):
    """4 s clip: red 2 s then blue 2 s (one shot change); tone 1.5 s then silence."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "two_shots.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=64x48:r=10:d=2",
        "-f", "lavfi", "-i", "color=c=blue:s=64x48:r=10:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2.5",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out),
    ], check=True)
    return out


def test_ffmpeg_analyzer_detects_shot_change_and_trailing_silence(two_shot_clip):
    analyzer = FfmpegAnalyzer()
    assert analyzer.shot_changes(two_shot_clip, threshold=0.3, scale_width=32) == [2.0]
    silences = analyzer.silences(two_shot_clip, noise_db=-45, min_seconds=0.3, duration=4.0)
    assert len(silences) == 1 and silences[0][1] == 4.0 and 1.4 <= silences[0][0] <= 1.6


def test_ffmpeg_failure_is_an_analysis_error(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"not a video")
    with pytest.raises(AnalysisError, match="ffmpeg failed"):
        FfmpegAnalyzer().silences(bogus, noise_db=-45, min_seconds=0.3, duration=1.0)
