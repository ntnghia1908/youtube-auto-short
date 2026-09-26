# Task: CP0-S1 — Framework checker validates task contract metadata

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Base commit / branch: `d04bb13` / `feature/cp0-framework-bootstrap`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26)
- Implementation authorized: YES

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

- Main changes: `scripts/framework-check.mjs` kiểm metadata (`Status`, `Type`, `Change class`, `Owner`, `Execution profile`, `Implementation authorized`) và section bắt buộc của mọi `docs/tasks/*.md` trừ `_template.md`.
- Tests: `node scripts/framework-check.mjs` → exit 0 (2 task contract PASS). Negative test trên bản copy tạm: xóa `Change class`, `Execution profile: triple-agent`, xóa `## Acceptance Criteria` → exit 1 với đúng message; `_template.md` hỏng vẫn exit 0. `git diff --stat` → chỉ checker + contract này.
- Review: ACCEPTED (single-agent review riêng: contract → diff → AC → evidence); không có blocking finding.
- Important findings / decisions: checker chỉ enforce rule đã có ở workflow §4, không tạo rule mới.
- Known limitations: giá trị field phải khớp chính xác (không cho ghi chú sau `Status`); section so khớp theo dòng LF, file CRLF sẽ báo thiếu section.
- PR: https://github.com/ntnghia1908/youtube-auto-short/pull/1 (cùng PR với CP0)
