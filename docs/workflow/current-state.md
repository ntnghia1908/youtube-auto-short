# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành ít dùng (backup, GPU worker, IP, tuning): `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token của file: xem `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-24.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`) chạy `965044c` (`feature/tc-aiq2`, PR #131 = main + TC-AIQ2; restart 2026-10-24). Restart: hỏi HUMAN LEAD rồi `~/.local/bin/auto-short-web-restart` (mật khẩu ở `~/.local/share/auto-short/web.env`, từ chối khi làn bận).
- Thư mục dự án chuyển sang `~/projects/` ngày 2026-10-19; backup JSON trước khi chuyển: xem ops-notes.
- `config.toml` (không trong git) `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- 2026-10-24: worker #100 đã chép lên 3090 + 3050 (HUMAN LEAD xác nhận; log server: cả hai nhận việc, không lỗi CUDA — `__version__` vẫn "3" nên server không phân biệt bản). CP8.38 phần nhìn: HUMAN LEAD bỏ qua manual test (API đã PASS 12/12). Manual test cũ (FIX-dl-abort-grace, smoke CLEAN-P5, TC2.3, CP8.37, TC2.2): HUMAN LEAD cho PASS.
- A100 mượn (2026-10-24): Ollama + 3 enhance worker chạy qua Slurm; VM trỏ AI sang A100. Chi tiết + bước trả máy: ops-notes "A100 mượn".
- CL1 Chinese Learning: HUMAN LEAD bỏ, đã gỡ (#107); quy ước host CL1 C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD đăng 13 bài tập 10 Thập Thiện `W2d-xS4ttTw` (xử lý lại 2026-10-24).
2. TC-AIQ2 (`docs/tasks/TC-AIQ2-theme-target-length.md`, READY, PR #131): chạy thật 4/5 chủ đề đạt 30–40 phút; HUMAN LEAD chấm ngữ nghĩa trên 8080 rồi merge #130 → #131.
3. Đóng gói video ghép chủ đề (thumbnail / hình ambient / nhạc nền): boundary `docs/decisions/PKG-video-packaging-authorization.md` PROPOSED, chờ HUMAN LEAD G1–G6; contract DRAFT `PKG1` → `VIS1` → `AUD1`. Hàng đăng bài (PUB1) và nhật ký thử nghiệm (PKG1.1): HUMAN LEAD bỏ 2026-10-24.
4. Cũ, vẫn mở: HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
