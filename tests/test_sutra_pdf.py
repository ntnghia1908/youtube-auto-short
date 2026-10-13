"""SR1.3: sutra PDF import (S5a). Layout logic on hand-built Line / Run objects; the pypdf path and the child
process on a tiny hand-written Helvetica PDF. No real sutra text anywhere (copyrighted)."""

import importlib.util
import json
import subprocess
import sys
import unicodedata

import pytest

from auto_short.sutra import importer, markup, pdf
from auto_short.sutra.pdf import Line, Page, PdfError, Run
from sutra_pdf_helpers import make_pdf, sample_pdf, u


needs_pypdf = pytest.mark.skipif(importlib.util.find_spec("pypdf") is None, reason="pypdf (extra [web]) not installed")


# --- builders ----------------------------------------------------------------------------------------------


def L(text, y, x=72.0, size=12.0, bold=False, col=0):
    return Line(text, x, y, size, bold, col)


def P(*lines, height=800.0, width=600.0):
    return Page(list(lines), height, width)


def ys(n, top=700.0, step=14.0):
    return [top - i * step for i in range(n)]


def convert(pages):
    text, warnings = pdf.layout(pages)
    markup.parse(text)  # every layout result must be valid S2
    return text, warnings


def body_lines(text):
    return [ln for ln in text.split("\n") if ln and not ln.startswith(("#", "=", "[^"))]


LONG = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu"  # 65 chars


# --- headers / footers / page numbers (AC 1) ---------------------------------------------------------------


def test_running_header_footer_and_page_number_removed():
    pages = []
    for i in range(6):
        pages.append(P(L(f"BOOK TITLE {i + 1}", 770),
                       *[L(f"{LONG} {u(i, k)}", y) for k, y in enumerate(ys(5))],
                       L(str(i + 1), 30)))
    text, _ = convert(pages)
    assert "BOOK TITLE" not in text and "\n1\n" not in text
    assert LONG in text


def test_numbered_header_in_the_middle_of_the_page_and_glued_to_a_line():
    pages = []
    for i in range(8):
        pages.append(P(*[L(f"{LONG} {u(i, k)}", y) for k, y in enumerate(ys(4))],
                       L(f"Tiêu đề sách {i + 1}", 600 - i * 7),  # Google Docs: footer right after the text, varying y
                       L(f"{LONG} tail {u(i, 9)} Tiêu đề sách {i + 1}", 400)))  # glued to the end of another line
    text, _ = convert(pages)
    assert "Tiêu đề sách" not in text
    assert f"{LONG} tail {u(3, 9)}" in text


def test_repeated_phrase_without_number_in_the_middle_is_kept():
    pages = [P(*[L(f"{LONG} {u(i, k)}", y) for k, y in enumerate(ys(4))], L("Xá Lợi Phất! lặp lại", 300 - 11 * i))
             for i in range(8)]
    text, _ = convert(pages)
    assert text.count("Xá Lợi Phất! lặp lại") == 8


def test_refrain_in_the_zone_at_varying_height_is_kept():
    pages = [P(*[L(f"{LONG} {u(i, k)}", y) for k, y in enumerate(ys(4))], L("Nam mô Phật", 120 - 9 * i)) for i in range(8)]
    text, _ = convert(pages)
    assert text.count("Nam mô Phật") == 8


def test_chapter_running_header_with_page_number_even_when_rare():
    pages = [P(L("PHÁP TẠNG NHÂN ĐỊA ĐỆ TỨ 35", 770), L(f"{LONG} a", 700), L(f"{LONG} b", 686), L("PHẨM 12", 672, x=120)),
             P(L(f"{LONG} c", 700), L(f"{LONG} d", 686), L("ĐỆ NHẤT 36 THẬP PHƯƠNG ĐỆ NHỊ", 20)),
             P(L(f"{LONG} e", 700), L("37", 20))]
    text, _ = convert(pages)
    assert "PHÁP TẠNG" not in text and "THẬP PHƯƠNG" not in text and "37" not in text
    assert "# PHẨM 12" in text  # a heading with a number is not a running header


