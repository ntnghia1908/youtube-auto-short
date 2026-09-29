"""CP8.15 P2/P3/P4/P6/P7: source text, validation, link/copy-text logic, posts.json schema."""

from __future__ import annotations

import pytest

from auto_short.post import source, store
from auto_short.post.logic import LinkError, chunk_lines, compose_copy_text, header_line, normalize_link
from auto_short.post.validate import parse_response, validate_paragraphs, raw_fallback, ResponseError
from auto_short.review.logic import with_added, with_cut
from cp9_helpers import seg
from post_helpers import make_post_episode

# --- P2 source text -------------------------------------------------------------------------------------------


def test_source_text_ai_clip_full_text(tmp_path):
    from auto_short.config import Config, RenderConfig, WorkspaceConfig

    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))
    ep = source.load("post8TestEp1", cfg)
    text = source.source_text(ep, "k01")
    # lines 1..8 of the synthetic timeline, joined
    expected = " ".join(f"dòng {i} lời giảng thứ {i} về tâm" for i in range(1, 9))
    assert text == expected
    assert source.source_sha256(text) == source.source_sha256(expected)


def test_source_text_manual_cut_uses_caption_lines(tmp_path):
    from auto_short.config import Config, RenderConfig, WorkspaceConfig

    ws = make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))
    ep0 = source.load("post8TestEp1", cfg)
    segments = ep0.rng.segments
    # cut k01 to lines 2..4 (a strict subset of its original unit range 1..8)
    start = source._full_clip_lines  # sanity import path exists
    a, b = seg([s for s in segments], 2)["id"], seg(segments, 4)["id"]

    review = with_cut({"schema_version": 1, "episode_id": "post8TestEp1", "titles": []}, ["k01", "k02"],
                      clip_id="k01", candidate_id="c00001",
                      start=seg(segments, 2)["start"] - 0.1, end=seg(segments, 4)["end"] + 0.1)
    (ws.dir / "review.json").write_text(__import__("json").dumps(review), encoding="utf-8")
    ep = source.load("post8TestEp1", cfg)
    text = source.source_text(ep, "k01")
    assert text == " ".join(f"dòng {i} lời giảng thứ {i} về tâm" for i in range(2, 5))


def test_source_text_added_short_uses_range(tmp_path):
    from auto_short.config import Config, RenderConfig, WorkspaceConfig

    ws = make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))
    ep0 = source.load("post8TestEp1", cfg)
    segments = ep0.rng.segments
    entry = {"clip_id": "m01", "candidate_id": "manual", "start": seg(segments, 30)["start"] - 0.1,
             "end": seg(segments, 32)["end"] + 0.1, "source": "transcript", "title": None, "ai_title": None,
             "alternatives": []}
    review = with_added({"schema_version": 1, "episode_id": "post8TestEp1", "titles": []}, ["k01", "k02", "m01"],
                        entry)
    (ws.dir / "review.json").write_text(__import__("json").dumps(review), encoding="utf-8")
    ep = source.load("post8TestEp1", cfg)
    text = source.source_text(ep, "m01")
    assert text == " ".join(f"dòng {i} lời giảng thứ {i} về tâm" for i in range(30, 33))


def test_source_load_missing_clip_raises(tmp_path):
    from auto_short.config import Config, RenderConfig, WorkspaceConfig

    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))
    ep = source.load("post8TestEp1", cfg)
    with pytest.raises(source.PostSourceError):
        source.source_text(ep, "k99")


# --- P3 validation ---------------------------------------------------------------------------------------------


def test_validate_paragraphs_accepts_punctuation_and_case_changes():
    src = "hôm nay chúng ta học về tâm và cảnh"
    ok = ["Hôm nay, chúng ta học về tâm và cảnh."]
    assert validate_paragraphs(ok, src) is None
    ok2 = ["Hôm nay chúng ta học về tâm", "và cảnh."]
    assert validate_paragraphs(ok2, src) is None


def test_validate_paragraphs_rejects_word_changes():
    src = "hôm nay chúng ta học về tâm và cảnh"
    assert validate_paragraphs(["Hôm nay chúng ta học về tâm và cảnh giới."], src)  # added a word
    assert validate_paragraphs(["Hôm nay chúng ta học tâm và cảnh."], src)  # dropped "về"
    assert validate_paragraphs(["Hôm nay chúng ta học về cảnh và tâm."], src)  # reordered
    assert validate_paragraphs(["Hôm nay chúng ta học về tim và cảnh."], src)  # changed a word


