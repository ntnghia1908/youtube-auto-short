"""CL1.2 stage ``lesson`` (C8, C9): lesson.json schema/provenance, failure, skip/stale, preflight, CLI."""

import hashlib
import json
import shutil

import pytest
from learning_helpers import (REAL_JSON3, URL, VIDEO_ID, ZH_EVENTS, FakeChat, FakeClipDownloader, FakeLister,
                              FakePreflight, fake_enrichment, json3, learning_config, make_clip)
from learning_helpers import no_real_ollama  # noqa: F401  (autouse: no test reaches a real Ollama)

from auto_short import hashing, learning
from auto_short.cli import main
from auto_short.learning import LearningError, run_learning
from auto_short.learning import lesson
from auto_short.learning.preflight import LearningPreflightError
from auto_short.learning.subtitle import is_han
from auto_short.selection.client import ChatError
from auto_short.transcript.normalize import normalize
from auto_short.transcript.parsers import parse_json3
from auto_short.workspace import FAILED, STALE, Workspace


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    return make_clip(tmp_path_factory.mktemp("learning-lesson") / "clip3.mp4")


def _ws(cfg):
    return cfg.workspace.dir / "_learning" / VIDEO_ID


def _manifest(cfg):
    return json.loads((_ws(cfg) / "manifest.json").read_text(encoding="utf-8"))


def _lesson(cfg):
    return json.loads((_ws(cfg) / "lesson.json").read_text(encoding="utf-8"))


def _cfg(tmp_path, **kw):
    return learning_config(tmp_path, **{"retry_backoff": (5.0, 15.0), **kw})


def _run(cfg, clip, *, force=False, chat=None, preflight=None, lister=None, downloader=None, sleep=None):
    return run_learning(URL, cfg, force=force, lister=lister or FakeLister(),
                        downloader=downloader or FakeClipDownloader(clip), client=chat or FakeChat(),
                        preflight=preflight or FakePreflight(), sleep=sleep or (lambda s: None))


def _real_lister():
    return FakeLister(REAL_JSON3.read_bytes(), duration=414)


# --- AC4: lesson.json C8 ------------------------------------------------------------------------

def test_lesson_json_schema_and_provenance(tmp_path, clip):
    cfg = _cfg(tmp_path)
    chat = FakeChat()
    result = _run(cfg, clip, chat=chat)
    assert result.stages == [("subtitle", True), ("media", True), ("lesson", True)]
    ws = _ws(cfg)
    doc = _lesson(cfg)
    assert list(doc) == ["schema_version", "episode_id", "video", "window", "subtitle", "media", "enrichment",
                         "lines_sha256", "stats", "lines"]
    assert doc["schema_version"] == 1 and doc["episode_id"] == VIDEO_ID
    assert doc["video"] == {"id": VIDEO_ID, "title": "中文课 1", "channel": "Teacher", "duration": 3.0,
                            "url": f"https://youtu.be/{VIDEO_ID}"}
    assert doc["window"] == {"start": 0.0, "end": 300.0}
    data = (ws / "subtitle.json3").read_bytes()
    assert doc["subtitle"] == {"path": "subtitle.json3", "sha256": hashlib.sha256(data).hexdigest(),
                               "track": "zh-Hans", "auto": False}
    assert doc["media"] == {"path": "clip.mp4", "sha256": hashing.sha256_file(ws / "clip.mp4"), "start": 0.0,
                            "end": 300.0}
    assert doc["enrichment"] == {"model": "qwen3:14b", "prompt_version": "v1", "think": False,
                                 "temperature": 0.0, "seed": 42}
    assert doc["stats"] == {"lines": 3, "han_chars": sum(len(t) for _, _, t in ZH_EVENTS)}
    assert [list(ln) for ln in doc["lines"]] == [["id", "start", "end", "zh", "pinyin", "vi"]] * 3
    assert [ln["zh"] for ln in doc["lines"]] == [t for _, _, t in ZH_EVENTS]
    assert [(ln["pinyin"], ln["vi"]) for ln in doc["lines"]] == [fake_enrichment(t) for _, _, t in ZH_EVENTS]
    text = (ws / "lesson.json").read_text(encoding="utf-8")
    assert "_at" not in text and "attempt" not in text and "messages" not in text  # no time, no log content
    entry = _manifest(cfg)["stages"]["lesson"]
    assert entry["status"] == "done" and entry["artifacts"] == ["lesson.json", "lesson_log.json"]
    assert entry["inputs"] == [
        {"path": "subtitle.json3", "sha256": hashing.sha256_file(ws / "subtitle.json3")},
        {"path": "source.json", "sha256": hashing.sha256_file(ws / "source.json")},
        {"path": "clip.mp4", "sha256": hashing.sha256_file(ws / "clip.mp4")}]
    log_doc = json.loads((ws / "lesson_log.json").read_text(encoding="utf-8"))
    assert log_doc["batches"][0]["accepted_attempt"] == 1 and len(chat.calls) == 1


# --- AC2: timestamps and Han text always from the subtitle ------------------------------------

def test_ai_changes_ignored_and_lines_sha256(tmp_path, clip):
    def liar(items):
        return json.dumps({"lines": [{"id": it["id"], "zh": "假的", "start": 999.0, "end": 1000.0,
                                      "pinyin": "  jiǎ de  ", "vi": " giả "} for it in items]}, ensure_ascii=False)

    cfg = _cfg(tmp_path, batch_lines=3)
    _run(cfg, clip, chat=FakeChat(script=[liar] * 10), lister=_real_lister())
    doc = _lesson(cfg)
    segs = [s for s in normalize(parse_json3(REAL_JSON3.read_bytes())) if s["kind"] == "speech" and s["start"] < 300]
    assert len(segs) > 3  # several batches
    assert [(ln["id"], ln["start"], ln["end"], ln["zh"]) for ln in doc["lines"]] == [
        (s["id"], s["start"], s["end"], s["text"]) for s in segs]
    assert all((ln["pinyin"], ln["vi"]) == ("jiǎ de", "giả") for ln in doc["lines"])
    expected = hashlib.sha256(json.dumps([{"id": s["id"], "start": s["start"], "end": s["end"], "zh": s["text"]}
                                          for s in segs], sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    assert doc["lines_sha256"] == expected
    assert doc["stats"] == {"lines": len(segs), "han_chars": sum(1 for s in segs for c in s["text"] if is_han(c))}


def test_window_limits_lines(tmp_path, clip):
    cfg = _cfg(tmp_path, window_seconds=2.0)
    chat = FakeChat()
    _run(cfg, clip, chat=chat)
    assert [ln["zh"] for ln in _lesson(cfg)["lines"]] == ["大家好", "我是你们的老师"]  # starts 0.5, 1.6 < 2.0
    assert [it["zh"] for it in json.loads(chat.calls[0]["messages"][1]["content"])] == ["大家好", "我是你们的老师"]


# --- AC4: byte-identical across --force; media null ---------------------------------------------

def test_force_byte_identical(tmp_path, clip):
    cfg = _cfg(tmp_path, batch_lines=4)
    _run(cfg, clip, lister=_real_lister())
    first = (_ws(cfg) / "lesson.json").read_bytes()
    result = _run(cfg, clip, force=True, lister=_real_lister())
    assert result.stages == [("subtitle", True), ("media", True), ("lesson", True)]
    assert (_ws(cfg) / "lesson.json").read_bytes() == first


def test_media_null_without_clip(tmp_path, clip):
    cfg = _cfg(tmp_path)
    _run(cfg, clip)
    ws = Workspace(cfg.workspace.dir / "_learning", VIDEO_ID)
    with_clip = _lesson(cfg)
    (ws.dir / "clip.mp4").unlink()
    assert lesson.inputs(ws) == [{"path": "subtitle.json3", "sha256": hashing.sha256_file(ws.dir / "subtitle.json3")},
                                 {"path": "source.json", "sha256": hashing.sha256_file(ws.dir / "source.json")}]
    assert lesson.produce(ws, cfg, FakeChat(), lambda s: None) == ["lesson.json", "lesson_log.json"]
    doc = _lesson(cfg)
    assert doc["media"] is None
    assert {k: v for k, v in doc.items() if k != "media"} == {k: v for k, v in with_clip.items() if k != "media"}


# --- AC3: retry exhaustion -> failed, no lesson.json, log kept ---------------------------------

def test_retry_exhaustion_fails_and_keeps_log(tmp_path, clip):
    cfg = _cfg(tmp_path, batch_lines=2)
    _run(cfg, clip)  # a previous good lesson must disappear on failure
    ws = _ws(cfg)
    assert (ws / "lesson.json").is_file()
    bad = [lambda items: json.dumps({"lines": [{"id": it["id"], "pinyin": "", "vi": "x"} for it in items]})]
    chat = FakeChat(script=[None] + bad * 3)  # batch 1 ok, batch 2 fails 3 times
    waits = []
    with pytest.raises(LearningError) as info:
        _run(cfg, clip, force=True, chat=chat, sleep=waits.append)
    assert str(info.value) == "lesson failed: batch 2 (s00003..s00003): s00003: empty pinyin (after 3 attempts)"
    assert waits == [5.0, 15.0]
    entry = _manifest(cfg)["stages"]["lesson"]
    assert entry["status"] == FAILED and entry["artifacts"] == []
    assert "batch 2" in entry["error"] and "empty pinyin" in entry["error"]
    assert not (ws / "lesson.json").exists()
    log_doc = json.loads((ws / "lesson_log.json").read_text(encoding="utf-8"))
    b1, b2 = log_doc["batches"]
    assert b1["accepted_attempt"] == 1 and b2["accepted_attempt"] is None and b2["ids"] == ["s00003"]
    assert [a["attempt"] for a in b2["attempts"]] == [1, 2, 3]
    for a in b2["attempts"]:
        assert a["rejection"] == "s00003: empty pinyin" and json.loads(a["response"])
        assert a["request"]["messages"][1]["content"] == '[{"id": "s00003", "zh": "今天学习中文"}]'
    # the failure is recorded; the next run re-runs lesson and succeeds
    result = _run(cfg, clip)
    assert result.stages[-1] == ("lesson", True) and (ws / "lesson.json").is_file()


def test_chat_error_every_attempt(tmp_path, clip):
    cfg = _cfg(tmp_path, retries=0)
    with pytest.raises(LearningError, match=r"lesson failed: batch 1 \(s00001..s00003\): HTTP 500"):
        _run(cfg, clip, chat=FakeChat(script=[ChatError("HTTP 500 from x")]))
    assert not (_ws(cfg) / "lesson.json").exists()
    log_doc = json.loads((_ws(cfg) / "lesson_log.json").read_text(encoding="utf-8"))
    assert log_doc["batches"][0]["attempts"][0]["error"] == "HTTP 500 from x"


def test_interrupt_removes_outputs(tmp_path, clip):
    cfg = _cfg(tmp_path)
    _run(cfg, clip)
    with pytest.raises(KeyboardInterrupt):
        _run(cfg, clip, force=True, chat=FakeChat(script=[KeyboardInterrupt()]))
    entry = _manifest(cfg)["stages"]["lesson"]
    assert entry["status"] == FAILED and entry["error"] == "interrupted"
    assert not (_ws(cfg) / "lesson.json").exists() and not (_ws(cfg) / "lesson_log.json").exists()


# --- AC5: skip / rerun rules -------------------------------------------------------------------

def test_skip_when_up_to_date_and_preflight_not_called(tmp_path, clip):
    cfg = _cfg(tmp_path)
    _run(cfg, clip)
    chat, pre = FakeChat(), FakePreflight()
    result = _run(cfg, clip, chat=chat, preflight=pre)
    assert result.stages == [("subtitle", False), ("media", False), ("lesson", False)]
    assert chat.calls == [] and pre.calls == 0


@pytest.mark.parametrize("change", [
    {"model": "qwen3:30b"}, {"think": True}, {"temperature": 0.5}, {"seed": 7},
    {"num_ctx": 4096}, {"batch_lines": 2},
])
def test_hash_keys_rerun_lesson_only(tmp_path, clip, change):
    _run(_cfg(tmp_path), clip)
    chat, pre = FakeChat(), FakePreflight()
    result = _run(_cfg(tmp_path, **change), clip, chat=chat, preflight=pre)
    assert result.stages == [("subtitle", False), ("media", False), ("lesson", True)]
    assert pre.calls == 1 and chat.calls


def test_prompt_version_change_reruns(tmp_path, clip, monkeypatch):
    _run(_cfg(tmp_path), clip)
    monkeypatch.setitem(learning.prompt.PROMPTS, "v2", "another prompt")
    result = _run(_cfg(tmp_path, prompt_version="v2"), clip)
    assert result.stages[-1] == ("lesson", True)
    assert _lesson(_cfg(tmp_path))["enrichment"]["prompt_version"] == "v2"


def test_prompt_text_change_without_version_reruns(tmp_path, clip, monkeypatch):
    _run(_cfg(tmp_path), clip)
    monkeypatch.setitem(learning.prompt.PROMPTS, "v1", learning.prompt.PROMPTS["v1"] + " Edited.")
    assert _run(_cfg(tmp_path), clip).stages[-1] == ("lesson", True)


def test_unknown_prompt_version_fails_before_any_stage(tmp_path, clip):
    cfg = _cfg(tmp_path, prompt_version="v9")
    with pytest.raises(LearningError, match="learning.prompt_version: unknown prompt_version 'v9'"):
        _run(cfg, clip)
    assert not _ws(cfg).exists()


@pytest.mark.parametrize("change", [
    {"ollama_host": "http://elsewhere:1"}, {"timeout": 5.0}, {"retries": 0}, {"retry_backoff": (1.0,)},
])
def test_execution_only_keys_skip(tmp_path, clip, change):
    _run(_cfg(tmp_path), clip)
    chat = FakeChat()
    result = _run(_cfg(tmp_path, **change), clip, chat=chat)
    assert result.stages == [("subtitle", False), ("media", False), ("lesson", False)] and chat.calls == []


def test_subtitle_rerun_makes_lesson_stale_media_untouched(tmp_path, clip):
    cfg = _cfg(tmp_path)
    _run(cfg, clip)
    media_before = _manifest(cfg)["stages"]["media"]
    downloader = FakeClipDownloader(clip)
    new = FakeLister(json3(ZH_EVENTS[:2]))  # the caption changed upstream
    ws = _ws(cfg)
    manifest = _manifest(cfg)
    manifest["stages"]["subtitle"]["config_hash"] = "old"  # subtitle re-runs; media's own state is untouched
    (ws / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    stale_seen = []

    def preflight(config):  # lesson status right before it runs
        stale_seen.append(_manifest(cfg)["stages"]["lesson"]["status"])
    result = _run(cfg, clip, lister=new, downloader=downloader, preflight=preflight)
    assert result.stages == [("subtitle", True), ("media", False), ("lesson", True)]
    assert stale_seen == [STALE]
    assert downloader.calls == []
    assert _manifest(cfg)["stages"]["media"] == media_before
    assert [ln["zh"] for ln in _lesson(cfg)["lines"]] == ["大家好", "我是你们的老师"]


def test_clip_change_reruns_lesson(tmp_path, clip):
    cfg = _cfg(tmp_path)
    _run(cfg, clip)
    (_ws(cfg) / "clip.mp4").write_bytes(b"other bytes")  # input sha changes (media itself still 'done')
    result = _run(cfg, clip)
    assert result.stages[-1] == ("lesson", True)
    assert _lesson(cfg)["media"]["sha256"] == hashlib.sha256(b"other bytes").hexdigest()


# --- AC6: preflight ----------------------------------------------------------------------------

@pytest.mark.parametrize("message", ["cannot reach Ollama at http://127.0.0.1:11437: refused",
                                     "model 'qwen3:14b' ([learning] model) is not available at "
                                     "http://127.0.0.1:11437 (ollama pull qwen3:14b)"])
def test_preflight_failure_no_chat(tmp_path, clip, message):
    cfg = _cfg(tmp_path)
    chat = FakeChat()
    with pytest.raises(LearningError) as info:
        _run(cfg, clip, chat=chat, preflight=FakePreflight(LearningPreflightError(message)))
    assert str(info.value) == message and chat.calls == []
    stages = _manifest(cfg)["stages"]
    assert (stages["subtitle"]["status"], stages["media"]["status"]) == ("done", "done")
    assert "lesson" not in stages and not (_ws(cfg) / "lesson.json").exists()


def test_media_failure_does_not_run_lesson(tmp_path, clip):
    cfg = _cfg(tmp_path)
    chat, pre = FakeChat(), FakePreflight()
    with pytest.raises(LearningError, match="media failed"):
        _run(cfg, clip, chat=chat, preflight=pre, downloader=FakeClipDownloader(clip, video_duration=100.0))
    assert chat.calls == [] and pre.calls == 0 and "lesson" not in _manifest(cfg)["stages"]


def test_default_preflight_is_learning_preflight(tmp_path, clip, no_real_ollama):
    """Without an injected preflight/client the orchestrator uses the (here faked) module defaults."""
    cfg = _cfg(tmp_path)
    run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clip), sleep=lambda s: None)
    assert no_real_ollama["preflight"].calls == 1 and len(no_real_ollama["chat"].calls) == 1


# --- CLI -----------------------------------------------------------------------------------------

@pytest.fixture
def cli_fakes(monkeypatch, clip):
    monkeypatch.setattr(learning.run, "YtDlpChineseFetcher", lambda js_runtimes=("node",): FakeLister())
    monkeypatch.setattr(learning.run, "ytdlp_clip",
                        lambda url, dest_dir, **kw: FakeClipDownloader(clip)(url, dest_dir, **kw))


def _config_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'[workspace]\ndir = "{(tmp_path / "work").as_posix()}"\n', encoding="utf-8")
    return str(p)


def test_cli_lesson_line_and_rerun(tmp_path, capsys, cli_fakes):
    cfg = _config_file(tmp_path)
    assert main(["learn", URL, "--config", cfg]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[2] == f"{VIDEO_ID}\tlesson\tran" and out[3].startswith(f"{VIDEO_ID}\tdone\t")
    assert main(["learn", URL, "--config", cfg]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == [f"{VIDEO_ID}\t{s}\tskipped (up to date)" for s in ("subtitle", "media", "lesson")]


def test_cli_preflight_error_exit_1(tmp_path, capsys, cli_fakes, no_real_ollama):
    no_real_ollama["preflight"].fail = LearningPreflightError("cannot reach Ollama at http://127.0.0.1:11437: x")
    assert main(["learn", URL, "--config", _config_file(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "auto-short: error: cannot reach Ollama at http://127.0.0.1:11437: x" in captured.err
    assert captured.out.splitlines()[:2] == [f"{VIDEO_ID}\tsubtitle\tran", f"{VIDEO_ID}\tmedia\tran"]
    assert no_real_ollama["chat"].calls == []
