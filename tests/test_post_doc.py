"""CP8.19 ``post/doc.py`` + the ``doc`` branch of ``compose_posts``: link template (D1), parse / fetch (D2, P13), cache +
match (D3), alignment (D4), sentence expansion (D5), compose (D6). No network: a fake opener, tmp_path only."""

from __future__ import annotations

import gzip
import json

import pytest

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig
from auto_short.post import doc, fetch, source, stage, store
from auto_short.selection.client import ChatResult
from doc_helpers import (BASE_URL, GZ_PARAGRAPHS, GZ_PATH, HEAD_PARAGRAPHS, FakeOpener, full_routes, page_html,
                         private_resolver, public_resolver, write_playlist)
from post_helpers import EID, make_post_episode

FULL = HEAD_PARAGRAPHS + GZ_PARAGRAPHS


# --- D1 link -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://ph.tinhtong.vn/Home/KinhVoLuongTho10?d=KinhVoLuongTho10_001.html",
    "  https://ph.tinhtong.vn/Home/CamUngThien?d=CamUngThien_001.html ",
    "https://ph.tinhtong.vn/Home/KinhThapThienNghiep?d=KinhThapThienNghiep_07.html"])
def test_normalize_url_accepts(url):
    assert doc.normalize_url(url) == url.strip()


@pytest.mark.parametrize("url", [
    None, 5, "", "http://ph.tinhtong.vn/Home/A?d=A_001.html", "https://evil.example/Home/A?d=A_001.html",
    "https://ph.tinhtong.vn.evil.com/Home/A?d=A_001.html", "https://ph.tinhtong.vn/Home/A?d=B_001.html",
    "https://ph.tinhtong.vn/Home/A?d=A_x.html", "https://ph.tinhtong.vn/Home/A?d=A_001.html&x=1",
    "https://ph.tinhtong.vn/Home/A/b?d=A_001.html", "https://user@ph.tinhtong.vn/Home/A?d=A_001.html"])
def test_normalize_url_rejects(url):
    with pytest.raises(doc.DocError):
        doc.normalize_url(url)


@pytest.mark.parametrize("url,n,expected", [
    ("https://ph.tinhtong.vn/Home/K?d=K_001.html", "7", "https://ph.tinhtong.vn/Home/K?d=K_007.html"),
    ("https://ph.tinhtong.vn/Home/K?d=K_1.html", "7", "https://ph.tinhtong.vn/Home/K?d=K_7.html"),
    ("https://ph.tinhtong.vn/Home/K?d=K_07.html", "12", "https://ph.tinhtong.vn/Home/K?d=K_12.html"),
    ("https://ph.tinhtong.vn/Home/K?d=K_001.html", "128", "https://ph.tinhtong.vn/Home/K?d=K_128.html"),
    ("https://ph.tinhtong.vn/Home/K?d=K_01.html", "1234", "https://ph.tinhtong.vn/Home/K?d=K_1234.html")])
def test_url_for_episode_keeps_padding(url, n, expected):
    assert doc.url_for_episode(url, n) == expected


def test_url_for_episode_not_a_number():
    assert doc.url_for_episode(BASE_URL, "abc") is None and doc.url_for_episode(BASE_URL, None) is None


def test_lookup_smallest_playlist_id_with_doc_url_and_kt(tmp_path):
    work = tmp_path / "work"
    write_playlist(work, "PLb", [("vidAAAAAAA1", "3")], doc_url="https://ph.tinhtong.vn/Home/B?d=B_01.html")
    write_playlist(work, "PLa", [("vidAAAAAAA1", "3")], doc_url="https://ph.tinhtong.vn/Home/A?d=A_001.html")
    write_playlist(work, "PL0", [("vidAAAAAAA1", "3")], doc_url=None)  # no link: skipped
    assert doc.lookup(work, "vidAAAAAAA1") == ("https://ph.tinhtong.vn/Home/A?d=A_003.html", "3")
    assert doc.lookup(work, "vidAAAAAAA1.kt") == ("https://ph.tinhtong.vn/Home/A?d=A_003.html", "3")  # AC8
    assert doc.lookup(work, "vidOTHER111") is None


