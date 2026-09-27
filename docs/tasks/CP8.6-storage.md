# Task: CP8.6 — Storage Tab + Cleanup Recommendations

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `cc86540` (`feature/cp8.5-web-review`, implement xong + review, stacked) / `feature/cp8.6-storage`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-27; S1–S4; P1 7 ngày; P2 10 GB / 3 GB; P3 gộp chung PR)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm thao tác xóa dữ liệu mới (dọn video nguồn) làm episode chuyển sang trạng thái "chỉ xem" — rule mới xuyên pipeline/web (chặn sửa title, khôi phục, chạy lại); đổi API/UI web (CP8.3). Yêu cầu HUMAN LEAD 2026-09-27. Không thêm dependency.

## Goal

Tab "Bộ nhớ" trên web cho biết ổ đĩa server còn bao nhiêu, mỗi tập chiếm bao nhiêu (video nguồn / Short / khác), và gợi ý dọn dẹp cụ thể kèm nút làm luôn — để giữ server không đầy.

## Scope

- In scope:
  - Tab "Bộ nhớ" (S1): tổng/đã dùng/còn trống của ổ chứa `work/` và `output/`; bảng từng tập; dung lượng cache khác (model Whisper `models/`).
  - Gợi ý dọn dẹp (S2) + nút hành động: dọn video nguồn (S3), xóa cả tập (CP8.5 X3).
  - Cảnh báo khi ổ còn ít (S4).
  - Tests + chạy thật trên bản sao + HUMAN LEAD thử.
  - Docs: CP8.3 record (tab, API, archived), README, contract Result.
- Out of scope:
  - Tự động xóa theo lịch (không tự xóa gì khi người dùng chưa bấm).
  - Dọn file tạm ngoài `work/`/`output/` của hệ thống; quản lý model Ollama (máy GPU riêng).

## Authority / key decisions

- Dữ kiện đo 2026-09-27: ổ `/` 98 GB, dùng 31 GB, trống 63 GB. Mỗi tập ≈ 650–700 MB video nguồn (`work/<id>/source.mp4`) + 180–300 MB Short (`output/<id>/`), JSON < 5 MB. `models/` (Whisper) 1.6 GB. → Video nguồn chiếm ≈ 70 % dung lượng mỗi tập; ổ hiện chứa thêm được ≈ 60–70 tập.
- Quyết định (DECIDE cùng APPROVE TASK):
  - **S1 Tab Bộ nhớ:** `shutil.disk_usage` của ổ chứa `workspace.dir` (và `output_dir` nếu khác ổ); mỗi tập: video nguồn, Short, khác, tổng, số Short đã đăng / tổng, trạng thái (đang xử lý / xong / đã dọn nguồn); sắp xếp theo dung lượng. Tính bằng `os.scandir` (không gọi `du`), cache ≤ 30 s.
  - **S2 Gợi ý (theo thứ tự ưu tiên, chỉ gợi ý — người dùng bấm mới làm):**
    1. Tập đã đăng hết Short → "Xóa cả tập" (giải phóng toàn bộ) hoặc "Dọn video nguồn" (giữ Short để tải lại).
    2. Tập xong render > 7 ngày còn video nguồn → "Dọn video nguồn" (≈ 650 MB/tập).
    3. Tập lỗi / dở dang > 7 ngày → "Xóa cả tập".
    Mỗi gợi ý ghi dung lượng sẽ giải phóng; nút "Làm" hỏi xác nhận.
  - **S3 Dọn video nguồn (giữ Short):** xóa `work/<id>/source.*` (chỉ nguồn YouTube tải về; nguồn local ngoài workspace không bao giờ xóa); ghi cờ `archived` (vd `work/<id>/archive.json` hoặc trường trong `publish.json` — implement chọn, ghi decision record). Tập archived: **vẫn xem/tải/tick đã đăng/xóa Short** được; **không** sửa title, khôi phục Short, hay gửi lại URL (409 + thông báo "đã dọn video nguồn; muốn sửa thì xóa tập rồi chạy lại") — vì tải lại video có thể khác byte → cả pipeline chạy lại, AI chọn clip/title khác (CP5/CP6 không tất định).
  - **S4 Cảnh báo:** ổ còn < 10 GB (hoặc < 10 %) → banner đỏ trên mọi trang + chặn gửi URL mới khi < 3 GB (một tập cần ≈ 1 GB + chỗ tạm render).
- Đã chốt (APPROVE TASK 2026-09-27, theo đề xuất):
  - **P1 Ngưỡng "cũ":** 7 ngày (đề xuất).
  - **P2 Ngưỡng cảnh báo / chặn:** 10 GB / 3 GB (đề xuất).
  - **P3 Push:** gộp CP8.6 vào cùng PR CP8–CP8.5 (đề xuất).

## Acceptance Criteria

