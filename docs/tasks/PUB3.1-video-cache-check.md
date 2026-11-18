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

## Result

- Main changes:
