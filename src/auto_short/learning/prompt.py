"""Versioned enrichment prompt of stage ``lesson`` (CL1 C7). Changing any text here requires a new
``PROMPT_VERSION``; the text is in the stage config hash through :func:`prompt_sha256`, so an edited
prompt never skips as "up to date".

The user message of a batch is exactly the JSON array ``[{"id", "zh"}]`` (no timestamps, durations,
media or title); every instruction lives in the system prompt.
"""

from __future__ import annotations

import hashlib
import json

PROMPT_VERSION = "v1"

SYSTEM_PROMPT_V1 = """\
You are a Chinese teacher preparing a listening lesson for Vietnamese learners.

Input: a JSON array of consecutive subtitle lines of one Chinese video, each {"id": ..., "zh": ...}. \
Use the neighbouring lines as context.

For EVERY input line return exactly one item with the same "id":
- "pinyin": Hanyu Pinyin of the whole "zh" text.
  - Tone marks on the vowels (nǐ hǎo), neutral tone unmarked (de, le, ma); use ü where needed (lǜ, nǚ).
  - Syllables of one word are written together, words are separated by one space \
(wǒmen xuéxí Zhōngwén). Proper nouns start with a capital letter.
  - Polyphonic characters: choose the reading that fits this context (了 le/liǎo, 的 de/dí, 还 hái/huán, \
长 cháng/zhǎng, 行 xíng/háng, 得 de/dé/děi, 觉 jué/jiào).
  - For 一 and 不 write the tone actually spoken (yí gè, bú shì, yìqǐ).
  - Latin letters and digits in "zh" stay as they are; Chinese punctuation becomes the matching ASCII \
punctuation (，→ ,  。→ .  ？→ ?  ！→ !).
  - NEVER write a Chinese character in "pinyin".
- "vi": a natural Vietnamese translation of the line in the context of the video (not word by word, \
no explanation, no Pinyin, no Chinese characters).

Do not merge, split, add, drop or reorder lines; copy each "id" exactly.
Answer with JSON only: {"lines": [{"id": ..., "pinyin": ..., "vi": ...}, ...]}."""

PROMPTS = {"v1": SYSTEM_PROMPT_V1}

# Property order is the generation order: id, then pinyin, then the meaning.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "pinyin": {"type": "string"},
                    "vi": {"type": "string"},
                },
                "required": ["id", "pinyin", "vi"],
            },
        },
    },
    "required": ["lines"],
}


def prompt_texts(version: str) -> str:
    """The system prompt of ``version``; ``ValueError`` for an unknown version."""
    try:
        return PROMPTS[version]
    except KeyError:
        raise ValueError(f"unknown prompt_version {version!r} (known: {', '.join(sorted(PROMPTS))})") from None


def prompt_sha256(version: str) -> str:
    """sha256 of the system prompt and the output schema of ``version``."""
    text = prompt_texts(version) + "\n\x00\n" + json.dumps(OUTPUT_SCHEMA, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def batch_payload(lines: list[dict]) -> str:
    """User message of one batch: exactly ``[{"id", "zh"}]``."""
    return json.dumps([{"id": ln["id"], "zh": ln["zh"]} for ln in lines], ensure_ascii=False)


def messages(version: str, lines: list[dict]) -> list[dict]:
    return [{"role": "system", "content": prompt_texts(version)},
            {"role": "user", "content": batch_payload(lines)}]