def test_validate_paragraphs_rejects_disallowed_punctuation():
    src = "hôm nay chúng ta học về tâm"
    assert validate_paragraphs(["Hôm nay chúng ta học về #tâm"], src)
    assert validate_paragraphs(["Hôm nay chúng ta học về tâm~"], src)


def test_validate_paragraphs_rejects_empty():
    assert validate_paragraphs([], "x")
    assert validate_paragraphs(["  "], "x")
    assert validate_paragraphs("not a list", "x")


def test_raw_fallback():
    assert raw_fallback("hôm nay chúng ta học") == ["Hôm nay chúng ta học."]
    assert raw_fallback("hôm nay chúng ta học?") == ["Hôm nay chúng ta học?"]
    assert raw_fallback("") == [""]


def test_parse_response():
    assert parse_response('{"paragraphs": ["a", "b"]}') == ["a", "b"]
    with pytest.raises(ResponseError):
        parse_response("not json")
    with pytest.raises(ResponseError):
        parse_response('{"paragraphs": []}')
    with pytest.raises(ResponseError):
        parse_response('{"paragraphs": [1]}')
    with pytest.raises(ResponseError):
        parse_response('{"nope": []}')


# --- P3 chunking -----------------------------------------------------------------------------------------------


def test_chunk_lines_respects_max_words():
    lines = ["a b c", "d e", "f g h i", "j"]
    chunks = chunk_lines(lines, 5)
    assert chunks == [["a b c", "d e"], ["f g h i", "j"]]
    assert all(sum(len(line.split()) for line in c) <= 5 for c in chunks)
    assert sum(len(c) for c in chunks) == len(lines)


def test_chunk_lines_oversized_line_is_its_own_chunk():
    lines = ["a b c d e f", "g"]
    assert chunk_lines(lines, 3) == [["a b c d e f"], ["g"]]


# --- P6 link ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("https://youtube.com/shorts/AbCdEfGhIjK", "https://youtube.com/shorts/AbCdEfGhIjK"),
    ("https://www.youtube.com/shorts/AbCdEfGhIjK?feature=share", "https://youtube.com/shorts/AbCdEfGhIjK"),
    ("https://youtu.be/AbCdEfGhIjK", "https://youtube.com/shorts/AbCdEfGhIjK"),
    ("https://m.youtube.com/watch?v=AbCdEfGhIjK&t=5s", "https://youtube.com/shorts/AbCdEfGhIjK"),
    ("youtu.be/AbCdEfGhIjK", "https://youtube.com/shorts/AbCdEfGhIjK"),
    ("", None),
    ("   ", None),
])
def test_normalize_link_valid(raw, expected):
    assert normalize_link(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://example.com/watch?v=AbCdEfGhIjK",
    "https://youtube.com/playlist?list=PLxxx",
    "not a url",
    "ftp://youtu.be/AbCdEfGhIjK",
    "https://youtube.com/watch?v=short",
])
def test_normalize_link_invalid(raw):
    with pytest.raises(LinkError):
        normalize_link(raw)


# --- P4 copy text -----------------------------------------------------------------------------------------------


def test_header_line():
    assert header_line({"speaker": "HT.Tịnh Không", "series": "Kinh A", "episode": "9"}) == \
        "— HT.Tịnh Không, Kinh A tập 9"
    assert header_line(None) is None
    assert header_line({}) is None
    assert header_line({"speaker": "HT.Tịnh Không"}) == "— HT.Tịnh Không"


def test_compose_copy_text_full():
    text = compose_copy_text(title="Tâm và cảnh", paragraphs=["Đoạn một.", "Đoạn hai."],
                             header_fields={"speaker": "HT.Tịnh Không", "series": "Kinh A", "episode": "9"},
                             link="https://youtube.com/shorts/AbCdEfGhIjK", hashtags=["#KinhA", "#TịnhKhông"])
    assert text == ("Tâm và cảnh\n\nĐoạn một.\n\nĐoạn hai.\n\n— HT.Tịnh Không, Kinh A tập 9\n\n"
                    "▶ Xem video: https://youtube.com/shorts/AbCdEfGhIjK\n\n#KinhA #TịnhKhông")


