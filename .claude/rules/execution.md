# Claude Code — execution adapter

Adapter riêng cho Claude Code. Shared workflow nằm ở `AGENTS.md` và `docs/ai/`.

@../../docs/workflow/current-state.md

## Mapping vai trò

- `dual-agent`: main session = ORCHESTRATOR; `.claude/agents/implementer` = IMPLEMENTER.
- `single-agent`: main session đóng cả ORCHESTRATOR + IMPLEMENTER; không delegate implementer.
- Không gọi agent/model/AI CLI ngoài execution profile của task.

## Delegation

Giao task cho implementer kèm task contract, base commit, `Implementation authorized: YES` và plan ngắn.
Cùng task thì resume đúng context; task mới dùng context mới.

## Session

Bootstrap từ repository. Session mới không dùng transcript chat làm authority.
