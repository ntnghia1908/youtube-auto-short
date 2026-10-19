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

Codex CLI làm IMPLEMENTER / reviewer (phân vai: project-profile §7; cài đặt: §8). Mỗi lần giao:

1. Quota: `python3 scripts/codex-usage.py`. Cửa sổ 5 giờ ≥ 85 % hoặc tuần ≥ 80 % → giao subagent `implementer` (Sonnet). Codex hết quota giữa chừng → ORCHESTRATOR kiểm diff dở rồi giao tiếp cho Sonnet, ghi vào Result.
2. Chạy nền trong worktree của task, prompt từ file:

   ```text
   codex exec -C <worktree> -s workspace-write -m gpt-6.1-sol -c model_reasoning_effort='"high"' -o <tmp>/codex.out - < <prompt.md> > <tmp>/codex.log 2>&1
   ```

   Effort: `high` cho module / tính năng mới, `medium` cho fix nhỏ (mặc định của Codex trên VM là `none` — không dùng). Không `danger-full-access`.
3. Prompt (mẫu delegation): contract + mục / plan cụ thể (đường dẫn tuyệt đối), branch / HEAD, Owned paths, bằng chứng (log / số đo thật) nếu là vòng sửa, helper / module có sẵn để tái dùng và mục "Code bị thay / xóa" của contract (`docs/ai/workflow.md` §5), “không commit / push / PR / gọi agent khác / gọi mạng thật”, lệnh verification targeted với đúng env, READY report ngắn có helper mới, AC → test, dòng + / − (`docs/ai/workflow.md` §7).
4. Giới hạn sandbox: không mạng (Ollama / YouTube), **không socket loopback** → test HTTP / web (TestClient + server) và full suite có thể treo trong sandbox. Codex chỉ chạy test targeted không cần socket và phải ghi rõ lệnh nào không chạy được; ORCHESTRATOR chạy test web, full suite và mọi lần chạy thật ngoài sandbox trước READY.
5. Sau khi chạy: đọc `<tmp>/codex.out`, `tokens used` trong log; `git status` / `git diff --stat` (không commit lạ, inventory ⊆ Owned paths); review như mọi IMPLEMENTER; ghi thời gian / tokens / vòng sửa vào Result.
6. Vòng sửa cùng context: `codex exec resume <session id> -c sandbox_mode='"workspace-write"' -c model_reasoning_effort='"high"' -o … - < <finding.md>` (session id ở dòng `session id:` đầu log).
7. Reviewer thứ hai (read-only): `codex exec review --commit <sha> -c sandbox_mode='"read-only"' -m gpt-6.1-sol -c model_reasoning_effort='"high"' -o <tmp>/review.out` (lệnh `review` không nhận `-s`; dùng `--uncommitted` cho diff chưa commit). Finding của reviewer là thông tin để ORCHESTRATOR kiểm, không tự động là blocking.

## Delegation

Áp dụng khi Claude là ORCHESTRATOR; khi là IMPLEMENTER cho Codex thì không delegate tiếp. Giao task cho implementer kèm task contract, base commit, `Implementation authorized: YES` và plan ngắn.
Resume cùng task theo `docs/ai/workflow.md` §9; task mới dùng context mới.

Mẫu delegation prompt:

```text
Contract: <path>; base commit: <SHA>; Implementation authorized: YES.
Plan: <ngắn, trong owned paths>.
Giới hạn chờ lệnh: xem docs/ai/workflow.md §5 (Claude Code subagent: 5 phút).
Tái dùng: <helper / module có sẵn>; code bị thay: <mục Code bị thay / xóa của contract>.
READY report theo docs/ai/workflow.md §5 / §7 (helper mới, AC → test, dòng + / −).
```

## Session

Bootstrap từ repository. Session mới không dùng transcript chat làm authority.

## Kết thúc session

Rule session scope và handoff: `docs/ai/workflow.md` §9. Trong Claude Code, khi đủ scope thì đề xuất `/clear` và đưa handoff prompt trong một code block để dán vào session mới.
