# Framework History

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Scope | Lịch sử thay đổi framework (core, adapter, checker) sau adoption |

File này chỉ ghi lịch sử; rule hiện hành nằm ở canonical owner của nó (`docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, adapter, checker).

## Quy ước

- Mỗi thay đổi framework (core, adapter, checker) thêm một entry mới: ngày, thay đổi, lý do, PR/commit.
- Version tăng khi rule trong Framework Core thay đổi. Thay đổi chỉ ở adapter hoặc checker ghi entry dưới version hiện tại, không tăng version.
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
- PR: pending.
