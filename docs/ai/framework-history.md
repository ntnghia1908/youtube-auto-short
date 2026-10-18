# Framework History

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Scope | Lịch sử thay đổi framework (core, adapter, checker) sau adoption |

File này chỉ ghi lịch sử; rule hiện hành nằm ở canonical owner của nó (`docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, adapter, checker).

## Quy ước

- Mỗi thay đổi framework (core, adapter, checker) thêm một entry mới: ngày, thay đổi, lý do, PR/commit.
- Version tăng khi rule trong Framework Core thay đổi, hoặc khi HUMAN LEAD quyết một đợt thay đổi adapter / project policy đủ lớn để đánh version mới (vd v4.2). Thay đổi nhỏ chỉ ở adapter hoặc checker ghi entry dưới version hiện tại, không tăng version.
- Heading version có dạng `## v<Version>`, khớp giá trị `Version` trong metadata của `docs/ai/workflow.md`; `scripts/framework-check.mjs` kiểm tra điều này.

## v4

- Ngày: 2026-09-26
- Thay đổi: adopt Framework v4 từ `ntnghia1908/dang-vu-spring` @ `c5092ce` trong CP0. Chi tiết adopted/adapted/not adopted: `FRAMEWORK_ADOPTION.md`.
  - `CLAUDE.md` rút thành bridge tối giản (`@AGENTS.md`).
  - Checker kiểm task contract S1/S2 (S1 pilot, `docs/tasks/CP0-S1-pilot-task-contract-check.md`).
- Lý do: khởi tạo project greenfield với workflow đã kiểm chứng.
- PR: #1 (merge `0798a67`).

### v4 — CP1: checker kiểm decision record

- Ngày: 2026-09-26
- Thay đổi: `scripts/framework-check.mjs` kiểm metadata `Status` của decision record trong `docs/decisions/`. Chỉ tooling, không đổi version.
- Lý do: CP1 tạo decision record đầu tiên (`docs/decisions/CP1-product-contract.md`).
- PR: #2 (merge `287752e`).

## v4.1

- Ngày: 2026-09-26
- Thay đổi: thêm "Session scope và handoff" (`docs/ai/workflow.md` §9); adapter Claude Code map sang kết thúc session + handoff prompt; thêm file lịch sử này; checker yêu cầu history có entry cho version của workflow.
- Lý do: quyết định HUMAN LEAD 2026-09-26: "Nên xác định scope cho mỗi session chat. Khi đủ scope nên suggest clear và viết prompt ngắn cho session tiếp theo. Việc này nên update vào framework và ghi nhận vào lịch sử phát triển framework."
- Task: `docs/tasks/FW-v4.1-session-scope.md`
- PR: #4 (merge `5edeb1f`).

## v4.2

Đánh version lại (HUMAN LEAD 2026-09-29): đợt FW-implementer-speed thực chất là bản cập nhật của v4.1 (IMPLEMENTER + tối ưu chạy test) nên ghi thành v4.2 thay vì entry phụ dưới v4.1. Framework Core (`docs/ai/workflow.md` §1–§9) không đổi nội dung; chỉ đổi metadata `Version` và quy ước tăng version ở trên.

### v4.2 — FW-implementer-speed: test policy + adapter IMPLEMENTER

- Ngày: 2026-09-29
- Thay đổi: adapter Claude Code (`.claude/agents/implementer.md`) khai `model: sonnet` và hướng dẫn làm việc gọn; project policy "Test policy" (`docs/ai/project-profile.md` §8); dev dependency `pytest-xdist`. Không đổi rule Framework Core; lúc merge ghi dưới v4.1, đánh lại thành v4.2 theo quyết định trên.
- Lý do: đo 22 lần chạy IMPLEMENTER cho thấy suite tuần tự 3 phút 30 giây chạy 10–32 lần mỗi task và subagent kế thừa model đắt của session chính.
- Task: `docs/tasks/FW-implementer-speed.md`
- PR: #31 (merge `6516638`).

### v4.2 — FW-starter-kit: starter kit + checker dùng chung + nhiều IMPLEMENTER

- Ngày: 2026-09-29
- Thay đổi: tách Core khỏi hai đoạn project-specific; checker dùng chung đọc `framework.config.json`; thêm adapter Copilot IMPLEMENTER và field `Implementer` trong `_template.md`. Không đổi rule Core nên không tăng version.
- Lý do: dùng lại framework cho project khác; HUMAN LEAD 2026-09-29.
- Task: `docs/tasks/FW-starter-kit.md`
- PR: #34; kit ntnghia1908/ai-dev-framework#1

## v4.4 — AS-FW-UPGRADE-01: adaptive native dual-agent

- Ngày: 2026-10-18
- Thay đổi: nâng Core lên v4.4 từ kit `ntnghia1908/ai-dev-framework` SHA `aa9688d1b987aae6dc58f7c518f3b6cac7965930` (ADR-001, ADR-002, ADR-003): `workflow.md`, `execution-profiles.md`, `agent-adapter-contract.md`, `adapter-descriptor.schema.json`, `_template.md`, `.claude/rules/execution.md`, adapter descriptor claude-code / copilot / codex; `framework.config.json` bật `codex`, `governance` = `boundary/3`, không có `agents` cố định. Checker = kit v4.4 + `legacyTasks` + sửa mâu thuẫn explicit `task` mode. Chính sách task legacy: `docs/ai/framework-migration-notes.md`.
- Lý do: HUMAN LEAD duyệt 2026-10-18 (task + compatibility option A); mở project bằng Claude Code hoặc Codex.
- Giới hạn: Codex native worker, cross-agent review, handoff, multi-writer chưa chạy thử runtime; write concurrency thực tế = 1; không thêm `.codex/*.toml`.
- Task: `docs/tasks/AS-FW-UPGRADE-01.md`

### v4.4 project amendment — Codex CLI IMPLEMENTER cho Claude ORCHESTRATOR

- Ngày: 2026-10-18
- Thay đổi: thêm Codex CLI (`codex exec`, sandbox `workspace-write`) vào danh sách IMPLEMENTER khi Claude Code là ORCHESTRATOR (`docs/ai/project-profile.md` §7), yêu cầu cài đặt VM (§8), cách gọi trong `.claude/rules/execution.md`. Không đổi Core / adapter descriptor / `framework.config.json` (`codex` đã bật, role `implementer` đã khai).
- Lý do: HUMAN LEAD 2026-10-18 muốn dùng Codex trên máy làm worker để tăng hiệu suất và tiết kiệm token ORCHESTRATOR; sandbox Codex trước đó lỗi do AppArmor userns, HUMAN LEAD đã cài bubblewrap + profile.
- Giới hạn: write concurrency vẫn 1. Pilot thật 2026-10-18 (TC3, TC2 phase C + 3 vòng sửa, review FIX-enhance-cuda-fatal) → phân vai trong project-profile §7; thêm quy tắc quota.
