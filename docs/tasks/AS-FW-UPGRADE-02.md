# Task: AS-FW-UPGRADE-02 — Áp quy tắc FW-TOKEN-01 (§10) + FW-GROWTH-01 (F1–F3) từ kit

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Human Lead: HUMAN LEAD
- Execution profile: single-agent
- Orchestrator: claude-code — làm luôn IMPLEMENTER: chép nguyên văn text kit đã merge + vài pointer, giao Codex tốn hơn tự làm; S2 vì đổi project-wide workflow policy
- Authorization mode: task
- Authorization source: HUMAN LEAD yêu cầu 2026-10-19 "upgrade framework của dự án để áp F1–F3 (+ §10)"; kit ntnghia1908/ai-dev-framework#11 (FW-GROWTH-01) và #10 (FW-TOKEN-01) đã merge
- Parallel group: —
- Owned paths: `docs/ai/workflow.md`, `docs/tasks/_template.md`, `.claude/rules/execution.md`, `.claude/agents/implementer.md`, `docs/workflow/current-state.md` (1 dòng pointer), `docs/ai/framework-history.md`, file này
- Dependencies: kit main `7496eac` (merge PR #11)
- Base commit / branch: `3022775` (origin/main) / `chore/fw-upgrade-growth`
- Human Lead approval: APPROVED 2026-10-19 (chat, single-agent)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Workflow của dự án khớp kit tại `7496eac`: có quy tắc tiết kiệm token (FW-TOKEN-01: §4 "Phải giữ nguyên", §5 giới hạn chờ 5 phút + chi phí / task merge, §9 handoff 250k / không resume sau 1 giờ, §10 ngân sách context) và quy tắc chống phình code (FW-GROWTH-01: F2 §4, F1 §5, F3 §7). Task sau (P2 / P3) dùng ngay template mới.

## Scope

- In scope:
  1. `docs/ai/workflow.md`: thay bằng `core/docs/ai/workflow.md` của kit `7496eac`. Diff hiện tại chỉ gồm phần kit thêm (không có sửa riêng của dự án cần giữ) — kiểm lại lúc làm.
  2. `docs/tasks/_template.md`: thêm "Phải giữ nguyên", "Code bị thay / xóa", 3 field Result (AC → test, Diff + / −, Helper mới) như template kit.
  3. `.claude/agents/implementer.md`: 3 dòng pointer của kit (giới hạn chờ §5, tái dùng / xóa §5, READY report §7).
  4. `.claude/rules/execution.md`: giữ mục Codex riêng của dự án; bước 3 (prompt Codex) thêm tái dùng / code bị thay / READY report theo §5 / §7; mục Delegation thêm mẫu delegation prompt của kit (pointer §5 / §7, resume theo §9).
  5. `docs/workflow/current-state.md`: thêm 1 dòng "Ngân sách token của file: xem `docs/ai/workflow.md` §10." (kit template).
  6. `docs/ai/framework-history.md`: một mục ghi upgrade (SHA kit, PR kit, phạm vi).
- Out of scope:
  - F4–F6 (chưa có trong kit). P2 / P3 dọn code: task riêng sau task này.
  - Checker (`scripts/framework-check.mjs`), `framework.config.json`, `frameworkVersion` (kit không nâng version Core).
  - Viết lại task contract cũ theo template mới.
  - `scripts/token-audit.py` (đã có từ FW-token-audit).

## Phải giữ nguyên

- Mục Codex IMPLEMENTER 7 bước trong `.claude/rules/execution.md` (lệnh, quota, sandbox) — chỉ thêm, không rút gọn theo bản kit.
- `model: sonnet` và các dòng hiện có trong `implementer.md`.
- Nội dung vận hành của `current-state.md`.

## Code bị thay / xóa

- Không có (chỉ tài liệu; text workflow cũ được thay bằng bản kit chứa nó).

## Acceptance Criteria

1. `diff docs/ai/workflow.md <kit 7496eac core/docs/ai/workflow.md>` rỗng.
2. `docs/tasks/_template.md` có "## Phải giữ nguyên", "## Code bị thay / xóa", "AC → test, docs/ai/workflow.md §7", "Diff + / −", "Helper mới".
3. `implementer.md` và `execution.md` có pointer `docs/ai/workflow.md` §5 và "AC → test"; mục Codex 7 bước còn đủ.
4. `current-state.md` có pointer §10; framework-history có mục AS-FW-UPGRADE-02.
5. `node scripts/framework-check.mjs` PASS (file này cũng hợp lệ theo template mới).

## Required verification

- `gh api repos/ntnghia1908/ai-dev-framework/contents/core/docs/ai/workflow.md?ref=7496eac -H 'Accept: application/vnd.github.raw' | diff docs/ai/workflow.md -` — AC1.
- `grep -n` các token ở AC2–AC4 trên từng file — AC2–AC4.
- `node scripts/framework-check.mjs` — AC5.
- `git diff --stat origin/main` + `git status --short` — inventory ⊆ Owned paths.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract.

- [ ] Sau 3–5 task (bắt đầu từ P2 / P3), đo lại theo `docs/audit/code-growth-report.md` phụ lục A: tỉ lệ xóa / thêm theo Type, test / AC, bản copy helper mới.

## Result

- Main changes: `workflow.md` = kit `7496eac` (+28 dòng: §4 Phải giữ nguyên / Code bị thay / xóa, §5 giới hạn chờ + chi phí / task + tái dùng, §7 READY report, §9 handoff, §10 ngân sách context); `_template.md` = template kit; pointer §5 / §7 trong `implementer.md` và `execution.md` (bước 3 Codex + mẫu delegation prompt, resume theo §9); pointer §10 trong current-state; mục framework-history.
- Tests:

  | AC | Verification | Kết quả |
  |---|---|---|
  | 1 | `diff docs/ai/workflow.md <kit 7496eac>` | rỗng |
  | 2 | `grep -c` 5 token trong `_template.md` | 5 |
  | 3 | `grep` pointer §5 + "AC → test" trong 2 adapter; đếm 7 bước Codex | có đủ; 7 |
  | 4 | `grep` §10 trong current-state, AS-FW-UPGRADE-02 trong history | có |
  | 5 | `node scripts/framework-check.mjs` | exit 0, 0 FAIL |

- Diff + / − (app, test): app 0 / 0, test 0 / 0; tài liệu +65 / −4 (không kể file này).
- Helper mới (đã tìm, lý do không tái dùng): không có.
- Review: tự review single-agent (diff → AC); inventory `git status` ⊆ Owned paths.
- Important findings / decisions: workflow / template của dự án trước đó trùng kit trước PR #10, nên thay nguyên file không mất sửa riêng. Kit `execution.md` rút mục Codex thành pointer README; dự án giữ 7 bước riêng (Phải giữ nguyên).
- Known limitations: checker chưa bắt buộc mục mới (kit cũng chưa). Hiệu quả F1–F3 đo sau 3–5 task (Manual test checklist).
- PR: #116
