# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành: `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token: `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-25.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`): chạy `origin/main` `db9738e` (restart `--force` 2026-10-25 05:05; branch tạm `web/main-pkg31*` đã xóa); `[store]` bật (kho 3090 qua tunnel 18090, chi tiết ops-notes). Mật khẩu `~/.local/share/auto-short/web.env`.
- Kinh Địa Tạng 41 tập đã giải phóng bản HD (HD1, bản ở kho 3090 `E:\KinhDiaTang_HD`); HUMAN LEAD chạy định kỳ trên 3090 `backup.ps1 -Dest E:\KinhDiaTang_HD -Release` (mặc định trong file là D:). Đợt bản dọc 2026-10-25 (61 tập xếp hàng): 6 có bản dọc, 5 tập `.kt` xếp lại sau restart (job 51–55), 50 tập chỉ có workspace gốc chưa có `titles.json` → fail "chưa có tiêu đề" (cần xử lý tập trước).
- Bug (chưa có contract): khôi phục hàng đợi sau restart bỏ job bản dọc của tập chỉ có `work/<id>.kt/` — `web/app.py` `_rebuild_job` kiểm `work/<id>/` thay vì `enhance_state.owner_for`. Tránh: xếp lại bằng tay sau restart.
- Dự án ở `~/projects/` từ 2026-10-19; backup JSON: ops-notes. `config.toml` `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: ưu tiên Codex (HUMAN LEAD 2026-10-25, tiết kiệm quota Claude); `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- 3050 thôi làm enhance 2026-10-24; worker #100 đã chép lên 3090 + 3050, không lỗi CUDA (`__version__` vẫn "3"). CP8.38: HUMAN LEAD bỏ qua manual test (API PASS 12/12); manual test cũ: HUMAN LEAD cho PASS.
- A100 Slurm ngừng 2026-10-25 (`scancel`, config / token / tunnel đã gỡ); AI về 3090 (`/api/monitor/ollama` connected `11437` sau restart). Ưu tiên fairshare + dùng lại: ops-notes.
- Bài đăng sửa 2026-10-24 (#139): 149 bài về bản gốc, backup `~/.local/share/auto-short/backup-posts-2026-10-24T140515Z/`. 6 bài đã đăng sai chờ HUMAN LEAD sửa: VLT T9 S9; CƯT T5 S8, T6 S9, T7 S1, T9 S7, T11 S3. ~106 bài chữ AI cảnh báo khi sao chép.
- Test chập chờn đã biết: `tests/test_prepare_parallel_cp829.py::test_lower_thread_priority_is_per_thread_and_inherited_by_children` — fail ngẫu nhiên khi chạy full suite; chạy lại riêng thì PASS.
- CL1 đã gỡ (#107); quy ước host C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD đăng 13 bài tập 10 Thập Thiện `W2d-xS4ttTw` (xử lý lại 2026-10-24).
2. Đóng gói (`docs/decisions/PKG-video-packaging-authorization.md` ACCEPTED): PKG1, PKG2, VIS1, PKG2.1, PKG2.2, PKG3, PKG3.1, PUB2, FIX-theme-index-summary, AUD1 đã merge; HD1, HD2a cũng vậy. PKG3.1: HUMAN LEAD bấm "Ghép lại" một video ghép Thái Thượng Cảm Ứng Thiên (cả 3 đang stale) rồi xem trang Đóng gói.
   AUD1: HUMAN LEAD chọn −18 / −22 / −26 LU; nhạc YouTube Audio Library do HUMAN LEAD tải từ Studio (G3). Kho: 1 bản CC0 "The Budding of Consciousness"; không nạp "nhạc hòa tấu Niệm Phật" (chưa rõ license), "月下獨酌" (thương mại). PUB1 / PKG1.1: bỏ.
   PUB2: chờ `~/.local/share/auto-short/youtube-client.json`: auth → `thumbs` chạy thử → `--apply` 1 video.
3. HD2b (decision HD2 G5–G7 ACCEPTED: tải qua web từ kho, đẩy bản dọc mới lên kho + tự giải phóng, theme_render mượn từ kho, dọn file mượn sót; generator backup thêm tùy chọn ổ): viết contract khi HUMAN LEAD muốn.
4. Còn mở: HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
