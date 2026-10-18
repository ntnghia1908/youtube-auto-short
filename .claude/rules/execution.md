# Claude Code — execution adapter

Adapter riêng cho Claude Code. Shared workflow nằm ở `AGENTS.md` và `docs/ai/`.

@../../docs/workflow/current-state.md

## Mapping vai trò

- `dual-agent`, Claude là ORCHESTRATOR (`agents.orchestrator = claude-code` hoặc không bind): main session = ORCHESTRATOR; `.claude/agents/implementer` = IMPLEMENTER.
- `dual-agent`, external Codex là ORCHESTRATOR (`agents.orchestrator = codex`, task ghi `Orchestrator: codex` và `Implementer: claude-code`): Claude main session = IMPLEMENTER do ORCHESTRATOR giao. Main session không tự nhận ORCHESTRATOR, không delegate tiếp sang subagent hay agent khác, không tự mở rộng scope; dừng ở READY report cho Codex review. Không giả định subagent `implementer` đã được đăng ký.
- `single-agent`: main session đóng cả ORCHESTRATOR + IMPLEMENTER; không delegate implementer.
- Không gọi agent/model/AI CLI ngoài execution profile và field `Implementer` của task.

## Entry point

Đọc entry point thực sự tồn tại. Adopted project: `AGENTS.md`, `docs/ai/project-profile.md`, `docs/workflow/current-state.md`, task contract. Starter-kit root không phải adopted project và không có các file trên: dùng `core/`, `templates/`, ADR và task contract. Capabilities trong adapter descriptor không cấp authorization.

## Chọn IMPLEMENTER

Task `dual-agent` do Claude làm ORCHESTRATOR: ORCHESTRATOR chọn IMPLEMENTER theo Danh sách IMPLEMENTER ở `docs/ai/project-profile.md` §7 lúc viết contract và ghi vào field `Implementer`. Gọi adapter tương ứng: subagent `implementer` (Claude Code), hoặc CLI của adapter khác theo README của adapter đó (`adapters/<tool>/README.md` trong kit). Chỉ gọi IMPLEMENTER ghi trong contract.

Codex CLI làm IMPLEMENTER (project-profile §7, §8): chạy nền trong worktree của task

```text
codex exec -C <worktree> -s workspace-write -c model_reasoning_effort='"medium"' -o <tmp>/codex.out - < <delegation prompt>
```

- Prompt theo mẫu delegation (contract, branch / HEAD, Owned paths, không commit / push / PR / gọi agent khác, required verification với đúng env, READY report). Mặc định effort của Codex trên VM là `none`: luôn đặt `medium` (hoặc cao hơn cho task khó).
- Sandbox không cho mạng; tests không cần mạng (conftest chặn dịch vụ thật). Cần mạng thì ORCHESTRATOR tự chạy phần đó.
- Sau khi chạy: ORCHESTRATOR kiểm `git status` / `git log` (không commit lạ, inventory ⊆ Owned paths) rồi review như mọi IMPLEMENTER. Vòng fix: `codex exec resume <session id>` (cùng context) hoặc lần chạy mới kèm finding.

## Delegation

Áp dụng khi Claude là ORCHESTRATOR; khi là IMPLEMENTER cho Codex thì không delegate tiếp. Giao task cho implementer kèm task contract, base commit, `Implementation authorized: YES` và plan ngắn.
Cùng task thì resume đúng context; task mới dùng context mới.

## Session

Bootstrap từ repository. Session mới không dùng transcript chat làm authority.

## Kết thúc session

Rule session scope và handoff: `docs/ai/workflow.md` §9. Trong Claude Code, khi đủ scope thì đề xuất `/clear` và đưa handoff prompt trong một code block để dán vào session mới.