def test_no_text_layer_is_an_error():
    with pytest.raises(PdfError) as e:
        pdf.layout([P(), P()])
    assert e.value.status == 422 and "lớp chữ" in str(e.value)


# --- headings (AC 1) ---------------------------------------------------------------------------------------


def test_multi_line_uppercase_heading_merges_into_one_section_title():
    body = [L(f"{LONG} {k}", y) for k, y in enumerate(ys(6, top=640))]
    text, _ = convert([P(L("PHẨM THỨ NHẤT", 760, x=150), L("PHÁP HỘI THÁNH CHÚNG", 745, x=150), *body)])
    assert "# PHẨM THỨ NHẤT PHÁP HỘI THÁNH CHÚNG\n" in text
    assert text.count("\n# ") == 1


def test_big_font_uppercase_line_is_a_heading_but_a_normal_one_is_not():
    body = [L(f"{LONG} {k}", y) for k, y in enumerate(ys(6, top=640))]
    text, _ = convert([P(L("TÊN LỚN", 760, size=20), *body, L("CHỮ HOA THƯỜNG", 540))])
    assert "# TÊN LỚN" in text and "# CHỮ HOA THƯỜNG" not in text and "CHỮ HOA THƯỜNG" in text


# --- joining lines (AC 2) ----------------------------------------------------------------------------------


def test_indented_paragraphs_join_wrapped_lines():
    lines = []
    y = 700.0
    for k in range(4):
        lines += [L(f"Đoạn {k} bắt đầu thụt lề và dài đến mức phải xuống dòng", y, x=90),
                  L("xuống dòng tiếp và kết thúc ở đây.", y - 14)]
        y -= 28
    lines.append(L("Dòng sát lề thứ ba", y))
    text, _ = convert([P(*lines)])
    body = body_lines(text)
    assert body[0] == "Đoạn 0 bắt đầu thụt lề và dài đến mức phải xuống dòng xuống dòng tiếp và kết thúc ở đây."
    assert len([b for b in body if b.startswith("Đoạn")]) == 4


def test_full_lines_continue_and_a_short_line_ends_the_paragraph():
    lines = []
    for k, y in enumerate(ys(9)):
        lines.append(L(LONG if k % 3 != 2 else "câu cuối ngắn.", y))
    text, _ = convert([P(*lines)])
    body = body_lines(text)
    assert body[0] == f"{LONG} {LONG} câu cuối ngắn." and len(body) == 3


def test_lowercase_start_is_always_a_continuation():
    lines = [L("Một dòng ngắn", 700), L("viết thường nối tiếp", 686), L("Dòng mới", 672), L("Dòng khác", 658), L("Dòng nữa", 644)]
    text, _ = convert([P(*lines)])
    assert "Một dòng ngắn viết thường nối tiếp" in text


def test_loose_spacing_keeps_each_verse_line_and_gap_makes_stanzas():
    prose = P(*[L(LONG, y) for y in ys(12, top=700, step=14)])  # full lines at normal spacing: one paragraph
    verse_y = [700, 676, 652, 628, 574, 550, 526, 502]  # step 24 (looser than the book), a 54 gap = new stanza
    verse = P(L("KỆ MỘT", 740, x=140), *[L(f"Câu kệ số {chr(65 + k)} dài vừa phải thôi nhé", y) for k, y in enumerate(verse_y)])
    text, _ = convert([prose, verse])
    head, tail = text.split("# KỆ MỘT\n\n")
    assert head.strip().split("\n")[-1] == " ".join([LONG] * 12)
    kệ = tail.strip().split("\n")
    assert [b for b in kệ if b] == [f"Câu kệ số {chr(65 + k)} dài vừa phải thôi nhé" for k in range(8)]
    assert kệ.count("") == 1 and kệ[4] == ""


def test_prose_section_gets_blank_line_between_paragraphs():
    lines = []
    y = 700.0
    for k in range(4):
        lines += [L(LONG + f" {k}", y), L("kết thúc.", y - 14)]
        y -= 28
    text, _ = convert([P(*lines)])
    body = text.split("# Mở đầu\n\n")[1].strip().split("\n")
    assert len(body) == 7 and body[1] == "" and body[2].startswith(LONG)


