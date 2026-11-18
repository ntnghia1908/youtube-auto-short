# Task: PUB3.1 — Lưu id video kênh (bớt search) + lệnh `check` trùng / thiếu tập

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1 — mở rộng lệnh `publish` của PUB3, chỉ đọc YouTube (không thêm thao tác ghi / scope)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, full suite, chạy thật 4 kênh
- Implementer: codex — mở rộng package `publish` có sẵn, test không cần mạng / socket
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-18: hỏi "nên có cơ chế ghi lại kết quả tìm kiếm" + "upload nháp bị trùng hoặc bị thiếu tập … nên có cơ chế check"; "Người Dân Cực Lạc đăng Thập Thiện Nghiệp Đạo"
- Parallel group: —
- Owned paths: `src/auto_short/publish/youtube.py`, `src/auto_short/publish/schedule.py`, `src/auto_short/publish/check.py` (mới), `src/auto_short/publish/__main__.py`, `tests/test_publish_video_cache.py` (mới), `tests/test_publish_check.py` (mới), contract này
- Dependencies: PUB3 (PR #218)
- Base commit / branch: `651933d` / `feature/pub31-check` (xếp chồng trên `feature/pub3-schedule`)
- Human Lead approval: accepted 2026-11-18 ("Duyệt")
- Implementation authorized: YES

## Goal

1. Chạy `schedule` / `check` nhiều lần trong ngày mà không cạn giới hạn `search.list` 100 lần / ngày / project (client chung CƯT / VLT / Người Dân Cực Lạc; đo 2026-11-18: lỗi 429 `defaultSearchListPerDayPerProject`, đặt lại 15:00 giờ VN).
2. `python -m auto_short.publish check --client … --token … --playlist <PID>` in các video **trùng**, **thiếu** và **lạ** trên kênh so với những gì website đã làm cho bộ đó, để HUMAN LEAD dọn trước khi lên lịch.

## Scope

- In scope: bộ nhớ id video theo kênh + search tăng dần; `--refresh`; lệnh `check` (chỉ đọc); `schedule --playlist` in cảnh báo của `check` trước bảng lịch.
- Out of scope: xóa / sửa video trên YouTube; tự upload; ánh xạ kênh → bộ trong config (người chạy truyền `--playlist`); khóa Short / KT có tên bộ; web UI.

## Authority / key decisions

- PUB2 G1 / G4 (sửa đổi ở PUB3): không thêm thao tác ghi hay scope.
- **C1 bộ nhớ id**: `work/_publish/videos/<channel_id>.json` (atomic, `schema_version` 1: `channel_id`, `ids` (list), `full_scan_at`, `updated_at`). Chỉ lưu id, không lưu trạng thái (trạng thái luôn đọc mới).
- **C2 đọc video** (`YouTube.all_videos(cache=…)`): uploads playlist (như cũ) → `videos.list` theo lô 50 cho id trong bộ nhớ mà uploads không có (id không còn trả về = đã xóa → bỏ khỏi bộ nhớ) → `search forMine type=video order=date` phân trang, **dừng ở trang đầu tiên không có id mới**. Chưa có bộ nhớ hoặc `--refresh` → quét search đủ trang như PUB3. Chỉ ghi bộ nhớ khi đọc xong không lỗi. Ghi số lượt search đã dùng vào dòng tổng.
- **C3 kho website theo bộ** (`--playlist <PID>` như lệnh `kt-thumbs` / `short-thumbs`): mỗi tập trong playlist nguồn (`kt._episodes`) →
  - bản dọc: có khi `render.full.vertical_path` tồn tại hoặc `review.backup.released_vertical` khác None;
  - khai thị: `khaithi_thumbs.titles(config, "<id>.kt")` → `T{n}_KT01…KT{k}`;
  - Short: `khaithi_thumbs.titles(config, "<id>", short=True)` → `T{n}_S01…S{k}`.
  Khóa so khớp theo số tập + loại + số clip (bản dọc: số tập; bỏ tên bộ vì mỗi kênh một bộ — HUMAN LEAD 2026-11-18).
- **C4 phân nhóm** (mọi trạng thái riêng tư / công khai / unlisted / đã lên lịch; phân loại bằng `schedule.classify`):
  - **trùng**: ≥ 2 video cùng khóa → in mọi id, ngày upload, trạng thái; đánh dấu bản giữ = bản có lịch / công khai trước, nếu không thì upload sớm nhất (cùng quy tắc S4 PUB3);
  - **thiếu**: website có, kênh không có, với số tập ≤ tập lớn nhất của loại đó đã có trên kênh (lỗ hổng); tập lớn hơn chỉ in một dòng tổng "chưa đăng T…–T…";
  - **lạ**: kênh có, website không có (vd `T35_S05` khi website chỉ có 4 Short) hoặc không nhận ra loại.
- **C5 ánh xạ đã biết** (ghi ops-notes khi chạy thật, không mã hóa cứng): Hương Quê Cực Lạc → Cảm Ứng Thiên `PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa`; Cực Lạc Là Đây → Vô Lượng Thọ `PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_`; Người Dân Cực Lạc → Thập Thiện Nghiệp Đạo `PLOynZc0cJJfBdXCpRfBeFUeqoz-iOMBRF`; Tín Nguyện Trì Danh → Địa Tạng `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`.

## Implementation approach

- `youtube.py`: `all_videos(cache=None, refresh=False)`; hàm đọc / ghi bộ nhớ dùng `workspace.atomic_write_json` / `read_json_dict`; bộ nhớ hỏng → coi như chưa có (quét đủ), không ghi đè cho tới khi quét xong.
- `check.py`: hàm thuần `inventory(config, pid)` (C3) và `compare(videos, inventory) -> rows/summary` (C4); in bảng gọn theo nhóm + dòng tổng mỗi loại.
- `__main__.py`: subcommand `check` (`--client`, `--token`, `--config`, `--playlist` bắt buộc, `--refresh`); `schedule` thêm `--refresh` và `--playlist` tùy chọn (có thì in phần trùng / thiếu trước bảng; kế hoạch giờ không đổi).
- Tái dùng: `schedule.classify`, `kt._episodes`, `khaithi_thumbs.titles`, `render.full.vertical_path`, `review.backup.released_vertical`, transport giả như `tests/test_publish_schedule.py`.

## Phải giữ nguyên

- Kế hoạch giờ / `--apply` của `schedule` (S1–S8 PUB3) và test PUB3 PASS không sửa; các lệnh `auth`, `thumbs`, `kt-thumbs`, `short-thumbs`, web đọc token.
- `check` không gọi API ghi nào.

## Code bị thay / xóa

- Không có (đường quét search đủ trang của PUB3 thành nhánh "chưa có bộ nhớ / `--refresh`").

## Acceptance Criteria

1. Lần đầu (không bộ nhớ) quét search đủ trang và ghi bộ nhớ; lần sau chỉ gọi search tới trang đầu không có id mới (test: 1 lượt khi không có video mới), video riêng tư cũ vẫn có nhờ `videos.list` theo id.
2. Id trong bộ nhớ không còn trả về bị bỏ khỏi bộ nhớ; bộ nhớ hỏng → quét đủ; lỗi giữa chừng → bộ nhớ cũ giữ nguyên; `--refresh` quét đủ.
3. `inventory` đúng C3 (bản dọc local hoặc đã giải phóng; số KT / Short theo titles; tập không có marker khai thị → không có KT).
4. `compare` đúng C4: trùng (bản giữ đúng quy tắc), thiếu chỉ trong lỗ hổng + dòng "chưa đăng", lạ.
5. `check` chỉ GET; `schedule --playlist` in cảnh báo mà giờ xếp giống hệt khi không có `--playlist`.
6. Test PUB3 và test publish cũ PASS không sửa.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_publish_video_cache.py tests/test_publish_check.py tests/test_publish_schedule.py tests/test_publish_thumbs.py tests/test_publish_kt.py tests/test_publish_shorts.py` — AC1–6 (IMPLEMENTER, sandbox).
- `PYTHONPATH=src python -m pytest -q -n auto` — full suite (ORCHESTRATOR).
- Chạy thật (ORCHESTRATOR, sau 15:00 giờ VN): `check` 4 kênh theo C5 (lần đầu quét đủ), chạy lại `check` → mỗi kênh ≤ 1–2 lượt search; đối chiếu nhóm trùng với số PUB3 (VLT 14, Người Dân Cực Lạc 2).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract (chỉ đọc YouTube bằng token sẵn có).

- [ ] HUMAN LEAD xem bảng `check` 4 kênh, xác nhận trùng / thiếu đúng với Studio.
- [ ] Sau khi dọn: `schedule` chạy thử → duyệt → `--apply` (manual test PUB3).

## Amendment B — danh sách phát + client theo token (HUMAN LEAD 2026-11-18)

Nguồn duyệt: HUMAN LEAD 2026-11-18 "T21_KT01 đã đúng nhưng chưa được thêm vào danh sách phát" → đề xuất của ORCHESTRATOR (chọn danh sách theo tên) → "1. Đồng ý". Thêm thao tác ghi `playlistItems.insert` (mở rộng PUB2 G1 như PUB3; scope `youtube` đã có). Mỗi kênh nay có client OAuth riêng (CƯT `youtube-client-cut.json`, VLT `youtube-client-vlt.json`, Tín Nguyện `youtube-client-tntd.json`, Người Dân Cực Lạc `youtube-client.json`).

- **B1 chọn danh sách phát** (hàm thuần trong module mới `publish/playlists.py`; Owned paths thêm file này + `tests/test_publish_playlists.py`): đọc `playlists.list mine=true` (phân trang). Tiêu đề chuẩn hóa NFC, không phân biệt hoa thường:
  - khai thị: `^\[\s*Tập\s+a\s*-\s*b\s*\]\s*Kh[aạ]i\s*Th[ịi]\s*Ng[ắa]n` với a ≤ tập ≤ b;
  - Short: `^\[\s*Tập\s+a\s*-\s*b\s*\]\s*Short` với a ≤ tập ≤ b;
  - bản dọc: tiêu đề chứa `[HD Mobile]` / `[HD - Mobile]` / `[HD Moblie]` (không phân biệt hoa thường, khoảng trắng / gạch tùy ý);
  - 0 danh sách khớp → "thiếu danh sách phát"; ≥ 2 khớp → "nhiều danh sách phát khớp" (không tự chọn).
- **B2 `schedule --apply`**: với mỗi video đặt lịch thành công, nếu video chưa có trong danh sách đã chọn (`playlistItems.list playlistId=…` đọc một lần mỗi danh sách, cache trong lần chạy) → `POST playlistItems?part=snippet` thêm cuối danh sách. Thiếu / nhiều danh sách → vẫn đặt lịch, cột lý do ghi cảnh báo. Lỗi ghi danh sách phát → dừng như lỗi API S6 (video đã đặt lịch vẫn trong nhật ký; chạy lại sẽ thấy video "đã có lịch" → B3 bù). Bảng chạy thử in thêm cột "Danh sách phát" (tên danh sách sẽ thêm, hoặc cảnh báo).
- **B3 `check`**: thêm nhóm **"chưa vào danh sách phát"** = video đã nhận ra loại, công khai / unlisted / đã lên lịch, không nằm trong danh sách B1 tương ứng. `check --add-playlists` (chỉ cờ này mới ghi; `check` mặc định vẫn chỉ GET) thêm các video đó, theo thứ tự tập / số clip; quota dừng như S6.
- **B4 client theo token**: `auth` ghi đường dẫn tuyệt đối của client vào file token (khóa `client_path`, không phải secret); khi refresh giữ khóa này. `YouTube(client_path=None, …)` dùng `client_path` trong token nếu có, nếu không mới dùng `default_client()`. `--client` truyền rõ vẫn thắng. Nhờ đó web (LNK1 `post_links._clients`, không sửa file web) và mọi lệnh dùng đúng client mỗi kênh. Token cũ không có khóa → hành vi như cũ (ORCHESTRATOR tự thêm khóa cho 4 token sau khi merge).

AC bổ sung:

7. B1: khớp đúng các mẫu tiêu đề thật (`[Tập 01-20] Khai thị Ngắn Thái Thượng…`, `[ Tập 01-20] Khai Thị Ngắn - …`, `[Tập 121-128] Short - …`, `[HD Moblie] …`, `[HD - Mobile] …`); 0 / ≥ 2 khớp cho cảnh báo đúng.
8. B2: chạy thử không ghi; `--apply` thêm vào đúng danh sách sau mỗi lần đặt lịch, bỏ qua video đã có trong danh sách, thiếu / nhiều danh sách → vẫn đặt lịch + cảnh báo; lỗi API dừng, nhật ký giữ.
9. B3: `check` không ghi; `--add-playlists` chỉ thêm video thiếu, đúng thứ tự.
10. B4: token mới có `client_path`; refresh giữ khóa; `YouTube()` không truyền client dùng client trong token; `--client` thắng; token cũ dùng client mặc định; test web LNK1 cũ PASS không sửa.

Verification bổ sung: thêm `tests/test_publish_playlists.py` và `tests/test_post_links*.py` (nếu có) vào lệnh targeted. Chạy thật (ORCHESTRATOR): `check` CƯT → bảng "chưa vào danh sách phát"; `schedule --apply` CƯT 15 khai thị + 32 Short còn lại (HUMAN LEAD đã duyệt bảng), xác nhận trong Studio.

## Result

- Main changes: `YouTube.all_videos(cache=None, refresh=False)` đọc uploads, đọc mới metadata của id đã lưu theo lô 50, search tăng dần theo ngày và chỉ ghi cache atomic sau khi hoàn tất. Cache chỉ giữ id + timestamp, tách theo channel id lấy từ phản hồi uploads; xóa id không còn trả về. `check.py` lập inventory bằng helper C3, so sánh C4 và in nhóm trùng / thiếu / lạ, bản giữ và dòng "chưa đăng" theo loại. CLI thêm `check`, `--refresh`, `schedule --playlist` và tổng lượt search. `schedule.py` bổ sung nhận diện / so trùng bản dọc trong vòng sửa 1 bên dưới; các test PUB3 / publish cũ không đổi.
- Compatibility: không truyền cache giữ đường quét PUB3; phản hồi uploads thiếu channel id an toàn thì quét đủ và không ghi cache, tránh gán dữ liệu nhầm kênh. Khi CLI có channel id hợp lệ, cả chạy thử và apply đều cập nhật cache id; thuật toán xếp giờ và status PUB3 giữ nguyên, phần so trùng bản dọc mở rộng theo vòng sửa 1; Amendment B nối thêm thao tác danh sách phát sau khi ghi nhật ký lịch.
- AC → test (tên trong hai file test mới, trừ AC6):

  | AC | Test |
  |---|---|
  | 1 | `test_first_scan_and_repeat_read_private_metadata_in_batches`; `test_incremental_search_continues_for_new_upload_and_new_private` |
  | 2 | `test_deleted_ids_pruned_and_caches_isolated_by_channel`; `test_damaged_cache_forces_full_scan`; `test_refresh_scans_all_pages_despite_known_ids`; `test_error_never_replaces_old_or_creates_partial_cache` |
  | 3 | `test_inventory_local_released_vertical_and_resolved_titles` (artifact thật: local / released, resolved titles / rejected, thiếu marker KT) |
  | 4 | `test_compare_duplicate_keep_priority_and_earliest_upload`; `test_compare_holes_pending_and_unexpected_by_independent_kind` |
  | 5 | `test_check_cli_get_only_and_refresh_cache`; `test_schedule_playlist_warnings_preserve_slots_and_apply`; `test_check_requires_playlist_and_validates_local_before_http` |
  | 6 | Toàn bộ `test_publish_schedule.py`, `test_publish_thumbs.py`, `test_publish_kt.py`, `test_publish_shorts.py` không sửa, PASS trong lệnh chung |

- Test budget: AC2 dùng 4 hàm vì 4 chuyển trạng thái độc lập (id bị xóa / cache hỏng / refresh chủ động / lỗi giữa chừng); các nhánh tương tự đã parametrize. Tái dùng fixture / transport hiện có, helper test mới chỉ dùng trong `test_publish_video_cache.py`.
- Verification IMPLEMENTER: `PYTHONPATH=src python -m pytest -q tests/test_publish_video_cache.py tests/test_publish_check.py tests/test_publish_schedule.py tests/test_publish_thumbs.py tests/test_publish_kt.py tests/test_publish_shorts.py` — **269 passed in 13.26s**, với `PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH`. Lần đầu dùng Python mặc định `/home/ntnghia/miniconda3/bin/python` không chạy được: `No module named pytest`; không cài dependency, chuyển sang môi trường `auto-short` có sẵn. `git diff --check` PASS.
- Diff + / − (đo bằng `git diff --numstat`, file mới bằng `git diff --no-index --numstat /dev/null <file>`): app **+167 / −6**; test **+290 / −0**. Không tính contract.
- Helper mới: `_video_cache` (validate schema cache riêng, tái dùng `read_json_dict`, ghi bằng `atomic_write_json`); `inventory` / `compare` / `report` (boundary mới của task, chưa có helper tương đương); `_code` (mã C4 bỏ tên bộ của bản dọc); `_keep_order` (ưu tiên bản giữ cho mọi trạng thái, dùng lại `schedule._timestamp`, không đổi planner); `_video_row` (chỉ lấy id / upload / privacy / lịch / title cho report; `kt._video_row` phụ thuộc pid / shape và trả tuple nên không dùng được). Đã tìm bằng `rg -n 'def (titles|vertical_path|released_vertical|read_json_dict)|PUB3|def local|def listing' ...` và `rg -n 'def (_video_cache|inventory|compare|report|_code|_keep_order|_video_row)|classify|_episodes|released_vertical|atomic_write_json|read_json_dict' src/auto_short/publish src/auto_short/workspace.py src/auto_short/review/backup.py`; tái dùng toàn bộ helper C3 và `schedule.classify` thay vì viết lại phân loại / đọc kho.
- Review / handoff: diff đã tự rà theo C1–C4, AC1–6; chỉ các Owned paths và Result này thay đổi. Sẵn sàng ORCHESTRATOR review phần IMPLEMENTER; chưa tuyên bố READY toàn task.
- Chưa chạy (phân công ORCHESTRATOR, ngoài phạm vi IMPLEMENTER): `PYTHONPATH=src python -m pytest -q -n auto`; `check` thật 4 kênh, chạy lại đo 1–2 lượt search và đối chiếu trùng VLT / Người Dân Cực Lạc. Không gọi mạng thật, không commit / push / PR; manual checklist phía trên còn chờ HUMAN LEAD.
- Vòng sửa 1 (ORCHESTRATOR 2026-11-18, bằng chứng chạy thật CƯT; sửa đổi nhỏ AC1 PUB3): nhận thêm `<bộ>_Tập<N>_Doc(.mp4)` không phân biệt hoa thường, NFC; fileName không nhận ra được thử title bản dọc, bao gồm `[HD mobile] <bộ> - PS. Tịnh Không - Tập N`. FileName nhận ra vẫn ưu tiên hơn title. 29 video không fileName / không mã tiếp tục là "lạ". Không chạy lại kênh thật trong sandbox; test tái hiện bằng fixture theo bằng chứng 25 bản dọc + 29 video không mã.
- Phạm vi fallback vòng 1: giữ yêu cầu không sửa test PUB3 cũ, nên fallback bổ sung từ fileName lạ chỉ nhận title bản dọc. Test `test_classification_filename_priority_and_fallback` hiện yêu cầu fileName lạ + title mã Short vẫn không nhận ra; thử fallback mọi loại đã xác nhận xung đột này (1 failed, 282 passed), sau đó thu hẹp cho bản dọc. Khi thiếu fileName, title Short / KT vẫn được nhận như trước. Đã nêu lựa chọn phạm vi cho ORCHESTRATOR; triển khai mặc định tối thiểu để xử lý ca CƯT và giữ regression suite.
- Khóa so trùng vòng 1: `_duplicate_key` chỉ bỏ đuôi ` ps tịnh không` của series bản dọc khi planner đặt / tra khóa đã có; giữ `series` / `key` do `classify` trả về và thứ tự xếp giờ. Cách nhỏ này nối tên file cũ với bản HD Mobile có tên giảng sư, không dùng tiền tố tùy ý để gộp cả bộ "… Chú Giải". `check.compare` vẫn bỏ series như C3 / C4. `apply` không đổi; giữ nguyên Amendment A từ base rebase `3f5e084`: luôn gửi `selfDeclaredMadeForKids=False`.
- AC → test vòng 1: `test_legacy_vertical_classification_and_title_fallback` (9 ca: hoa thường, NFD, có / không `.mp4`, title có dấu ngoặc / gạch, ưu tiên fileName, tên lạ); `test_check_legacy_verticals_fill_25_episodes_and_leave_29_unknown` (AC4, fixture CƯT không còn thiếu bản dọc); `test_legacy_vertical_blocks_modern_draft_without_merging_other_series` (4 trạng thái, cả hai thứ tự input; bản cũ chặn bản mới, bộ khác không bị gộp). Tất cả nằm trong `tests/test_publish_check.py`; test PUB3 cũ không sửa.
- Helper vòng 1: tách `_classify_name` từ thân `classify` để dùng chung parser cho fileName / title, tái dùng `kt._code`, `kt._title_key`, `nfc`; thêm `_duplicate_key` dùng tại hai điểm đặt / tra khóa trong `plan`. Đã tìm `rg -n 'classify|duplicate|series|title_key' src/auto_short/publish/schedule.py src/auto_short/publish/kt.py src/auto_short/publish/thumbs.py`; `_same_series` hiện giữ dấu ` - `, không khớp khóa đã chuẩn hóa mất dấu câu nên không dùng để so khóa planner.
- Verification vòng 1: chạy lại đúng lệnh targeted ở trên trong môi trường `auto-short` — **283 passed in 13.05s**; `git diff --check` PASS. Không có lệnh targeted nào không chạy được trong vòng này. Full suite / chạy thật sau sửa vẫn dành cho ORCHESTRATOR.
- Diff vòng 1: app **+29 / −10**; test **+52 / −0** so với lần bàn giao trước. Tổng task trên HEAD contract sau rebase: app **+196 / −16**, test **+342 / −0** (không tính contract). Không commit / push / PR, không gọi mạng hoặc agent khác. Sẵn sàng ORCHESTRATOR review vòng sửa 1; chưa tuyên bố READY toàn task.
- Vòng 2 — Amendment B: `playlists.select` khớp loại / khoảng tập theo các mẫu B1 (NFC, không phân biệt hoa thường), cảnh báo khi thiếu / mơ hồ; không tạo danh sách mới. `schedule` in thêm cột "Danh sách phát"; apply đặt lịch → ghi nhật ký atomic → đọc thành viên một lần mỗi danh sách / lần chạy → thêm video còn thiếu. Thiếu / nhiều danh sách vẫn đặt lịch và ghi cảnh báo trong lý do. Lỗi thêm dừng ngay, nhật ký lịch đã thành công được giữ để B3 bù.
- B3: nhóm "Chưa vào danh sách phát" chứa video đã phân loại, công khai / unlisted / đã lên lịch nhưng chưa có trong danh sách được chọn; mục không có đích duy nhất hiển thị cảnh báo và không ghi. `check` mặc định giữ client read-only; chỉ `--add-playlists` thêm các video thiếu theo tập / số clip. Cache thành viên dùng chung khi so sánh và ghi, cập nhật sau mỗi lần thêm thành công; chạy lại không thêm trùng.
- B4: `auth` lưu `client_path` tuyệt đối trong token private hiện có; refresh giữ khóa. Thứ tự chọn client: tham số rõ → đường dẫn trong token → `default_client()`. Không sửa file web; `post_links._clients` tự nhận thay đổi qua `YouTube(token_path=…, read_only=True)`. Quyền ghi vẫn bị chặn trước OAuth refresh khi client read-only.
- Giữ nguyên vòng trước / Amendment A: cache video, inventory, phân loại tên file cũ và khóa so trùng không đổi; `selfDeclaredMadeForKids=False` vẫn luôn gửi khi đặt lịch. Phản hồi uploads không có channel id tiếp tục nhánh tương thích cũ: không ghi cache hay tự chọn playlist, hiển thị cảnh báo thiếu danh sách. `tests/test_publish_check.py` chỉ thêm phản hồi GET danh sách phát rỗng vào transport của các test CLI; giữ nguyên assertions. Các test PUB3 / thumbnail / KT / Short và file web không sửa.
- AC → test Amendment B (đều trong `tests/test_publish_playlists.py`):

  | AC | Test |
  |---|---|
  | 7 | `test_select_real_playlist_titles_nfc_case_and_range`; `test_select_missing_and_ambiguous_never_guesses`; `test_playlist_api_pagination_membership_fields_and_validation` |
  | 8 | `test_schedule_dry_run_and_apply_add_only_absent_members_after_journal`; `test_schedule_missing_or_ambiguous_playlist_still_schedules_with_warning`; `test_schedule_playlist_error_stops_with_journal_then_check_repairs` |
  | 9 | `test_check_read_only_or_adds_missing_sorted_and_idempotently`; `test_check_add_warns_without_guessing_and_stops_on_quota` |
  | 10 | `test_auth_saves_absolute_client_path_and_refresh_keeps_binding`; `test_client_precedence_refresh_and_web_read_only_guard`; regression web LNK1 còn chờ ORCHESTRATOR |

- Helper mới vòng 2: `playlists.select` / `assign` (chọn theo B1, trang trí bảng mà không đổi giờ); `Memberships.contains` / `add` (cache id theo danh sách trong lần chạy, chống thêm lại); `check.missing_playlists` (tái dùng `schedule.classify`, `_video_row`, `_code`); `YouTube.owned_playlists` / `playlist_ids` / `add_to_playlist` (các boundary API B1–B3). `_pages` tách từ vòng phân trang `_playlist_videos` cũ; `_playlist_videos` dùng lại `playlist_ids` và `_videos_by_ids`, không giữ bản copy vòng lặp. Đã tìm `rg -n 'def .*playlist|playlistItems|client_path' src/auto_short/publish tests/test_publish*.py`: helper cũ chỉ đọc metadata của playlist cụ thể / thumbnail, chưa có chọn khoảng tập, đọc catalog mine hoặc chèn playlist item. B4 dùng lại `_token_doc`, `_save_token`, `_credentials`, `_refresh`; không thêm helper token riêng. Fixture / transport dùng lại từ test PUB3 / publish; helper test mới chỉ dùng trong file mới.
- Verification vòng 2: `PYTHONPATH=src python -m pytest -q tests/test_publish_playlists.py tests/test_publish_video_cache.py tests/test_publish_check.py tests/test_publish_schedule.py tests/test_publish_thumbs.py tests/test_publish_kt.py tests/test_publish_shorts.py`, với `PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH` — **323 passed in 13.67s**. Lượt đầu 2 failed do fixture theo dõi nhật ký bắt cả request uploads trước khi đặt lịch; đã sửa fixture chỉ theo dõi playlist đích, không đổi assertions về thứ tự ghi. `git diff --check` PASS.
- Chưa chạy vòng 2: `PYTHONPATH=src python -m pytest -q tests/test_post_links.py` (web LNK1, theo giới hạn socket sandbox do ORCHESTRATOR giao); `PYTHONPATH=src python -m pytest -q -n auto`; kiểm tra kênh thật / Studio sau sửa. ORCHESTRATOR chạy các phần này; không claim PASS AC10 phần regression web.
- Diff vòng 2 (so với snapshot lần bàn giao trước, `git diff --no-index --numstat`): app **+161 / −33**, test **+262 / −4**. Tổng task trên HEAD contract sau rebase: app **+351 / −43**, test **+600 / −0** (không tính contract). Diff đã rà theo B1–B4 / AC7–10 và Owned paths; không commit / push / PR, không gọi mạng thật / agent khác. Sẵn sàng ORCHESTRATOR review vòng 2, chưa tuyên bố READY toàn task.
