# Adapter Copilot — IMPLEMENTER

> **Kiểm chứng:** Copilot Free, 2026-09-29, pilot task FW-starter-kit phần 2 (dogfood 7 file). Đạt; số đo ở mục "Kết quả pilot". Chưa đo với gói Pro: **khi có Pro, đo lại** và cập nhật tiêu chí trong Danh sách IMPLEMENTER của project. Tool và tên tính năng của Copilot thay đổi nhanh: kiểm lại tài liệu nguồn trước khi dùng.

Adapter thực hiện vai trò IMPLEMENTER của profile `dual-agent` (định nghĩa ở `core/docs/ai/execution-profiles.md`) bằng GitHub Copilot chạy **local**. ORCHESTRATOR (một agent khác, vd Claude Code) vẫn review diff.

## Cài đặt

Copy vào project (giữ đường dẫn):

- `.github/copilot-instructions.md` — pointer về `AGENTS.md`, không định nghĩa rule riêng.
- `.github/agents/implementer.agent.md` — custom agent IMPLEMENTER.

Bật trong `framework.config.json`: thêm `"copilot"` vào `adapters` (checker sẽ yêu cầu hai file trên).

## Sự kiện đã xác minh (tra 2026-09-29)

Nguồn: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/create-custom-agents

- Custom agent là file `.github/agents/<name>.agent.md`.
- Frontmatter: `name` (tùy chọn, mặc định = tên file), `description` (bắt buộc), `tools` (tùy chọn; bỏ = mọi tool), `target` (`vscode` hoặc `github-copilot`), `model`.
- `model` chỉ có hiệu lực ở IDE (VS Code, JetBrains, Eclipse, Xcode). Vì vậy file mẫu **không đặt `model`**; chọn model ở IDE nếu cần.
- Copilot CLI dùng custom agent qua lệnh `/agent`; chế độ non-interactive chọn agent bằng `--agent implementer` (đã xác minh khi pilot).

Nguồn: https://docs.github.com/en/copilot/get-started/plans

- Mọi gói có Copilot CLI; gói Free có giới hạn hạn mức.

Không suy diễn thêm ngoài các điểm trên.

## Cách chạy (hướng local)

1. ORCHESTRATOR tạo worktree / branch cho task và viết task contract (`Implementation authorized: YES`).
2. Mở Copilot trong **worktree của task**: Copilot CLI (`/agent` → chọn `implementer`) hoặc agent mode trong IDE.
3. HUMAN LEAD chuyển delegation prompt (mẫu bên dưới) cho Copilot.
4. Copilot làm việc, chạy required verification, trả READY report. **Không commit / push / tạo PR.**
5. ORCHESTRATOR review diff trên cùng branch (`core/docs/ai/workflow.md` §7) và điều phối fix.

**Không dùng coding agent chạy trên cloud** (giao issue cho Copilot): nó tự tạo branch và draft PR, lệch integration mechanism của workflow (`core/docs/ai/workflow.md` §8; commit / push / PR do HUMAN LEAD kiểm soát).

## Mẫu delegation prompt

```text
Bạn là IMPLEMENTER (agent `implementer`) cho task <ID>.

Task contract (APPROVED): <đường dẫn tới docs/tasks/<ID>.md>
Base commit: <sha>   Branch: <branch>   Worktree: <đường dẫn>
Implementation authorized: YES
Plan ngắn:
1. ...
2. ...

Làm theo AGENTS.md và task contract. Chạy required verification theo Test policy.
Không commit, không push, không tạo PR. Dừng ở READY và trả READY report:
thay đổi chính, verification (lệnh + kết quả), finding ngoài scope, giới hạn.
```

## ORCHESTRATOR gọi non-interactive

Cài: `npm install -g @github/copilot` (Node >= 22). Đăng nhập: `/login` trong CLI, hoặc token có quyền "Copilot Requests" qua biến môi trường `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`.

Lệnh đã chạy thật ở pilot (chạy trong worktree của task; `<...>` là chỗ điền):

```bash
copilot -p "$(cat <delegation-prompt-file>)" --agent implementer --add-dir <thư mục cần đọc thêm> \
  --allow-tool write --allow-tool 'shell(node:*)' --allow-tool 'shell(git status:*)' --allow-tool 'shell(git diff:*)' \
  --allow-tool 'shell(diff:*)' --allow-tool 'shell(cp:*)' --allow-tool 'shell(ls:*)' --allow-tool 'shell(cat:*)' \
  --allow-tool 'shell(grep:*)' --allow-tool 'shell(sort:*)' --allow-tool 'shell(echo:*)' \
  --deny-tool 'shell(git commit)' --deny-tool 'shell(git push)' --deny-tool 'shell(gh)' --deny-tool 'shell(rm)' \
  --output-format json > pilot.jsonl
```

- `--agent implementer` chọn custom agent trong `.github/agents/`.
- `--deny-tool` luôn thắng `--allow-tool` (nguồn: `copilot help permissions`). Deny `git commit`, `git push`, `gh` là cách chặn cứng việc commit / push / tạo PR; không chỉ dựa vào prompt.
- Pilot: 3 lệnh chỉ-đọc bị chặn vì allowlist thiếu (`find`, `cmp`, `sha256sum` / `test`); agent tự đổi cách. Khuyến nghị thêm vào allowlist: `find`, `cmp`, `sha256sum`, `test`, `head`, `tail`, `wc`, cộng lệnh test của project (vd `shell(python:*)`).
- Số đo lấy từ event `result.usage` trong JSONL (`premiumRequests`, `sessionDurationMs`, `codeChanges`).

## Kết quả pilot

Copilot Free, 2026-09-29, task FW-starter-kit phần 2 (dogfood 7 file).

| Chỉ số | Giá trị |
|---|---|
| Copilot CLI | 1.0.89 |
| Model | tự chọn (`gpt-6-luna`) |
| Thời gian | 134 s |
| Premium request | 1 |
| Tool call | 37 (19 view, 17 bash, 1 apply_patch) |
| Verification | tự chạy đúng |
| Blocking finding ở review | 0 |
| Vi phạm boundary | 0 (không commit / push, không sửa file ngoài scope) |
| READY report | đúng 4 mục |

## Checklist pilot

Đã chạy trên một task S1/S2 nhỏ. Mục đánh dấu đạt ở pilot Free 2026-09-29.

- [x] Copilot CLI nhận `implementer` từ `.github/agents/implementer.agent.md` (`--agent implementer`).
- [x] Copilot đọc `AGENTS.md`, project profile, current-state và task contract trước khi sửa.
- [x] Không commit / push / tạo PR; không sửa ngoài scope.
- [x] Chạy required verification và báo kết quả thật.
- [x] READY report đủ 4 mục.
- [x] Số blocking finding ở review không cao bất thường (0).
- [ ] Dừng BLOCKED khi prompt thiếu contract / base / `Implementation authorized: YES` (chưa thử).
- [ ] Đo lại khi có gói Pro (hạn mức premium request, model, thời gian) và cập nhật tiêu chí trong Danh sách IMPLEMENTER.
- [ ] Ghi kết quả pilot vào `docs/ai/framework-history.md` của project dùng adapter.