def test_compose_copy_text_minimal_no_header_no_link_no_hashtags():
    text = compose_copy_text(title=None, paragraphs=["Chỉ một đoạn."], header_fields=None, link=None, hashtags=[])
    assert text == "Chỉ một đoạn."


# --- P7 posts.json ----------------------------------------------------------------------------------------------


def _entry(**over):
    base = {"clip_id": "k01", "candidate_id": "c00001", "source_sha256": "a" * 64, "paragraphs": ["X."],
            "origin": store.AI, "image": "01.jpg", "link": None, "posted_at": None,
            "updated_at": "2026-09-29T10:00:00Z"}
    return {**base, **over}


def test_check_posts_accepts_valid_document():
    doc = {"schema_version": 1, "episode_id": "e1", "posts": [_entry()]}
    assert store.check_posts(doc, "e1") is doc


@pytest.mark.parametrize("doc", [
    {"schema_version": 2, "episode_id": "e1", "posts": []},
    {"schema_version": 1, "episode_id": "other", "posts": []},
    {"schema_version": 1, "episode_id": "e1", "posts": "nope"},
    {"schema_version": 1, "episode_id": "e1", "posts": [{**_entry(), "extra": 1}]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(paragraphs=[])]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(paragraphs=["", "x"])]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(origin="bogus")]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(source_sha256="short")]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(posted_at="not-a-time")]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(updated_at=None)]},
    {"schema_version": 1, "episode_id": "e1", "posts": [_entry(), _entry()]},  # duplicate clip_id
])
def test_check_posts_rejects_invalid(doc):
    with pytest.raises(store.PostsError):
        store.check_posts(doc, "e1")


def test_read_posts_missing_file_is_empty(tmp_path):
    doc = store.read_posts(tmp_path / "posts.json", "e1")
    assert doc == store.empty_posts("e1")


def test_read_posts_broken_file_raises_and_quiet_variant_is_empty(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(store.PostsError):
        store.read_posts(path, "e1")
    assert store.read_posts_quiet(path, "e1") == store.empty_posts("e1")


def test_with_compose_new_entry_then_recompose_keeps_image_link_posted():
    doc = store.empty_posts("e1")
    doc = store.with_compose(doc, ["k01", "k02"], clip_id="k01", candidate_id="c00001", source_sha256="a" * 64,
                             paragraphs=["Đoạn."], origin=store.AI, image="03.jpg", now="2026-09-29T10:00:00Z")
    entry = store.find(doc, "k01")
    assert entry["image"] == "03.jpg" and entry["link"] is None and entry["posted_at"] is None

    doc = store.with_fields(doc, ["k01", "k02"], "k01", {"link": "https://youtube.com/shorts/AbCdEfGhIjK"},
                            now="2026-09-29T10:01:00Z")
    doc = store.with_posted(doc, ["k01", "k02"], "k01", True, now="2026-09-29T10:02:00Z")
    doc = store.with_compose(doc, ["k01", "k02"], clip_id="k01", candidate_id="c00001", source_sha256="b" * 64,
                             paragraphs=["Đoạn mới."], origin=store.AI, image="99.jpg", now="2026-09-29T10:03:00Z")
    entry = store.find(doc, "k01")
    # image passed to with_compose on a recompose is ignored: the existing image/link/posted_at are kept (P7)
    assert entry["image"] == "03.jpg"
    assert entry["link"] == "https://youtube.com/shorts/AbCdEfGhIjK"
    assert entry["posted_at"] == "2026-09-29T10:02:00Z"
    assert entry["paragraphs"] == ["Đoạn mới."] and entry["source_sha256"] == "b" * 64


def test_with_fields_requires_existing_entry():
    doc = store.empty_posts("e1")
    with pytest.raises(store.PostsError):
        store.with_fields(doc, ["k01"], "k01", {"paragraphs": ["x"]}, now="2026-09-29T10:00:00Z")


def test_order_follows_clip_order():
    doc = store.empty_posts("e1")
    doc = store.with_compose(doc, ["k02", "k01"], clip_id="k01", candidate_id="c1", source_sha256="a" * 64,
                             paragraphs=["x"], origin=store.AI, image=None, now="t1")
    doc = store.with_compose(doc, ["k02", "k01"], clip_id="k02", candidate_id="c2", source_sha256="b" * 64,
                             paragraphs=["y"], origin=store.AI, image=None, now="t1")
    assert [e["clip_id"] for e in doc["posts"]] == ["k02", "k01"]
