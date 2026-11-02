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

## Sửa đổi 1 (HUMAN LEAD 2026-11-02 "Đồng ý" dùng ảnh ngang cho KT)

- Lý do: video KT 4–7 phút là video thường; YouTube hiện thumbnail trong khung 16:9 (trang chủ, tìm kiếm, đề xuất), ảnh dọc bị thu nhỏ → chữ nhỏ.
- `kt-thumbs` thêm `--shape {vertical,landscape}`, **mặc định `landscape`**; ảnh = `khaithi_thumbs.valid_files(...)[clip][shape]`; bản ghi nhật ký `shape` theo lựa chọn. Video đã gắn ảnh dọc → sha khác → `--apply` gắn lại không cần `--force`.
- AC8: `--shape landscape` chọn ảnh ngang; clip thiếu ảnh ngang → bỏ qua với lý do; mặc định là landscape; `--shape vertical` giữ hành vi cũ.
- Decision PUB2 G2 (đoạn KT): "→ ảnh KT ngang (mặc định) hoặc dọc theo `--shape`".

## Result

- IMPLEMENTER READY (2026-11-02), branch `feature/pub2k-kt-thumbs`, base HEAD `7d438c4` theo giao việc; chưa commit / push / PR.
- Đổi 7 file trong owned paths: `publish/__main__.py`, `publish/thumbs.py`, `publish/kt.py` (mới), `tests/test_publish_thumbs.py` (chỉ thêm test), `tests/test_publish_kt.py` (mới), decision PUB2 (G1/G2 + trường nhật ký KT ở G3), mục Result này.
- Helper mới: `kt._code` (parse mã đầu) và `kt.plan` (ghép playlist KT). Đã tìm bằng `rg -n 'def (plan|apply|_journal|_thumbnail|_series|short_code|read|valid_files|titles)|KT.*re\.compile|re\.compile.*KT' src/auto_short/publish src/auto_short/review/names.py src/auto_short/packaging/khaithi_thumbs.py`: chưa có parser / planner KT; `review.names.short_code` chỉ tạo mã. Tái dùng `YouTube.playlist_videos`, `thumbs._series`, `_thumbnail` (thêm chọn provider theo `clip_id`), `apply` / `_journal`, `episode.header` và `khaithi_thumbs.read/valid_files/titles/directory`; giữ một vòng apply.

| AC | Test |
|---|---|
| 1 | `test_code_matching` (parametrize; gồm `KT05` → `m01`, đọc `thumbs.json` thật), `test_cli_requires_both_playlists` |
| 2 | `test_code_conflict` |
| 3 | `test_local_resolution_skips` (thiếu / nhiều tập, ngoài playlist, thiếu clip / hồ sơ / ảnh dọc, ảnh stale) |
| 4 | `test_title_warning_only` |
| 5 | `test_cli_dry_run_apply_skip_force`, `test_apply_revalidates_kt_image`, `test_kt_api_failure_stops_after_journaled_success` |
| 6 | `test_playlist_ignores_kt_journal_records` + toàn bộ test PUB2/PUB2P cũ giữ nguyên |

- Kiểm thêm schema bằng `test_journal_optional_clip_id_must_be_string`. Fixture dùng workspace tạm, read / titles KT thật; chỉ giả `valid_files` để bỏ setup cover / render và transport HTTP.
- Dòng ứng dụng: **+127 / −21** (`__main__.py` +23/−11, `thumbs.py` +19/−10, `kt.py` +85/−0); test: **+272 / −0** (file cũ +19, file mới +253).
- Verification: `cd /home/ntnghia/projects/yas-pub2k && PYTHONPATH=/home/ntnghia/projects/yas-pub2k/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_publish_thumbs.py tests/test_publish_kt.py` → **98 passed in 3.53s**. `git diff --check` PASS.
- Không có lệnh verification bị chặn / không chạy được. Full suite và mạng thật không chạy theo giao việc; full suite / thử 4 playlist / apply thật thuộc ORCHESTRATOR. Chưa claim các bước đó PASS.

### Vòng sửa sau chạy thật — 2026-11-02

- Theo phản hồi ORCHESTRATOR: nhận mã KT 1–3 chữ số, vẫn chặn số dài hơn thay vì ghép nhầm tiền tố; so mã bằng `int` nên `KT1`, `KT01`, `KT001` cùng số. `test_clip_number_widths_without_filename` kiểm `T8_KT1`, `T8_KT4`, `T8_KT123` không có fileDetails; `test_code_matching` thêm kiểm khác độ rộng / số 0 đầu và cập nhật biên từ 3 sang 4 chữ số.
- Thêm `kt._title_key`: NFC / casefold qua `thumbs._series`, thay dấu câu / ký hiệu bằng khoảng trắng và gộp khoảng trắng; giữ chữ có dấu tiếng Việt và chữ số. `test_title_warning_only` kiểm dấu hỏi cuối / giữa câu, dấu câu Unicode, NFD / hoa thường / khoảng trắng; `vi tín` khác `vi tính`, khác dấu tiếng Việt hoặc chữ số vẫn cảnh báo. Đã tìm `rg` ở `publish`, `review/names.py`, `post`: helper chuẩn hóa phrase của post phục vụ token bài đăng, helper hashtag xóa khoảng trắng; không phù hợp so tiêu đề KT.
- File sửa trong vòng này: `src/auto_short/publish/kt.py`, `tests/test_publish_kt.py`, mục Result contract. Không sửa test PUB2/PUB2P cũ; không commit / push / PR / gọi mạng thật.
- Dòng cộng dồn so với HEAD: ứng dụng **+132 / −21**; tests **+299 / −0** (kể cả hai file mới chưa tracked).
- Verification đúng lệnh ở trên → **108 passed in 7.07s**; `git diff --check` PASS. Không có lệnh verification bị chặn / không chạy được; chưa chạy lại playlist thật, thuộc ORCHESTRATOR.

### Vòng 3 — Sửa đổi 1, chọn khuôn KT (2026-11-02)

- IMPLEMENTER READY theo Sửa đổi 1 đã duyệt: CLI `kt-thumbs --shape {vertical,landscape}` và `kt.plan(..., shape=...)` mặc định `landscape`. Mỗi row mang khuôn đã chọn; `_thumbnail` chọn đúng ảnh qua provider hiện có và nêu rõ ảnh ngang / dọc thiếu hoặc stale, không fallback sang khuôn khác. Giữ nguyên vòng `apply`, ghi nhật ký theo `row["shape"]`.
- File sửa vòng này: `publish/__main__.py`, `publish/kt.py`, `publish/thumbs.py` (chỉ lý do thiếu ảnh KT), `tests/test_publish_kt.py`, decision PUB2 G2 (khuôn mặc định / tùy chọn; G3 đổi trường shape cố định thành pointer tới lựa chọn G2), mục Result này. Không thêm helper; tái dùng `_thumbnail`, `apply` / `_journal` như trên.
- AC8 → `test_shape_selection` (mặc định / ngang / dọc, có / thiếu ảnh; giữ ảnh khuôn kia để kiểm không fallback), `test_cli_shape_selection` (ảnh upload + row / nhật ký đúng khuôn), `test_shape_change_reapplies_without_force` (dọc → ngang sha khác gắn lại, lần sau bỏ qua). Fixture có cả hai khuôn; test KT cũ điều chỉnh theo mặc định mới hoặc truyền `shape="vertical"` để kiểm hành vi dọc. Test PUB2/PUB2P cũ không sửa.
- Dòng cộng dồn so với HEAD: ứng dụng **+134 / −21**; tests **+356 / −0** (kể cả hai file mới chưa tracked).
- Verification: `PYTHONPATH=/home/ntnghia/projects/yas-pub2k/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_publish_thumbs.py tests/test_publish_kt.py` → **118 passed in 5.87s**; `git diff --check` PASS.
- Không lệnh verification nào bị chặn / không chạy được. Không commit / push / PR; không mạng thật / full suite theo giao việc.
