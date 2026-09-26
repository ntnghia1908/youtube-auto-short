# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

CP5 — AI Clip Selection (`docs/tasks/CP5-selection.md`): IN_PROGRESS (APPROVED 2026-09-26), branch `feature/cp5-selection`. CP4 đã merge (PR #6, `f0c21d4`).

## Next proposed action

1. IMPLEMENTER: mặc định C2 (`qwen3:30b`, think, v2) + B11 lọc từ nối, đo lại; ORCHESTRATOR review → READY.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
