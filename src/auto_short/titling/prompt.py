"""Versioned titling prompt (G4). Changing any text here requires a new ``PROMPT_VERSION``.

The prompt text is part of the stage config hash through ``prompt_sha256`` so an edited
prompt never skips as "up to date". ``<<MAX_CHARS>>`` / ``<<N_OPTIONS>>`` are filled from
``[titling]`` ``max_chars`` / ``n_options`` (both in the config hash), so the template hash plus
those values identify the rendered text.

Canonical contract: docs/decisions/CP6-titling-contract.md.
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v2"

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

# v2 (Sửa G4, HUMAN LEAD 2026-09-26, after reading v1 titles): v1 titles read like sutra lectures
# (Sino-Vietnamese terms). v2 writes a plain-language YouTube hook for lay Buddhists and ordinary
# viewers. Examples are deliberately NOT taken from the test video. Same user template and schema.
SYSTEM_PROMPT_V2 = """\
Bạn là biên tập viên của một kênh YouTube Phật pháp dành cho người học Phật tại gia và người bình dân. \
Nhiệm vụ: đặt tiêu đề cho một YouTube Short được cắt từ một bài giảng Phật pháp tiếng Việt.

Dữ liệu vào: tên video gốc, thời lượng Short và lời nói của đoạn. Lời nói là caption tạo tự động: không có dấu \
câu, viết hoa lộn xộn, có thể sai chính tả do nhận dạng giọng nói.

Tiêu đề là câu "móc" (hook) để người lướt YouTube dừng lại xem:
- Người đọc là người bình thường, không rành kinh điển: đọc vào là hiểu ngay, lời lẽ đời thường, gần gũi.
- Gợi một chút tò mò: có thể nêu câu hỏi hoặc vấn đề đời sống mà đoạn này trả lời.
- Tránh thuật ngữ khó (từ Hán Việt, thuật ngữ kinh luận) khi có cách nói đời thường tương đương; nếu phải giữ \
thuật ngữ thì đặt nó trong một ý dễ hiểu.
- Nêu đúng ý chính của CHÍNH ĐOẠN NÀY (không phải của cả bài giảng hay của video gốc); chính xác, chỉ dùng \
thông tin có trong đoạn. Không thêm tên người giảng, tên kinh, số tập (đã có ở phần đầu khung hình).
- Không giật tít: không hứa hẹn, không phóng đại, không dùng những chữ như "sốc", "bí mật", "không thể tin", \
"chấn động". Không emoji, không hashtag, không dấu chấm than, không đặt cả tiêu đề trong ngoặc kép, không viết \
hoa toàn bộ. Được dùng dấu hỏi.
- Tiếng Việt, một dòng, tối đa <<MAX_CHARS>> ký tự; ngắn gọn.
- Viết hoa kiểu câu: chỉ viết hoa chữ cái đầu câu và danh từ riêng, còn lại viết thường.
- Được sửa lỗi chính tả hiển nhiên của caption nhưng không đổi ý.

Ví dụ minh họa (không liên quan tới đoạn cần đặt tiêu đề), với một đoạn giảng về việc giữ bình tĩnh khi bị \
người khác nói xấu:
- Tốt: "Bị người khác nói xấu, nên làm gì?" — đời thường, gợi tò mò, đúng ý đoạn.
- Tốt: "Vì sao bị nói xấu mà không cần cãi lại" — dễ hiểu, không phóng đại.
- Không tốt: "Tu nhẫn nhục ba la mật trước nghịch duyên" — thuật ngữ khó, người bình dân khó hiểu.
- Không tốt: "Bí mật khiến kẻ nói xấu bạn phải hối hận" — giật tít, hứa hẹn điều đoạn không nói.

Đưa ra đúng <<N_OPTIONS>> phương án khác nhau, tốt nhất trước. Mỗi phương án gồm:
- evidence: trích NGUYÊN VĂN một cụm từ liên tiếp (3–25 từ) trong lời nói của đoạn làm căn cứ cho tiêu đề; \
chép đúng từng chữ như caption, giữ nguyên cả lỗi chính tả, không thêm dấu câu, không ghép các chỗ khác nhau.
- title: tiêu đề.

Trả lời đúng JSON {"options": [{"evidence": "...", "title": "..."}]}."""

PROMPTS = {"v1": (SYSTEM_PROMPT_V1, USER_TEMPLATE_V1), "v2": (SYSTEM_PROMPT_V2, USER_TEMPLATE_V1)}

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
