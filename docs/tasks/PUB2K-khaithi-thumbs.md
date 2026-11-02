# Task: PUB2K — PUB2 gắn thumbnail khai thị (KT) cho video trong playlist KT trên YouTube

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-02 "gắn thumbnail KT lên YouTube cho cả 3 kênh … video KT trên YouTube đã có số tập và mã đúng như web quy định → ghép theo số tập + mã"
- Parallel group: —
- Owned paths: `src/auto_short/publish/__main__.py`, `src/auto_short/publish/thumbs.py`, `src/auto_short/publish/kt.py` (mới, nếu tách), `tests/test_publish_thumbs.py`, `tests/test_publish_kt.py` (mới), `docs/decisions/PUB2-youtube-thumbnail-set.md`, file này
- Dependencies: PUB2M (`fix/pub2-hd-mobile`, đã push, chưa PR), PUB2P (`feature/pub2p-yt-playlist` `787c590`, chưa push) — dựng chồng; PR theo thứ tự PUB2M → PUB2P → PUB2K hoặc gộp
- Base commit / branch: `787c590` / `feature/pub2k-kt-thumbs` (worktree `~/projects/yas-pub2k`)
- Human Lead approval: accepted 2026-11-02 ("Duyệt", gồm sửa G1 / G2 của decision PUB2)
- Implementation authorized: YES

## Bằng chứng đọc thật (2026-11-02, chỉ đọc, `playlists.list` / `playlistItems.list` / `videos.list`)

Playlist KT do HUMAN LEAD khai ở LNK1 (lưu trong `work/_playlists/<pid>.json` field `link_playlists`; kết quả quét ở `work/_publish/post_links.json`):

| Kênh (token) | Bộ kinh (pid nguồn) | Playlist KT YouTube | Video | Có mã `T<tập>_KT<nn>` |
|---|---|---|---|---|
| Người Dân Cực Lạc (`youtube-token.json` mặc định) | Thập Thiện `PLOynZc0cJJfBdXCpRfBeFUeqoz-iOMBRF` | `PLaEL0bqgCvao` [Tập 1-20] | 113 | 105 (8 video tập 9 dạng `T9_ <tiêu đề>`, không số KT) |
| Cực Lạc Là Đây (`youtube-tokens/vlt.json`) | Vô Lượng Thọ `PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_` | `PLLXPsmkMdkPg` [01-20] | 108 | 102 (6 không mã) |
| | | `PLVBxpPU8Z1A0` [21-40] | 51 | 51 |
| Hương Quê Cực Lạc (`youtube-tokens/cam-ung-thien.json`) | Cảm Ứng Thiên `PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa` | `PLJqfbBViLIRw` [01-20] | 108 | 97 (11 không mã) |
| | | `PLWD4r7j4zOag` [21-40] | 0 | — |

- Mã lấy từ tên file gốc `T11_KT01_<tiêu đề>.mp4` (đọc được với 318 video) hoặc tiêu đề `T11 KT01 …` / `T2_KT02_… #…`; khi có cả hai thì **luôn trùng nhau**; không mã nào trùng lặp trong một playlist.
- Ghép thử bằng script ngoài git: 356 / 356 video có mã → đúng một tập `<id>.kt` trong bộ kinh, clip thứ `nn` (đánh số như `khaithi_thumbs` `clip_numbers` = số trong tên file tải về web) có ảnh KT dọc hợp lệ; 354 tiêu đề khớp tiêu đề web, 2 khác do lỗi gõ (`vi tín` / `vi tính`, `giáng` / `vãng sanh`).
- Video KT là 1080×1920 → ảnh KT **dọc** (`vertical`).

## Goal

```text
python -m auto_short.publish kt-thumbs --playlist <pid nguồn> --yt-playlist <id playlist KT> --token <token kênh> [--apply] [--force]
```

lập bảng video KT → ảnh KT dọc cho đúng các video trong playlist KT chỉ định; `--apply` gắn. Chạy một lần cho mỗi playlist KT ở bảng trên.

## Scope