def test_lookup_none_without_episode_number_or_dir(tmp_path):
    assert doc.lookup(tmp_path / "work", "vidAAAAAAA1") is None
    write_playlist(tmp_path / "work", "PLa", [("vidAAAAAAA1", None)])
    assert doc.lookup(tmp_path / "work", "vidAAAAAAA1") is None


# --- D2 parse ------------------------------------------------------------------------------------------------------


def test_parse_keeps_body_paragraphs_only():
    html = page_html(HEAD_PARAGRAPHS + ["Dòng có <b>chữ đậm</b> giữa &amp; <i>nghiêng</i> ”.", "<b>Cả đoạn đậm</b>",
                                        "Hai<br>dòng", "   "])
    got = doc.parse_paragraphs(html)
    assert got[:2] == HEAD_PARAGRAPHS
    assert got[2] == "Dòng có chữ đậm giữa & nghiêng ”."
    assert got[3:] == ["Hai dòng"]  # header, text-center, all-bold, empty, nav / footer / script paragraphs dropped


def test_parse_fragment_whole_and_no_body():
    assert doc.parse_paragraphs("<p>Một.</p><p><b>Tiêu đề</b></p><p>Hai.</p>", whole=True) == ["Một.", "Hai."]
    assert doc.parse_paragraphs("<html><p>Ngoài</p></html>") == []


def test_gunzip_bounded():
    assert doc.gunzip_bounded(gzip.compress(b"abc")) == b"abc"
    with pytest.raises(doc.DocError):
        doc.gunzip_bounded(gzip.compress(b"x" * 1000), limit=100)
    with pytest.raises(doc.DocError):
        doc.gunzip_bounded(b"not gzip")
    with pytest.raises(doc.DocError):
        doc.gunzip_bounded(gzip.compress(b"x" * 1000)[:-8], limit=5000)  # truncated


def test_fetch_paragraphs_page_plus_gzip():  # AC2
    opener = FakeOpener(full_routes())
    got = doc.fetch_paragraphs(BASE_URL, opener=opener, resolver=public_resolver)
    assert got == FULL
    assert opener.requests == [BASE_URL, "https://ph.tinhtong.vn" + GZ_PATH]


def test_fetch_paragraphs_page_without_gzip_link():
    opener = FakeOpener({BASE_URL: page_html(gz_path=None)})
    assert doc.fetch_paragraphs(BASE_URL, opener=opener, resolver=public_resolver) == HEAD_PARAGRAPHS


def test_fetch_gzip_too_big_is_error(monkeypatch):  # AC2
    monkeypatch.setattr(doc, "MAX_BYTES", 2000)
    routes = full_routes()
    routes["https://ph.tinhtong.vn" + GZ_PATH] = gzip.compress(b"<p>" + b"a" * 100_000 + b"</p>")
    with pytest.raises(doc.DocError, match="sau khi giải nén"):
        doc.fetch_paragraphs(BASE_URL, opener=FakeOpener(routes), resolver=public_resolver)


def test_fetch_gzip_link_to_other_host_and_page_host(monkeypatch):  # AC2
    html = page_html(gz_path="https://evil.example/html-end/K/K_001.gz.z")
    with pytest.raises(doc.DocError, match="host khác"):
        doc.fetch_paragraphs(BASE_URL, opener=FakeOpener({BASE_URL: html}), resolver=public_resolver)
    with pytest.raises(doc.DocError, match="chỉ tải từ"):
        doc.fetch_paragraphs("https://evil.example/Home/K?d=K_001.html", opener=FakeOpener({}), resolver=public_resolver)


