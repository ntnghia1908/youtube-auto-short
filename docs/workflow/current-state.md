# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành ít dùng (backup, GPU worker, IP, tuning): `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token của file: xem `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-19.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`) chạy `c7c08e1`. Restart: hỏi HUMAN LEAD rồi `~/.local/bin/auto-short-web-restart` (mật khẩu ở `~/.local/share/auto-short/web.env`, từ chối khi làn bận).
- Thư mục dự án chuyển sang `~/projects/` ngày 2026-10-19; backup JSON trước khi chuyển: xem ops-notes.
- `config.toml` (không trong git) `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- CL1 Chinese Learning: HUMAN LEAD bỏ, đã gỡ (#107); quy ước host CL1 C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD cập nhật `tools/enhance_worker/worker.py` trên máy 3090 + 3050 (bản #100: thoát mã 4 khi lỗi CUDA); ORCHESTRATOR kiểm log server sau đó.
2. Manual test HUMAN LEAD trên điện thoại: ghép theo chủ đề (TC2.3) và "Khôi phục nguồn" (CP8.37) trên tập đã dọn; chấm tiêu đề AI (TC2.2).
3. Chất lượng AI TC1 / TC2: synopsis đôi khi là mẩu ngắn, chủ đề có xu hướng gom theo tập; qwen3:30b `think=true` ≈ 1–2 phút / clip.
4. CLEAN-P5 tách `web/app.py` thành router (HUMAN LEAD chọn hướng 2026-10-19): contract DRAFT `docs/tasks/CLEAN-P5-web-routers.md`, chờ APPROVE.
5. Cũ, vẫn mở: CP8.34 tránh tải lại khi token `aborted`; HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- CLEAN-P5 D1–D4 (rule W1 CP8.3 mới, `WebContext`, chia 3 PR, thứ tự route): chờ HUMAN LEAD duyệt.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
