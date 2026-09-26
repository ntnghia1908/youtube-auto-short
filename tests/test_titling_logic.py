"""Titling pure logic: header (AC1), clip text (AC2), parsing (AC5), option validation / choice (AC4), G8."""

import json
from dataclasses import replace

import pytest

from auto_short import config as config_mod
from auto_short.config import ConfigError, TitlingHeaderConfig
from auto_short.titling.logic import (
    INVALID,
    VALID,
    ResponseError,
    TitlingError,
    choose_title,
    clip_text,
    normalize_match,
    parse_response,
    reject_reason,
    resolve_header,
    validate_options,
    validate_titles,
)
from auto_short.titling.prompt import prompt_sha256, render_user_prompt, system_prompt
from titling_helpers import VIDEO_TITLE

H = TitlingHeaderConfig()


# --- AC1 header ---------------------------------------------------------------------------------------

def test_header_default_on_test_video():
    h = resolve_header(H, VIDEO_TITLE)
    assert h == {"lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
                 "fields": {"speaker": "HT.Tịnh Không", "series": "Thập Thiện Nghiệp Đạo Kinh", "episode": "9"},
                 "sources": {"speaker": "config", "series": "metadata", "episode": "metadata"}}


def test_header_title_without_prefix():
    h = resolve_header(H, "Thập Thiện Nghiệp Đạo Kinh tập 14")
    assert h["lines"] == ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 14)"]


def test_header_precedence_cli_config_metadata():
    hcfg = replace(H, series="Kinh A", episode="3")
    h = resolve_header(hcfg, VIDEO_TITLE, {"speaker": "  Pháp sư  B ", "series": None, "episode": ""})
    assert h["fields"] == {"speaker": "Pháp sư B", "series": "Kinh A", "episode": "3"}
    assert h["sources"] == {"speaker": "cli", "series": "config", "episode": "config"}
    h = resolve_header(hcfg, VIDEO_TITLE, {"episode": "12"})
    assert h["lines"] == ["HT.Tịnh Không", "Kinh A (tập 12)"] and h["sources"]["episode"] == "cli"


def test_header_missing_field_names_flag():
    with pytest.raises(TitlingError, match=r"series \(pass --series.*episode \(pass --episode"):
        resolve_header(H, None)  # local video without a title
    with pytest.raises(TitlingError, match="--speaker"):
        resolve_header(replace(H, speaker=""), VIDEO_TITLE)
    with pytest.raises(TitlingError, match="--episode"):
        resolve_header(H, "Thập Thiện Nghiệp Đạo Kinh", {"series": "X"})
    # a field not used by the template may stay unresolved
    h = resolve_header(replace(H, lines=("{speaker}",)), None)
    assert h["lines"] == ["HT.Tịnh Không"] and h["fields"]["series"] is None and h["sources"]["series"] is None
    # pattern off -> metadata not used
    with pytest.raises(TitlingError, match="--series"):
        resolve_header(replace(H, title_pattern=""), VIDEO_TITLE)


def test_header_template_lines():
    h = resolve_header(replace(H, lines=("{speaker}", "{series}", "Tập {episode}")), VIDEO_TITLE)
    assert h["lines"] == ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh", "Tập 9"]
    with pytest.raises(TitlingError, match="renders empty"):
        resolve_header(replace(H, lines=("{speaker}", " ")), VIDEO_TITLE)


@pytest.mark.parametrize("header", [
    {"lines": []}, {"lines": ["a", "b", "c", "d"]}, {"lines": ["{speaker}", ""]}, {"lines": "{speaker}"},
    {"lines": ["{title}"]}, {"lines": ["{}"]}, {"lines": ["{speaker"]}, {"title_pattern": "("},
    {"speaker": 1}, {"episode": True}, {"series": ["x"]},
])
def test_header_config_invalid(header):
    with pytest.raises(ConfigError):
        config_mod.from_dict({"titling": {"header": header}})


def test_titling_config_parsing():
    t = config_mod.Config().titling
    assert (t.model, t.think, t.temperature, t.seed, t.num_ctx, t.prompt_version) == \
        ("qwen3:30b", True, 0.0, 42, 16384, "v2")
    assert (t.n_options, t.min_chars, t.max_chars, t.retries, t.timeout, t.retry_backoff) == \
        (3, 10, 60, 2, 600.0, (5.0, 15.0))
    assert t.ollama_host == "http://127.0.0.1:11437" and t.header == TitlingHeaderConfig()
    t = config_mod.from_dict({"titling": {"model": "qwen3:14b", "think": False, "max_chars": 40,
                                          "header": {"episode": 9, "lines": ["{speaker}"]}}}).titling
    assert (t.model, t.think, t.max_chars, t.header.episode, t.header.lines) == \
        ("qwen3:14b", False, 40, "9", ("{speaker}",))


@pytest.mark.parametrize("data", [
    {"model": ""}, {"think": 1}, {"n_options": 0}, {"n_options": 11}, {"min_chars": 0},
    {"min_chars": 70}, {"retries": -1}, {"timeout": 0}, {"retry_backoff": [-1]}, {"header": []},
])
def test_titling_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict({"titling": data})


# --- AC2 clip text ------------------------------------------------------------------------------------

UNITS = [{"id": "u0001", "text": "các vị đồng tu"}, {"id": "u0002", "text": "Thế là  chúng ta"},
         {"id": "u0003", "text": "học kinh Phật"}]


def test_clip_text_joins_units():
    assert clip_text({"id": "k01", "unit_ids": ["u0001", "u0002"], "head_cut": None}, UNITS) == \
        "các vị đồng tu Thế là chúng ta"


def test_clip_text_drops_head_cut_words():
    clip = {"id": "k02", "unit_ids": ["u0002", "u0003"], "head_cut": {"words": "thế là", "original_start": 1.0}}
    assert clip_text(clip, UNITS) == "chúng ta học kinh Phật"
    with pytest.raises(TitlingError, match="do not match"):
        clip_text(dict(clip, head_cut={"words": "cho nên", "original_start": 1.0}), UNITS)
    with pytest.raises(TitlingError, match="not found"):
        clip_text({"id": "k03", "unit_ids": ["u0003", "u0001"], "head_cut": None}, UNITS)


# --- AC3 prompt -----------------------------------------------------------------------------------------

def test_prompt_versions():
    assert prompt_sha256("v1") != prompt_sha256("v2")
    v1, v2 = (system_prompt(v, max_chars=60, n_options=3) for v in ("v1", "v2"))
    assert v1 != v2 and "Các bậc thang tu học Phật pháp" in v1  # v1 kept verbatim
    for phrase in ("người học Phật tại gia và người bình dân", "hook", "đời thường", "Gợi một chút tò mò",
                   "Tránh thuật ngữ khó", "Không giật tít", "không hứa hẹn", "Được dùng dấu hỏi",
                   "Viết hoa kiểu câu", "tối đa 60 ký tự", "đúng 3 phương án", "NGUYÊN VĂN", "không dấu chấm than",
                   "Không emoji", "Không thêm tên người giảng, tên kinh, số tập"):
        assert phrase in v2, phrase
    assert "<<" not in v2
    assert render_user_prompt("v2", title="T", duration=1, text="x") == render_user_prompt("v1", title="T", duration=1,
                                                                                          text="x")


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_prompt_text(version):
    s = system_prompt(version, max_chars=60, n_options=3)
    assert "tối đa 60 ký tự" in s and "đúng 3 phương án" in s and "<<" not in s
    for phrase in ("CHÍNH ĐOẠN NÀY", "Không thêm tên người giảng, tên kinh, số tập", "không hashtag",
                   "không dấu chấm than", "NGUYÊN VĂN", "một dòng"):
        assert phrase in s, phrase
    assert "giật tít" in s.lower() and "không emoji" in s.lower()
    assert render_user_prompt(version, title="", duration=38.379, text="abc") == \
        "Video: (không rõ)\nThời lượng Short: 38.4 giây\n\nLời nói của đoạn:\nabc"
    assert len(prompt_sha256("v1")) == 64
    with pytest.raises(ValueError):
        prompt_sha256("v9")


# --- AC5 parsing ----------------------------------------------------------------------------------------

def _opts(*pairs):
    return json.dumps({"options": [{"evidence": e, "title": t} for t, e in pairs]}, ensure_ascii=False)


def test_parse_response_ok():
    assert parse_response(_opts(("A b c d e f g", "x y z")), 1) == [{"title": "A b c d e f g", "evidence": "x y z"}]


@pytest.mark.parametrize("content,match", [
    ("not json", "not valid JSON"),
    ('{"clips": []}', '"options" array'),
    ('[]', '"options" array'),
    (_opts(("a", "b"), ("c", "d")), "expected 3 options, got 2"),
    ('{"options": [1, 2, 3]}', r"options\[0\] is not an object"),
    ('{"options": [{"title": "a"}, {"title": "b"}, {"title": "c"}]}', r"options\[0\].evidence"),
    ('{"options": [{"evidence": "a", "title": 5}, {}, {}]}', r"options\[0\].title"),
])
def test_parse_response_errors(content, match):
    with pytest.raises(ResponseError, match=match):
        parse_response(content, 3)


# --- AC4 option validation --------------------------------------------------------------------------------

TEXT = "chúng ta thường thường nói Tướng Tùy Tâm chuyển lời nói này không sai chút nào"
TEXT_N = normalize_match(TEXT)
EV = "tướng tùy tâm chuyển"


def _reason(title, evidence=EV, min_chars=10, max_chars=60):
    return reject_reason(title, evidence, TEXT_N, min_chars=min_chars, max_chars=max_chars)


