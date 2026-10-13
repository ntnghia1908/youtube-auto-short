# SR2 — Khai Thị Library Contract (đọc bài đăng trong thư viện Đọc Kinh)

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | HUMAN LEAD 2026-10-12: APPROVE SR2 (K-a–K-d), SR2.1 cùng PR SR1. Hướng đã duyệt: thư viện chia "Đọc Kinh" / "Khai thị"; Khai thị chia theo bộ kinh, mỗi nhóm 10 tập; lấy bài của Short + video khai thị; mỗi bài có nút copy để đăng, copy **tự tick "Đã đăng bài"** như tab Bài đăng; tab Bài đăng giữ nguyên |
| Checkpoint | SR2 (S2) |
| Task contract | `docs/tasks/SR2.1-khaithi-library.md` |
| Builds on | `docs/decisions/SR1-sutra-reader-contract.md` (S3 cấu trúc đọc, S7 phía client); `docs/decisions/CP8.15-community-post-contract.md` P4 (text sao chép), P7 (`posts.json`), P8 (tick "Đã đăng bài"), P16 (xuất `.docx` theo bộ kinh, nhóm 10 tập — CP8.31 A1); `docs/decisions/CL1-chinese-learning-contract.md` C1 |

Khi ACCEPTED, file này là **canonical owner** của: mục "Khai thị" trong thư viện đọc (K1), API đọc bài theo bộ kinh / nhóm tập (K2), trang đọc khai thị và nút copy (K3). Không đổi `posts.json`, tab Bài đăng, quy tắc soạn bài hay `.docx`.

## K1. Boundary

- Dữ liệu bài đăng thuộc Auto Short (CP8.15). API K2 nằm ở **phía host / Auto Short** (`web/app.py` hoặc module mới `web/reading.py`), dùng lại đúng các helper của xuất `.docx` CP8.31 (`_export_episode`, nhóm theo `episode` của playlist, `RANGE_SIZE = 10`, `other=1` cho tập không có số). Package `sutra/` **không** import Auto Short (giữ SR1 S1).
- Phía client: trang đọc SR1 (`sutra.html` / `sutra.js`) nhận thêm một nguồn dữ liệu (K2) cùng dạng S3, nên dùng chung cài đặt, mục lục, lật trang, giữ màn hình sáng. Ẩn đếm biến tụng ở khai thị.
- Chỉ đọc. Không lưu bản sao bài vào `work/_sutras/` → bài sửa ở tab Bài đăng hiện ngay trong thư viện.

## K2. API (sau đăng nhập, `Cache-Control: no-store`)

| API | Kết quả |
|---|---|
| `GET /api/reading/khaithi` | Các bộ kinh có ít nhất một bài: `[{playlist_id, title (series hoặc tên playlist), ranges: [{from, to, label "Tập 1–10", posts}], other: {posts} \| null}]`, theo tên bỏ dấu; thêm mục "Video lẻ" (`playlist_id: "_single"`) cho tập không thuộc bộ nào, nhóm 10 tập theo ngày tạo (mới trước) |
| `GET /api/reading/khaithi/{playlist_id}?from=&to=` hoặc `?other=1` | Một "cuốn" dạng S3 (SR1): `title` = "<bộ> · Tập a–b"; mỗi **tập** là một nhóm (`@`, tiêu đề = heading của `_export_episode`); mỗi **bài** là một mục (tiêu đề = title Short / khai thị kèm mã `T<tập>_S<NN>` / `T<tập>_KT<NN>`; thứ tự như `.docx`: Shorts rồi Khai thị); đoạn = `paragraphs` của bài. Thêm cho mỗi mục: `episode_id`, `clip_id`, `copy_text` (= text sao chép P4, giống tab Bài đăng), `posted`. Giới hạn `to - from < 10` (422), bộ / nhóm không có bài → 404 |

Bài `stale` vẫn hiện (chữ đang lưu), có nhãn nhỏ "Short đã đổi". Bài chưa soạn (chưa có trong `posts.json`) không hiện.

## K3. Trang và copy

- Thư viện `/sutras`: hai tab **Đọc Kinh** (như SR1) | **Khai thị** (danh sách bộ → các nhóm "Tập 1–10", "Tập 11–20"…, số bài, "Đọc tiếp"). Tab đang chọn nhớ trong `localStorage`.
- Trang đọc khai thị: `/sutras/khaithi/{playlist_id}?from=&to=` (hoặc `?other=1`), dùng `sutra.html`. Vị trí đọc lưu khóa `sutra:pos:kt:<playlist_id>:<from>-<to>`.
- Mỗi bài có nút **Copy** dưới tiêu đề: sao chép `copy_text` (cùng cách dự phòng khi không có `navigator.clipboard` trên HTTP như `app.js`), rồi gọi route có sẵn `POST /api/episodes/{episode_id}/posts/{clip_id}/posted` `{value: true}` (P8) → nút hiện "Đã đăng ✓". Copy lại bài đã đăng không gọi lại route. Không tải ảnh (ảnh vẫn ở tab Bài đăng).
- Không đổi tab Bài đăng, `posts.json`, `.docx`.

## Ngoài scope SR2

Tìm kiếm trong khai thị; đánh dấu "đã đọc"; tải ảnh từ thư viện; sửa bài từ thư viện; thứ tự xen kẽ theo thời gian trong video.

## Decision gates (HUMAN LEAD)

| Gate | Đề xuất |
|---|---|
| K-a boundary | API đọc ở phía Auto Short, client dùng chung trang đọc SR1 (K1) |
| K-b nhóm | Theo bộ kinh, 10 tập / nhóm theo số tập (như `.docx` CP8.31), "Video lẻ" riêng (K2) |
| K-c copy | Copy = text tab Bài đăng + tick "Đã đăng bài" qua route P8 có sẵn (K3) |
| K-d dependency | Không thêm |
