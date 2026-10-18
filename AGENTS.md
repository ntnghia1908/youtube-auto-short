# AGENTS.md

Entry point cho mọi agent làm việc trong repository này.

| Cần biết | Ở đâu |
|---|---|
| Quy trình S0/S1/S2, decision gate, lifecycle, review, integration | `docs/ai/workflow.md` |
| Vai trò HUMAN LEAD / ORCHESTRATOR / IMPLEMENTER | `docs/ai/execution-profiles.md` |
| Project này là gì, authority, module, policy, integration | `docs/ai/project-profile.md` |
| Focus, blocker, open decision, next action | `docs/workflow/current-state.md` |
| Task contract S1/S2 | `docs/tasks/_template.md` |
| Hợp đồng adapter / agent descriptor | `docs/ai/agent-adapter-contract.md` |
| Chính sách validate task legacy (v4.2) và migration | `docs/ai/framework-migration-notes.md` |
| Lịch sử thay đổi framework sau adoption | `docs/ai/framework-history.md` |

## Bootstrap

Đầu mỗi session/task, đọc theo thứ tự:

1. file này;
2. `docs/ai/project-profile.md`;
3. `docs/workflow/current-state.md`;
4. approved task contract, nếu có;
5. `AGENTS.md` gần nhất của subtree sắp sửa;
6. authority, source và tests liên quan.

Không preload toàn bộ tài liệu. Session mới bootstrap từ repository, không dựa vào transcript chat.

## Native dual-agent

Claude Code hoặc Codex đều có thể bootstrap từ file này; CLI đang mở chỉ đóng ORCHESTRATOR và giao cho subagent native của chính nó khi adapter được bật, task cho phép và không có binding cố định mâu thuẫn. Chi tiết: `docs/ai/project-profile.md` §7.

## Invariants

- Repository là source of truth; chat/session không thay thế authority, task contract hoặc source/tests.
- Tuân thứ tự authority trong `docs/ai/project-profile.md`.
- File lịch sử không được dùng làm authority hiện hành.
- Không mô tả thành phần mới chỉ được lên kế hoạch như đã implemented.
- Chỉ làm những gì authority và task contract đã duyệt; không âm thầm mở rộng scope.
- Không thay đổi architecture, dependency, security model, public API contract hoặc project-wide policy một cách âm thầm.
- Một normative rule chỉ có một canonical owner; nơi khác chỉ pointer tới rule.
- Không tuyên bố PASS cho verification chưa chạy thành công trong môi trường hiện tại.
- Không sửa test để che lỗi.

## Current project boundary

Project này đang ở giai đoạn bootstrap. Các module xử lý video/AI chỉ là boundary được định nghĩa trong Project Profile; implementation phải đi qua task contract và decision gate tương ứng.