@pytest.mark.parametrize("title,evidence,reason", [
    ("Tướng tùy tâm chuyển", EV, None),
    ("  Tướng  tùy tâm chuyển ", EV, None),  # normalized before checks
    ("Tướng tùy tâm chuyển, không sai chút nào", "Tướng Tùy Tâm chuyển, lời nói này", None),
    ("", EV, "empty title"),
    ("   ", EV, "empty title"),
    ("Tướng tùy\ntâm chuyển", EV, "multi-line title"),
    ("Tướng tùy tâm chuyển\u2028thật", EV, "multi-line title"),
    ("Tâm chuyển", EV, "too short (10 < 11 chars)"),  # with min_chars=11 below
    ("Tướng " * 12, EV, "too long (71 > 60 chars)"),
    ("Tướng tùy tâm chuyển 🙏", EV, "emoji/pictograph"),
    ("Tướng tùy tâm chuyển ✨", EV, "emoji/pictograph"),
    ("Tướng tùy tâm chuyển #phatphap", EV, "hashtag"),
    ("Tướng tùy tâm chuyển @kenh", EV, "@ mention"),
    ("Tướng tùy tâm chuyển!", EV, "exclamation mark"),
    ("Xem tại https://x.io/a nhé", EV, "URL"),
    ("Xem thêm ở phaphanh.vn nhé", EV, "URL"),
    ('"Tướng tùy tâm chuyển"', EV, "wrapped in quotes"),
    ("“Tướng tùy tâm chuyển”", EV, "wrapped in quotes"),
    ("TƯỚNG TÙY TÂM CHUYỂN", EV, "all caps"),
    ("Tướng tùy tâm chuyển", "tướng tùy", "evidence too short (2 < 3 words)"),
    ("Tướng tùy tâm chuyển", "tướng tùy tâm biến", "evidence not in clip text"),
    ("Tướng tùy tâm chuyển", "ướng tùy tâm", "evidence not in clip text"),  # whole words only
])
def test_reject_reason_rules(title, evidence, reason):
    min_chars = 11 if reason and reason.startswith("too short") else 10
    assert _reason(title, evidence, min_chars=min_chars) == reason


def test_length_counts_nfc_code_points():
    decomposed = "Tu\u0301ng tu\u0300y ta\u0302m"  # combining marks -> NFC 'Túng tùy tâm'
    assert len("Túng tùy tâm") == 12
    assert _reason(decomposed, max_chars=12) is None and _reason(decomposed, max_chars=11) == "too long (12 > 11 chars)"


def test_validate_options_and_choose():
    opts = [{"title": "Tướng tùy tâm chuyển!", "evidence": EV},
            {"title": " Tướng  tùy tâm chuyển ", "evidence": " Tướng Tùy Tâm  chuyển "},
            {"title": "Lời nói không sai chút nào", "evidence": "không sai chút nào"}]
    recs = validate_options(opts, TEXT, min_chars=10, max_chars=60)
    assert [(r["status"], r["reject_reason"]) for r in recs] == [(INVALID, "exclamation mark"), (VALID, None),
                                                                 (VALID, None)]
    assert recs[1]["title"] == "Tướng tùy tâm chuyển" and recs[1]["evidence"] == "Tướng Tùy Tâm chuyển"
    chosen, alts = choose_title(recs)
    assert chosen == {"title": "Tướng tùy tâm chuyển", "evidence": "Tướng Tùy Tâm chuyển"}
    assert alts == [{"title": "Lời nói không sai chút nào", "evidence": "không sai chút nào"}]
    assert choose_title([dict(r, status=INVALID) for r in recs]) == (None, [])


# --- G8 -------------------------------------------------------------------------------------------------------

def _doc():
    clips_doc = {"clips": [{"id": "k01", "candidate_id": "c1"}, {"id": "k02", "candidate_id": "c2"}]}
    doc = {"clips_sha256": "a", "candidates_sha256": "b", "header": {"lines": ["H"]},
           "titles": [{"clip_id": "k01", "candidate_id": "c1", "title": "Tướng tùy tâm chuyển", "evidence": EV,
                       "alternatives": [], "status": "titled"},
                      {"clip_id": "k02", "candidate_id": "c2", "title": None, "evidence": None, "alternatives": [],
                       "status": "untitled"}]}
    return doc, clips_doc


def _check(doc, clips_doc):
    validate_titles(doc, clips_doc, {"k01": TEXT, "k02": TEXT}, clips_sha256="a", candidates_sha256="b",
                    min_chars=10, max_chars=60)


def test_validate_titles_ok_and_violations():
    doc, clips_doc = _doc()
    _check(doc, clips_doc)
    bad = [
        lambda d: d.update(clips_sha256="x"),
        lambda d: d.update(candidates_sha256="x"),
        lambda d: d["header"].update(lines=[]),
        lambda d: d["header"].update(lines=["a", "b", "c", "d"]),
        lambda d: d["titles"].pop(),
        lambda d: d["titles"].reverse(),
        lambda d: d["titles"][0].update(candidate_id="c9"),
        lambda d: d["titles"][0].update(title="Quá ngắn"),
        lambda d: d["titles"][0].update(evidence="không có trong text"),
        lambda d: d["titles"][0].update(alternatives=[{"title": "Tướng tùy tâm!", "evidence": EV}]),
        lambda d: d["titles"][1].update(title="Tướng tùy tâm chuyển"),
        lambda d: d["titles"][1].update(status="skipped"),
    ]
    for mutate in bad:
        doc, clips_doc = _doc()
        mutate(doc)
        with pytest.raises(TitlingError):
            _check(doc, clips_doc)
