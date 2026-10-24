# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành ít dùng (backup, GPU worker, IP, tuning): `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token của file: xem `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-24.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`) chạy main `1ae8958` (CP8.38 #128; process khởi động trên `9033cb5`, code giống main). Restart: hỏi HUMAN LEAD rồi `~/.local/bin/auto-short-web-restart` (mật khẩu ở `~/.local/share/auto-short/web.env`, từ chối khi làn bận).
- Thư mục dự án chuyển sang `~/projects/` ngày 2026-10-19; backup JSON trước khi chuyển: xem ops-notes.
- `config.toml` (không trong git) `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- 2026-10-24: worker #100 đã chép lên 3090 + 3050 (HUMAN LEAD xác nhận; log server: cả hai nhận việc, không lỗi CUDA — `__version__` vẫn "3" nên server không phân biệt bản). CP8.38 phần nhìn: HUMAN LEAD bỏ qua manual test (API đã PASS 12/12).
- CL1 Chinese Learning: HUMAN LEAD bỏ, đã gỡ (#107); quy ước host CL1 C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD đăng 13 bài tập 10 Thập Thiện `W2d-xS4ttTw` (xử lý lại 2026-10-24). Manual test cũ chưa làm: FIX-dl-abort-grace (hoãn, xem `docs/tasks/FIX-dl-abort-grace.md`); smoke router CLEAN-P5 (checklist P5.2 / P5.3 trong `docs/tasks/CLEAN-P5-web-routers.md`); ghép theo chủ đề (TC2.3) và "Khôi phục nguồn" (CP8.37) trên tập đã dọn; chấm tiêu đề AI (TC2.2).
2. Chất lượng AI TC1 / TC2: synopsis đôi khi là mẩu ngắn, chủ đề có xu hướng gom theo tập; qwen3:30b `think=true` ≈ 1–2 phút / clip.
3. Cũ, vẫn mở: HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
