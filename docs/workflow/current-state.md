# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

CP3 — Transcript Acquisition & Normalization (`docs/tasks/CP3-transcript.md`): READY trên branch local `feature/cp3-transcript` (chưa push), chờ HUMAN LEAD approve push/PR. FW-v4.1: PR #4 chờ HUMAN LEAD merge.

## Next proposed action

1. HUMAN LEAD merge PR #4 (FW-v4.1); sau đó đồng bộ file này với framework v4.1.
2. HUMAN LEAD xác nhận transitive deps của `faster-whisper` (có `pyyaml`) và approve push/PR cho `feature/cp3-transcript`.
3. HUMAN LEAD quyết mở CP4 — Shot / Segment Analysis (roadmap §4 CP4).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Chấp nhận transitive deps của `faster-whisper` (gồm `pyyaml`) hay không.
- Mở CP4 hay chưa.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