- In scope:
  - Lệnh con `kt-thumbs` (dùng chung `YouTube.playlist_videos`, `--config/--client/--token`, `apply` kiểm sha256 / 2 MB / ảnh còn hiệu lực, nhật ký, `--force` của PUB2 / PUB2P).
  - Ghép: mã `T<N>[ _]KT<NN>` ở đầu tên file gốc (ưu tiên) hoặc đầu tiêu đề (bỏ khoảng trắng đầu, không phân biệt hoa thường). Tên file và tiêu đề cùng có mã mà khác nhau → bỏ qua, lý do "tên file và tiêu đề lệch mã". Tập N → đúng một tập `<id>.kt` trong playlist nguồn (số tập theo `episode.header`), không có / nhiều hơn một → bỏ qua. Clip = clip có số `NN` trong `clip_numbers` của `thumbs.json` KT; ảnh = `khaithi_thumbs.valid_files(...)[clip]["vertical"]`. Không có ảnh hợp lệ → bỏ qua với lý do.
  - Nhật ký `work/_publish/thumbs.json` giữ `schema_version` 1; bản ghi KT có `video_id = "<id>.kt"` và thêm `clip_id`. Lệnh `thumbs` (tập) bỏ qua bản ghi có `clip_id` khi ghép theo nhật ký.
  - Bảng in: video YouTube, mã, clip, ảnh, trạng thái / lý do, cảnh báo "tiêu đề YouTube khác tiêu đề web" (so sau chuẩn hóa, chỉ cảnh báo — HUMAN LEAD đã xác nhận mã đúng).
- Out of scope: video không mã (25 video: bỏ qua, in ra; gắn tay nếu muốn); Short; khai thị ghép; tìm playlist KT tự động từ `link_playlists` (đoán theo tên playlist); upload / sửa metadata / playlist; route web; scope OAuth.

## Authority / key decisions

- Sửa decision `docs/decisions/PUB2-youtube-thumbnail-set.md` (HUMAN LEAD duyệt cùng contract):
  - G1: thêm lệnh `kt-thumbs --playlist <pid> --yt-playlist <id>` (bắt buộc playlist chỉ định; cùng API, scope).
  - G2: video KT ghép theo mã `T<N>_KT<NN>` ở tên file gốc hoặc tiêu đề (HUMAN LEAD 2026-11-02: mã trên YouTube đúng như web quy định) → tập `.kt` số N → clip số NN → ảnh KT dọc. Không mã / lệch mã → bỏ qua.
  - G3 không đổi; nhật ký thêm `clip_id` cho bản ghi KT.

## Phải giữ nguyên

- `thumbs` (có / không `--yt-playlist`): test cũ PASS không sửa.
- `apply`: một lỗi API dừng lô; ghi nhật ký từng video.

## Code bị thay / xóa

- Không thay code cũ; tái dùng `YouTube.playlist_videos`, `thumbs.apply` / `_journal` (mở rộng để kiểm ảnh KT qua `khaithi_thumbs.valid_files` thay vì `episode.valid_files` khi bản ghi là KT — không chép đôi logic kiểm sha / 2 MB).
- Script ghép thử `kt_match.py` ở scratchpad: không đưa vào repo.

## Acceptance Criteria

1. Tên file `T11_KT01_<…>.mp4` → tập 11, KT 1; tiêu đề ` T7_KT05_… #…` (không tên file) → tập 7, KT 5; `T9_ <…>` → bỏ qua "không có mã KT".
2. Tên file và tiêu đề khác mã → bỏ qua với lý do.
3. Tập không có `.kt` duy nhất trong playlist nguồn, số KT vượt số clip, clip không có ảnh dọc hợp lệ → bỏ qua với lý do riêng.
4. Tiêu đề YouTube khác tiêu đề web → vẫn "sẵn sàng", có cảnh báo.
5. `--apply` ghi bản ghi KT (`video_id` `.kt`, `clip_id`, `shape` vertical); lần sau cùng sha → bỏ qua; `--force` gắn lại; ảnh đổi giữa lập bảng và gắn → bỏ qua.
6. `thumbs --yt-playlist` của tập không dùng nhầm bản ghi KT trong nhật ký; test PUB2 / PUB2P cũ PASS.

## Required verification

- `pytest tests/test_publish*.py` (transport giả, không mạng).
- Full suite `-n 4` (ORCHESTRATOR, ngoài sandbox).
- Chạy thật (ORCHESTRATOR): chạy thử 4 playlist KT → 356 sẵn sàng, 25 bỏ qua không mã; `--apply` 1 video (Thập Thiện) → HUMAN LEAD xem trên YouTube; rồi `--apply` phần còn lại cả 4 playlist.

## Result

-