def test_numbered_list_item_opens_a_new_line():
    lines = [L(LONG, 700), L("1. Điều thứ nhất.", 686), L("2. Điều thứ hai.", 672), L(LONG, 658)]
    text, _ = convert([P(*lines)])
    assert "\n1. Điều thứ nhất.\n" in text or "\n1. Điều thứ nhất.\n\n" in text
    assert LONG + " 1." not in text


def test_two_columns_on_a_landscape_page_read_left_then_right():
    runs = []
    for k, y in enumerate(ys(5, top=500)):
        runs.append(Run(60, y, f"trái {k}", 12))
        runs.append(Run(460, y, f"phải {k}", 12))
    page = pdf.group_runs(runs, 800, 600)
    assert [l.col for l in page.lines] == [0] * 5 + [1] * 5
    assert page.lines[0].text == "trái 0" and page.lines[5].text == "phải 0"
    assert [l.col for l in pdf.group_runs(runs, 600, 800).lines] == [0] * 5  # portrait: one column


# --- bold, Chinese side cell ---------------------------------------------------------------------------------


def test_bold_lines_are_marked_unless_most_of_the_book_is_bold():
    mixed = [L("Câu Hán Việt in đậm", 700, bold=True), L("Bản dịch thường", 686), L("Dòng khác nữa", 672),
             L("Thêm một dòng", 658), L("Dòng cuối cùng", 644), *[L(LONG, 630 - 14 * k) for k in range(4)]]
    text, _ = convert([P(*mixed)])
    assert "* Câu Hán Việt in đậm" in text and "\n* Bản dịch" not in text
    all_bold = [L(f"Dòng {k}", y, bold=True) for k, y in enumerate(ys(5))]
    text, _ = convert([P(*all_bold)])
    assert "*" not in text.replace("\n", "")


def test_special_start_of_a_content_line_is_escaped():
    text, _ = convert([P(L("# không phải tiêu đề", 700), L("= cũng không", 686), L("Dòng bình thường 3", 672),
                         *[L(LONG, 658 - 14 * k) for k in range(4)])])
    assert "\\# không phải tiêu đề" in text and "\\= cũng không" in text


def test_chinese_column_becomes_separate_lines_after_the_section_body():
    runs = []
    for k, y in enumerate(ys(5)):
        runs.append(Run(72, y, f"Dòng Việt {k}", 12))
        runs.append(Run(420, y, "如是我聞一時", 12))
    page = pdf.group_runs(runs, 600, 800)
    assert len(page.lines) == 10
    text, _ = convert([page])
    assert text.count("如是我聞一時") == 5
    assert text.index("Dòng Việt 4") < text.index("如是我聞一時")
    assert sutra_kinds(text).count("han") == 5


def sutra_kinds(text):
    return [ln.kind for sec in markup.parse(text).groups[0].sections for para in sec.paragraphs for ln in para]


# --- text repair (AC 3) --------------------------------------------------------------------------------------


def test_combining_marks_in_separate_runs_are_composed_nfc():
    runs = [Run(72, 700, "Vie", 12), Run(90, 700, "̣", 12), Run(92, 700, "̂", 12), Run(95, 700, "t nam", 12)]
    page = pdf.group_runs(runs, 600, 800)
    assert page.lines[0].text == unicodedata.normalize("NFC", "Việt nam") == "Việt nam"


def test_split_diacritic_run_with_leading_space_is_decided_by_x_distance():
    # Word: "h" + " ữ" (the space has no advance: next run starts one glyph later) + "u"
    runs = [Run(72, 700, "h", 14), Run(80, 700, " ữ", 14), Run(87, 700, "u phước", 14)]
    assert pdf.group_runs(runs, 600, 800).lines[0].text == "hữu phước"
    # a real word space: the run is wide enough for space + glyph
    runs = [Run(72, 700, "đi", 14), Run(86, 700, " ữ", 14), Run(97, 700, "u", 14)]
    assert pdf.group_runs(runs, 600, 800).lines[0].text == "đi ữu"
    # no usable width (some producers do not advance x): the space stays
    runs = [Run(72, 700, "h", 14), Run(80, 700, " ữ", 14), Run(80, 700, "u", 14)]
    assert pdf.group_runs(runs, 600, 800).lines[0].text == "h ữu"


