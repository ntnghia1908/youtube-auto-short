# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

CP3 — Transcript Acquisition & Normalization (`docs/tasks/CP3-transcript.md`): READY, PR #5 chờ HUMAN LEAD merge. Framework v4.1 đã merge (PR #4).

## Next proposed action

1. HUMAN LEAD merge PR #5 (CP3).
2. HUMAN LEAD quyết mở CP4 — Shot / Segment Analysis (roadmap §4 CP4); CP4 cần loại phần nhạc intro/outro (CP1 §5).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Mở CP4 hay chưa.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
