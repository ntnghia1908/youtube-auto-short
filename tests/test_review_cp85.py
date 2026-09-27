"""CP8.5 review functions (no ffmpeg): download names (X1), deleted Shorts in review.json (X2), episode delete
(X3), publish.json (X4)."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.review import (EpisodeNotFound, ReviewError, content_disposition, delete_episode, download_name,
                               episode_label, list_titles, load_published, reject_clip, restore_clip, set_published,
                               set_title, zip_name)
from auto_short.review.logic import check_review, empty_review, resolve_titles, with_rejected, without_rejected
from auto_short.review.names import MAX_TITLE_BYTES, ascii_fallback, clean_part, truncate_utf8
from auto_short.review.publish import check_publish, publish_status
from render_helpers import EID, TITLES, make_render_episode, write_docs

SHA_A, SHA_B = "a" * 64, "b" * 64


@pytest.fixture
def rcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output"))


@pytest.fixture
def ws(rcfg, tmp_path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"not a video")
    ws = make_render_episode(rcfg.workspace.dir, src)
    write_docs(ws)
    return ws


def _review(ws):
    return json.loads((ws.dir / "review.json").read_text(encoding="utf-8"))


# --- X1 download names ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("episode, n, total, title, name", [
    ("29", 1, 20, "Đánh mắng trẻ là có tội không?", "Tập29_S01_Đánh mắng trẻ là có tội không.mp4"),
    ("29", 3, 20, 'Chữ "hiếu" là gì', "Tập29_S03_Chữ hiếu là gì.mp4"),
    ("29", 12, 20, "a/b\\c:d*e?f\"g<h>i|j", "Tập29_S12_abcdefghij.mp4"),
    ("29", 5, 99, "  nhiều   khoảng\ttrắng\x00\x1f ", "Tập29_S05_nhiều khoảng trắng.mp4"),
    ("29", 7, 100, "Ba chữ số", "Tập29_S007_Ba chữ số.mp4"),
    ("29", 123, 150, "x", "Tập29_S123_x.mp4"),
    ("29", 4, 20, "???", "Tập29_S04.mp4"),
    ("29", 4, 20, None, "Tập29_S04.mp4"),
])
def test_download_name(episode, n, total, title, name):
    assert download_name(episode, n, total, title) == name


def test_download_name_nfc_and_truncation():
    decomposed = "Tâm thiện".encode("utf-8").decode("utf-8")
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Tâm thiện")
    assert download_name("29", 1, 2, nfd) == "Tập29_S01_Tâm thiện.mp4" == download_name("29", 1, 2, decomposed)
    long = " ".join(["Thập Thiện Nghiệp Đạo"] * 20)
    t = truncate_utf8(clean_part(long))
    assert len(t.encode("utf-8")) <= MAX_TITLE_BYTES and long.startswith(t) and long[len(t)] == " "
    assert not t.endswith(" ")
    one_word = "ạ" * 100  # 3 bytes each, no space: cut at a character boundary
    assert truncate_utf8(one_word) == "ạ" * 50
    assert truncate_utf8("ngắn") == "ngắn"


def test_episode_label_and_zip():
    assert episode_label("29", "tHtxw6ykUmM") == "29"
    assert episode_label(None, "tHtxw6ykUmM") == "tHtxw6ykUmM"
    assert episode_label(" 3/4 ", "x") == "34"
    assert zip_name("29") == "Tập29_Shorts.zip"


def test_content_disposition_rfc5987():
    name = "Tập29_S01_Đánh mắng trẻ là có tội không.mp4"
    assert ascii_fallback(name) == "Tap29_S01_Danh mang tre la co toi khong.mp4"
    assert content_disposition(name) == (
        'attachment; filename="Tap29_S01_Danh mang tre la co toi khong.mp4"; filename*=UTF-8\'\''
        "T%E1%BA%ADp29_S01_%C4%90%C3%A1nh%20m%E1%BA%AFng%20tr%E1%BA%BB%20l%C3%A0%20c%C3%B3%20t%E1%BB%99i"
        "%20kh%C3%B4ng.mp4")
    assert ascii_fallback("心") == "download"


# --- X2 rejected in review.json ------------------------------------------------------------------------------

def test_check_review_rejected_schema():
    base = empty_review(EID)
    ok = {**base, "rejected": [{"clip_id": "k01", "candidate_id": "c00001"}]}
    assert check_review(ok, EID) is ok
    for doc, msg in [({**base, "rejected": []}, "non-empty array"),
                     ({**base, "rejected": [{"clip_id": "k01"}]}, r"rejected\[0\]"),
                     ({**base, "rejected": [{"clip_id": "k01", "candidate_id": ""}]}, "non-empty string"),
                     ({**base, "rejected": [{"clip_id": "k01", "candidate_id": "c1"}] * 2}, "duplicate rejected"),
                     ({"schema_version": 1, "episode_id": EID, "rejected": [], "titles": []}, "must be an object")]:
        with pytest.raises(ReviewError, match=msg):
            check_review(doc, EID)


def test_with_without_rejected_and_resolve():
    order = ["k01", "k02", "k03"]
    doc = with_rejected(empty_review(EID), order, clip_id="k02", candidate_id="c2")
    doc = with_rejected(doc, order, clip_id="k01", candidate_id="c1")
    assert list(doc) == ["schema_version", "episode_id", "titles", "rejected"]
    assert [e["clip_id"] for e in doc["rejected"]] == ["k01", "k02"]
    titles = [{"clip_id": "k01", "candidate_id": "c1", "title": "A", "status": "titled"},
              {"clip_id": "k02", "candidate_id": "cX", "title": "B", "status": "titled"},
              {"clip_id": "k03", "candidate_id": "c3", "title": None, "status": "untitled"}]
    resolved, warnings = resolve_titles(titles, doc)
    assert [(r.clip_id, r.title, r.rejected) for r in resolved] == [("k01", "A", True), ("k02", "B", False),
                                                                     ("k03", None, False)]
    assert warnings == ["deleted Short k02 ignored: deleted as candidate c2, the clip is now candidate cX "
                        "(selection re-run)"]
    doc, removed = without_rejected(doc, order, "k01")
    assert removed and doc["rejected"] == [{"clip_id": "k02", "candidate_id": "c2"}]
    doc, removed = without_rejected(doc, order, "k02")
    assert removed and list(doc) == ["schema_version", "episode_id", "titles"]  # key dropped when empty
    assert without_rejected(doc, order, "k02")[1] is False


def test_reject_restore_keep_override(ws, rcfg):
    set_title(EID, rcfg, "k02", "Một câu khác")
    before = (ws.dir / "review.json").read_bytes()
    assert reject_clip(EID, rcfg, "k02") is True
    assert _review(ws)["rejected"] == [{"clip_id": "k02", "candidate_id": "c00002"}]
    assert _review(ws)["titles"][0]["title"] == "Một câu khác"  # override kept
    after_reject = (ws.dir / "review.json").read_bytes()
    assert reject_clip(EID, rcfg, "k02") is False and (ws.dir / "review.json").read_bytes() == after_reject
    clips = {c["clip_id"]: c for c in list_titles(EID, rcfg)["clips"]}
    assert clips["k02"]["rejected"] is True and clips["k01"]["rejected"] is False
    assert clips["k02"]["title"] == "Một câu khác"
    # title edits keep the deletion
    set_title(EID, rcfg, "k02", "Câu thứ ba")
    assert _review(ws)["rejected"] == [{"clip_id": "k02", "candidate_id": "c00002"}]
    set_title(EID, rcfg, "k02", "Một câu khác")
    assert restore_clip(EID, rcfg, "k02") is True
    assert (ws.dir / "review.json").read_bytes() == before  # back to the CP8.2 shape, byte-identical
    assert restore_clip(EID, rcfg, "k02") is False
    with pytest.raises(ReviewError, match="no clip 'k99'"):
        reject_clip(EID, rcfg, "k99")
    with pytest.raises(ReviewError, match="no clip 'k99'"):
        restore_clip(EID, rcfg, "k99")


def test_reject_without_review_file(ws, rcfg):
    assert not (ws.dir / "review.json").exists()
    assert reject_clip(EID, rcfg, "k01")
    assert _review(ws) == {"schema_version": 1, "episode_id": EID, "titles": [],
                           "rejected": [{"clip_id": "k01", "candidate_id": "c00001"}]}


# --- X4 publish.json -----------------------------------------------------------------------------------------

def _render_manifest(rcfg, shas=(SHA_A, SHA_B), statuses=("rendered", "rendered")):
    out = Path(rcfg.render.output_dir) / EID
    out.mkdir(parents=True, exist_ok=True)
    shorts = [{"clip_id": cid, "candidate_id": cand, "status": st,
               "skip_reason": None if st == "rendered" else "rejected",
               "sha256": sha if st == "rendered" else None, "title": TITLES[cid]}
              for cid, cand, sha, st in zip(("k01", "k02"), ("c00001", "c00002"), shas, statuses)]
    (out / "render_manifest.json").write_text(json.dumps({"episode_id": EID, "shorts": shorts}), encoding="utf-8")


def test_publish_tick_untick_stale(ws, rcfg):
    _render_manifest(rcfg)
    assert load_published(EID, rcfg) == []
    r = set_published(EID, rcfg, "k02", True, at="2026-09-27T10:00:00Z")
    assert r == {"clip_id": "k02", "published": True, "stale": False, "at": "2026-09-27T10:00:00Z"}
    set_published(EID, rcfg, "k01", True, at="2026-09-27T10:01:00Z")
    doc = json.loads((ws.dir / "publish.json").read_text(encoding="utf-8"))
    assert doc == {"schema_version": 1, "episode_id": EID, "published": [
        {"clip_id": "k01", "candidate_id": "c00001", "sha256": SHA_A, "at": "2026-09-27T10:01:00Z"},
        {"clip_id": "k02", "candidate_id": "c00002", "sha256": SHA_B, "at": "2026-09-27T10:00:00Z"}]}
    # re-render with a new title: the tick stays, "đã đăng bản cũ"
    _render_manifest(rcfg, shas=(SHA_A, "c" * 64))
    rm = json.loads((Path(rcfg.render.output_dir) / EID / "render_manifest.json").read_text())
    st = publish_status(doc, rm["shorts"])
    assert st["k02"] == {"published": True, "stale": True, "at": "2026-09-27T10:00:00Z"}
    assert st["k01"]["stale"] is False
    # ticking again marks the new version
    assert set_published(EID, rcfg, "k02", True, at="2026-09-27T11:00:00Z")["stale"] is False
    # deleted Short: keeps its tick, not stale; cannot be ticked when not ticked
    _render_manifest(rcfg, statuses=("rendered", "skipped"))
    rm = json.loads((Path(rcfg.render.output_dir) / EID / "render_manifest.json").read_text())
    assert publish_status(json.loads((ws.dir / "publish.json").read_text()), rm["shorts"])["k02"]["published"]
    assert set_published(EID, rcfg, "k02", False)["published"] is False
    with pytest.raises(ReviewError, match="no rendered file"):
        set_published(EID, rcfg, "k02", True)
    with pytest.raises(ReviewError, match="no rendered file"):
        set_published(EID, rcfg, "k99", True)
    before = (ws.dir / "publish.json").read_bytes()
    assert set_published(EID, rcfg, "k02", False)["published"] is False  # nothing to remove: untouched
    assert (ws.dir / "publish.json").read_bytes() == before
    # a tick for another candidate (selection re-run) does not count
    doc = json.loads(before)
    doc["published"][0]["candidate_id"] = "c09999"
    assert publish_status(doc, rm["shorts"])["k01"]["published"] is False
    # never a render input: the render stage inputs do not mention it (checked in test_web_cp85 end to end)


@pytest.mark.parametrize("doc, msg", [
    ([], "must be an object"),
    ({"schema_version": 2, "episode_id": EID, "published": []}, "schema_version"),
    ({"schema_version": 1, "episode_id": "x", "published": []}, "episode_id"),
    ({"schema_version": 1, "episode_id": EID, "published": [{"clip_id": "k01"}]}, r"published\[0\]"),
    ({"schema_version": 1, "episode_id": EID, "published": [
        {"clip_id": "k01", "candidate_id": "c", "sha256": "xyz", "at": "2026-09-27T10:00:00Z"}]}, "64 hex"),
    ({"schema_version": 1, "episode_id": EID, "published": [
        {"clip_id": "k01", "candidate_id": "c", "sha256": SHA_A, "at": "2026-09-27T10:00:00Z"}] * 2}, "duplicate"),
])
def test_check_publish_rejects(doc, msg):
    with pytest.raises(ReviewError, match=msg):
        check_publish(doc, EID)


# --- X3 delete episode ---------------------------------------------------------------------------------------

def test_delete_episode_keeps_local_source(rcfg, tmp_path):
    src = tmp_path / "input" / "lecture.mp4"
    src.parent.mkdir()
    src.write_bytes(b"source bytes")
    ws = make_render_episode(rcfg.workspace.dir, src)
    (ws.dir / "link.mp4").symlink_to(src)  # a symlink inside the workspace is removed, not followed
    out = Path(rcfg.render.output_dir) / EID
    (out / "shorts").mkdir(parents=True)
    (out / "shorts" / "k01.mp4").write_bytes(b"x")
    other = Path(rcfg.workspace.dir) / "other"
    other.mkdir()
    removed = delete_episode(EID, rcfg)
    assert removed == [ws.dir, out] or set(removed) == {ws.dir, out}
    assert not ws.dir.exists() and not out.exists()
    assert src.read_bytes() == b"source bytes" and other.is_dir()
    with pytest.raises(EpisodeNotFound):
        delete_episode(EID, rcfg)


@pytest.mark.parametrize("eid", ["..", ".", "../work", "a/b", "", "x" * 200, ".hidden"])
def test_delete_episode_invalid_id(rcfg, eid):
    Path(rcfg.workspace.dir).mkdir(parents=True)
    with pytest.raises(EpisodeNotFound):
        delete_episode(eid, rcfg)
    assert Path(rcfg.workspace.dir).is_dir()


def test_delete_episode_refuses_symlinked_dir(rcfg, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")
    Path(rcfg.workspace.dir).mkdir(parents=True)
    os.symlink(victim, Path(rcfg.workspace.dir) / "evil")
    with pytest.raises(ReviewError, match="refusing to delete"):
        delete_episode("evil", rcfg)
    assert (victim / "keep.txt").read_text() == "keep"


def test_delete_episode_output_only_and_same_root(tmp_path):
    same = Config(workspace=WorkspaceConfig(dir=tmp_path / "d"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "d"))
    (tmp_path / "d" / "ep1").mkdir(parents=True)
    assert delete_episode("ep1", same) == [tmp_path / "d" / "ep1"]
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "w"),
                 render=replace(RenderConfig(), output_dir=tmp_path / "o"))
    (tmp_path / "o" / "ep2").mkdir(parents=True)
    assert delete_episode("ep2", cfg) == [tmp_path / "o" / "ep2"]
