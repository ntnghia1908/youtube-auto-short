# Task: FW-v4.1 — Session scope + handoff prompt; framework history

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `287752e` / `feature/framework-session-scope`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2: thay đổi Framework Core (`docs/ai/workflow.md`, tài liệu class B) và tạo project-wide convention.

## Goal

Mỗi session làm việc với agent có scope rõ; khi scope xong (hoặc context đã dài), agent chủ động đề xuất kết thúc session (Claude Code: `/clear`) và viết một prompt ngắn để bắt đầu session tiếp theo. Framework có lịch sử phát triển (framework history) ghi lại mỗi thay đổi framework.

## Scope

- In scope:
  - `docs/ai/workflow.md`: mục mới "Session scope và handoff" (tool-agnostic, không tên tool/model); version metadata 4 → 4.1.
  - `.claude/rules/execution.md`: mapping Claude Code (`/clear`, prompt handoff).
  - `docs/ai/framework-history.md` (mới): lịch sử framework — v4 adoption (CP0, PR #1) và v4.1 (thay đổi này).
  - `AGENTS.md`: thêm dòng pointer tới framework history trong bảng; không chép rule.
  - `FRAMEWORK_ADOPTION.md`: pointer tới framework history cho các thay đổi sau adoption.
  - `scripts/framework-check.mjs`: `docs/ai/framework-history.md` là required file; version trong `workflow.md` phải có entry tương ứng trong history.
- Out of scope:
  - `docs/workflow/current-state.md` (đang được CP2 sửa trên branch khác; đồng bộ sau khi cả hai merge).
  - Thay đổi S0/S1/S2, decision gate, lifecycle hay execution profile.
  - Code pipeline.

## Authority / key decisions

- HUMAN LEAD 2026-09-26: "Nên xác định scope cho mỗi session chat. Khi đủ scope nên suggest clear và viết prompt ngắn cho session tiếp theo. Việc này nên update vào framework và ghi nhận vào lịch sử phát triển framework."
- Canonical owner: rule ở `docs/ai/workflow.md`; cách làm cụ thể theo tool ở adapter; lịch sử ở `docs/ai/framework-history.md`.
- Nội dung rule đề xuất:
  - Đầu session: xác định **session scope** (một checkpoint/task hoặc một phần rõ ràng của nó) từ repository + yêu cầu HUMAN LEAD; nêu scope trong phản hồi đầu.
  - Session kết thúc khi: scope đạt READY/DONE hoặc dừng ở gate chờ HUMAN LEAD; hoặc context đã dài tới mức ảnh hưởng chất lượng.
  - Khi kết thúc: agent đề xuất đóng session và đưa **handoff prompt** ngắn (≤ ~10 dòng): mục tiêu session sau, bootstrap từ repository (không dựa transcript), trạng thái/gate hiện tại, việc đầu tiên cần làm. Handoff prompt không thay repository làm source of truth; state phải nằm trong repo trước khi đề xuất đóng session.
  - Không mở scope mới trong session cũ khi scope hiện tại đã xong; đề xuất session mới thay vì kéo dài.

## Implementation approach

- Viết rule ngắn trong workflow.md; adapter chỉ map sang `/clear`.
- History dạng bảng/đoạn theo version: ngày, thay đổi, lý do, PR/commit.

## Acceptance Criteria

1. `docs/ai/workflow.md` có mục session scope + handoff, tool-agnostic, Version 4.1.
2. `.claude/rules/execution.md` map rule sang Claude Code (`/clear` + handoff prompt) mà không chép rule.
3. `docs/ai/framework-history.md` có entry v4 (adoption, CP0) và v4.1 (thay đổi này, ngày 2026-09-26, lý do).
4. `AGENTS.md` và `FRAMEWORK_ADOPTION.md` chỉ trỏ tới history.
5. `node scripts/framework-check.mjs` PASS; FAIL khi thiếu history hoặc version workflow không có entry trong history.

## Required verification

- `node scripts/framework-check.mjs` → exit 0 (AC5).
- Negative test trên bản copy tạm: xóa history → exit 1; đổi Version workflow sang `9` → exit 1 (AC5).
- `grep -niE "claude|copilot|/clear" docs/ai/workflow.md` → rỗng (AC1 tool-agnostic).
- `git diff --stat main...HEAD` → chỉ file trong scope.
- Diff review theo contract (AC1–AC4).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract; manual test là điểm danh.

- [ ] Đọc mục session scope trong `docs/ai/workflow.md`.
- [ ] Session sau bắt đầu bằng handoff prompt và nêu scope.

## Result

- Main changes: `docs/ai/workflow.md` §9 "Session scope và handoff" (Version 4.1); `.claude/rules/execution.md` mục "Kết thúc session" (`/clear` + handoff prompt); `docs/ai/framework-history.md` (v4, v4 CP1 tooling, v4.1); pointer ở `AGENTS.md`, `FRAMEWORK_ADOPTION.md`; checker yêu cầu history (Status CURRENT) và heading `## v<Version>` khớp workflow. IMPLEMENTER commit `0575ccd`.
- Tests (ORCHESTRATOR chạy lại): `node scripts/framework-check.mjs` → exit 0; bản copy tạm: xóa history → exit 1 `missing required file`; Version `9` → exit 1 `missing entry for workflow Version 9`; `grep -niE "claude|copilot|/clear" docs/ai/workflow.md` → rỗng.
- Review: ACCEPTED (dual-agent). Micro-fix ORCHESTRATOR: metadata `Accepted by` của workflow ghi v4.1.
- Important findings / decisions: `.github/copilot-instructions.md` không cần mapping riêng (đã trỏ workflow). `docs/workflow/current-state.md` đồng bộ sau khi CP2 và branch này cùng merge.
- Known limitations: rule là hành vi của agent, không kiểm tự động được; checker chỉ kiểm cấu trúc.
- PR: chưa; chờ HUMAN LEAD approve integration.
