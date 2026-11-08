"""PCX1 AC1–3: media, untrusted data, parse/logging, borrowing and content-preserving failures."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import ConfigError, from_dict
from auto_short.post import codex_text as ct, source, store
from auto_short.store.client import StoreUnavailable
from post_helpers import EID
from test_post_codex_helpers import Codex, Media, Whisper, seed


@pytest.mark.parametrize("width,height,kt,cropped", [(1080, 1920, False, True), (1920, 1080, False, False),
                                                     (1080, 1920, True, False)])
def test_media_prompt_all_images_schema_and_log(tmp_path, width, height, kt, cropped):
    cfg, path = seed(tmp_path)
    before = store.read_posts(path, EID)
    media, whisper, runner = Media(width, height), Whisper(), Codex()
    st = ct.rewrite_posts(EID, cfg, ["k01"], media_runner=media, whisper=whisper, runner=runner)
    assert st.rewritten == ["k01"] and not st.errors
    after = store.check_posts(store.read_posts(path, EID), EID)
    assert after["schema_version"] == 1 and after["posts"][1] == before["posts"][1]
    p = after["posts"][0]
    assert p["origin"] == "codex" and p["paragraphs"] == ["Cứ Nha, huống chi!", "Giữ đủ lời giảng."]
    assert p["source_sha256"] == source.source_sha256(source.source_text(source.load(EID, cfg), "k01"))
    assert whisper.calls[0][1] == {"language": cfg.transcript.language, "config": cfg.transcript.whisper}
    cmd, kw = runner.calls[0]
    assert cmd[cmd.index("-s") + 1] == "workspace-write"
    assert cmd.count("-i") == 2 and cmd[-1] == "-"
    assert all(Path(cmd[i+1]).name == f"frames-{n:03d}.jpg" for n, i in enumerate(
        [i for i, arg in enumerate(cmd) if arg == "-i"], 1))
    prompt = kw["input"]
    payload = json.loads(prompt.split("BEGIN_DATA_JSON\n")[1].split("\nEND_DATA_JSON")[0])
    assert payload["whisper"] == whisper.text
    assert "không tin cậy" in prompt and "không tóm tắt" in prompt and "Hán Việt" in prompt
    assert prompt.count("\nEND_DATA_JSON\n") == 1
    # Test khai thị's full-frame policy separately, without changing fixture episode identities.
    frames = tmp_path / "media"
    frames.mkdir()
    ct.prepare_media(tmp_path / "short.mp4", frames, khai_thi=kt, runner=media)
    vf = media.calls[-1][media.calls[-1].index("-vf") + 1]
    assert ("crop=1080:1140:0:170" in vf) == cropped
    assert "fps=1/2" in vf and "tile=3x2" in vf and "drawtext" in vf
    entry = json.loads(path.with_name("post_log.json").read_text())["entries"][-1]
    assert entry["han"] == "鋸牙" and entry["tokens"] == 1234 and entry["seconds"] >= 0
    assert entry["raw_output"] == runner.output and entry["error"] is None


@pytest.mark.parametrize("case", ["missing", "empty", "capacity", "whisper", "manual", "posted", "source"])
def test_failure_keeps_old_text_and_logs_reason(tmp_path, case):
    cfg, path = seed(tmp_path)
    before = path.read_bytes()
    def change():
        if case in ("manual", "posted"):
            doc = store.read_posts(path, EID)
            doc["posts"][0].update({"origin": "manual", "paragraphs": ["Sửa tay."]} if case == "manual"
                                   else {"posted_at": "2026-11-08T01:00:00Z"})
            store.write(path, doc)
        elif case == "source":
            clips = path.with_name("clips.json")
            doc = json.loads(clips.read_text())
            doc["clips"][0]["head_cut"] = {"words": "dòng 1", "original_start": 0}
            clips.write_text(json.dumps(doc))
    outputs = {"missing": "Bài không có khối", "empty": "=== HAN ===\n無\n=== VI ===\n  "}
    runner = Codex(**({"output": outputs[case]} if case in outputs else {}),
                   code=1 if case == "capacity" else 0,
                   log="at capacity" if case == "capacity" else "tokens used\n22", on_call=change)
    st = ct.rewrite_posts(EID, cfg, ["k01"], runner=runner, media_runner=Media(),
                          whisper=Whisper("" if case == "whisper" else "Lời giảng"))
    assert "k01" in st.errors and not st.rewritten
    if case not in ("manual", "posted"):
        assert path.read_bytes() == before
    else:
        p = store.read_posts(path, EID)["posts"][0]
        assert p["origin"] == "manual" if case == "manual" else p["posted_at"] is not None
    entry = json.loads(path.with_name("post_log.json").read_text())["entries"][-1]
    assert entry["error"] == st.errors["k01"] and entry["seconds"] >= 0
    assert ct.errors(cfg, EID)["k01"] == st.errors["k01"]


@pytest.mark.parametrize("unavailable", [False, True])
def test_released_short_uses_borrow_short_and_store_failure_is_explicit(tmp_path, unavailable):
    cfg, path = seed(tmp_path)
    cfg = replace(cfg, store=replace(cfg.store, enabled=True))
    out = cfg.render.output_dir / EID
    local = out / "shorts/k01.mp4"
    local.unlink()
    (out / "store.json").write_text(json.dumps({"released": {"k01": {
        "sha256": "a" * 64, "size": 8, "mtime_ns": 0}}}))
    before = path.read_bytes()
    calls = []
    class Client:
        def fetch(self, eid, kind, dest, sha, **kwargs):
            calls.append((eid, kind, dest, sha, kwargs))
            if unavailable:
                raise StoreUnavailable("offline")
            dest.write_bytes(b"borrowed")
    st = ct.rewrite_posts(EID, cfg, ["k01"], runner=Codex(), media_runner=Media(), whisper=Whisper(), store_client=Client())
    assert len(calls) == 1 and calls[0][0:2] == (EID, "short") and calls[0][4] == {"clip": "k01.mp4"}
    assert not calls[0][2].exists() and not local.exists()
    if unavailable:
        assert "3090 không trả lời" in st.errors["k01"] and path.read_bytes() == before
    else:
        assert st.rewritten == ["k01"]


@pytest.mark.parametrize("include_posted", [False, True])
def test_eligibility_and_config_preserve_other_origins(tmp_path, include_posted):
    cfg, path = seed(tmp_path)
    doc = store.read_posts(path, EID)
    doc["posts"][0]["posted_at"] = "2026-11-08T00:00:00Z"
    assert ct.eligible(doc, ["k01", "k02"], include_posted=include_posted) == (["k01", "k02"] if include_posted else ["k02"])
    for origin in (store.DOC, store.MANUAL, store.CODEX):
        doc["posts"][1]["origin"] = origin
        assert "k02" not in ct.eligible(doc, ["k01", "k02"], include_posted=include_posted)
    with pytest.raises(ct.CodexTextError):
        ct.eligible(doc, ["k01"], ["k99"])
    assert from_dict({}).post.codex_auto is True
    assert from_dict({"post": {"codex_auto": False}}).post.codex_auto is False
    with pytest.raises(ConfigError):
        from_dict({"post": {"codex_auto": "false"}})
