"""Versioned "post" prompt (P3, amended ORCHESTRATOR review round 1): the AI is free to punctuate however it
likes; the result is a plain-text reply (no JSON, no response schema) that is then projected deterministically
onto the source words (:mod:`auto_short.post.validate`) so the post can never contain a word the AI did not see.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P3.
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v2"

# v1 (superseded, HUMAN LEAD 2026-09-29 after Q4 BLOCKED at 72%): asked for strict JSON + forbade any rewording,
# validated by exact token equality — too strict in practice (real captions have spacing/word-boundary noise the
# model "corrects", which the old validator rightly rejected as a content change, but drove most posts to `raw`).
# Kept only as a text constant (P3 amendment); the pipeline no longer parses JSON for any prompt_version.
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

# v2 (P3 amendment, ORCHESTRATOR review round 1 / HUMAN LEAD 2026-09-29): short free-form instruction; the reply
# is plain text, projected onto the source tokens afterwards (post/validate.py) so wording never drifts even
# though the model is not asked to preserve it word-for-word itself.
SYSTEM_PROMPT_V2 = """\
Bạn biên tập lại lời giảng Phật pháp tiếng Việt (caption tự động, chưa có dấu câu) để đăng thành bài viết.

Hãy thêm dấu câu phù hợp, chia đoạn văn hợp lý (xuống dòng giữa các đoạn), viết hoa chữ đầu câu. Giữ nguyên đúng \
các từ của lời vào, không thêm/bớt/đổi từ nào, không diễn giải lại, không thêm ý.

Chỉ trả về đoạn văn bản đã có dấu câu (không giải thích, không JSON, không markdown)."""

USER_TEMPLATE_V1 = "Lời giảng (chưa có dấu câu):\n{text}"
USER_TEMPLATE_V2 = USER_TEMPLATE_V1

PROMPTS = {"v1": (SYSTEM_PROMPT_V1, USER_TEMPLATE_V1), "v2": (SYSTEM_PROMPT_V2, USER_TEMPLATE_V2)}


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
