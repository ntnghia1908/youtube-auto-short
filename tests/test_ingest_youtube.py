import json
import shutil
from dataclasses import replace

import pytest

from auto_short.ingest import IngestError, run_ingest
from auto_short.ingest.source import YOUTUBE, classify, youtube_video_id
from auto_short.ingest.youtube import Download, DownloadError

URL = "https://youtu.be/rbjfCfFq3Dk"
INFO = {
    "id": "rbjfCfFq3Dk",
    "title": "Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9",
    "channel": "PhapHanh",
    "upload_date": "20200101",
    "webpage_url": "https://www.youtube.com/watch?v=rbjfCfFq3Dk",
    "duration": 2,
    "formats": ["dropped"],
}


class FakeDownloader:
    """Stands in for yt-dlp: copies the synthetic clip, no network."""

    def __init__(self, video, fail=False):
        self.video, self.fail, self.calls = video, fail, []

    def __call__(self, url, dest_dir, config):
        self.calls.append((url, config.youtube_format))
        out = dest_dir / "source.mp4"
        shutil.copy2(self.video, out)
        if self.fail:
            raise DownloadError("yt-dlp download failed: HTTP Error 429: Too Many Requests")
        return Download(out, dict(INFO))


@pytest.mark.parametrize("url", [
    "https://youtu.be/rbjfCfFq3Dk",
    "https://www.youtube.com/watch?v=rbjfCfFq3Dk&t=10",
    "https://m.youtube.com/watch?v=rbjfCfFq3Dk&list=PL123",
    "https://www.youtube.com/shorts/rbjfCfFq3Dk",
])
def test_youtube_video_id(url):
    assert youtube_video_id(url) == "rbjfCfFq3Dk"
    assert classify(url).kind == YOUTUBE


@pytest.mark.parametrize("url", ["https://example.com/v.mp4", "https://www.youtube.com/playlist?list=PL1"])
def test_unsupported_url(url, cfg):
    with pytest.raises(IngestError, match="unsupported URL"):
        run_ingest(url, cfg)


def test_youtube_ingest_downloads_into_workspace(video, cfg):
    fake = FakeDownloader(video)
    result = run_ingest(URL, cfg, downloader=fake)

    assert result.ran and result.episode_id == "rbjfCfFq3Dk"
    assert fake.calls == [(URL, cfg.ingest.youtube_format)]
    ws = result.workspace
    assert sorted(p.name for p in ws.iterdir()) == ["manifest.json", "metadata.json", "source.mp4"]

    meta = json.loads((ws / "metadata.json").read_text())
    assert meta["source"]["kind"] == "youtube" and meta["source"]["uri"] == URL
    assert meta["source"]["path"] == "source.mp4"
    assert meta["title"] == INFO["title"] and meta["channel"] == "PhapHanh"
    assert meta["youtube"] == {k: INFO[k] for k in
                               ("id", "title", "channel", "upload_date", "webpage_url", "duration")}
    assert (meta["width"], meta["height"]) == (320, 240)

    ingest = json.loads((ws / "manifest.json").read_text())["stages"]["ingest"]
    assert ingest["status"] == "done"
    assert ingest["artifacts"] == ["source.mp4", "metadata.json"]


def test_youtube_rerun_skips_without_download(video, cfg):
    fake = FakeDownloader(video)
    run_ingest(URL, cfg, downloader=fake)
    again = run_ingest("https://www.youtube.com/watch?v=rbjfCfFq3Dk", cfg, downloader=fake)
    assert not again.ran and len(fake.calls) == 1


def test_youtube_config_change_reruns(video, cfg):
    fake = FakeDownloader(video)
    run_ingest(URL, cfg, downloader=fake)
    cfg2 = replace(cfg, ingest=replace(cfg.ingest, youtube_format="bv*[height<=720]+ba/b"))
    assert run_ingest(URL, cfg2, downloader=fake).ran
    assert fake.calls[-1][1] == "bv*[height<=720]+ba/b"
    # Execution-only key (js_runtimes) is not part of the config hash.
    cfg3 = replace(cfg2, ingest=replace(cfg2.ingest, js_runtimes=("deno",)))
    assert not run_ingest(URL, cfg3, downloader=fake).ran


def test_youtube_download_failure_leaves_no_partial_files(video, cfg):
    with pytest.raises(IngestError, match="429"):
        run_ingest(URL, cfg, downloader=FakeDownloader(video, fail=True))
    ws = cfg.workspace.dir / "rbjfCfFq3Dk"
    assert sorted(p.name for p in ws.iterdir()) == ["manifest.json"]
    ingest = json.loads((ws / "manifest.json").read_text())["stages"]["ingest"]
    assert ingest["status"] == "failed" and "429" in ingest["error"]


def test_workspace_of_other_source_is_refused(video, cfg):
    run_ingest(URL, cfg, downloader=FakeDownloader(video))
    with pytest.raises(IngestError, match="already belongs"):
        run_ingest(str(video), cfg, episode_id="rbjfCfFq3Dk")
