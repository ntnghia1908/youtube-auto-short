# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Re-plan HUMAN LEAD 2026-09-27 (`AUTO_SHORT_CHECKPOINT_PLAN.md`): CP8 → CP8.1 → CP8.2 → CP8.3, push chung một lượt khi cả chuỗi READY (HUMAN LEAD). CP8.4 upload YouTube: planned, chưa lên lịch.

- CP8 (`docs/tasks/CP8-pipeline.md`): READY.
- CP8.1 (`docs/tasks/CP8.1-dissolve.md`): READY.
- CP8.2 (`docs/tasks/CP8.2-title-override.md`): READY.
- CP8.3 (`docs/tasks/CP8.3-web.md`): phase A + B implement xong, review ORCHESTRATOR; chờ manual test HUMAN LEAD (gate security) trên `http://10.8.102.101:8080`.

Cả chuỗi nằm trên `feature/cp8.3-web` (merge CP8.1/CP8.2 vào nhánh xếp chồng trên CP8).

## Next proposed action

1. HUMAN LEAD thử web từ máy/điện thoại khác (checklist CP8.3).
2. Đạt → CP8.3 READY → push `feature/cp8.3-web`, mở một PR cho cả chuỗi CP8–CP8.3.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
