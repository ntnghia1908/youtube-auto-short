"""Versioned selection prompt (B3). Changing any text here requires a new ``PROMPT_VERSION``.

The prompt text is part of the stage config hash through ``prompt_sha256`` so an edited
prompt never skips as "up to date".
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v1"

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

PROMPTS = {"v1": (SYSTEM_PROMPT_V1, USER_TEMPLATE_V1)}

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


def render_user_prompt(version: str, *, title: str, window_id: str, units: list[dict],
                       durations: dict[str, float]) -> str:
    _, template = prompt_texts(version)
    lines = []
    for i, u in enumerate(units):
        before = break_label(u["break_before"], edge="đầu")
        if i == 0 and u["break_before"]["kind"] == "silence":
            before += " (đầu danh sách)"
        lines.append(f"{u['id']} | {durations[u['id']]:.1f} | {before} | {u['text']}")
    return template.format(
        title=title or "(không rõ)", window_id=window_id, n_units=len(units),
        start=f"{units[0]['start']:.1f}", end=f"{units[-1]['end']:.1f}",
        before=break_label(units[0]["break_before"], edge="đầu"),
        after=break_label(units[-1]["break_after"], edge="cuối"),
        lines="\n".join(lines))
