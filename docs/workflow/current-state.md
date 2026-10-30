# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi state không suy ra được từ Git, task contract hoặc accepted decisions. PR đã merge: xem `git log`. Chi tiết vận hành: `docs/workflow/ops-notes.md` — chỉ đọc khi cần.

Ngân sách token: `docs/ai/workflow.md` §10.

## Current focus

Cập nhật 2026-10-30.

- Web 8080 (tmux `youtube:web`, worktree `~/projects/youtube-auto-short-web`): chạy `origin/main` `06f7f92` (detached; restart 2026-10-30 sau #183 HDI1); `[store]` bật (kho 3090 qua tunnel 18090, chi tiết ops-notes), `offload = true` (bản dọc tự lên kho + giải phóng), `offload_shorts = true` (SHO1, từ 2026-10-27). Script restart từ chối khi làn bận; mật khẩu `~/.local/share/auto-short/web.env`. Đã thấy, chưa sửa: Ctrl-C server mất ≈ 13 phút (luồng nền băm source); id job trùng sau khi khôi phục hàng đợi.
- Kinh Địa Tạng 64 / 102 tập đã giải phóng bản HD (HD1 / HD2b, bản ở kho 3090 `E:\KinhDiaTang_HD`); HUMAN LEAD chạy định kỳ trên 3090 `backup.ps1 -Release` (#161: mặc định `-Dest` ổ E:, `danh-sach.csv` giữ dòng tập đã giải phóng). Chưa giải phóng: 38 tập (35–78 rải rác, và 100) mới có HD, chưa xử lý Short.
- HD intro Địa Tạng (HDI1, `[hd_intro] playlists = [ĐT]`, HUMAN LEAD duyệt letterbox 4:3): 2026-10-30 có 57 / 64 tập đã giải phóng xong; 7 tập (12, 19, 33, 58, 91, 99 kẹt `pending` vì URLError tới kho; 85 lỗi kiểm khung tại 1704.803 s) xếp lại 2026-10-30. 38 tập chưa giải phóng chỉ làm được sau khi giải phóng HD.
- Khai thị có intro bìa (KTI1, `khaithi_from.json`): Thái Thượng từ tập 11, Vô Lượng Thọ từ 10 (bìa vàng), Cảm Ứng Thiên từ 10 (bìa xanh cũ của VLT); dựng lại xong 2026-10-30, backup bìa / queue `~/.local/share/auto-short/backup-covers-2026-10-30/`.
- Dự án ở `~/projects/` từ 2026-10-19; backup JSON: ops-notes. `config.toml` `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`.
- Kho nguồn ghép chủ đề `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`).
- Codex IMPLEMENTER: ưu tiên Codex (HUMAN LEAD 2026-10-25, tiết kiệm quota Claude); `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.
- 3050 thôi làm enhance 2026-10-24; worker #100 đã chép lên 3090 + 3050, không lỗi CUDA (`__version__` vẫn "3"). CP8.38: HUMAN LEAD bỏ qua manual test (API PASS 12/12); manual test cũ: HUMAN LEAD cho PASS.
- A100 Slurm ngừng 2026-10-25 (`scancel`, config / token / tunnel đã gỡ); AI về 3090 (`11437`). Ưu tiên fairshare + dùng lại: ops-notes.
- Bài đăng sửa 2026-10-24 (#139): 149 bài về bản gốc, backup `~/.local/share/auto-short/backup-posts-2026-10-24T140515Z/`. 6 bài đã đăng sai: HUMAN LEAD đã sửa (2026-10-26). ~106 bài chữ AI cảnh báo khi sao chép.
- Test chập chờn đã biết: `tests/test_prepare_parallel_cp829.py::test_lower_thread_priority_is_per_thread_and_inherited_by_children` — fail ngẫu nhiên khi chạy full suite; chạy lại riêng thì PASS.
- CL1 đã gỡ (#107); quy ước host C0 / C1 vẫn hiệu lực.

## Next proposed action

1. HUMAN LEAD đăng 13 bài tập 10 Thập Thiện `W2d-xS4ttTw` (xử lý lại 2026-10-24).
2. Đóng gói (`docs/decisions/PKG-video-packaging-authorization.md` ACCEPTED): PKG1, PKG2, VIS1, PKG2.1, PKG2.2, PKG3, PKG3.1, PUB2, FIX-theme-index-summary, AUD1 đã merge; HD1, HD2a cũng vậy. PKG3.1: HUMAN LEAD đã bấm "Ghép lại" video ghép Thái Thượng stale (2026-10-26).
   AUD1: HUMAN LEAD chọn −18 / −22 / −26 LU; nhạc YouTube Audio Library do HUMAN LEAD tải từ Studio (G3). Kho: 1 bản CC0 "The Budding of Consciousness"; không nạp "nhạc hòa tấu Niệm Phật" (chưa rõ license), "月下獨酌" (thương mại). PUB1 / PKG1.1: bỏ.
   PUB2: chờ `~/.local/share/auto-short/youtube-client.json`: auth → `thumbs` chạy thử → `--apply` 1 video.
3. HD2b (#167), #169–#171 đã merge + chạy thật. Còn mở: HUMAN LEAD chạy `scripts/archive/luu-tru-short.ps1` trên 3090 (cú pháp PowerShell chưa kiểm); thử restart lúc offload đang băm khi có bản dọc mới.
4. SRC1–SRC4, TC3.2 đã merge (#154, #159, #160). Chưa có ca thật, chỉ test tự động: SRC3 G2 a (bản kho khác byte), nhánh chờ khi YouTube chặn của TC3.2 / SRC4. FIX job "đợi 3090" khi restart (#165) và gộp snapshot kho (#166) đã merge.
5. SHO1a / SHO1b (#174, #176), VERT1 / VERT2 / COV1 (#177, #180), FIX-theme-offloaded-shorts (#181), THUMB1 (#182), THUMB2 (#184), FIX-process-archived-restore (#185), KTI1 (#187), HDI1 (#183) đã merge. Còn mở: chạy thật VERT2 hàng loạt (dựng lại bản dọc VLT + Địa Tạng); kiểm 7 tập HD intro xếp lại 2026-10-30 (mục Current focus).
6. Còn mở: HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
