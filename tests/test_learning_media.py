"""CL1.1 stage ``media``: clip acceptance, media.json, partial-retrieval options, cleanup (AC8, AC10)."""

import json
import shutil

import pytest
from learning_helpers import URL, VIDEO_ID, FakeClipDownloader, FakeLister, learning_config, make_clip

from auto_short import hashing
from auto_short.learning import LearningError, run_learning
from auto_short.learning.media import CLIP_NAME, MEDIA_NAME, TMP_DIR, MediaError, check_clip, ytdlp_clip
from auto_short.workspace import FAILED


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    d = tmp_path_factory.mktemp("learning-clips")
    return {"av": make_clip(d / "av.mp4"), "video_only": make_clip(d / "v.mp4", audio=False)}


def _ws(cfg):
    return cfg.workspace.dir / "_learning" / VIDEO_ID


def _manifest(cfg):
    return json.loads((_ws(cfg) / "manifest.json").read_text(encoding="utf-8"))


def test_clip_accepted_and_media_json(tmp_path, clips):
    cfg = learning_config(tmp_path)
    downloader = FakeClipDownloader(clips["av"])
    run_learning(URL, cfg, lister=FakeLister(), downloader=downloader)
    ws = _ws(cfg)
    call = downloader.calls[0]
    assert call["url"] == f"https://youtu.be/{VIDEO_ID}" and call["end"] == 300.0
    assert call["media_format"] == "bv*[height<=720]+ba/b[height<=720]" and call["js_runtimes"] == ("node",)
    assert call["dest_dir"] == ws / TMP_DIR
    assert not (ws / TMP_DIR).exists()
    doc = json.loads((ws / MEDIA_NAME).read_text(encoding="utf-8"))
    assert list(doc) == ["schema_version", "episode_id", "path", "sha256", "size", "window", "duration", "width",
                         "height", "video_codec", "audio_codec", "format_id", "method"]
    assert doc["path"] == CLIP_NAME and doc["sha256"] == hashing.sha256_file(ws / CLIP_NAME)
    assert doc["size"] == (ws / CLIP_NAME).stat().st_size
    assert doc["window"] == {"start": 0.0, "end": 300.0}
    assert abs(doc["duration"] - 3.0) < 0.2 and (doc["width"], doc["height"]) == (320, 240)
    assert (doc["video_codec"], doc["audio_codec"]) == ("h264", "aac")
    assert doc["format_id"] == "fake+1" and doc["method"] == "yt-dlp download_ranges"
    entry = _manifest(cfg)["stages"]["media"]
    assert entry["status"] == "done" and entry["artifacts"] == [CLIP_NAME, MEDIA_NAME] and entry["inputs"] == []


@pytest.mark.parametrize("kind, video_duration, reason", [
    ("video_only", 3.0, "clip has no audio stream"),
    ("av", 100.0, "clip duration"),  # a 3 s clip for a 100 s video: expected >= 98 s
])
def test_unacceptable_clip_fails_and_is_removed(tmp_path, clips, kind, video_duration, reason):
    cfg = learning_config(tmp_path)
    with pytest.raises(LearningError, match=reason):
        run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clips[kind],
                                                                                    video_duration=video_duration))
    ws = _ws(cfg)
    entry = _manifest(cfg)["stages"]["media"]
    assert entry["status"] == FAILED and reason in entry["error"] and entry["artifacts"] == []
    assert sorted(p.name for p in ws.iterdir()) == ["manifest.json", "source.json", "subtitle.json3"]


def test_non_mp4_download_rejected(tmp_path, clips):
    cfg = learning_config(tmp_path)
    with pytest.raises(LearningError, match="expected .mp4"):
        run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clips["av"], name="clip.webm"))
    assert not (_ws(cfg) / TMP_DIR).exists() and not (_ws(cfg) / CLIP_NAME).exists()


