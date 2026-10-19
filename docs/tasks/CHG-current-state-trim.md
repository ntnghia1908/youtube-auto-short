# Task: CHG-current-state-trim — Rút gọn current-state.md

## Status / Approval

- Status: DRAFT
- Type: DOC
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Orchestrator: claude-code
- Authorization mode: task
- Authorization source: HUMAN LEAD duyệt hướng trong phiên token 2026-10-19; cần duyệt contract trước khi làm
- Parallel group: —
- Owned paths: `docs/workflow/current-state.md`
- Dependencies: none
- Base commit / branch: <điền khi bắt đầu>
- Human Lead approval: pending
- Implementation authorized: NO

## Goal

`current-state.md` (nạp vào mọi phiên, ≈ 4,4k token) chỉ còn operational state hiện hành, mục tiêu ≤ 1,5k token, không mất thông tin không suy ra được từ Git, contract hay decision.

## Scope

- In scope: bỏ các khối "cập nhật <ngày>" cũ chỉ liệt kê PR đã merge (suy ra được từ Git); gộp hạ tầng / cách khởi động lại web thành một mục ngắn; giữ Next proposed action, Open decisions, Blockers.
- Out of scope: đổi quy tắc workflow; chuyển thông tin sang file nạp mỗi phiên khác.

## Implementation approach

- Thông tin vận hành còn cần nhưng ít dùng (đường dẫn backup, cấu hình GPU worker, lịch sử IP) chuyển sang một doc vận hành chỉ đọc khi cần (đề xuất `docs/workflow/ops-notes.md`), current-state chỉ để pointer.

## Acceptance Criteria

1. `current-state.md` ≤ 1,5k token theo `/context`.
2. Mọi fact bị bỏ khỏi current-state hoặc suy ra được từ Git / contract, hoặc có trong doc vận hành.
3. Framework checker PASS.

## Required verification

- `/context` ở phiên mới — AC1.
- Framework checker theo `docs/ai/workflow.md` — AC3.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract.

- [ ] HUMAN LEAD đọc bản rút gọn, xác nhận không thiếu thứ cần cho phiên sau.

## Result

- PR:
