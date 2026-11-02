# Task: PUB2P — PUB2 gắn thumbnail cho video trong một playlist YouTube

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-02 chọn "C. viết contract để PUB2 nhận `--yt-playlist`, dùng lâu dài"; sửa G2 của `docs/decisions/PUB2-youtube-thumbnail-set.md` (xem Authority) cần HUMAN LEAD duyệt cùng contract này
- Parallel group: —
- Owned paths: `src/auto_short/publish/__main__.py`, `src/auto_short/publish/thumbs.py`, `src/auto_short/publish/youtube.py`, `tests/test_publish_thumbs.py`, `tests/test_publish_youtube.py` (nếu có), `docs/decisions/PUB2-youtube-thumbnail-set.md`, file này
- Dependencies: PUB2M (`fix/pub2-hd-mobile` `5ebc002`, đã push 2026-11-02, chưa PR — cùng file `thumbs.py`; PR PUB2M merge trước hoặc gộp)
- Base commit / branch: `5ebc002` / `feature/pub2p-yt-playlist` (worktree `~/projects/yas-pub2p`)
- Human Lead approval: accepted 2026-11-02 ("Duyệt contract gồm cả việc nới G2")
- Implementation authorized: YES

## Goal

HUMAN LEAD gom các video cần gắn thumbnail vào một playlist trên kênh (vd Cảm Ứng Thiên `PLM-L9-YGkahc`, 23 video, tên file gốc kiểu web cũ `…_TậpN_Doc.mp4` mà PUB2 không nhận). Lệnh

```text
python -m auto_short.publish thumbs --playlist <pid nguồn> --yt-playlist <id playlist YouTube> --token <token kênh> [--apply] [--force]
```

lập bảng video → ảnh cho **đúng các video trong playlist đó** và gắn khi có `--apply`. Không còn cần script một lần như `output/_operations/pub2-test-2026-11-02/pub2_old_names.py`.

## Scope

- In scope:
  - `YouTube.playlist_videos(playlist_id)`: `playlistItems.list` (phân trang, chống trùng / lặp trang như `videos()`) rồi `videos.list part=fileDetails,snippet` theo lô 50. Dùng chung phần phân trang / lô với `videos()`, không chép đôi.
  - Ghép video ↔ tập khi có `--yt-playlist`, theo thứ tự:
    1. **Nhật ký** `work/_publish/thumbs.json`: `youtube_id` đã có bản ghi cùng `playlist_id` nguồn → dùng `video_id` / khuôn của bản ghi.
    2. **Tên file gốc** theo mẫu PUB2 hiện có (`[HD]` / `[HD Dọc]` / `[HD Mobile]`) hoặc mẫu web cũ `[HD ]<bộ kinh>_Tập<N>_Doc.mp4` (khuôn dọc).
    3. **Tiêu đề** `[HD …] <bộ kinh> - … - Tập N` (thẻ `[HD]` → ngang; `[HD Dọc]` / `[HD Mobile]` không phân biệt hoa thường → dọc; tên bộ so như `_series`).
    Không khớp cả ba → bỏ qua, in lý do. Hai nguồn cho ra tập / khuôn khác nhau → bỏ qua, lý do "nhật ký và tên / tiêu đề lệch nhau".
  - Bảng in thêm cột "ghép theo" (nhật ký / tên file / tiêu đề).
- Out of scope: không có `--yt-playlist` thì hành vi cũ giữ nguyên (chỉ tên file gốc, toàn bộ uploads); upload / sửa metadata / playlist; route web; đổi scope OAuth.

## Authority / key decisions

- Sửa G2 trong `docs/decisions/PUB2-youtube-thumbnail-set.md` (HUMAN LEAD duyệt cùng contract): "Không đoán theo tiêu đề" chỉ áp dụng cho lệnh không có `--yt-playlist`. Với `--yt-playlist`, HUMAN LEAD đã tự chọn video vào playlist nên được ghép theo nhật ký → tên file → tiêu đề. G1 thêm `playlistItems.list` cho playlist chỉ định (cùng scope `youtube.readonly`). G3 (chạy thử mặc định, `--apply`, nhật ký, bỏ qua cùng sha256, `--force`) không đổi.
- Quota: thêm 1 đơn vị / trang 50 video; không đáng kể.

## Implementation approach

- `youtube.py`: tách vòng phân trang `playlistItems` của `videos()` thành helper dùng cho cả uploads và playlist chỉ định.
- `thumbs.py`: `plan(..., journal=None)` hoặc hàm ghép riêng nhận danh sách video + nhật ký; giữ `apply` nguyên.
- `__main__.py`: thêm `--yt-playlist`.

## Phải giữ nguyên

- `thumbs` không có `--yt-playlist`: bảng và kết quả byte-identical với hiện tại (test cũ PASS không sửa).
- `apply`: kiểm sha256 / 2 MB / thumbnail còn hiệu lực, ghi nhật ký từng video, lỗi API dừng lô.

## Code bị thay / xóa

- Vòng phân trang trong `YouTube.videos()` chuyển vào helper chung (không để hai bản).
- `output/_operations/pub2-test-2026-11-02/pub2_old_names.py` (ngoài git) thôi dùng; không xóa (bằng chứng vận hành).

## Acceptance Criteria

1. `--yt-playlist Y`: chỉ video thuộc Y vào bảng; phân trang nhiều trang, trang lặp → lỗi rõ.
2. Video có bản ghi nhật ký cùng playlist nguồn → ghép theo nhật ký (cột "ghép theo" = nhật ký), kể cả khi tên file / tiêu đề không theo mẫu.
3. Tên file web cũ `Thái Thượng Cảm Ứng Thiên_Tập12_Doc.mp4` → tập 12, dọc.
4. Tiêu đề `[HD mobile] Thái Thượng Cảm Ứng Thiên - PS. Tịnh Không - Tập 12` → tập 12, dọc; `[HD] … - Tập 3` → ngang; bộ kinh khác → bỏ qua.
5. Nhật ký và tên / tiêu đề lệch tập → bỏ qua với lý do.
6. Không có `--yt-playlist`: hành vi cũ (test cũ PASS).
7. `--apply --force` gắn lại ảnh mới dù nhật ký có sha cũ; không `--force` thì video cùng sha bỏ qua.

## Required verification

- `pytest tests/test_publish*.py` (AC1–7, transport giả, không mạng).
- Full suite `-n auto` (ORCHESTRATOR, ngoài sandbox).
- Chạy thật (ORCHESTRATOR, HUMAN LEAD đã đồng ý gắn lại 2026-11-02): chạy thử `--yt-playlist PLM-L9-YGkahc` trên kênh Cảm Ứng Thiên → 23 dòng sẵn sàng; `--apply --force` 1 video, HUMAN LEAD xem trên YouTube; rồi phần còn lại + tập 24, 25 (nhật ký, ngoài playlist: chạy riêng theo playlist uploads hoặc HUMAN LEAD thêm vào playlist).

## Result

- IMPLEMENTER Codex (gpt-6.1-sol, effort high), 1 vòng, 58.497 tokens. `YouTube.playlist_videos` + helper chung `_playlist_videos` (uploads dùng lại); `thumbs._playlist_match` (nhật ký → tên file → tiêu đề), `plan(journal=)`; `apply` giữ nguyên; CLI `--yt-playlist`, cột "ghép theo". Diff +261 / −19 (5 file).
- AC → test (`tests/test_publish_thumbs.py`): AC1 `test_playlist_pagination_batches_and_deduplication`, `test_playlist_invalid_pagination`; AC2, AC5 `test_playlist_journal_priority_and_conflicts`; AC3, AC4 `test_playlist_filename_and_title_matches`; AC6 test cũ không sửa + `test_playlist_fallback_is_opt_in`; AC7 `test_playlist_cli_journal_dry_run_apply_and_force`.
- Verification (ORCHESTRATOR): full suite `-n 4` **3690 passed, 1 skipped**; `git diff --check` PASS.
- Chạy thật 2026-11-02 (kênh Cảm Ứng Thiên, playlist `PLM-L9-YGkahc`, 25 video tập 1–25): chạy thử 25/25 sẵn sàng, ghép theo nhật ký; `--apply --force` 1 video tập 1 `Kh6kz45j5Xc` → đã gắn (ảnh có chân dung). Phần còn lại chờ HUMAN LEAD xem tập 1.
