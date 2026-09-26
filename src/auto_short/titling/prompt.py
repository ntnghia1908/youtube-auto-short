"""Versioned titling prompt (G4). Changing any text here requires a new ``PROMPT_VERSION``.

The prompt text is part of the stage config hash through ``prompt_sha256`` so an edited
prompt never skips as "up to date". ``<<MAX_CHARS>>`` / ``<<N_OPTIONS>>`` are filled from
``[titling]`` ``max_chars`` / ``n_options`` (both in the config hash), so the template hash plus
those values identify the rendered text.

Canonical contract: docs/decisions/CP6-titling-contract.md.
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v1"

MAX_CHARS_PLACEHOLDER = "<<MAX_CHARS>>"
N_OPTIONS_PLACEHOLDER = "<<N_OPTIONS>>"

SYSTEM_PROMPT_V1 = """\
Bạn là biên tập viên của một kênh YouTube Phật pháp. Nhiệm vụ: đặt tiêu đề cho một YouTube Short được cắt \
từ một bài giảng Phật pháp tiếng Việt.

Dữ liệu vào: tên video gốc, thời lượng Short và lời nói của đoạn. Lời nói là caption tạo tự động: không có dấu \
câu, viết hoa lộn xộn, có thể sai chính tả do nhận dạng giọng nói.

Yêu cầu với tiêu đề:
- Nêu đúng ý chính của CHÍNH ĐOẠN NÀY (không phải của cả bài giảng hay của video gốc).
- Tiếng Việt, một dòng, tối đa <<MAX_CHARS>> ký tự; ngắn gọn, dễ hiểu.
- Viết hoa chữ cái đầu câu và danh từ riêng, còn lại viết thường, ví dụ: "Các bậc thang tu học Phật pháp".
- Chỉ dùng thông tin có trong đoạn. Không thêm tên người giảng, tên kinh, số tập (đã có ở phần đầu khung hình).
- Không emoji, không hashtag, không dấu chấm than, không đặt cả tiêu đề trong ngoặc kép, không viết hoa toàn \
bộ, không giật tít, không phóng đại.
- Được sửa lỗi chính tả hiển nhiên của caption (ví dụ thuật ngữ Phật học bị nhận dạng sai) nhưng không đổi ý.

Đưa ra đúng <<N_OPTIONS>> phương án khác nhau, tốt nhất trước. Mỗi phương án gồm:
- evidence: trích NGUYÊN VĂN một cụm từ liên tiếp (3–25 từ) trong lời nói của đoạn làm căn cứ cho tiêu đề; \
chép đúng từng chữ như caption, giữ nguyên cả lỗi chính tả, không thêm dấu câu.
- title: tiêu đề.

Trả lời đúng JSON {"options": [{"evidence": "...", "title": "..."}]}."""

USER_TEMPLATE_V1 = """\
Video: {title}
Thời lượng Short: {duration} giây

Lời nói của đoạn:
{text}"""

PROMPTS = {"v1": (SYSTEM_PROMPT_V1, USER_TEMPLATE_V1)}

# Property order is the generation order: evidence (the grounding quote) before the title.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["evidence", "title"],
            },
        },
    },
    "required": ["options"],
}


def prompt_texts(version: str) -> tuple[str, str]:
    try:
        return PROMPTS[version]
    except KeyError:
        raise ValueError(f"unknown prompt_version {version!r} (known: {', '.join(sorted(PROMPTS))})") from None


def system_prompt(version: str, *, max_chars: int, n_options: int) -> str:
    """System prompt text as sent (placeholders filled)."""
    system, _ = prompt_texts(version)
    return system.replace(MAX_CHARS_PLACEHOLDER, str(max_chars)).replace(N_OPTIONS_PLACEHOLDER, str(n_options))


def prompt_sha256(version: str) -> str:
    system, template = prompt_texts(version)
    return hashlib.sha256((system + "\n\x00\n" + template).encode("utf-8")).hexdigest()


def render_user_prompt(version: str, *, title: str, duration: float, text: str) -> str:
    _, template = prompt_texts(version)
    return template.format(title=title or "(không rõ)", duration=f"{duration:.1f}", text=text)
