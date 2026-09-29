"""Versioned "post" prompt (P3): the AI only adds punctuation and splits paragraphs; it never changes a word.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P3.
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v1"

SYSTEM_PROMPT_V1 = """\
Bạn biên tập lại lời giảng Phật pháp tiếng Việt để đăng thành bài viết. Lời vào là caption tạo tự động: không có \
dấu câu, viết hoa lộn xộn, có thể sai chính tả do nhận dạng giọng nói.

Việc CHỈ được làm:
- Thêm dấu câu: dấu chấm, dấu phẩy, dấu hỏi, dấu chấm than, dấu hai chấm, dấu chấm phẩy, dấu ba chấm (…), ngoặc kép.
- Chia đoạn văn (xuống dòng giữa các đoạn) ở chỗ hợp lý.
- Viết hoa chữ đầu câu và danh từ riêng; viết thường các chữ khác trong câu.

TUYỆT ĐỐI KHÔNG được làm, dù chỉ một chữ:
- Không thêm, không bớt, không đổi, không đảo thứ tự bất kỳ từ nào.
- Không sửa lỗi chính tả hay từ nhận dạng sai, không diễn giải lại, không tóm tắt, không thêm ý.
- Không thêm emoji, hashtag, hay bất kỳ chữ nào không có trong lời vào.

Nếu không chắc câu nên ngắt ở đâu, ngắt câu dài hơn thay vì đoán sai nghĩa; tuyệt đối không đổi từ.

Trả lời đúng JSON {"paragraphs": ["đoạn 1", "đoạn 2", ...]} — nối toàn bộ paragraphs bằng dấu cách phải cho lại \
đúng từng từ của lời vào (chỉ khác dấu câu và hoa/thường)."""

USER_TEMPLATE_V1 = "Lời giảng (chưa có dấu câu):\n{text}"

PROMPTS = {"v1": (SYSTEM_PROMPT_V1, USER_TEMPLATE_V1)}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
    "required": ["paragraphs"],
}


def prompt_texts(version: str) -> tuple[str, str]:
    try:
        return PROMPTS[version]
    except KeyError:
        raise ValueError(f"unknown post prompt_version {version!r} (known: {', '.join(sorted(PROMPTS))})") from None


def system_prompt(version: str) -> str:
    system, _ = prompt_texts(version)
    return system


def prompt_sha256(version: str) -> str:
    system, template = prompt_texts(version)
    return hashlib.sha256((system + "\n\x00\n" + template).encode("utf-8")).hexdigest()


def render_user_prompt(version: str, *, text: str) -> str:
    _, template = prompt_texts(version)
    return template.format(text=text)
