# Adapter Claude Code

Copy `.claude/` vào root project; `CLAUDE.md` (bridge `@AGENTS.md`) nằm ở `templates/`.

- `.claude/rules/execution.md`: mapping vai trò `dual-agent` / `single-agent`, delegation, kết thúc session. Import `docs/workflow/current-state.md`.
- `.claude/agents/implementer.md`: subagent IMPLEMENTER. `model: sonnet` là mặc định của kit; đổi ở frontmatter nếu project cần model khác. Task cần model khác riêng lẻ thì ghi trong task contract và ORCHESTRATOR truyền override lúc delegate.

Bật trong `framework.config.json`: `"adapters": ["claude-code"]`.

## Hai flow dual-agent

| Flow | ORCHESTRATOR | IMPLEMENTER |
|---|---|---|
| Claude ORCHESTRATOR (flow hiện có) | Claude main session | subagent `implementer` hoặc adapter khác ghi ở task |
| External Codex ORCHESTRATOR | Codex (`agents.orchestrator = codex`) | Claude Code Sonnet main session (`Implementer: claude-code`), một writer |

Ở flow thứ hai Codex giao task thủ công (delegation prompt mẫu ở `adapters/codex/README.md`); Claude main session chỉ là IMPLEMENTER: không tự nhận ORCHESTRATOR, không delegate tiếp, không commit / push / PR, dừng ở READY report. Flow này chưa pilot. Ví dụ config adopted project: `"adapters": ["codex", "claude-code"]`, `"agents": { "orchestrator": "codex" }`; Implementer ghi ở task contract. Capabilities trong `adapter.json` không cấp authorization.

Starter-kit root không phải adopted project: không có `AGENTS.md`, `framework.config.json`, project-profile / current-state hay subagent đã đăng ký. Hướng dẫn trên áp dụng sau khi copy `.claude/` vào adopted project.
