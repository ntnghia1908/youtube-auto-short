"""Versioned selection prompt (B3). Changing any text here requires a new ``PROMPT_VERSION``.

The prompt text is part of the stage config hash through ``prompt_sha256`` so an edited
prompt never skips as "up to date".
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v3"

SYSTEM_PROMPT_V1 = """\
Bạn là biên tập viên video. Nhiệm vụ: đọc bản ghi lời (caption) của một đoạn bài giảng tiếng Việt và \
đề xuất các đoạn trích có thể đăng thành YouTube Shorts ĐỘC LẬP.

Dữ liệu vào là danh sách "unit" liên tiếp theo thời gian. Mỗi dòng: id | thời lượng (giây, đã rút khoảng lặng) | \
ranh giới trước unit | lời nói. Một đề xuất là dãy unit liên tiếp từ first_unit đến last_unit (tính cả hai đầu).

Ràng buộc:
- Chỉ dùng id unit có trong danh sách; first_unit đứng trước hoặc trùng last_unit.
- Thời lượng Short = tổng thời lượng các unit + khoảng 1 giây cho mỗi ranh giới giữa hai unit liên tiếp. \
Bắt buộc 30–180 giây; lý tưởng 60–90 giây.
- QUAN TRỌNG NHẤT: mỗi đoạn phải trình bày TRỌN MỘT Ý.
  - Câu đầu tự đứng được: không bắt đầu giữa câu, không mở đầu bằng từ nối hay từ chỉ ngược về câu trước \
(ví dụ "cho nên", "vì vậy", "thế nên", "do đó", "và", "nhưng", "cái này", "điều đó", "như vậy") khiến người \
xem thiếu ngữ cảnh.
  - Câu cuối kết thúc ý: không dừng giữa câu, không bỏ dở lập luận hay ví dụ.
  - Thà không đề xuất còn hơn đề xuất đoạn cụt ý.
- Caption tạo tự động: không có dấu câu, có thể sai chính tả; tự suy ra ranh giới câu theo nghĩa. \
Đầu và cuối danh sách có thể rơi giữa một ý.
- Các đề xuất được phép chồng lấn nhau; hệ thống sẽ tự chọn. Tối đa 12 đề xuất, ưu tiên đoạn tốt nhất.

Mỗi đề xuất gồm:
- first_unit, last_unit: id unit đầu và cuối.
- topic: chủ đề ngắn (tối đa 10 từ).
- reason: 1–2 câu ngắn tiếng Việt, vì sao đoạn này hay và trọn ý (hoặc thiếu gì).
- start_complete: true nếu câu đầu tự đứng được; end_complete: true nếu câu cuối kết thúc ý. Đánh giá trung thực.
- score: số nguyên 1–10, giá trị làm một Short độc lập (ý rõ ràng, có ích hoặc hấp dẫn, người xem không cần \
ngữ cảnh trước đó).

Trả lời đúng JSON {"clips": [...]}. Không có đoạn phù hợp thì trả {"clips": []}."""

USER_TEMPLATE_V1 = """\
Video: {title}
Đoạn {window_id}: {n_units} unit, {start}–{end} s trong video gốc. Trước đoạn: {before}. Sau đoạn: {after}.

Danh sách unit (id | thời lượng s | ranh giới trước | lời nói):
{lines}"""

# v2 (HUMAN LEAD 2026-09-26, after measuring v1): cumulative Short time per unit so the model can
# check 30-180 s itself; stricter guidance on judging the first sentence.
SYSTEM_PROMPT_V2 = """\
Bạn là biên tập viên video. Nhiệm vụ: đọc bản ghi lời (caption) của một đoạn bài giảng tiếng Việt và \
đề xuất các đoạn trích có thể đăng thành YouTube Shorts ĐỘC LẬP.

Dữ liệu vào là danh sách "unit" liên tiếp theo thời gian. Mỗi dòng:
id | từ X | đến Y | ranh giới trước unit | lời nói
X, Y là mốc thời gian (giây) trên đồng hồ Short tính từ đầu danh sách, đã rút khoảng lặng. Một đề xuất là dãy unit \
liên tiếp từ first_unit đến last_unit (tính cả hai đầu).

