# Task: FIX-image-library-thumbs — Lưới Thư viện ảnh dùng ảnh thu nhỏ

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1 — thêm query `thumb` (tùy chọn) cho `GET /files/post-images/{name}` và đổi URL ảnh trong lưới; không đổi dữ liệu thư viện / tên file / dependency
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota 5 giờ 21 %, tuần 34 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-25: "Thư viện ảnh hiện load ảnh rất chậm có cách nào cải thiện?" → đề xuất ảnh thu nhỏ → "Đồng ý"
- Parallel group: —
- Owned paths: `src/auto_short/web/routes/post_images.py` (chỉ `post_image_file`), `src/auto_short/post/images.py` (helper ảnh thu nhỏ của thư viện), `src/auto_short/web/static/app.js` (chỉ URL `<img>` trong lưới thư viện, `renderImageGrid`), test mới `tests/test_web_image_library_thumbs.py`, file này
- Dependencies: none
- Base commit / branch: `e7b2455` (origin/main) / `fix/image-library-thumbs` (worktree `~/projects/yas-imgthumb`)
- Human Lead approval: accepted 2026-11-25
- Implementation authorized: YES

## Bằng chứng (2026-11-25)

- Thư viện thật: 831 ảnh, 1,9 GB (trung bình ~2,3 MB; PNG AI 1024×1024 ~2,9 MB).
- Lưới (`app.js` `renderImageGrid`, `el("img", { src: "/files/post-images/<name>", loading: "lazy" })`) tải ảnh gốc cho ô nhỏ → mỗi màn hình hàng trăm MB.
- `GET /api/post-images` chỉ 0,8 s / 134 KB — không phải nút cổ chai.
- Đã có helper `dhash.thumbnail(data, width)` (ffmpeg → JPEG) dùng cho ảnh ứng viên (`imgsearch.candidate_file(..., thumb=True)`, `?thumb=1`).

## Goal

Lưới ảnh (trang Thư viện ảnh và hộp chọn ảnh của bài đăng) tải nhanh: mỗi ô dùng JPEG thu nhỏ vài chục KB; ảnh gốc vẫn dùng cho tải về, xem lớn và bài đăng.

## Scope

- In scope: `GET /files/post-images/{name}?thumb=1` trả JPEG rộng ≤ 400 px, tạo lần đầu từ ảnh gốc rồi lưu cache trên đĩa; lưới dùng URL `?thumb=1`.
- Out of scope: ảnh gốc, `list_images` / `next_name` / thứ tự, ảnh trong bài đăng và khung xem ảnh hiện tại của bài (`app.js` ~351, ~2263), ảnh ứng viên, dọn cache tự động, tạo trước hàng loạt.

## Implementation approach

- Cache ngoài thư viện (không bao giờ trong `image_dir`, vì `list_images` quét thư mục đó): thư mục con trong `imgsearch.cache_dir(image_dir)`, tên không khớp `SEARCH_ID_RE` (kiểm mọi chỗ duyệt `cache_dir` vẫn bỏ qua nó). Khóa cache gắn tên + mtime_ns + size của ảnh gốc → ảnh bị thay / xóa rồi tạo lại cùng tên không dùng nhầm ảnh cũ.
- Tái dùng `dhash.thumbnail`; ghi atomic. Thumbnail lỗi (ffmpeg không đọc được) → trả ảnh gốc, không 500.
- Tên ảnh vẫn qua `post_images.resolve` (chống path traversal). `download` + `thumb` cùng lúc → ảnh gốc.

## Phải giữ nguyên

