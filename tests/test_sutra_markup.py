"""SR1.1: sutra text format S2 -> S3 (markup.parse). Fixtures are self-written, not real sutra text."""

import pytest

from auto_short.sutra.markup import MarkupError, parse

GOOD = """= Kinh Thử
~ Người dịch: Không có
~ Nguồn: tự soạn

@ Nghi thức đầu
# Nguyện hương
(Lạy ba lạy)
Dòng một[^1]
Dòng hai

Đoạn hai
\\# không phải mục
[^1]: Chú thích một

@ Chính kinh
# Phẩm một
天地玄黄
宇宙洪荒 abc

# Phẩm hai
Chỉ một dòng.
"""


def errs(text):
    with pytest.raises(MarkupError) as e:
        parse(text)
    return e.value.errors


def test_full_structure():
    s = parse(GOOD).to_json()
    assert s["schema_version"] == 1 and s["title"] == "Kinh Thử"
    assert s["intro"] == ["Người dịch: Không có", "Nguồn: tự soạn"]
    assert [g["title"] for g in s["groups"]] == ["Nghi thức đầu", "Chính kinh"]
    sec = s["groups"][0]["sections"][0]
    assert sec["id"] == "s1" and sec["title"] == "Nguyện hương" and sec["notes"] == {"1": "Chú thích một"}
    assert [[ln["kind"] for ln in p] for p in sec["paragraphs"]] == [["inst", "text", "text"], ["text", "text"]]
    assert sec["paragraphs"][1][1]["text"] == "# không phải mục"  # escape
    assert sec["paragraphs"][0][1]["text"] == "Dòng một[^1]"
    assert [x["id"] for g in s["groups"] for x in g["sections"]] == ["s1", "s2", "s3"]
    han = s["groups"][1]["sections"][0]["paragraphs"][0]
    assert [ln["kind"] for ln in han] == ["han", "han"]  # second line: 4 Han / 3 latin letters = 57 %


def test_section_before_group_has_untitled_group_and_parses_nfc():
    s = parse("= Tên\n# Mục\nHộ\n").to_json()  # decomposed input is normalized to NFC
    assert s["groups"][0]["title"] is None
    assert s["groups"][0]["sections"][0]["paragraphs"][0][0]["text"] == "Hộ"


def test_inst_fullwidth_and_low_han_ratio():
    s = parse("= T\n# M\n（唱）\n天 and many latin letters here\n").to_json()
    kinds = [ln["kind"] for ln in s["groups"][0]["sections"][0]["paragraphs"][0]]
    assert kinds == ["inst", "text"]


def test_crlf_and_bom():
    assert parse("﻿= T\r\n# M\r\nx\r\n").title == "T"


def test_missing_title():
    assert errs("# M\nx\n")[0] == (1, "thiếu dòng '= <tên>' ở đầu văn bản")
    assert errs("")[0][0] == 0


def test_title_must_be_first_and_only_once():
    e = errs("# M\nx\n= T\n")
    assert any(n == 3 and "đầu tiên" in m for n, m in e)
    e = errs("= A\n= B\n# M\nx\n")
    assert (2, "chỉ được có một dòng '='") in e


def test_content_outside_section_and_empty_section():
    e = errs("= T\nxin chào\n# Rỗng\n# Có\nx\n")
    assert (2, "nội dung nằm ngoài mục (cần dòng '# <tên mục>' trước)") in e
    assert (3, "mục 'Rỗng' rỗng") in e


def test_intro_only_before_first_marker():
    assert any(n == 4 and "'~'" in m for n, m in errs("= T\n# M\nx\n~ muộn\n"))
    assert any(n == 3 and "'~'" in m for n, m in errs("= T\n@ G\n~ muộn\n# M\nx\n"))


def test_note_errors_reported_together():
    text = "= T\n# M\na[^1] b[^2]\n[^1]: một\n[^1]: lại\n[^3]: thừa\n"
    e = errs(text)
    assert (5, "chú thích [^1] bị trùng") in e
    assert (3, "chú thích [^2] chưa có định nghĩa trong mục") in e
    assert (6, "chú thích [^3] được định nghĩa nhưng không dùng") in e
    assert [n for n, _ in e] == sorted(n for n, _ in e)


def test_note_outside_section_and_note_scope_is_section():
    assert any("ngoài mục" in m for _, m in errs("= T\n[^1]: x\n# M\ny\n"))
    # reference in section 2, definition only in section 1 -> both errors
    e = errs("= T\n# A\nx[^1]\n[^1]: n\n# B\ny[^1]\n")
    assert any(n == 6 and "chưa có định nghĩa" in m for n, m in e)


def test_line_too_long_and_too_many_sections():
    assert any("quá dài" in m for _, m in errs("= T\n# M\n" + "x" * 5001 + "\n"))
    assert parse("= T\n# M\n" + "x" * 5000 + "\n")
    text = "= T\n" + "".join(f"# M{i}\nx\n" for i in range(2001))
    assert any("2000" in m for _, m in errs(text))
    assert parse("= T\n" + "".join(f"# M{i}\nx\n" for i in range(2000))).section_count == 2000


def test_text_too_large():
    e = errs("= T\n# M\n" + "x" * (2 * 1024 * 1024) + "\n")
    assert e == [(0, "văn bản quá lớn (tối đa 2 MB)")]


def test_empty_names():
    e = errs("=\n# \nx\n")
    assert (1, "tên bộ kinh rỗng") in e and (2, "tên mục rỗng") in e


def test_empty_group_dropped_and_marker_needs_space():
    s = parse("= T\n@ Trống\n@ Có\n# M\n#hashtag\n=x\n").to_json()
    assert [g["title"] for g in s["groups"]] == ["Có"]
    assert [ln["text"] for ln in s["groups"][0]["sections"][0]["paragraphs"][0]] == ["#hashtag", "=x"]


def test_strong_lines():
    s = parse("= T\n# M\n* 天地玄黄\n* (Lạy)\n* Câu đậm[^1]\n\\* literal\n(Lạy)\n*không cách\n[^1]: n\n").to_json()
    lines = s["groups"][0]["sections"][0]["paragraphs"][0]
    assert [(ln["text"], ln["kind"]) for ln in lines] == [
        ("天地玄黄", "strong"), ("(Lạy)", "strong"), ("Câu đậm[^1]", "strong"), ("* literal", "text"),
        ("(Lạy)", "inst"), ("*không cách", "text")]


def test_strong_empty_prefix_ignored_and_ref_checked():
    assert parse("= T\n# M\n* \nx\n").to_json()["groups"][0]["sections"][0]["paragraphs"][0][0]["text"] == "x"
    assert any("chưa có định nghĩa" in m for _, m in errs("= T\n# M\n* a[^2]\n"))
