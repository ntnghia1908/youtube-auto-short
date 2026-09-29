"""Render R5: font reading, line breaking and fit (no ffmpeg)."""

import pytest

from auto_short.config import RenderConfig
from auto_short.render import plan
from auto_short.render.stage import font_path
from auto_short.render.text import (
    Font,
    TextError,
    baselines,
    check_glyphs,
    fit_header,
    fit_title,
    wrap_balanced,
    wrap_greedy,
)

CFG = RenderConfig()
GEO = plan.geometry(CFG)
HEADER_INNER = GEO.header_w - 2 * CFG.panel_padding_x * plan.WIDTH
TITLE_INNER = GEO.title_w - 2 * CFG.panel_padding_x * plan.WIDTH
PAD_Y = CFG.panel_padding_y * plan.WIDTH
SIZE_H, SIZE_T = plan.px(CFG.header_font_size), plan.px(CFG.title_font_size)  # 49 / 70 px (CP8.14 V16)
# CP7 reference-image geometry (panels 853 / 875 px wide, header 292 px, 67 / 88 px): the line-breaking rules
# are checked against the reference image with it, independently of the current default layout.
REF_HEADER = dict(size0=67, inner_width=853 - 2 * CFG.panel_padding_x * plan.WIDTH, panel_height=292)
REF_TITLE_INNER = 875 - 2 * CFG.panel_padding_x * plan.WIDTH
VIET = "aăâeêioôơuưyAĂÂEÊIOÔƠUƯY"


@pytest.fixture(scope="module")
def font():
    return Font(font_path(CFG))


def _title(font, text, **kw):
    args = dict(size0=SIZE_T, line_spacing=CFG.line_spacing, inner_width=TITLE_INNER, panel_height=GEO.title_h,
                max_panel_height=GEO.title_max_h, padding_y=PAD_Y, min_font_scale=CFG.min_font_scale)
    return fit_title(font, text, **{**args, **kw})


def _header(font, lines, **kw):
    args = dict(size0=SIZE_H, line_spacing=CFG.line_spacing, inner_width=HEADER_INNER, panel_height=GEO.header_h,
                padding_y=PAD_Y, min_font_scale=CFG.min_font_scale)
    return fit_header(font, lines, **{**args, **kw})


def test_font_metrics_and_vietnamese_coverage(font):
    assert font.family == "Be Vietnam Pro"
    assert (font.units_per_em, font.cap_height, font.x_height) == (1000, 740, 530)
    import unicodedata
    tones = ["", "̀", "́", "̉", "̃", "̣"]
    forms = [unicodedata.normalize("NFC", b + t) for b in VIET for t in tones] + ["đ", "Đ"]
    check_glyphs(font, forms)  # all 134 Vietnamese forms present
    assert font.width_units("ab") == font.width_units("a") + font.width_units("b")
    # decomposed input is measured as NFC
    assert font.width_units(unicodedata.normalize("NFD", "Thập")) == font.width_units("Thập")


def test_missing_glyph_is_an_error(font):
    with pytest.raises(TextError, match="no glyph for '漢'"):
        check_glyphs(font, ["Tâm 漢"])
    with pytest.raises(TextError, match="no glyph"):
        _title(font, "Tâm thiện 🙂 thì")
    with pytest.raises(TextError, match="no glyph"):
        _header(font, ["HT.Tịnh Không ☸"])