- `GET /files/post-images/{name}` không có `thumb`: byte, content-type, header như cũ (kể cả `?download=1`).
- Field / thứ tự của `GET /api/post-images`; upload / xóa / tìm / vẽ ảnh.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. `?thumb=1` với ảnh PNG/JPEG lớn → `image/jpeg`, rộng ≤ 400 px, nhỏ hơn ảnh gốc nhiều lần.
2. Lần gọi thứ hai không chạy lại ffmpeg (cache hit); ảnh gốc đổi nội dung / mtime → thumbnail tạo lại.
3. Cache không nằm trong `image_dir`: `list_images` / `GET /api/post-images` không thấy file thumbnail; các lượt vẽ / tìm (`imggen._runs`, …) không hỏng.
4. Tên không hợp lệ / không tồn tại → 404 như cũ; ffmpeg lỗi → ảnh gốc 200.
5. Không có `thumb` → hành vi cũ (byte gốc, `?download=1` có `Content-Disposition`).
6. Lưới thư viện dùng `?thumb=1`; ảnh trong bài đăng giữ URL gốc.
7. Full suite PASS.

## Required verification

- `PYTHONPATH=<worktree>/src pytest -q tests/test_web_image_library_thumbs.py tests/test_post_images.py tests/test_web_image_library_page.py tests/test_web_image_library_order.py` (ORCHESTRATOR ngoài sandbox — TestClient).
- `pytest -q -n auto` (ORCHESTRATOR) — AC7.
- Đo trên 8080: kích thước + thời gian một thumbnail thật (lần đầu / lần hai).

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract (query tùy chọn mới, hành vi cũ giữ nguyên) → manual test là điểm danh.

- [ ] 8080 pin commit nhánh: mở Thư viện ảnh trên điện thoại, cuộn lưới — ảnh hiện nhanh, nét đủ nhìn.
- [ ] Bấm tải ảnh / chọn ảnh cho bài → vẫn ảnh gốc.

## Result

- Main changes: `post_images.thumbnail_file` (cache `<image_dir>-candidates/library-thumbs/<sha256(tên, mtime_ns, size)>.jpg`, ≤ 400 px, ghi atomic, lỗi → None); `GET /files/post-images/{name}?thumb=1` trả JPEG đó (có `download` → ảnh gốc; thumbnail lỗi → ảnh gốc); `imageCard` (lưới) dùng `?thumb=1`.
- Tests: `tests/test_web_image_library_thumbs.py`:

  | AC | Test |
  |---|---|
  | 1 | helper + HTTP: JPEG, rộng ≤ 400, nhỏ hơn gốc |
  | 2 | đếm lần tạo; đổi mtime / size / thay file → tạo lại |
  | 3 | cache ngoài thư viện; `list_images` / API / `imggen._runs` / purge |
  | 4 | tên sai / thiếu → 404; lỗi decode / ghi → ảnh gốc |
  | 5 | byte / header gốc; `download` ưu tiên |
  | 6 | URL lưới có `?thumb=1`, bài đăng giữ URL gốc |
  | 7 | `pytest -q -n auto`: 4866 passed, 2 skipped (ORCHESTRATOR, 2026-11-25) |

  Targeted (ORCHESTRATOR ngoài sandbox): 43 passed.
- Diff + / − (app, test): app +32 / −2; test +168 / −0.
- Helper mới (đã tìm, lý do không tái dùng): `thumbnail_file` — `imgsearch.candidate_file` chỉ đọc thumbnail ứng viên đã tạo sẵn; tái dùng `dhash.thumbnail`, `cache_dir`, `atomic_write_bytes`.
- Review: ORCHESTRATOR đọc diff; Codex (effort medium, 58 k token, 1 vòng).
- Important findings / decisions: đo thật — `833.png` 2,90 MB → 87 KB (lần đầu 0,25 s, cache hit 0,3 ms); `01.jpg` 0,19 MB → 26 KB. Giữ `Cache-Control: private, no-cache` (trình duyệt hỏi lại, nhận 304 nhỏ) — an toàn khi tên ảnh bị dùng lại.
- Known limitations: thumbnail cũ của ảnh bị thay / xóa không tự dọn (mỗi file ~30–90 KB).
- PR: #228