CÁCH TÍNH THỜI LƯỢNG: thời lượng đoạn = "đến" của last_unit − "từ" của first_unit.
Ví dụ: first_unit có "từ 40.2", last_unit có "đến 118.9" → thời lượng 78.7 giây.
Luôn tính thời lượng như vậy TRƯỚC khi đề xuất.

Ràng buộc:
- Chỉ dùng id unit có trong danh sách; first_unit đứng trước hoặc trùng last_unit.
- Thời lượng bắt buộc 30–180 giây; lý tưởng 60–90 giây. Đoạn dưới 30 giây hoặc trên 180 giây bị loại bỏ. \
Một unit thường quá ngắn: hãy nối nhiều unit liên tiếp cho tới khi trọn ý và đủ thời lượng.
- QUAN TRỌNG NHẤT: mỗi đoạn phải trình bày TRỌN MỘT Ý.
  - Câu đầu tự đứng được: người xem chưa nghe gì trước đó vẫn hiểu. Nếu lời nói của first_unit mở đầu bằng từ \
nối hoặc từ chỉ ngược về câu trước — ví dụ "cho nên", "vì vậy", "thế nên", "thế là", "do đó", "còn", "và", \
"nhưng", "mà", "rồi", "thì", "cái này", "điều đó", "việc này", "như vậy", "ở đây" — hoặc bắt đầu giữa câu, \
thì start_complete PHẢI là false. Khi đó hãy chọn first_unit khác (sớm hơn, nơi ý bắt đầu thật sự).
  - Câu cuối kết thúc ý: không dừng giữa câu, không bỏ dở lập luận hay ví dụ; nếu last_unit dừng giữa câu \
thì end_complete PHẢI là false.
  - Thà không đề xuất còn hơn đề xuất đoạn cụt ý.
- Caption tạo tự động: không có dấu câu, có thể sai chính tả; tự suy ra ranh giới câu theo nghĩa. \
Đầu và cuối danh sách có thể rơi giữa một ý.
- Các đề xuất được phép chồng lấn nhau; hệ thống sẽ tự chọn. Tối đa 12 đề xuất, ưu tiên đoạn tốt nhất.

Mỗi đề xuất gồm:
- first_unit, last_unit: id unit đầu và cuối.
- topic: chủ đề ngắn bằng tiếng Việt (tối đa 10 từ).
- reason: 1–2 câu ngắn tiếng Việt: thời lượng đã tính, vì sao đoạn này hay và trọn ý (hoặc thiếu gì).
- start_complete: true chỉ khi câu đầu tự đứng được theo quy tắc trên; end_complete: true chỉ khi câu cuối kết \
thúc ý. Đánh giá trung thực, nghiêm khắc.
- score: số nguyên 1–10, giá trị làm một Short độc lập (ý rõ ràng, có ích hoặc hấp dẫn, người xem không cần \
ngữ cảnh trước đó).

Trả lời đúng JSON {"clips": [...]}. Không có đoạn phù hợp thì trả {"clips": []}."""

USER_TEMPLATE_V2 = """\
Video: {title}
Đoạn {window_id}: {n_units} unit, {start}–{end} s trong video gốc. Trước đoạn: {before}. Sau đoạn: {after}.

Danh sách unit (id | từ X | đến Y | ranh giới trước | lời nói); thời lượng đoạn = đến(last_unit) − từ(first_unit):
{lines}"""

# v3 (HUMAN LEAD 2026-09-26, B11 head cut): leading pure connectors are cut by code; the model
# judges the first sentence without them. <<HEAD_CUT_WORDS>> is filled from [selection] head_cut_words
# (part of the config hash), so the template hash plus that list identify the rendered text.
HEAD_CUT_PLACEHOLDER = "<<HEAD_CUT_WORDS>>"

SYSTEM_PROMPT_V3 = """\
Bạn là biên tập viên video. Nhiệm vụ: đọc bản ghi lời (caption) của một đoạn bài giảng tiếng Việt và \
đề xuất các đoạn trích có thể đăng thành YouTube Shorts ĐỘC LẬP.