def test_header_greedy_like_reference(font):
    fit = _header(font, ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"], **REF_HEADER)
    assert fit.lines == ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo", "Kinh (tập 9)"]
    assert fit.font_size == 67 and fit.panel_height == 292
    assert wrap_greedy(font, "Thập Thiện Nghiệp Đạo Kinh (tập 14)", 67, REF_HEADER["inner_width"]) == \
        ["Thập Thiện Nghiệp Đạo", "Kinh (tập 14)"]


def test_header_default_layout_v16(font):
    """CP8.14: at 49 px the 2nd line wraps to 3 lines that do not fit 184 px; at 48 px it fits on one line."""
    fit = _header(font, ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"])
    assert fit.lines == ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]
    assert (fit.font_size, fit.panel_height) == (48, GEO.header_h) == (48, 184)


def test_header_shrinks_then_fails(font):
    fit = _header(font, ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh Đại Phương Quảng (tập 129)"])
    assert fit.font_size < SIZE_H and len(fit.lines) <= 3
    with pytest.raises(TextError, match="header .* does not fit"):
        _header(font, [" ".join(["Một hai ba bốn năm sáu bảy tám chín mười"] * 5)])


def test_title_balanced_break_like_reference(font):
    assert wrap_balanced(font, "Các bậc thang tu học Phật pháp", 88, REF_TITLE_INNER) == \
        ["Các bậc thang", "tu học Phật pháp"]


def test_title_tie_break_avoids_short_first_line(font):
    # Same longest line (the last) for several splits: the smaller squared shortfall wins.
    lines = wrap_balanced(font, "Tại sao nói tự tính như huyễn như mộng như bèo bọt?", 85, REF_TITLE_INNER)
    widths = [font.width(x, 85) for x in lines]
    assert len(lines) == 3 and max(widths) == widths[2]
    assert lines[0] != "Tại sao nói tự"  # the plain min-max without tie-break picked this short first line


def test_title_short_keeps_reference_panel(font):
    fit = _title(font, "Mỗi suy nghĩ đều là tội lỗi?")
    assert fit.lines == ["Mỗi suy nghĩ", "đều là tội lỗi?"]
    assert (fit.font_size, fit.panel_height) == (SIZE_T, GEO.title_h) == (70, 227)


def test_title_three_lines_grow_panel_first(font):
    """P3: 3 lines at the reference size -> taller panel, same font size. CP8.14 L3: the max panel height is
    exactly the height 3 lines need at that size, so such a title always keeps it."""
    fit = _title(font, "Chân tướng sự thật không thể nói ra hay tưởng tượng")
    assert len(fit.lines) == 3 and fit.font_size == SIZE_T
    need = 3 * SIZE_T * CFG.line_spacing + 2 * PAD_Y
    assert fit.panel_height == pytest.approx(need, abs=1)
    assert GEO.title_h < fit.panel_height == GEO.title_max_h == 297


def test_title_longest_shrinks_only_when_panel_max_is_not_enough(font):
    text = "Vì sao người niệm Phật phải buông bỏ vạn duyên mới được vãng sinh?"
    fit = _title(font, text)
    assert fit.font_size < SIZE_T and fit.panel_height == GEO.title_max_h and len(fit.lines) == 3
    # with more room (larger max panel) the same title keeps a larger size
    roomy = _title(font, text, inner_width=TITLE_INNER * 1.2)
    assert roomy.font_size >= fit.font_size


def test_title_below_min_scale_fails(font):
    with pytest.raises(TextError, match="does not fit"):
        _title(font, " ".join(["Phật pháp"] * 20))
    with pytest.raises(TextError, match="does not fit"):
        _title(font, "Một_từ_rất_dài_không_có_khoảng_trắng_nào_để_ngắt_dòng_được_cả")


def test_widths_leave_room_in_panel(font):
    for text in ("Chân tướng sự thật không thể nói ra hay tưởng tượng", "Hành là gì? Vì sao không ngừng nghỉ"):
        fit = _title(font, text)
        assert all(font.width(x, fit.font_size) <= TITLE_INNER for x in fit.lines)


def test_baselines_centre_cap_block(font):
    b = baselines(2, font=font, size=88, pitch=92.4, panel_height=292)
    cap = 88 * 0.74
    top, bottom = b[0] - cap, b[1]
    assert abs((top + bottom) / 2 - 146) <= 1
    assert b[1] - b[0] in (92, 93)