def test_fetch_empty_page_and_http_error():
    with pytest.raises(doc.DocError, match="không đọc được"):
        doc.fetch_paragraphs(BASE_URL, opener=FakeOpener({BASE_URL: "<html></html>"}), resolver=public_resolver)
    with pytest.raises(doc.DocError, match="HTTP 404"):
        doc.fetch_paragraphs(BASE_URL, opener=FakeOpener({}), resolver=public_resolver)


def test_fetch_blocks_private_host_p13():  # AC3
    opener = FakeOpener(full_routes())
    with pytest.raises(doc.DocError, match="không được phép"):
        doc.fetch_paragraphs(BASE_URL, opener=opener, resolver=private_resolver)
    assert opener.requests == []


def test_redirect_handler_rejects_other_host_and_internal():  # AC2, AC3
    import urllib.request

    handler = doc._host_redirect_handler(public_resolver)()
    req = urllib.request.Request(BASE_URL)
    with pytest.raises(fetch.FetchError, match="chỉ nhận"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://other.example/x")
    internal = doc._host_redirect_handler(private_resolver)()
    with pytest.raises(fetch.FetchError, match="không được phép"):
        internal.redirect_request(req, None, 302, "Found", {}, "https://ph.tinhtong.vn/x")
    ok = handler.redirect_request(req, None, 302, "Found", {}, "https://ph.tinhtong.vn/Home/K?d=K_002.html")
    assert ok is not None and ok.full_url.startswith("https://ph.tinhtong.vn/")


# --- D3 cache + match ----------------------------------------------------------------------------------------------


def _segments(text: str) -> list[dict]:
    words = text.split()
    return [{"id": f"s{n:05d}", "kind": "speech", "start": n, "end": n + 1, "text": " ".join(words[i:i + 8])}
            for n, i in enumerate(range(0, len(words), 8))]


def _asr(text: str) -> str:
    """The text as an ASR would write it: no punctuation / caps, a few substitutions."""
    out = " ".join(w for w in (doc.normalize_word(t) for t in text.split()) if w)
    return out.replace("rốt cuộc", "suốt cuộc").replace("hủy báng", "hủy bán")


def test_prepare_writes_cache_then_reuses_it(tmp_path):  # AC4
    work = tmp_path / "work"
    write_playlist(work, "PLa", [("vidAAAAAAA1", "1")])
    opener = FakeOpener(full_routes())
    segs = _segments(_asr(" ".join(FULL)))
    t = doc.prepare("vidAAAAAAA1", work, segs, opener=opener, resolver=public_resolver, now="2026-10-02T00:00:00Z")
    assert t is not None and t.usable and t.match > 0.9 and t.paragraphs == FULL
    cache = json.loads((work / "vidAAAAAAA1" / "doc.json").read_text(encoding="utf-8"))
    assert list(cache) == ["schema_version", "url", "fetched_at", "paragraphs", "match"]
    assert cache["url"] == BASE_URL and cache["paragraphs"] == FULL and cache["fetched_at"] == "2026-10-02T00:00:00Z"
    n_requests = len(opener.requests)
    again = doc.prepare("vidAAAAAAA1", work, segs, opener=FakeOpener({}), resolver=public_resolver)
    assert again.paragraphs == FULL and again.match == t.match
    assert n_requests == 2 and not (work / "vidAAAAAAA1" / "doc.json.tmp").exists()


def test_prepare_refetches_when_doc_url_changes(tmp_path):  # AC4
    work = tmp_path / "work"
    pl = write_playlist(work, "PLa", [("vidAAAAAAA1", "1")])
    segs = _segments(_asr(" ".join(FULL)))
    doc.prepare("vidAAAAAAA1", work, segs, opener=FakeOpener(full_routes()), resolver=public_resolver)
    new = "https://ph.tinhtong.vn/Home/KinhThu?d=KinhThu_01.html"
    d = json.loads(pl.read_text(encoding="utf-8"))
    d["doc_url"] = new
    pl.write_text(json.dumps(d), encoding="utf-8")
    opener = FakeOpener(full_routes(new.replace("_01", "_01"), head=["Khác hẳn. Một đoạn khác."], tail=["Hết."]))
    t = doc.prepare("vidAAAAAAA1", work, segs, opener=opener, resolver=public_resolver)
    assert t.url == new and t.paragraphs == ["Khác hẳn. Một đoạn khác.", "Hết."] and opener.requests


def test_prepare_low_match_is_cached_but_unusable(tmp_path):  # AC4
    work = tmp_path / "work"
    write_playlist(work, "PLa", [("vidAAAAAAA1", "1")])
    segs = _segments("hoàn toàn khác nhau giữa hai bản giảng này " * 20)
    t = doc.prepare("vidAAAAAAA1", work, segs, opener=FakeOpener(full_routes()), resolver=public_resolver)
    assert t is not None and not t.usable and t.match < doc.MIN_MATCH
    assert (work / "vidAAAAAAA1" / "doc.json").is_file()
    again = doc.prepare("vidAAAAAAA1", work, segs, opener=FakeOpener({}), resolver=public_resolver)
    assert again is not None and not again.usable  # no re-download


def test_prepare_failure_writes_no_cache_and_no_link_is_none(tmp_path):  # AC2, AC4
    work = tmp_path / "work"
    write_playlist(work, "PLa", [("vidAAAAAAA1", "1")])
    with pytest.raises(doc.DocError):
        doc.prepare("vidAAAAAAA1", work, [], opener=FakeOpener({}), resolver=public_resolver)
    assert not (work / "vidAAAAAAA1" / "doc.json").exists()
    assert doc.prepare("vidOTHER111", work, [], opener=FakeOpener({}), resolver=public_resolver) is None


# --- D4 / D5 alignment ---------------------------------------------------------------------------------------------

TEXT = doc.build_text(BASE_URL, FULL, 0.9)


def _src(text: str) -> str:
    return _asr(text)


def test_short_starting_mid_sentence_with_asr_errors_expands_to_sentence():  # AC5
    src = ("chỉ là chút ít thôi hay nói cách khác đối với thế giới cùng xuất thế gian pháp không quá mê hoạc "
           "không mê chính là không bị nó xoay chuyển")
    post = doc.compose(TEXT, src)
    assert post is not None and post.ratio >= 0.8
    assert post.paragraphs == ["Nhưng chỉ là chút ít thôi, hay nói cách khác, đối với thế gian cùng xuất thế gian "
                               "pháp không quá mê hoặc. Không mê chính là không bị nó xoay chuyển."]
    assert (post.head, post.tail) == (1, 0) and not post.head_ellipsis and not post.tail_ellipsis


def test_repeated_phrase_picks_the_denser_occurrence_and_whole_sentences():  # AC5
    # the first 8 words occur in the 2nd paragraph and (denser, with the rest) in the third
    src = ("tâm thanh tịnh là gốc của mọi công đức cũng là gốc của vãng sanh nếu hủy bán tam bảo thì tự mình chuốc "
           "lấy quả báo cho nên mỗi ngày chúng ta phải niệm phật")
    post = doc.compose(TEXT, src)
    assert post is not None
    assert post.paragraphs == [
        "Đồng tu cần nhớ, tâm thanh tịnh là gốc của mọi công đức, cũng là gốc của vãng sanh. Nếu hủy báng Tam bảo "
        "thì tự mình chuốc lấy quả báo. Cho nên mỗi ngày chúng ta phải niệm Phật, không để tâm chạy theo cảnh giới "
        "bên ngoài."]
    assert post.head == 4  # "Đồng tu cần nhớ,"


def test_span_over_two_paragraphs_keeps_breaks_and_cleans_quotes():  # AC5
    src = ("đại đức xưa thường nói cảnh giới tu tập mỗi năm không như nhau cho nên phải đem những chỗ ngộ mới nêu ra "
           "cùng chia sẻ đồng tu cần nhớ tâm thanh tịnh là gốc của mọi công đức cũng là gốc của vãng sanh")
    post = doc.compose(TEXT, src)
    assert post is not None and len(post.paragraphs) == 2
    assert post.paragraphs[0] == ("Đại đức xưa thường nói: “Cảnh giới tu tập mỗi năm không như nhau”, cho nên phải "
                                  "đem những chỗ ngộ mới nêu ra cùng chia sẻ.")
    assert post.paragraphs[1] == "Đồng tu cần nhớ, tâm thanh tịnh là gốc của mọi công đức, cũng là gốc của vãng sanh."
    assert "“ " not in " ".join(post.paragraphs) and " ”" not in " ".join(post.paragraphs)


def test_unrelated_or_too_short_source_is_not_aligned():  # AC6
    assert doc.compose(TEXT, "chủ đề hoàn toàn khác về bóng đá và thời tiết hôm nay thật đẹp trời") is None
    assert doc.compose(TEXT, "tâm thanh tịnh") is None  # fewer than MIN_BLOCK words
    # a few shared blocks inside a much longer unrelated text: ratio below MIN_RATIO
    noise = " ".join(f"từ{n}" for n in range(300))
    assert doc.compose(TEXT, "tâm thanh tịnh là gốc của mọi công đức " + noise) is None


def test_more_than_60_tokens_stops_at_aligned_point_with_ellipsis():  # AC5
    words = [f"w{n}" for n in range(1, 101)]
    para = " ".join(words) + "."
    t = doc.build_text("u", ["Câu trước. " + para + " Câu sau."], 1.0)
    # aligned span w70..w79: 70 tokens back to the sentence start (> 60), 21 tokens to its end (<= 60)
    paragraphs, head, tail, he, te = doc.expand(t, 71, 81)
    assert he and not te
    assert paragraphs[0].startswith("…w70 ") and paragraphs[0].endswith("w100.") and (head, tail) == (0, 21)
    # both sides too far: a 200-token sentence, span in the middle
    long = doc.build_text("u", [" ".join(f"x{n}" for n in range(1, 201)) + "."], 1.0)
    paragraphs, head, tail, he, te = doc.expand(long, 100, 110)
    assert he and te and paragraphs == ["…x101 x102 x103 x104 x105 x106 x107 x108 x109 x110…"]


def test_sentence_boundaries_with_closing_quotes_and_standalone_closers():
    t = doc.build_text("u", ["Ông nói “đủ rồi.” Rồi đi. Bà bảo “thôi! ” Sau đó về."], 1.0)
    # span on "Rồi đi" -> "Rồi đi." (the closing quote of the previous sentence is not part of it)
    paragraphs, *_ = doc.expand(t, 4, 6)
    assert paragraphs == ["Rồi đi."]
    # a sentence ending "!” " keeps the standalone closing quote
    paragraphs, *_ = doc.expand(t, 6, 9)
    assert paragraphs == ["Bà bảo “thôi!”"]


def test_first_letter_is_capitalized_only_without_head_ellipsis():
    t = doc.build_text("u", ["và rồi chúng ta đi. Ta về."], 1.0)
    assert doc.expand(t, 0, 2)[0] == ["Và rồi chúng ta đi."]


# --- D6 compose_posts ---------------------------------------------------------------------------------------------


class FailClient:
    def __init__(self):
        self.calls = 0

    def chat(self, **kw):
        self.calls += 1
        text = kw["messages"][-1]["content"].split("\n", 1)[1]
        return ChatResult(content=text[0].upper() + text[1:] + ".", thinking=None, eval_count=1,
                          prompt_eval_count=1, total_duration=1)


def _cfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images", corrections_path=tmp_path / "corr.json",
                                  retries=0, retry_backoff=(0.0,)))


def _doc_for_k01(tmp_path, cfg, *, match=0.9):
    """A lecture text containing the words of k01 (lines 1-8) with punctuation, nothing of k02."""
    ep = source.load(EID, cfg)
    text = source.source_text(ep, "k01")
    sentences = [f"Dòng {i} lời giảng thứ {i} về tâm." for i in range(1, 9)]
    assert doc.words_of(" ".join(sentences)) == doc.words_of(text)
    return doc.build_text("https://ph.tinhtong.vn/Home/K?d=K_001.html",
                          [" ".join(sentences[:4]), " ".join(sentences[4:]), "Một đoạn khác hẳn. Chuyện không liên quan."],
                          match), text


def test_compose_posts_uses_doc_without_ai_and_falls_back_per_short(tmp_path):  # AC6
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _cfg(tmp_path)
    text, k01_src = _doc_for_k01(tmp_path, cfg)
    client = FailClient()
    seen = []

    def loader(eid, segments):
        seen.append((eid, len(segments)))
        return text

    summary = stage.compose_posts(EID, cfg, ["k01", "k02"], client=client, sleep=lambda s: None, doc_loader=loader)
    assert (summary.doc, summary.ai, summary.raw) == (1, 1, 0) and seen == [(EID, seen[0][1])] and seen[0][1] > 0
    assert client.calls == 1  # only k02 (not in the document) went to the AI

    posts = store.read_posts(tmp_path / "work" / EID / "posts.json", EID)
    k01, k02 = store.find(posts, "k01"), store.find(posts, "k02")
    assert k01["origin"] == store.DOC and k02["origin"] == store.AI
    assert k01["paragraphs"] == [" ".join(f"Dòng {i} lời giảng thứ {i} về tâm." for i in range(1, 5)),
                                 " ".join(f"Dòng {i} lời giảng thứ {i} về tâm." for i in range(5, 9))]
    assert k01["source_sha256"] == source.source_sha256(k01_src)  # unchanged semantics
    assert not stage.compute_stale(source.load(EID, cfg), k01)

    log_doc = json.loads((tmp_path / "work" / EID / "post_log.json").read_text(encoding="utf-8"))
    e01 = next(e for e in log_doc["entries"] if e["clip_id"] == "k01")
    assert e01["origin"] == "doc" and e01["doc_url"] == text.url and e01["doc_match"] == 0.9
    assert e01["ratio"] >= 0.9 and e01["span"] == [0, 8 * 8] and e01["expanded"] == {"head": 0, "tail": 0}
    assert "ai_calls" not in e01
    assert "ai_calls" in next(e for e in log_doc["entries"] if e["clip_id"] == "k02")


