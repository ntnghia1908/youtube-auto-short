"""Shared helpers for Chinese Learning tests: fake track lister, fake clip downloader, json3 builder,
fake Ollama chat client and preflight (no test reaches a real Ollama)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from auto_short.config import Config, IngestConfig, LearningConfig, WorkspaceConfig
from auto_short.learning.media import ClipDownload
from auto_short.selection.client import ChatResult
from auto_short.learning.tracks import Listing, Track

FIXTURES = Path(__file__).parent / "fixtures" / "learning"
REAL_JSON3 = FIXTURES / "qcqQbMj4s-w.zh-CN.head20.json3"  # first 20 s of a real manual zh-CN track

VIDEO_ID = "AbCdEfGh123"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
SHORT_DURATION = 3.0  # duration of the fake video (and of the synthetic clip)

# (tStartMs, dDurationMs, text) of the default Chinese caption, inside SHORT_DURATION + 1 s.
ZH_EVENTS = [(500, 1000, "大家好"), (1600, 1200, "我是你们的老师"), (2900, 900, "今天学习中文")]


def json3(events: list[tuple[int, int, str]]) -> bytes:
    doc = {"wireMagic": "pb3", "events": [
        {"tStartMs": s, "dDurationMs": d, "segs": [{"utf8": t}]} for s, d, t in events]}
    return json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")


def track(key: str, *, auto: bool = False, lang: str | None = None, kind: str | None = None,
          tlang: str | None = None, json3: bool = True) -> Track:
    return Track(key=key, auto=auto, lang=lang or key, kind=kind, tlang=tlang, json3=json3)


def video(duration: float = SHORT_DURATION) -> dict:
    return {"id": VIDEO_ID, "title": "中文课 1", "channel": "Teacher", "duration": duration,
            "webpage_url": f"https://www.youtube.com/watch?v={VIDEO_ID}"}


DEFAULT_TRACKS = (
    track("zh-Hans"),
    track("en"),
    track("zh-Hans", auto=True, lang="en", kind="asr", tlang="zh-Hans"),  # machine translation
)


class FakeLister:
    """Deterministic ``TrackLister``: one listing, the same bytes for every download."""

    def __init__(self, data: bytes | None = None, *, tracks=DEFAULT_TRACKS, duration: float = SHORT_DURATION,
                 fail: BaseException | None = None):
        self.data = json3(ZH_EVENTS) if data is None else data
        self._listing = Listing(video(duration), tuple(tracks))
        self.fail = fail
        self.listings: list[str] = []
        self.downloads: list[tuple[str, str, bool]] = []

    def listing(self, url: str) -> Listing:
        self.listings.append(url)
        return self._listing

    def download(self, url: str, lang: str, auto: bool) -> bytes:
        self.downloads.append((url, lang, auto))
        if self.fail is not None:
            raise self.fail
        return self.data


def make_clip(path: Path, seconds: float = SHORT_DURATION, *, audio: bool = True) -> Path:
    """Synthetic H.264 (+ AAC) clip from ffmpeg lavfi sources."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


class FakeClipDownloader:
    """``ClipDownloader`` copying a prepared clip into ``dest_dir``; can fail after a partial write."""

    def __init__(self, clip: Path, *, video_duration: float | None = SHORT_DURATION, name: str = "clip.mp4",
                 fail: BaseException | None = None):
        self.clip, self.video_duration, self.name, self.fail = clip, video_duration, name, fail
        self.calls: list[dict] = []

    def __call__(self, url, dest_dir, *, end, media_format, js_runtimes):
        self.calls.append({"url": url, "dest_dir": dest_dir, "end": end, "media_format": media_format,
                           "js_runtimes": js_runtimes})
        target = dest_dir / self.name
        if self.fail is not None:
            target.with_suffix(".part").write_bytes(b"partial")
            raise self.fail
        shutil.copy2(self.clip, target)
        return ClipDownload(target, "fake+1", self.video_duration)


def learning_config(tmp_path: Path, **learning) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), ingest=IngestConfig(),
                  learning=LearningConfig(**learning))


def tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (relative path -> bytes)."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def fake_enrichment(zh: str) -> tuple[str, str]:
    """Deterministic (pinyin, vi) for a line: Latin only, derived from the text length."""
    return f"pin yin {len(zh)}", f"nghĩa {len(zh)}"


class FakeChat:
    """Deterministic ``ChatClient``: echoes every submitted id with :func:`fake_enrichment`.

    ``script``: optional list of per-call overrides, consumed in order; each is a response string,
    a ``ChatError`` (raised) or a callable ``(items) -> str``. Afterwards the default answer is used.
    """

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls: list[dict] = []

    @staticmethod
    def default(items: list[dict]) -> str:
        return json.dumps({"lines": [{"id": it["id"], "pinyin": fake_enrichment(it["zh"])[0],
                                      "vi": fake_enrichment(it["zh"])[1]} for it in items]}, ensure_ascii=False)

    def chat(self, *, model, messages, format, options, think):
        self.calls.append({"model": model, "messages": messages, "format": format, "options": options,
                           "think": think})
        items = json.loads(messages[-1]["content"])
        step = self.script.pop(0) if self.script else None
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return ChatResult(content=step(items))
        return ChatResult(content=self.default(items) if step is None else step)


class FakePreflight:
    """Records calls; raises ``fail`` when set."""

    def __init__(self, fail: BaseException | None = None):
        self.fail = fail
        self.calls = 0

    def __call__(self, config) -> None:
        self.calls += 1
        if self.fail is not None:
            raise self.fail


@pytest.fixture(autouse=True)
def no_real_ollama(monkeypatch):
    """Default Ollama client and preflight of ``learning.run`` replaced by fakes (import into a test module
    to make it autouse there); tests may still inject their own ``client``/``preflight``."""
    from auto_short.learning import run as learning_run

    state = {"chat": FakeChat(), "preflight": FakePreflight()}
    monkeypatch.setattr(learning_run, "OllamaClient", lambda *a, **kw: state["chat"])
    monkeypatch.setattr(learning_run, "learning_preflight", state["preflight"])
    return state