def test_fix_split_words_fallback():
    assert pdf.fix_split_words("quả h ữu duyên") == "quả hữu duyên"
    assert pdf.fix_split_words("nh ư vậy, tr ọng") == "như vậy, trọng"
    assert pdf.fix_split_words("a b c") == "a b c"  # no vowel-initial syllable made
    assert pdf.fix_split_words("là một") == "là một"


# --- footnotes (AC 3) ----------------------------------------------------------------------------------------


def footnote_page(ref_run=True):
    runs = []
    for k, y in enumerate(ys(6, top=700)):
        runs.append(Run(72, y, f"Dòng thân bài số {k} có chữ", 14))
    if ref_run:
        runs.append(Run(210, 700 + 5, "1", 9))  # superscript right after a word of the first line
    runs.append(Run(72, 83.2, "1", 6.5))
    runs.append(Run(80, 79.7, " Chú thích một.", 10))
    runs.append(Run(72, 69.7, "tiếp theo của chú thích.", 10))
    return pdf.group_runs(runs, 600, 800)


def test_superscript_becomes_reference_and_definition_goes_to_the_end_of_the_section():
    page = footnote_page()
    assert any("[^1]" in l.text for l in page.lines)
    text, warnings = convert([page, footnote_page(ref_run=False)])
    assert "[^1]" in text and "[^1]: Chú thích một. tiếp theo của chú thích." in text
    assert text.index("[^1]: ") > text.index("Dòng thân bài số 5")
    assert any("không có dấu tham chiếu" in w for w in warnings)  # page 2 has a definition without a reference
    assert "Chú thích một." not in text.split("[^1]: ")[0]  # not left in the body


def test_reference_without_definition_is_dropped_with_warning():
    page = footnote_page()
    page.lines[:] = [l for l in page.lines if l.y > 100]  # the definition lines are gone
    text, warnings = convert([page])
    assert "[^" not in text and any("không có nội dung" in w for w in warnings)


def test_small_print_numbered_list_is_body_not_a_footnote():
    runs = [Run(72, y, f"Dòng thân bài số {k}", 14) for k, y in enumerate(ys(6))]
    runs += [Run(72, 90, "1. Điều nguyện thứ nhất.", 10), Run(72, 78, "2. Điều nguyện thứ hai.", 10)]
    runs += [Run(72, 60, "3", 7), Run(78, 60, ". Điều nguyện thứ ba.", 10)]
    text, warnings = convert([pdf.group_runs(runs, 600, 800)])
    assert "1. Điều nguyện thứ nhất." in text and "2. Điều nguyện thứ hai." in text and "3. Điều nguyện thứ ba." in text
    assert "[^" not in text


def test_lone_small_number_without_a_word_is_a_warning():
    page = P(*[L(f"Dòng thân bài số {k}", y, size=14) for k, y in enumerate(ys(6))], L("7", 400, x=300, size=8))
    text, warnings = convert([page])
    assert any("số chú thích 7" in w for w in warnings) and "\n7\n" not in text


# --- sections -------------------------------------------------------------------------------------------------


def test_empty_heading_section_is_dropped_with_warning_and_title_placeholder():
    body = [L(f"{LONG} {k}", y) for k, y in enumerate(ys(6, top=700))]
    text, warnings = convert([P(*body, L("MỤC TRỐNG", 560, x=200))])
    assert text.startswith(f"= {pdf.DEFAULT_TITLE}\n") and "MỤC TRỐNG" not in text
    assert any("MỤC TRỐNG" in w for w in warnings)