def test_compose_posts_before_ai_called_once_before_first_ai_short(tmp_path):  # FIX-post-doc-no-gpu F1
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _cfg(tmp_path)
    text, _ = _doc_for_k01(tmp_path, cfg)
    posts_path = tmp_path / "work" / EID / "posts.json"

    # every Short from the document: never called
    calls = []
    client = FailClient()
    stage.compose_posts(EID, cfg, ["k01"], client=client, sleep=lambda s: None, doc_loader=lambda e, s: text,
                        before_ai=lambda: calls.append(1))
    assert calls == [] and client.calls == 0

    # doc Short first, then an AI one: called once, after the doc post was written; its error propagates and the
    # doc post stays
    class Down(Exception):
        pass

    seen = []

    def down():
        seen.append(store.find(store.read_posts(posts_path, EID), "k01") is not None)
        raise Down()

    posts_path.unlink()
    client = FailClient()
    with pytest.raises(Down):
        stage.compose_posts(EID, cfg, ["k01", "k02"], client=client, sleep=lambda s: None,
                            doc_loader=lambda e, s: text, before_ai=down)
    assert seen == [True] and client.calls == 0
    assert store.find(store.read_posts(posts_path, EID), "k01")["origin"] == store.DOC

    # two AI Shorts: once
    calls.clear()
    stage.compose_posts(EID, cfg, ["k01", "k02"], client=FailClient(), sleep=lambda s: None,
                        doc_loader=lambda e, s: None, before_ai=lambda: calls.append(1))
    assert calls == [1]


