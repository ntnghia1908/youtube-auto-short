"""CL1.1 ``auto-short learn``: output, exit codes, rerun/skip (AC9), ownership (AC11)."""

import json
import shutil

import pytest
from learning_helpers import URL, VIDEO_ID, FakeClipDownloader, FakeLister, make_clip, track, tree
from learning_helpers import no_real_ollama  # noqa: F401  (autouse: no test reaches a real Ollama)

from auto_short import learning
from auto_short.cli import main
from auto_short.learning.preflight import LearningPreflightError
from auto_short.workspace import Workspace, atomic_write_json, iter_manifests


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    return make_clip(tmp_path_factory.mktemp("learning-cli") / "clip3.mp4")


@pytest.fixture
def fakes(monkeypatch, clip):
    """Replace the network (caption listing/download and clip download) with deterministic fakes."""
    state = {"lister": FakeLister(), "downloads": []}

    def fetcher(js_runtimes=("node",)):
        return state["lister"]

    def downloader(url, dest_dir, **kw):
        state["downloads"].append(kw)
        return FakeClipDownloader(clip)(url, dest_dir, **kw)

    monkeypatch.setattr(learning.run, "YtDlpChineseFetcher", fetcher)
    monkeypatch.setattr(learning.run, "ytdlp_clip", downloader)
    return state


def _config(tmp_path, **learning_keys):
    p = tmp_path / "config.toml"
    lines = [f'[workspace]\ndir = "{(tmp_path / "work").as_posix()}"\n', "[learning]\n"]
    lines += [f"{k} = {json.dumps(v)}\n" for k, v in learning_keys.items()]
    p.write_text("".join(lines), encoding="utf-8")
    return str(p)


def _learn(capsys, *args):
    code = main(["learn", *args])
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err


def _ws_dir(tmp_path):
    return tmp_path / "work" / "_learning" / VIDEO_ID


def test_learn_prints_stages_then_done(tmp_path, capsys, fakes):
    code, out, err = _learn(capsys, URL, "--config", _config(tmp_path))
    assert code == 0
    assert out == [f"{VIDEO_ID}\tsubtitle\tran", f"{VIDEO_ID}\tmedia\tran", f"{VIDEO_ID}\tlesson\tran",
                   f"{VIDEO_ID}\tdone\t{_ws_dir(tmp_path)}"]
    assert "subtitle: selected manual zh-Hans" in err
    assert sorted(p.name for p in _ws_dir(tmp_path).iterdir()) == [
        "clip.mp4", "lesson.json", "lesson_log.json", "manifest.json", "media.json", "source.json", "subtitle.json3"]


def test_rerun_and_stale_rules(tmp_path, capsys, fakes, no_real_ollama):
    cfg = _config(tmp_path)
    assert _learn(capsys, URL, "--config", cfg)[0] == 0

    code, out, err = _learn(capsys, URL, "--config", cfg)  # unchanged -> all skipped
    assert code == 0 and out[:3] == [f"{VIDEO_ID}\tsubtitle\tskipped (up to date)",
                                     f"{VIDEO_ID}\tmedia\tskipped (up to date)",
                                     f"{VIDEO_ID}\tlesson\tskipped (up to date)"]
    assert "subtitle: skip (up to date)" in err and "media: skip (up to date)" in err
    assert len(fakes["downloads"]) == 1 and len(fakes["lister"].downloads) == 1

    code, out, _ = _learn(capsys, URL, "--config", _config(tmp_path, media_format="b"))  # media only
    assert out[:2] == [f"{VIDEO_ID}\tsubtitle\tskipped (up to date)", f"{VIDEO_ID}\tmedia\tran"]
    assert fakes["downloads"][-1]["media_format"] == "b"

    code, out, _ = _learn(capsys, URL, "--config", _config(tmp_path, media_format="b", window_seconds=2.0))
    assert out[:2] == [f"{VIDEO_ID}\tsubtitle\tran", f"{VIDEO_ID}\tmedia\tran"]  # window -> both
    assert fakes["downloads"][-1]["end"] == 2.0
    cfg = _config(tmp_path, media_format="b", window_seconds=2.0)

    (_ws_dir(tmp_path) / "clip.mp4").unlink()  # missing artifact -> media only
    code, out, err = _learn(capsys, URL, "--config", cfg)
    assert out[:2] == [f"{VIDEO_ID}\tsubtitle\tskipped (up to date)", f"{VIDEO_ID}\tmedia\tran"]
    assert "artifact missing: clip.mp4" in err

    ws = Workspace(tmp_path / "work" / "_learning", VIDEO_ID)  # a later 'lesson' entry becomes stale on --force
    manifest = ws.load_manifest()
    manifest["stages"]["lesson"] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x",
                                    "started_at": None, "finished_at": None, "error": None}
    ws.save_manifest(manifest)
    # the preflight refuses, so 'lesson' does not run again and its stale status stays observable
    no_real_ollama["preflight"].fail = LearningPreflightError("cannot reach Ollama at http://fake")
    code, out, err = _learn(capsys, URL, "--config", cfg, "--force")
    assert out[:2] == [f"{VIDEO_ID}\tsubtitle\tran", f"{VIDEO_ID}\tmedia\tran"]
    stages = ws.load_manifest()["stages"]
    assert stages["lesson"]["status"] == "stale"
    assert (stages["subtitle"]["status"], stages["media"]["status"]) == ("done", "done")
    assert "subtitle: marked downstream stale: lesson" in err