def test_check_clip_bounds():
    meta = {"audio_codec": "aac", "duration": 300.0}
    assert check_clip(meta, window=300.0, video_duration=1200.0) is None
    assert check_clip({**meta, "duration": 298.0}, window=300.0, video_duration=1200.0) is None
    assert check_clip({**meta, "duration": 302.0}, window=300.0, video_duration=1200.0) is None
    assert "outside [298, 302]" in check_clip({**meta, "duration": 297.9}, window=300.0, video_duration=1200.0)
    assert "outside" in check_clip({**meta, "duration": 302.1}, window=300.0, video_duration=1200.0)
    # video shorter than the window: min(window, video) - 2 .. window + 2
    assert check_clip({**meta, "duration": 120.0}, window=300.0, video_duration=121.0) is None
    assert "outside [119, 302]" in check_clip({**meta, "duration": 118.0}, window=300.0, video_duration=121.0)
    assert check_clip({**meta, "duration": 299.0}, window=300.0, video_duration=None) is None
    assert check_clip({"audio_codec": None, "duration": 300.0}, window=300.0, video_duration=None) == \
        "clip has no audio stream"


@pytest.mark.parametrize("exc, expected", [(MediaError("network down"), "network down"),
                                           (KeyboardInterrupt(), "interrupted")])
def test_download_failure_cleans_tmp_and_artifacts(tmp_path, clips, exc, expected):
    cfg = learning_config(tmp_path)
    run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clips["av"]))
    ws = _ws(cfg)
    assert (ws / CLIP_NAME).is_file()
    raised = KeyboardInterrupt if isinstance(exc, KeyboardInterrupt) else LearningError
    with pytest.raises(raised):
        run_learning(URL, cfg, force=True, lister=FakeLister(), downloader=FakeClipDownloader(clips["av"], fail=exc))
    entry = _manifest(cfg)["stages"]["media"]
    assert entry["status"] == FAILED and expected in entry["error"]
    assert not (ws / TMP_DIR).exists()
    assert sorted(p.name for p in ws.iterdir()) == ["manifest.json", "source.json", "subtitle.json3"]


def test_subtitle_interrupt_records_and_cleans(tmp_path, clips):
    cfg = learning_config(tmp_path)
    run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clips["av"]))
    downloader = FakeClipDownloader(clips["av"])
    with pytest.raises(KeyboardInterrupt):
        run_learning(URL, cfg, force=True, lister=FakeLister(fail=KeyboardInterrupt()), downloader=downloader)
    assert downloader.calls == []
    manifest = _manifest(cfg)
    assert manifest["stages"]["subtitle"]["status"] == FAILED
    assert manifest["stages"]["subtitle"]["error"] == "interrupted"
    ws = _ws(cfg)
    assert not (ws / "subtitle.json3").exists() and not (ws / "source.json").exists()
    assert not (ws / TMP_DIR).exists()


def test_stale_tmp_dir_is_replaced(tmp_path, clips):
    cfg = learning_config(tmp_path)
    tmp = _ws(cfg) / TMP_DIR
    tmp.mkdir(parents=True)
    (tmp / "clip.mp4.part").write_bytes(b"left over from a killed run")
    run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clips["av"]))
    assert not tmp.exists() and (_ws(cfg) / CLIP_NAME).is_file()


class _FakeYDL:
    opts = None

    def __init__(self, opts):
        type(self).opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        assert download is True
        dest = self.opts["outtmpl"]["default"].replace("%(ext)s", "mp4")
        with open(dest, "wb") as fh:
            fh.write(b"x")
        return {"format_id": "398+251", "duration": 1137, "requested_downloads": [{"filepath": dest}]}

    def sanitize_info(self, info):
        return info


def test_ytdlp_clip_requests_partial_retrieval(tmp_path, monkeypatch):
    """The real downloader asks yt-dlp for [0, end] only (download_ranges), never the whole video."""
    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    dl = ytdlp_clip("https://youtu.be/x", tmp_path, end=300.0, media_format="bv*[height<=720]+ba/b[height<=720]",
                    js_runtimes=("node",))
    opts = _FakeYDL.opts
    ranges = list(opts["download_ranges"]({"id": "x", "duration": 1137}, None))
    assert ranges == [{"start_time": 0, "end_time": 300.0}]
    assert opts["force_keyframes_at_cuts"] is True and opts["noplaylist"] is True
    assert opts["format"] == "bv*[height<=720]+ba/b[height<=720]" and opts["merge_output_format"] == "mp4"
    assert opts["js_runtimes"] == {"node": {}} and opts["logtostderr"] is True
    assert dl.path == tmp_path / "clip.mp4" and dl.format_id == "398+251" and dl.video_duration == 1137.0