Dữ liệu vào là danh sách "unit" liên tiếp theo thời gian. Mỗi dòng:
id | từ X | đến Y | ranh giới trước unit | lời nói
X, Y là mốc thời gian (giây) trên đồng hồ Short tính từ đầu danh sách, đã rút khoảng lặng. Một đề xuất là dãy unit \
liên tiếp từ first_unit đến last_unit (tính cả hai đầu).

CÁCH TÍNH THỜI LƯỢNG: thời lượng đoạn = "đến" của last_unit − "từ" của first_unit.
Ví dụ: first_unit có "từ 40.2", last_unit có "đến 118.9" → thời lượng 78.7 giây.
Luôn tính thời lượng như vậy TRƯỚC khi đề xuất.

TỰ ĐỘNG CẮT TỪ NỐI Ở ĐẦU: nếu lời nói của first_unit mở đầu bằng từ nối thuần — <<HEAD_CUT_WORDS>> — (kể cả \
nhiều từ nối liên tiếp như "thế là còn"), hệ thống sẽ tự cắt bỏ các từ đó khỏi đầu Short. Vì vậy hãy đánh giá \
câu đầu như thể các từ nối đó đã bị bỏ; KHÔNG cần tránh first_unit chỉ vì nó mở đầu bằng các từ nối này.

Ràng buộc:
- Chỉ dùng id unit có trong danh sách; first_unit đứng trước hoặc trùng last_unit.
- Thời lượng bắt buộc 30–180 giây; lý tưởng 60–90 giây. Đoạn dưới 30 giây hoặc trên 180 giây bị loại bỏ. \
Một unit thường quá ngắn: hãy nối nhiều unit liên tiếp cho tới khi trọn ý và đủ thời lượng.
- QUAN TRỌNG NHẤT: mỗi đoạn phải trình bày TRỌN MỘT Ý.
  - Câu đầu (sau khi bỏ từ nối thuần ở trên) phải tự đứng được: người xem chưa nghe gì trước đó vẫn hiểu. \
Nếu câu đầu bắt đầu giữa câu, hoặc phụ thuộc vào điều vừa nói trước đó (ví dụ chỉ ngược bằng "cái này", \
"điều đó", "như vậy"… mà không rõ chỉ cái gì), thì start_complete là false; khi đó hãy chọn first_unit khác \
(sớm hơn, nơi ý bắt đầu thật sự).
  - Câu cuối kết thúc ý: không dừng giữa câu, không bỏ dở lập luận hay ví dụ; nếu last_unit dừng giữa câu \
thì end_complete là false.
  - Thà không đề xuất còn hơn đề xuất đoạn cụt ý.
- Caption tạo tự động: không có dấu câu, có thể sai chính tả; tự suy ra ranh giới câu theo nghĩa. \
Đầu và cuối danh sách có thể rơi giữa một ý.
- Các đề xuất được phép chồng lấn nhau; hệ thống sẽ tự chọn. Tối đa 12 đề xuất, ưu tiên đoạn tốt nhất.

Mỗi đề xuất gồm:
- first_unit, last_unit: id unit đầu và cuối.
- topic: chủ đề ngắn bằng tiếng Việt (tối đa 10 từ).
- reason: 1–2 câu ngắn tiếng Việt: thời lượng đã tính, vì sao đoạn này hay và trọn ý (hoặc thiếu gì).
- start_complete: true khi câu đầu (sau khi bỏ từ nối thuần) tự đứng được; end_complete: true khi câu cuối kết \
thúc ý. Đánh giá trung thực, nghiêm khắc.
- score: số nguyên 1–10, giá trị làm một Short độc lập (ý rõ ràng, có ích hoặc hấp dẫn, người xem không cần \
ngữ cảnh trước đó).

