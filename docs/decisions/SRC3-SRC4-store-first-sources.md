# SRC3 / SRC4 — Sửa tập đã dọn tự lấy nguồn từ 3090; ingest lấy nguồn từ 3090 trước YouTube

| Metadata | Value |
|---|---|
| Status | PROPOSED — chờ HUMAN LEAD chọn G1–G6 |
| Authority | HUMAN LEAD 2026-10-25: "đồng ý, sau khi SRC1 merge mình sẽ viết decision và contract SRC3"; SRC1 G8 "Tải hết toàn bộ video nguồn về backup để khi xử lý không còn phụ thuộc youtube chặn"; "Làm luôn các việc nào làm đc" |
| Change class | S2 (đổi CP8.6 S3: tập `archived` không còn từ chối sửa; đổi CP8.37: chấp nhận bản khác byte có kiểm; đổi luồng ingest: nguồn từ kho 3090) |
| Integration | Push / PR / merge vẫn cần HUMAN LEAD duyệt riêng |

## 1. Bối cảnh — bằng chứng (2026-10-25, đọc read-only)

- Sửa tiêu đề / cắt lại / thêm / khôi phục Short trên tập `archived` trả 409 `ARCHIVED_MESSAGE` ("đã dọn video nguồn; bấm Khôi phục nguồn để sửa", `review/archive.py:35`, `web/routes/episode_edit.py` 5 route). Người dùng phải bấm "Khôi phục nguồn", chờ, rồi làm lại thao tác.
- `restore_source` (CP8.37, SRC1) thử workspace → cache → kho 3090 → YouTube nhưng **chỉ nhận đúng sha256 + size của ingest** (`MISMATCH_MESSAGE`). Bản SRC2 tải lại từ YouTube thường khác byte (TC3.1: `differs_from_ingest`), nên 49 video đã dọn trước SRC1 (≈ 49 giờ) sẽ **không khôi phục được** dù đã có trên 3090.
- `run_ingest` (`ingest/stage.py:134`) chỉ tải YouTube (`_ingest_youtube` → `ytdlp_download`); `needs_download` cho làn prepare chờ khi YouTube chặn. SRC2 đang đẩy 488 video chưa xử lý lên 3090 nhưng ingest chưa dùng bản đó.
- TC3 đã có kiểm âm thanh từng clip (`theme_render/audio.py::compare`, đối chiếu Short đã render với đoạn cắt từ nguồn tải lại, đo lệch `lag`).

## 2. Đề xuất

### SRC3 — Sửa tập đã dọn

- **G1 Tự khôi phục khi sửa (đề xuất: có)**: 5 thao tác sửa trên tập `archived` không trả 409 nữa mà xếp job "Khôi phục nguồn" (làn prepare, thứ tự G5 của SRC1: workspace → cache → 3090 → YouTube; YouTube chặn → chờ như hiện nay) rồi tự chạy thao tác đã yêu cầu (job render như khi chưa dọn). Giao diện hiện "đang lấy lại nguồn từ 3090…". Thao tác lỗi khôi phục → báo lỗi như nút "Khôi phục nguồn" hiện nay, không đổi gì.
- **G2 Bản khác byte (cần chọn)**:
  - **a (đề xuất)**: nhận bản khác sha ingest khi (1) thời lượng khớp như `fetch_to_cache` và (2) **mọi Short đã render** của tập khớp âm thanh với đoạn cắt tương ứng từ bản mới (`audio.compare`, lệch |lag| ≤ 1 khung hình); ghi `restored.json` `differs_from_ingest = true` + sha mới; `manifest.source` giữ sha ingest gốc (không làm stale transcript / analysis). Lệch > 1 khung → từ chối (mốc cắt sẽ sai).
  - b: giữ luật đúng sha; 49 video đã dọn trước SRC1 chỉ sửa được nếu YouTube trả đúng byte cũ (hiếm).
- **G3 Dọn lại**: giữ nguyên — tự dọn chạy lại sau `restored.json` grace (đã có) và chỉ khi kho có bản đúng sha của file sắp xóa (SRC1). Không đổi.
- **G4 Grace tự dọn (cần chọn)**: hiện `auto_archive_grace_minutes = 7200` (5 ngày). Khi đã có bản trên 3090 + G1, có thể giảm: **a (đề xuất) 1440 (1 ngày)**; b giữ 5 ngày. Chỉ đổi `config.toml` (HUMAN LEAD), không code.

### SRC4 — Ingest lấy nguồn từ 3090

- **G5 Ingest từ kho (đề xuất: có)**: tập YouTube chưa ingest: nếu `[store] enabled` và kho có `source` của video → tải từ kho (kiểm sha256 kho, cùng đường mượn của SRC1), ghi `manifest.source` như ingest YouTube (uri YouTube, sha / size của file thật) + `via = "store"`; kho lỗi / không có → YouTube như hiện nay. Khai thị dùng lại nguồn tập gốc như cũ (CP8.9 K5).
- **G6 Không chờ YouTube khi kho có (đề xuất: có)**: `needs_download` trả False khi kho có bản (dựa trên index kho nhớ tạm, không gọi mạng mỗi lần), để job prepare chạy tiếp lúc YouTube đang chặn.

## 3. Ngoài scope

Sửa transcript / analysis khi nguồn khác byte; xóa trên 3090; tự chọn chất lượng; ghép chủ đề (TC3.2).

## 4. Thứ tự làm khi được duyệt

SRC3 và SRC4 có Owned paths rời nhau (SRC3: `review/archive.py`, `web/routes/episode_edit.py`, frontend sửa tập; SRC4: `ingest/stage.py`, `web/jobs.py` phần `needs_download`) → làm song song (pilot ≤ 3 IMPLEMENTER), sau SRC2 / TC3.2. Contract: `docs/tasks/SRC3-auto-restore-on-edit.md`, `docs/tasks/SRC4-ingest-from-store.md`.