1. Tab Bộ nhớ hiển thị đúng số liệu ổ + từng tập (so với `du -sb` sai lệch ≤ 1 %).
2. Gợi ý đúng theo S2 trên dữ liệu thử (tập đã đăng hết, tập cũ, tập lỗi — thời gian giả trong test).
3. Dọn video nguồn trên bản sao tập 29: giải phóng ≈ 648 MB; Short vẫn xem/tải được (sha256 không đổi); sửa title / khôi phục / gửi lại URL → 409 + thông báo; nguồn local không bị xóa.
4. Cảnh báo / chặn theo ngưỡng (test với disk usage giả).
5. Test cũ + mới PASS; framework-check PASS; docs cập nhật.

## Required verification

- `pytest -q` — AC1–AC5.
- Chạy thật trên bản sao dữ liệu (server thử cổng riêng) — AC1, AC3.
- HUMAN LEAD xem tab Bộ nhớ trên web thật (manual).
- `node scripts/framework-check.mjs` — AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Thêm thao tác xóa dữ liệu → manual test là gate.

- [ ] Xem tab Bộ nhớ, số liệu hợp lý.
- [ ] Dọn video nguồn một tập đã đăng hết; Short vẫn tải được.

## Result

- Main changes:
  - `review/archive.py` (S3): `archive_source` (chỉ `source.*` của nguồn YouTube đã render `done`; ghi `archive.json` rồi xóa), `is_archived` / `read_archive`, `ArchivedError` (thông báo contract), `reject_archived_clip` (xóa Short không cần render). Chặn trên tập archived: `set_title` / `set_alternative` / `reset_title` / `restore_clip` (`ArchivedError`), `run_render` và `run_ingest` từ chối trước khi đụng manifest.
  - `web/storage.py` (S1, S2, S4): `tree_size` (`os.scandir`), `episode_sizes`, `recommend` (thời gian tiêm được), `disk_info` / `warning` (10 GB hoặc 10 %, chặn < 3 GB), `StorageCache` (≤ 30 s).
  - `web/app.py`: `GET /storage`, `GET /api/storage`, `GET /api/storage/status`, `POST /api/episodes/{id}/archive`; gửi URL: archived → 409, ổ < 3 GB → 507; sửa title / khôi phục archived → 409; xóa Short trên tập archived → áp thẳng, không job; `create_app(disk_usage=…, clock=…)`. `web/episodes.py`: `archived` trong view + danh sách.
  - UI: trang `storage.html` (thanh ổ, gợi ý + nút "Làm" có xác nhận, bảng từng tập, cache model), link "Bộ nhớ" + banner đỏ trên mọi trang, ghi chú / ẩn chức năng trên tập archived.
  - Docs: CP8.3 record W4, W7, W9 + số đo + giới hạn; pointer ở CP2 D4, CP7 R10, CP8.2 (hàm dùng chung); project profile; README.
- Tests: `pytest -q` 563 passed (mới `tests/test_storage_cp86.py` 19: kích thước so `du -sb`, trạng thái, 3 luật gợi ý + ưu tiên với "now" giả, ngưỡng cảnh báo / chặn với disk usage giả, cache 30 s, dọn nguồn + chặn review/render/ingest, nguồn local / render chưa xong, xóa Short trên tập archived, route + 409 + 507). `node scripts/framework-check.mjs` PASS. Chạy thật trên bản sao scratch (hardlink) của tập 29 + `rbjfCfFq3Dk` + 2 workspace giả, server `127.0.0.1:8081`: AC1 (lệch `du -sb` 0 %), AC2 (luật 1 và 3), AC3 (giải phóng 678 949 583 B ≈ 648 MiB, 20 Short sha256 không đổi và tải được, 5 thao tác → 409 đúng thông báo, nguồn local không bị xóa) — số đo ở `docs/decisions/CP8.3-web-contract.md` § CP8.6. Thư mục chính: 26 sha256 (mp4, manifest, video nguồn tập 29, file input local) không đổi trước/sau.
- Review: chờ ORCHESTRATOR.
- Important findings / decisions:
  - Cờ archived = file `work/<id>/archive.json` (không dùng `publish.json`: đây là trạng thái pipeline). File hỏng vẫn coi là archived.
  - Xóa Short trên tập archived phải bỏ qua stage render (không có nguồn): ghi `review.json` + sửa trực tiếp `render_manifest.json` (entry `skipped`/`rejected`, stats) + xóa mp4; không khôi phục được.
  - Chặn archived cả ở `ingest` / `render` (CLI) chứ không chỉ web, để `auto-short run` không tải lại và chạy lại AI.
  - Chặn < 3 GB áp cho mọi lần gửi URL cần job mới (cả gửi lại tập cũ), mã 507; ngưỡng là hằng (P2).
  - Luật 1 cho tập đã archived chỉ còn "Xóa cả tập".
  - "Cache khác" đọc `models_dir` của config; lần thử đọc (chỉ quét kích thước) `models/` của thư mục chính.
- Known limitations: xem `docs/decisions/CP8.3-web-contract.md` § Giới hạn đã biết (CP8.6). Chưa kiểm UI trên trình duyệt thật (manual gate HUMAN LEAD).
- PR: gộp chung PR CP8–CP8.5 (P3); chưa push.
