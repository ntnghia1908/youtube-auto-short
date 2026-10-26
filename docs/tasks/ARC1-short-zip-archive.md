# Task: ARC1 — Lưu trữ Short + khai thị về 3090 bằng ZIP tải hàng loạt

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, route + script mới); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-26: "làm đơn giản nhất lưu trữ là tải về file Zip Khai Thị và Short … tải hàng loạt xuống 3090"; chọn "Không đánh dấu Đã đăng" + "Mọi tập có Short + khai thị"; "Chấp nhận tất cả đề xuất khác"
- Parallel group: P1 (cùng FIX-ytdlp-timeout-wait, FIX-offload-incremental — owned paths rời nhau)
- Owned paths: `src/auto_short/web/routes/files_catchall.py` (tùy chọn `archive` + API liệt kê), `src/auto_short/web/episodes.py` (chỉ thêm helper liệt kê / vân tay nếu cần), `scripts/archive/luu-tru-short.ps1` (mới), `tests/test_archive_zips.py` (mới), contract này
- Dependencies: CP8.17 D5 (`all.zip`), CP8.31 D1 (tải ZIP đánh dấu "Đã đăng")
- Base commit / branch: `8cd3d13` (`main`) / `feature/arc1-short-zip-archive`
- Human Lead approval: APPROVED 2026-10-26
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: thêm một query param + một API đọc (sau đăng nhập, như mọi API) và một script Windows ngoài server; không đổi security model, dependency, dữ liệu; CP8.31 D1 giữ nguyên cho nút tải trên web.

## Bối cảnh (2026-10-26)

- Short ~82 GB trên VM. Web đã có "Tải cả hai" (`/files/<id>/all.zip`, `Shorts/` + `KhaiThị/`, ZIP_STORED stream, không `Content-Length`); tải ZIP đánh dấu "Đã đăng" mọi Short trong đó (CP8.31 D1).
- HUMAN LEAD muốn bản lưu trữ trên 3090 (ổ E:), chạy được nhiều lần như `backup.ps1`. Không xóa gì trên VM (giải phóng Short là quyết định riêng sau này).

## Goal

HUMAN LEAD chạy `luu-tru-short.ps1` trên 3090: mọi tập có cả Short + khai thị được tải thành `<thư mục bộ kinh>\<tên zip như web>.zip`, kiểm đủ file; chạy lại chỉ tải ZIP mới / đã đổi (dựng lại Short / khai thị); không Short nào bị đánh dấu "Đã đăng".

## Scope

- In scope:
  - **A1** `GET /files/<id>/all.zip?archive=1`: cùng nội dung / tên như hiện tại, **không** gọi `mark_downloaded`, không `dl` tracking. Không có `archive` → hành vi CP8.31 D1 như cũ.
  - **A2** `GET /api/archive/zips` (cần đăng nhập): mỗi tập có `all_zip` khác None: `video_id`, `series` (tên bộ kinh — như tên file tải), `episode` (số tập hoặc null), `name` (tên zip như `Content-Disposition` của web), `files` (số entry), `bytes` (tổng kích thước entry), `fingerprint` (sha256 của danh sách "tên entry | size | mtime_ns" theo thứ tự ZIP), `url` (`/files/<id>/all.zip?archive=1`). Chỉ `stat`, không đọc nội dung file; thứ tự ổn định (bộ kinh, số tập).
  - **A3** `scripts/archive/luu-tru-short.ps1` (PowerShell 5.1, `curl.exe`, theo mẫu `scripts/backup/backup.template.ps1`: `-Server` mặc định `http://10.8.102.102:8080`, `-Dest` mặc định `E:\LuuTru_Short`, kiểm ổ đích, hỏi mật khẩu / đăng nhập cookie, không cho máy ngủ, log `luu-tru-log.txt`, retry): lấy A2 → với mỗi tập: `danh-sach.csv` (video_id, series, episode, name, files, bytes, fingerprint, ngày tải) cùng fingerprint + file tồn tại → bỏ qua; ngược lại tải vào `.part`, kiểm bằng `System.IO.Compression.ZipFile` (số entry = `files`, tổng độ dài = `bytes`), đúng thì thay file cũ + cập nhật CSV, sai thì xóa `.part`, log, tập khác vẫn chạy. Tóm tắt cuối: đã tải / bỏ qua / lỗi, dung lượng.
  - Test cho A1, A2 (A3 kiểm cú pháp nếu có `pwsh`, nếu không ghi rõ chưa chạy).
- Out of scope: xóa / giải phóng Short trên VM; ZIP chỉ Short (tập không có khai thị); đẩy vào kho 3090 (`store`); generator theo bộ kinh; giao diện web.

## Authority / key decisions

- CP8.17 D5, CP8.31 D1 (giữ cho nút web); HD1 G6 (mẫu script `backup.ps1`).
- Quyết định HUMAN LEAD 2026-10-26: tải lưu trữ không đánh dấu "Đã đăng"; phạm vi mọi tập có Short + khai thị.

## Implementation approach

- Tái dùng `ep.all_zip`, `_zip_stream`, `content_disposition`; vân tay từ `stat` các path trong entries.

## Phải giữ nguyên

- `all.zip` / `shorts.zip` không `archive` đánh dấu "Đã đăng" như cũ; byte ZIP không đổi; mọi test CP8.17 / CP8.31 hiện có.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. `all.zip?archive=1` trả cùng entry / tên như `all.zip`, không Short nào chuyển "Đã đăng"; `all.zip` không tham số vẫn đánh dấu.
2. `/api/archive/zips` liệt kê đúng tập có cả Short + khai thị (tập thiếu một loại không có), đủ trường; dựng lại một Short (đổi mtime / size) → fingerprint đổi; chưa đăng nhập → 401 / chuyển login như API khác.
3. Script: cú pháp hợp lệ; logic bỏ qua theo fingerprint + kiểm ZIP mô tả trong A3 (review đọc code).
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_archive_zips.py` — AC 1–2.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- ORCHESTRATOR: trên 8080 (sau restart), `curl` A2 + tải một `all.zip?archive=1`, kiểm số entry và trạng thái "Đã đăng" không đổi.

## Manual test checklist (Tech Lead)

Không chạm database, security model; thêm 1 API đọc sau đăng nhập.

- [ ] Trên 3090: chạy script, có ZIP trong `E:\LuuTru_Short\<bộ kinh>\`; chạy lại → "bỏ qua" hết.

## Result

- (điền khi READY)