def test_no_chinese_caption_exit_1_without_clip(tmp_path, capsys, fakes):
    fakes["lister"] = FakeLister(tracks=[track("zh-Hans", auto=True, lang="vi", kind="asr", tlang="zh-Hans")])
    code, out, err = _learn(capsys, URL, "--config", _config(tmp_path))
    assert code == 1 and out == []
    assert "auto-short: error: subtitle failed: no Chinese subtitle track" in err
    assert fakes["downloads"] == []
    assert sorted(p.name for p in _ws_dir(tmp_path).iterdir()) == ["manifest.json"]


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PL1234567890",
    "https://vimeo.com/12345",
    "https://www.youtube.com/@channel",
])
def test_unsupported_url_exit_1(tmp_path, capsys, fakes, url):
    code, out, err = _learn(capsys, url, "--config", _config(tmp_path))
    assert code == 1 and out == []
    assert "auto-short: error: unsupported URL (expected a single YouTube video URL)" in err
    assert not (tmp_path / "work").exists()


def test_video_url_forms_share_one_workspace(tmp_path, capsys, fakes):
    cfg = _config(tmp_path)
    assert _learn(capsys, f"https://youtu.be/{VIDEO_ID}?t=30", "--config", cfg)[0] == 0
    code, out, _ = _learn(capsys, f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLx", "--config", cfg)
    assert code == 0 and out[0].endswith("skipped (up to date)")
    assert fakes["lister"].listings == [f"https://youtu.be/{VIDEO_ID}"]


def test_ownership_auto_short_workspace_untouched(tmp_path, capsys, fakes):
    """Only work/_learning/<id>/ is created; Auto Short work/<id>/ and output/<id>/ stay byte-identical."""
    work, output = tmp_path / "work", tmp_path / "output"
    auto_ws = Workspace(work, VIDEO_ID)
    atomic_write_json(auto_ws.manifest_path, {"schema_version": 1, "episode_id": VIDEO_ID, "source": {
        "kind": "youtube", "uri": URL, "path": "source.mp4", "sha256": None, "size": None, "mtime_ns": None},
        "stages": {"ingest": {"status": "done", "artifacts": ["source.mp4"]}}})
    (auto_ws.dir / "source.mp4").write_bytes(b"auto short source")
    (auto_ws.dir / "transcript.json").write_text("{}", encoding="utf-8")
    (output / VIDEO_ID / "shorts").mkdir(parents=True)
    (output / VIDEO_ID / "shorts" / "k01.mp4").write_bytes(b"short")
    (work / "_playlists").mkdir()
    (work / "_playlists" / "p.json").write_text("{}", encoding="utf-8")
    before_work, before_output = tree(work), tree(output)

    assert _learn(capsys, URL, "--config", _config(tmp_path))[0] == 0
    assert _learn(capsys, URL, "--config", _config(tmp_path), "--force")[0] == 0

    after_work = tree(work)
    learning_files = {k for k in after_work if k.startswith("_learning/")}
    assert {k.split("/")[1] for k in learning_files} == {VIDEO_ID}
    assert {k: v for k, v in after_work.items() if k not in learning_files} == before_work
    assert tree(output) == before_output
    assert [ws.episode_id for ws, _ in iter_manifests(work)] == [VIDEO_ID]  # the Auto Short episode only
    assert [ws.dir for ws, _ in iter_manifests(work)] == [work / VIDEO_ID]
