# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành ít dùng (backup, GPU worker, IP, tuning): `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token của file: xem `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-24.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`): chạy `1ba12e6` (branch tạm local `web/main-aiq2` = main + #131 TC-AIQ2 + #138 PKG2.2 + #139), restart 2026-10-24 14:28 UTC. Việc tiếp: khi #131 và #138 merge, trỏ checkout web về main, xóa branch tạm, restart (hỏi có / không), rồi HUMAN LEAD xem trang Đóng gói PKG3 (#140) trên 8080. Restart: script từ chối khi làn bận (mật khẩu `~/.local/share/auto-short/web.env`).
- Thư mục dự án chuyển sang `~/projects/` ngày 2026-10-19; backup JSON trước khi chuyển: xem ops-notes.
- `config.toml` (không trong git) `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- 2026-10-24: 3050 thôi làm enhance (ops-notes); worker #100 đã chép lên 3090 + 3050 (HUMAN LEAD xác nhận; log server: cả hai nhận việc, không lỗi CUDA — `__version__` vẫn "3" nên server không phân biệt bản). CP8.38 phần nhìn: HUMAN LEAD bỏ qua manual test (API đã PASS 12/12). Manual test cũ (FIX-dl-abort-grace, smoke CLEAN-P5, TC2.3, CP8.37, TC2.2): HUMAN LEAD cho PASS.
- A100 mượn (2026-10-24): Ollama + 3 enhance worker chạy qua Slurm; VM trỏ AI sang A100. Chi tiết + bước trả máy: ops-notes "A100 mượn".
- Bài đăng sửa 2026-10-24 (FIX-post-doc-gate, #139 đã merge): 149 bài chuyển về văn bản gốc, backup `~/.local/share/auto-short/backup-posts-2026-10-24T140515Z/`. 6 bài đã đăng sai chờ HUMAN LEAD sửa tay: VLT tập 9 S9; CƯT T5 S8, T6 S9, T7 S1, T9 S7, T11 S3. ~106 bài chữ AI hiện cảnh báo khi sao chép.
- CL1 Chinese Learning: HUMAN LEAD bỏ, đã gỡ (#107); quy ước host CL1 C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD đăng 13 bài tập 10 Thập Thiện `W2d-xS4ttTw` (xử lý lại 2026-10-24).
2. TC-AIQ2 (`docs/tasks/TC-AIQ2-theme-target-length.md`, READY, PR #131): HUMAN LEAD chấm ngữ nghĩa trên 8080 rồi merge #131.
3. Đóng gói (boundary `docs/decisions/PKG-video-packaging-authorization.md` ACCEPTED): PKG1, PKG2, VIS1, PKG2.1, FIX-theme-index-summary, AUD1 (#137) đã merge main. Chờ merge: PKG2.2 #138, PKG3 #140, PUB2 #141 (cần #138 trước khi chạy thật). AUD1: HUMAN LEAD chọn mức nhạc từ mẫu −18 / −22 / −26 LU; thêm nhạc YouTube Audio Library do HUMAN LEAD tải từ Studio (G3). Kho nhạc: 1 bản CC0 "The Budding of Consciousness"; không nạp bộ "nhạc hòa tấu Niệm Phật" (chưa rõ license), "月下獨酌" (album thương mại). PUB1 / PKG1.1: bỏ.
   PUB2 chạy thật khi HUMAN LEAD đặt `~/.local/share/auto-short/youtube-client.json` (chưa có): auth → `thumbs` chạy thử → `--apply` 1 video.
   Sau khi tích hợp êm: PR docs bỏ câu "số writer thực tế là 1" (project-profile §7, framework-migration-notes) — pilot 3 IMPLEMENTER song song 2026-10-24 không xung đột; HUMAN LEAD duyệt nội dung trước.
4. Cũ, vẫn mở: HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
