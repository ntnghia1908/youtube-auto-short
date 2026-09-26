# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

CP0 — Framework v4 adoption + greenfield project bootstrap.

## Next proposed action

1. Verify CP0 structure and checker.
2. Human Lead review CP0 diff/commit.
3. Integrate CP0 into `main`.
4. Sau CP0, tạo task/decision cho CP1 — Product Contract & Architecture Baseline (S2).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Execution profile mặc định cho feature development: chưa khóa; từng task phải ghi profile.
- Runtime stack/model versions: chưa khóa.
- Exact short-selection policy: chưa khóa.
- Exact yellow-panel template dimensions/typography: chưa khóa.
- Canonical roadmap: `main` có `AUTO_SHORT_CHECKPOINT_PLAN.md` (CP0–CP12), branch CP0 có `docs/roadmap/checkpoint-plan.md` (CP0–CP10); CP0/CP1 khớp, CP2+ khác nhau. Cần HUMAN LEAD chọn một canonical owner trước khi integrate CP0.

## Blockers

- CP0 S1 pilot `docs/tasks/CP0-S1-pilot-task-contract-check.md` ở DRAFT, chờ HUMAN LEAD `APPROVE TASK`.
- Branch `feat/cp0-framework-bootstrap` (base `39d3cf3`) đã diverge khỏi `main` (`46e8d55`); cách integrate chờ HUMAN LEAD.
