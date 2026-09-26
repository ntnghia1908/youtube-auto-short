"""Shared helpers for transcript tests: fake episodes, caption fetcher and Whisper backend."""

from __future__ import annotations

import json
from pathlib import Path

from auto_short.transcript.parsers import RawSegment, RawWord
from auto_short.transcript.youtube import CaptionFetchError, CaptionTracks
from auto_short.workspace import Workspace, atomic_write_json

FIXTURES = Path(__file__).parent / "fixtures"
JSON3_HEAD = FIXTURES / "rbjfCfFq3Dk.head60.json3"  # first 60 s of the test video's auto caption
JSON3_HEAD_DURATION = 67.0  # last fixture event ends at 66.979 s
YT_URL = "https://youtu.be/rbjfCfFq3Dk"

SRT_VI = """1
00:00:00,500 --> 00:00:03,000
<i>Phật thuyết thập thiện</i> nghiệp đạo kinh

2
00:00:02,800 --> 00:00:06,000
người giảng lão pháp sư Tịnh Không

3
00:00:06,000 --> 00:00:09,500
{\\an8}tại Tịnh Tông Học Hội Singapore
"""

# YouTube-style roll-up WebVTT: each cue repeats the previous line, 10 ms transition cues.
VTT_ROLLUP = """WEBVTT
Kind: captions
Language: vi

NOTE rolled up like YouTube auto captions

00:00:00.500 --> 00:00:03.000 align:start position:0%
Phật<00:00:01.000><c> thuyết</c><00:00:01.500><c> thập</c><00:00:02.000><c> thiện</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
Phật thuyết thập thiện

00:00:03.010 --> 00:00:06.000 align:start position:0%
Phật thuyết thập thiện
nghiệp<00:00:03.500><c> đạo</c><00:00:04.000><c> kinh</c><00:00:05.000><c> tập</c><00:00:05.500><c> chín</c>

00:00:06.000 --> 00:00:06.010 align:start position:0%
nghiệp đạo kinh tập chín

00:00:06.010 --> 00:00:09.500 align:start position:0%
nghiệp đạo kinh tập chín
người<00:00:07.000><c> giảng</c><00:00:08.000><c> lão</c><00:00:08.500><c> pháp</c><00:00:09.000><c> sư</c>
"""

SUB_DURATION = 10.0  # media duration used with SRT_VI / VTT_ROLLUP


def make_episode(root: Path, *, episode_id: str = "ep", kind: str = "local", duration: float = SUB_DURATION,
                 media_stem: str = "lecture") -> tuple[Workspace, Path]:
    """Write a workspace whose ingest stage is done, without ffmpeg. Returns (ws, media path)."""
    ws = Workspace(root, episode_id)
    ws.dir.mkdir(parents=True)
    if kind == "local":
        media = root.parent / "media" / f"{media_stem}.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"not really a video")
        uri, path = str(media), str(media)
    else:
        media = ws.dir / "source.mp4"
        media.write_bytes(b"not really a video")
        uri, path = YT_URL, "source.mp4"
    source = {"kind": kind, "uri": uri, "path": path, "sha256": "ab" * 32, "size": 18, "mtime_ns": 1}
    atomic_write_json(ws.dir / "metadata.json", {
        "schema_version": 1, "episode_id": episode_id,
        "source": {k: source[k] for k in ("kind", "uri", "path", "sha256", "size")},
        "duration": duration, "width": 320, "height": 240, "fps": 25.0,
        "video_codec": "h264", "audio_codec": "aac",
    })
    manifest = ws.new_manifest(source)
    manifest["stages"]["ingest"] = {
        "status": "done", "artifacts": ["metadata.json"], "inputs": [], "config_hash": "x",
        "started_at": "2026-09-26T00:00:00Z", "finished_at": "2026-09-26T00:00:00Z", "error": None,
    }
    ws.save_manifest(manifest)
    return ws, media


def manifest_of(ws: Workspace) -> dict:
    return json.loads(ws.manifest_path.read_text(encoding="utf-8"))


class FakeFetcher:
    """Stands in for yt-dlp captions: no network."""

    def __init__(self, tracks: dict[tuple[str, bool], bytes] | None = None, fail: bool = False):
        self.data = tracks or {}
        self.fail = fail
        self.downloads: list[tuple[str, bool]] = []

    def tracks(self, url):
        if self.fail:
            raise CaptionFetchError("yt-dlp cannot read url: HTTP Error 429: Too Many Requests")
        return CaptionTracks(
            manual=frozenset(lang for lang, auto in self.data if not auto),
            auto=frozenset(lang for lang, auto in self.data if auto),
        )

    def download(self, url, lang, auto):
        self.downloads.append((lang, auto))
        return self.data[(lang, auto)]


def whisper_segments(duration: float = SUB_DURATION) -> list[RawSegment]:
    text = "xin chào quý vị hôm nay chúng ta tiếp tục học kinh"
    words = text.split()
    step = (duration * 0.8) / len(words)
    return [RawSegment(0.0, duration * 0.8, " " + text,
                       [RawWord(i * step, " " + w, (i + 1) * step) for i, w in enumerate(words)])]


class FakeWhisper:
    version = "1.2.1-fake"

    def __init__(self, segments: list[RawSegment] | None = None):
        self.segments = segments if segments is not None else whisper_segments()
        self.calls: list[Path] = []

    def transcribe(self, media, *, language, config):
        self.calls.append(media)
        return self.segments