Trả lời đúng JSON {"clips": [...]}. Không có đoạn phù hợp thì trả {"clips": []}."""

PROMPTS = {"v1": (SYSTEM_PROMPT_V1, USER_TEMPLATE_V1), "v2": (SYSTEM_PROMPT_V2, USER_TEMPLATE_V2),
           "v3": (SYSTEM_PROMPT_V3, USER_TEMPLATE_V2)}

# Property order is the generation order: judge (topic/reason/flags) before the score.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_unit": {"type": "string"},
                    "last_unit": {"type": "string"},
                    "topic": {"type": "string"},
                    "reason": {"type": "string"},
                    "start_complete": {"type": "boolean"},
                    "end_complete": {"type": "boolean"},
                    "score": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["first_unit", "last_unit", "topic", "reason", "start_complete", "end_complete",
                             "score"],
            },
        },
    },
    "required": ["clips"],
}

def prompt_texts(version: str) -> tuple[str, str]:
    try:
        return PROMPTS[version]
    except KeyError:
        raise ValueError(f"unknown prompt_version {version!r} (known: {', '.join(sorted(PROMPTS))})") from None


def system_prompt(version: str, head_cut_words: tuple[str, ...] | list[str] = ()) -> str:
    """System prompt text as sent; v3 lists the head-cut connectors (B11)."""
    system, _ = prompt_texts(version)
    if HEAD_CUT_PLACEHOLDER in system:
        listed = ", ".join(f'"{w}"' for w in head_cut_words) if head_cut_words else "(không có)"
        system = system.replace(HEAD_CUT_PLACEHOLDER, listed)
    return system


def prompt_sha256(version: str) -> str:
    system, template = prompt_texts(version)
    return hashlib.sha256((system + "\n\x00\n" + template).encode("utf-8")).hexdigest()


def break_label(brk: dict, *, edge: str) -> str:
    """Human-readable boundary for the prompt. ``edge`` names a content edge ("đầu"/"cuối")."""
    kind = brk["kind"]
    if kind == "silence":
        return f"lặng {brk['seconds']:.1f} s"
    if kind == "hard_break":
        return "ngắt cứng (nhạc/nhãn hoặc lặng dài" + (f" {brk['seconds']:.1f} s)" if brk.get("seconds") else ")")
    return f"{edge} nội dung"


def cumulative_marks(units: list[dict], durations: dict[str, float], max_pause: float,
                     pad: float) -> list[tuple[float, float]]:
    """(from, to) Short clock per unit, relative to the window start, such that
    ``to[b] - from[a]`` equals ``logic.estimate_seconds(units[a..b])``: unit durations after
    trimming + boundary silences shortened to ``max_pause`` + ``2 * pad``."""
    marks, t = [], 0.0
    for i, u in enumerate(units):
        start = t
        end = t + durations[u["id"]] + 2 * pad
        marks.append((start, end))
        t += durations[u["id"]] + (min(u["break_after"]["seconds"] or 0.0, max_pause) if i < len(units) - 1 else 0)
    return marks


def render_user_prompt(version: str, *, title: str, window_id: str, units: list[dict],
                       durations: dict[str, float], max_pause: float = 1.0, pad: float = 0.3) -> str:
    _, template = prompt_texts(version)
    marks = cumulative_marks(units, durations, max_pause, pad) if version != "v1" else None
    lines = []
    for i, u in enumerate(units):
        before = break_label(u["break_before"], edge="đầu")
        if i == 0 and u["break_before"]["kind"] == "silence":
            before += " (đầu danh sách)"
        if marks is None:  # v1: id | duration | boundary | text
            lines.append(f"{u['id']} | {durations[u['id']]:.1f} | {before} | {u['text']}")
        else:
            lines.append(f"{u['id']} | từ {marks[i][0]:.1f} | đến {marks[i][1]:.1f} | {before} | {u['text']}")
    return template.format(
        title=title or "(không rõ)", window_id=window_id, n_units=len(units),
        start=f"{units[0]['start']:.1f}", end=f"{units[-1]['end']:.1f}",
        before=break_label(units[0]["break_before"], edge="đầu"),
        after=break_label(units[-1]["break_after"], edge="cuối"),
        lines="\n".join(lines))
