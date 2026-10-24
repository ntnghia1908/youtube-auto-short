# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành ít dùng (backup, GPU worker, IP, tuning): `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token của file: xem `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-24.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`): branch tạm local `web/main-aiq2` = main `fe82caf` (#137 AUD1) + #131 TC-AIQ2, restart 2026-10-24 13:20 UTC. Việc tiếp: thêm #138 PKG2.2 rồi restart; khi #131 merge thì trỏ về main, xóa branch tạm. Restart: script từ chối khi làn bận (mật khẩu `~/.local/share/auto-short/web.env`).
- Thư mục dự án chuyển sang `~/projects/` ngày 2026-10-19; backup JSON trước khi chuyển: xem ops-notes.
- `config.toml` (không trong git) `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- 2026-10-24: 3050 thôi làm enhance (ops-notes); worker #100 đã chép lên 3090 + 3050 (HUMAN LEAD xác nhận; log server: cả hai nhận việc, không lỗi CUDA — `__version__` vẫn "3" nên server không phân biệt bản). CP8.38 phần nhìn: HUMAN LEAD bỏ qua manual test (API đã PASS 12/12). Manual test cũ (FIX-dl-abort-grace, smoke CLEAN-P5, TC2.3, CP8.37, TC2.2): HUMAN LEAD cho PASS.
- A100 mượn (2026-10-24): Ollama + 3 enhance worker chạy qua Slurm; VM trỏ AI sang A100. Chi tiết + bước trả máy: ops-notes "A100 mượn".
- CL1 Chinese Learning: HUMAN LEAD bỏ, đã gỡ (#107); quy ước host CL1 C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD đăng 13 bài tập 10 Thập Thiện `W2d-xS4ttTw` (xử lý lại 2026-10-24).
2. TC-AIQ2 (`docs/tasks/TC-AIQ2-theme-target-length.md`, READY, PR #131): HUMAN LEAD chấm ngữ nghĩa trên 8080 rồi merge #130 → #131.
3. Đóng gói (boundary `docs/decisions/PKG-video-packaging-authorization.md` ACCEPTED): PKG1, PKG2, VIS1, PKG2.1, FIX-theme-index-summary, AUD1 (#137) đã merge main; mức nhạc mặc định −20 LU (HUMAN LEAD giữ). **PKG2.2** (G8: thumbnail mọi tập, không cần video trên VM) READY, PR #138; ảnh cả bộ Địa Tạng đã dựng (102 / 102 ngang + dọc). Backup Địa Tạng trên 3090 (`~/.local/share/auto-short/backup/kdt-backup.ps1`, `D:\KinhDiaTang_HD`) có thêm bước tải thumbnail cùng tên video (`-ThumbsOnly`), cần 8080 chạy #138. Đang chờ HUMAN LEAD: (a) script gắn thumbnail qua YouTube API sau khi upload tay (ngoài scope PKG — cần quyết định mới) hay gắn tay; (b) thiết kế thumbnail video khai thị ghép theo phong cách kiểu A (mẫu PKG1 hiện tại nhạt). Nhạc nền: HUMAN LEAD sẽ gửi 3–5 bài YouTube Audio Library (bản CC0 hiện có "chưa hay"); không nạp nhạc thương mại / chưa rõ license. Sau khi tích hợp êm: PR docs bỏ câu "số writer thực tế là 1" (project-profile §7, framework-migration-notes); HUMAN LEAD duyệt nội dung trước.
4. Cũ, vẫn mở: HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
