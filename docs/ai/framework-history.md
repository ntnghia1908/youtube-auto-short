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