def test_compose_posts_unusable_missing_or_failing_doc_takes_ai_path(tmp_path):  # AC4, AC6
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _cfg(tmp_path)
    text, _ = _doc_for_k01(tmp_path, cfg, match=0.3)

    def broken(eid, segments):
        raise doc.DocError("không tải được")

    for loader in (lambda e, s: text, lambda e, s: None, broken):
        client = FailClient()
        summary = stage.compose_posts(EID, cfg, ["k01"], client=client, sleep=lambda s: None, doc_loader=loader)
        assert (summary.doc, summary.ai) == (0, 1) and client.calls == 1
        assert store.find(store.read_posts(tmp_path / "work" / EID / "posts.json", EID), "k01")["origin"] == "ai"


def test_compose_posts_doc_not_passed_through_correction_dictionary(tmp_path):  # out of scope: CP8.18 on doc posts
    from auto_short.post import corrections

    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _cfg(tmp_path)
    text, _ = _doc_for_k01(tmp_path, cfg)
    cdoc = corrections.empty_doc()
    corrections.save(cfg.post.corrections_path, cdoc)
    client = FailClient()
    stage.compose_posts(EID, cfg, ["k01"], client=client, sleep=lambda s: None, doc_loader=lambda e, s: text)
    assert client.calls == 0
    log_doc = json.loads((tmp_path / "work" / EID / "post_log.json").read_text(encoding="utf-8"))
    assert "corrections" not in log_doc["entries"][0]


def test_auto_clips_recomposes_stale_doc_post_but_not_posted(tmp_path):  # D6 R4
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _cfg(tmp_path)
    text, _ = _doc_for_k01(tmp_path, cfg)
    stage.compose_posts(EID, cfg, ["k01"], client=FailClient(), sleep=lambda s: None, doc_loader=lambda e, s: text)
    ep = source.load(EID, cfg)
    posts = store.read_posts(tmp_path / "work" / EID / "posts.json", EID)
    entry = store.find(posts, "k01")
    assert stage.auto_clips(ep, posts, ["k01"]) == []
    entry["source_sha256"] = "0" * 64  # stale
    assert stage.auto_clips(ep, posts, ["k01"]) == ["k01"]
    entry["posted_at"] = "2026-10-02T00:00:00Z"
    assert stage.auto_clips(ep, posts, ["k01"]) == []


def test_default_loader_reads_playlist_and_transcript_end_to_end(tmp_path, monkeypatch):  # AC4, AC8
    work = tmp_path / "work"
    make_post_episode(work, tmp_path / "output")
    cfg = _cfg(tmp_path)
    text, _ = _doc_for_k01(tmp_path, cfg)
    write_playlist(work, "PLa", [(EID, "1")], doc_url="https://ph.tinhtong.vn/Home/K?d=K_001.html")
    segs = source.load(EID, cfg).rng.segments
    lines = [f"{sg['text'][0].upper()}{sg['text'][1:]}." for sg in segs if sg["kind"] == "speech"]
    html = page_html([" ".join(lines[i:i + 10]) for i in range(0, len(lines), 10)], gz_path=None)
    opener = FakeOpener({"https://ph.tinhtong.vn/Home/K?d=K_001.html": html})
    real_prepare = doc.prepare
    monkeypatch.setattr(doc, "prepare", lambda *a, **k: real_prepare(*a, opener=opener, resolver=public_resolver, **k))
    client = FailClient()
    summary = stage.compose_posts(EID, cfg, ["k01"], client=client, sleep=lambda s: None)
    assert summary.doc == 1 and client.calls == 0 and (work / EID / "doc.json").is_file()
