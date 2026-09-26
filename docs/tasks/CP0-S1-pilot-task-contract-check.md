# Task: CP0-S1 — Framework checker validates task contract metadata

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Base commit / branch: `f1072b7` / `feat/cp0-framework-bootstrap`
- Human Lead approval: pending
- Implementation authorized: NO

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

CP0 S1 low-risk pilot: `node scripts/framework-check.mjs` phát hiện task contract S1/S2 thiếu các field bắt buộc mà `docs/ai/workflow.md` §4 đã quy định.

## Scope

- In scope: `scripts/framework-check.mjs` — kiểm mọi `docs/tasks/*.md` trừ `_template.md`.
- Out of scope: thay đổi rule trong `docs/ai/workflow.md` hoặc template; dependency mới; test framework mới; CP1.

## Authority / key decisions

- `docs/ai/workflow.md` §4: task S1/S2 bắt buộc có `Type`, `Change class`, `Owner`, `Execution profile`, Goal, Scope, Acceptance Criteria, Required verification.
- Checker chỉ enforce rule đã có, không tạo rule mới → không chạm decision gate.
- Node stdlib only (CP0 AC7).

## Implementation approach

- Với mỗi task file: kiểm các dòng metadata `- Status:`, `- Type:`, `- Change class:`, `- Owner:`, `- Execution profile:`, `- Implementation authorized:` và các heading `## Goal`, `## Scope`, `## Acceptance Criteria`, `## Required verification`.
- `Status` phải thuộc `DRAFT | APPROVED | IN_PROGRESS | READY`; `Change class` phải là `S1 | S2`; `Execution profile` phải là `single-agent | dual-agent`.
- Báo `FAIL: <file>: <lý do>` theo format hiện có.

## Acceptance Criteria

1. Checker PASS trên repository hiện tại.
2. Checker FAIL (exit 1) khi task contract thiếu một field/heading bắt buộc hoặc có giá trị ngoài tập cho phép.
3. `_template.md` không bị kiểm.
4. Không thêm dependency; chỉ `scripts/framework-check.mjs` thay đổi (cùng Result của task này).

## Required verification

- `node scripts/framework-check.mjs` trên repo → exit 0 (AC1, AC3).
- Negative test trên bản copy tạm: xóa `- Change class:`, đổi `Execution profile` sang giá trị lạ, xóa `## Acceptance Criteria` → mỗi trường hợp exit 1 với message đúng (AC2).
- `git diff --stat` → chỉ file trong scope (AC4).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract; manual test là điểm danh sau automated verification.

- [ ] Chạy `node scripts/framework-check.mjs` → PASS.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
