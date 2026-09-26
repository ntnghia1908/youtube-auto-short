# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

CP5 — AI Clip Selection (`docs/tasks/CP5-selection.md`): IN_PROGRESS (APPROVED 2026-09-26), branch `feature/cp5-selection`. CP4 đã merge (PR #6, `f0c21d4`).

## Next proposed action

1. HUMAN LEAD nghe mẫu v1/v2 (scratchpad session, đã gửi), chốt model + `think` (P1) và quyết lọc từ nối câu đầu (CP5 hay CP9).
2. ORCHESTRATOR cập nhật config mặc định, decision record CP5 → ACCEPTED, task → READY.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- CP5 P1 (`think`) và model — chốt sau khi nghe mẫu.
- CP5: bộ lọc deterministic loại candidate mở đầu bằng từ nối (đề xuất sau đo v2) — decision gate.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