def test_very_long_logical_line_is_split_for_the_5000_char_limit():
    lines = [L("a" * 60 + ". " + "b" * 60 + ". ", y) for y in ys(80, top=790, step=9)]
    text, warnings = convert([P(*lines, height=900)])
    assert max(len(l) for l in text.split("\n")) <= pdf.MAX_LINE and any("chia nhỏ" in w for w in warnings)


# --- pypdf path + child process ---------------------------------------------------------------------------------


@needs_pypdf
def test_extract_from_a_real_pdf_file(tmp_path):
    f = tmp_path / "s.pdf"
    f.write_bytes(sample_pdf())
    text, warnings = pdf.extract(str(f))
    markup.parse(text)
    assert "RUNNING HEADER" not in text and "# CHAPTER ONE" in text
    assert f"Body line {u(0, 0)} of the sample text for testing." in text
    assert "Indented start of a new paragraph that wraps around to a second line." in text
    assert warnings == []


@needs_pypdf
def test_extract_scan_like_pdf_without_text_is_422(tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(make_pdf([[], []]))
    with pytest.raises(PdfError) as e:
        pdf.extract(str(f))
    assert e.value.status == 422 and "lớp chữ" in str(e.value)


@needs_pypdf
def test_extract_garbage_and_page_limit(tmp_path, monkeypatch):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"%PDF-1.4\nnot really a pdf\n")
    with pytest.raises(PdfError):
        pdf.extract(str(f))
    f.write_bytes(sample_pdf())
    monkeypatch.setattr(pdf, "MAX_PAGES", 3)
    with pytest.raises(PdfError) as e:
        pdf.extract(str(f))
    assert "trang" in str(e.value)


@needs_pypdf
def test_child_process_entry_prints_json(tmp_path):
    f = tmp_path / "s.pdf"
    f.write_bytes(sample_pdf())
    done = subprocess.run([sys.executable, "-I", "-c", importer._CHILD_BOOT, str(importer._SRC_DIR), str(f)],
                          capture_output=True, timeout=60)
    doc = json.loads(done.stdout.decode("utf-8"))
    assert done.returncode == 0 and "# CHAPTER ONE" in doc["text"] and doc["warnings"] == []
    f.write_bytes(make_pdf([[]]))
    done = subprocess.run([sys.executable, "-I", "-c", importer._CHILD_BOOT, str(importer._SRC_DIR), str(f)],
                          capture_output=True, timeout=60)
    assert json.loads(done.stdout.decode("utf-8"))["status"] == 422
    # `python -I -m auto_short.sutra.pdf <file>` is the documented entry too (needs the package installed)
    done = subprocess.run([sys.executable, "-I", "-m", "auto_short.sutra.pdf", str(f)], capture_output=True, timeout=60)
    if done.returncode == 0 and done.stdout:
        assert "error" in json.loads(done.stdout.decode("utf-8"))


# --- SR1.5: VNI fonts, ritual symbols, sheet music ---------------------------------------------------------


def R(text, x, y=700.0, font="", size=12.0):
    return Run(x, y, text, size, False, font)


def lines_of(runs, width=600.0, height=800.0):
    return [l.text for l in pdf.group_runs(runs, width, height).lines]


def test_font_kind():
    assert pdf.font_kind("/ABCDEF+VNI-Times") == "vni"
    assert pdf.font_kind("/VNI-Times-Bold") == "vni"
    assert pdf.font_kind("/ABCDEF+VNI-Helve") == "symbol"
    for f in ("/SegoeUISymbol", "/ABCDEF+MS-Mincho", "/EuphemiaCAS", "/Arial-BlackItalic", "/Vinhan"):
        assert pdf.font_kind(f) == "symbol", f
    assert pdf.font_kind("/TimesNewRoman") == ""
    assert pdf.font_kind("") == ""
    assert pdf.font_kind("/ABCDEF+.VnTime") == "tcvn"


