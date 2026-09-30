"""CP8.16 R4 (``clips: "auto"``: pure selection + compose_posts) and R5 (speaker in the post line)."""

from __future__ import annotations

import json

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig
from auto_short.post import source, stage, store
from auto_short.post.logic import header_line
from post_helpers import EID, make_post_episode
from test_post_stage import FakeClient, sleep_noop


def _config(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images", retries=1, retry_backoff=(0.0,)))


def _seed(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    stage.compose_posts(EID, cfg, ["k01", "k02"], client=FakeClient(), sleep=sleep_noop)
    path = tmp_path / "work" / EID / store.POSTS_NAME
    return cfg, path, store.read_posts(path, EID)


def test_auto_clips_selects_missing_and_stale_unticked_non_manual(tmp_path):  # AC1
    cfg, path, doc = _seed(tmp_path)
    ep = source.load(EID, cfg)
    order = ["k01", "k02"]
    assert stage.auto_clips(ep, doc, order) == []  # valid posts: nothing to do
    assert stage.auto_clips(ep, store.empty_posts(EID), order) == ["k01", "k02"]  # (i) no post yet

    def entry(cid):
        return store.find(doc, cid)

    entry("k01")["source_sha256"] = "0" * 64  # stale
    assert stage.auto_clips(ep, doc, order) == ["k01"]  # (ii) stale, not ticked, not manual
    entry("k01")["posted_at"] = "2026-09-30T10:00:00Z"
    assert stage.auto_clips(ep, doc, order) == []  # ticked "Đã đăng bài": kept
    entry("k01")["posted_at"] = None
    entry("k01")["origin"] = store.MANUAL
    assert stage.auto_clips(ep, doc, order) == []  # hand-edited text is kept
    entry("k01")["origin"] = store.RAW
    assert stage.auto_clips(ep, doc, order) == ["k01"]  # a raw post is only recomposed when stale
    entry("k01")["source_sha256"] = entry("k02")["source_sha256"]
    assert stage.auto_clips(ep, doc, order) == ["k01"]  # k01 now carries k02's hash: stale
    doc["posts"] = [p for p in doc["posts"] if p["clip_id"] != "k02"]
    assert stage.auto_clips(ep, doc, order) == ["k01", "k02"]
    assert stage.auto_clips(ep, doc, ["k02"]) == ["k02"]  # only Shorts of ``order`` (rejected ones are not in it)


def test_compose_posts_auto_composes_only_the_auto_set(tmp_path):  # AC1
    cfg, path, doc = _seed(tmp_path)
    before = {p["clip_id"]: dict(p) for p in doc["posts"]}
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["posts"][0]["source_sha256"] = "0" * 64  # k01 stale
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    client = FakeClient()
    summary = stage.compose_posts(EID, cfg, "auto", client=client, sleep=sleep_noop)
    assert summary.clip_ids == ["k01"] and (summary.ai, summary.raw) == (1, 0) and len(client.calls) == 1
    after = {p["clip_id"]: p for p in store.read_posts(path, EID)["posts"]}
    assert after["k01"]["source_sha256"] == before["k01"]["source_sha256"]  # recomposed → valid again
    assert after["k02"]["updated_at"] == before["k02"]["updated_at"] and after["k02"]["paragraphs"] == before["k02"]["paragraphs"]
    # nothing left: an empty pass calls no AI
    client2 = FakeClient()
    assert stage.compose_posts(EID, cfg, "auto", client=client2, sleep=sleep_noop).clip_ids == []
    assert client2.calls == []


def test_compose_posts_auto_ignores_rejected_short_and_broken_file(tmp_path):  # AC1
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    manifest = tmp_path / "output" / EID / "render_manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["shorts"][1]["status"] = "rejected"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    assert stage.compose_posts(EID, cfg, "auto", client=FakeClient(), sleep=sleep_noop).clip_ids == ["k01"]
    # a broken posts.json reads as empty (like "all") and is not overwritten by the read
    (tmp_path / "work" / EID / store.POSTS_NAME).write_text("{not json", encoding="utf-8")
    picked = stage.auto_clips(source.load(EID, cfg), store.empty_posts(EID), ["k01", "k02"])
    assert picked == ["k01", "k02"]


def test_all_and_list_keep_their_meaning(tmp_path):  # AC1
    cfg, path, doc = _seed(tmp_path)
    assert stage.compose_posts(EID, cfg, "all", client=FakeClient(), sleep=sleep_noop).clip_ids == []
    assert stage.compose_posts(EID, cfg, ["k02"], client=FakeClient(), sleep=sleep_noop).clip_ids == ["k02"]


def test_header_line_speaker_space_r5():  # AC4
    f = {"speaker": "HT.Tịnh Không", "series": "Kinh A", "episode": "9"}
    assert header_line(f) == "— HT. Tịnh Không, Kinh A tập 9"
    assert header_line({**f, "speaker": "HT. Tịnh Không"}) == "— HT. Tịnh Không, Kinh A tập 9"
    assert f["speaker"] == "HT.Tịnh Không"  # input untouched (titles.json / header video not changed)
    assert header_line({"speaker": "A.B.C"}) == "— A. B. C"