def test_vni_runs_converted_and_unicode_font_left_alone():
    assert lines_of([R("Nhö vaäy", 72, font="/AAAAAA+VNI-Times")]) == ["Như vậy"]
    # the same characters in an ordinary font are text, not VNI codes
    assert lines_of([R("aù", 72, font="/AAAAAA+TimesNewRoman")]) == [unicodedata.normalize("NFC", "aù")]
    assert lines_of([R("aù", 72)]) == [unicodedata.normalize("NFC", "aù")]


def test_vni_letter_split_over_two_runs():
    assert lines_of([R("Ha", 72, font="/VNI-Times"), R("ï", 84, font="/VNI-Times")]) == ["Hạ"]
    mixed = [R("Pha", 72, font="/VNI-Times"), R("ät", 90, font="/VNI-Times"), R(" va", 110, font="/Arial")]
    assert lines_of(mixed) == ["Phật va"]


def test_symbol_font_and_symbol_only_runs_dropped():
    runs = [R("abc", 72, font="/VNI-Times"), R("xyz", 200, font="/VNI-Helve"), R("●", 260), R("▬ ◎", 300),
            R("def", 340, font="/VNI-Times")]
    assert lines_of(runs) == ["abc def"]
    assert lines_of([R("O", 72), R("●", 100)]) == []  # nothing but marks: no line
    assert lines_of([R("°", 72, font="/Arial"), R("_", 120, font="/Arial")]) == []


def test_lone_o_is_a_mark_but_o_next_to_text_is_kept():
    # bell mark: stands apart from the words
    assert lines_of([R("O", 72), R("Nam mo", 140)]) == ["Nam mo"]
    # an O right after a word (width 3 chars x 0.5 x 12 = 18 pt) is part of the text
    assert lines_of([R("Nam", 72), R("O", 90)]) == ["NamO"]
    assert lines_of([R("Hello OK", 72)]) == ["Hello OK"]  # "O" inside a run with letters is text


def test_list_bullet_before_ordinary_text_is_kept():
    assert lines_of([R("•", 72), R(" mot hai", 84)]) == ["• mot hai"]
    assert lines_of([R("•", 72, font="/VNI-Helve"), R(" mot hai", 84)]) == ["mot hai"]


def test_symbol_only_line_makes_no_heading_or_section():
    head = L("ABC DEF", 700, x=120)  # a real heading, for contrast
    marks = [R("O", 150, 640, size=20), R("●", 200, 640, size=20), R("OOO", 240, 640, size=20)]
    page = pdf.group_runs([R("Mot dong chu thuong dai dai", 72, 600)] + marks, 600.0, 800.0)
    page.lines.append(head)
    text, _ = convert([page])
    assert text.count("\n# ") == 1 and "OOO" not in text and "\u25cf" not in text


def test_sheet_music_section_warns_but_mantra_and_prose_do_not():
    def body(words):
        return [L(" ".join(words[i:i + 10]), y, x=72) for i, y in zip(range(0, len(words), 10), ys(len(words) // 10))]

    music = ["a", "o", "a", "b", "c", "e", "a", "o", "i", "u"] * 5
    pages = [P(L("KE MOT", 760, x=130, size=14), *body(music))]
    text, warnings = convert(pages)
    assert any("bản nhạc" in w and "KE MOT" in w for w in warnings)
    mantra = ["na", "mo", "ha", "ra", "da", "no", "da", "ra", "da", "ya"] * 5
    pages = [P(L("CHU MOT", 760, x=130, size=14), *body(mantra))]
    assert not any("bản nhạc" in w for w in convert(pages)[1])
    prose = ["Dong chu bat ky", "co du chu", "de doc duoc", "va khong phai nhac"] * 10
    pages = [P(L("VAN XUOI", 760, x=130, size=14), *body(" ".join(prose).split()))]
    assert not any("bản nhạc" in w for w in convert(pages)[1])


@needs_pypdf
def test_page_runs_carry_the_font_name(tmp_path):
    from pypdf import PdfReader

    f = tmp_path / "s.pdf"
    f.write_bytes(sample_pdf())
    runs, _, _ = pdf.page_runs(PdfReader(str(f)).pages[0])
    assert runs and all(r.font.endswith("Helvetica") for r in runs)
