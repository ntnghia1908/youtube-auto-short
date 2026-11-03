# Task: IMG3-image-library-page — Trang "Thư viện ảnh" riêng, mở từ thanh menu

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`, sửa UI nhỏ)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-03: "thư viện ảnh trên web đang nằm sâu — phải vào Bài đăng → chọn ảnh mới tới được thư viện ảnh. Sửa để vào thư viện ảnh trực tiếp (link/tab riêng)"
- Parallel group: —
- Owned paths: `src/auto_short/web/routes/pages.py` (route `/images`), `src/auto_short/web/static/images.html` (mới), `src/auto_short/web/static/posts.html` (hộp thoại dùng markup chung), `src/auto_short/web/static/app.js` (khu "image library" + `initImages`), `src/auto_short/web/static/style.css` (nếu cần cho bố cục trang), thanh `topnav` của `index.html`, `episode.html`, `playlist.html`, `posts.html`, `monitor.html`, `storage.html`, `sutras.html`, `sutra-edit.html`, `favorites.html` (thêm 1 link), `tests/test_web_image_library_page.py` (mới), `docs/decisions/CP8.15-community-post-contract.md` (P9: 1 gạch đầu dòng), contract này
- Dependencies: IMG1, IMG2 (đã merge)
- Base commit / branch: `46fda23` (theo delegation HUMAN LEAD 2026-11-03) / `feature/img3-image-library-page`
- Human Lead approval: accepted — HUMAN LEAD 2026-11-03 "APPROVE IMG3"
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: thêm một trang HTML + một route GET trả file tĩnh; không API mới, không đổi schema, config, dependency, security model (route nằm sau cookie như mọi trang).

## Goal

Thanh menu trên cùng mọi trang có link **"Thư viện ảnh"** → trang `/images` mở thẳng thư viện (lưới ảnh, tải lên, tìm theo link / từ khóa, AI vẽ 10 ảnh, chia lại ảnh, xóa) mà không phải vào một tập → Bài đăng → "Đổi ảnh".

## Hiện trạng

- Thư viện là **dùng chung toàn workspace** (`GET /api/post-images`, không theo tập), nhưng UI chỉ có dạng hộp thoại `#image-dialog` trong `posts.html`, mở bằng nút "Đổi ảnh" của từng bài (`app.js` `openImageDialog`, ~dòng 2152–2525).
- Mọi chức năng trong hộp thoại đã không cần tập: tải lên, tìm link, tìm từ khóa, AI vẽ, chia lại ảnh (`/api/post-images/redistribute` chạy trên mọi tập), xóa.

## Scope

- In scope:
  - Route `GET /images` → `images.html` (`Cache-Control: no-cache`, như các trang khác trong `routes/pages.py`).
  - `images.html`: topbar như các trang khác + khu thư viện hiển thị thẳng trên trang (không modal, không nút "Đóng", không nút "Chọn" trên ảnh).
  - Link "Thư viện ảnh" trong `topnav` của 9 trang đang có topnav (sau "Đọc Kinh"); `theme_index.html` không có menu → không thêm.
  - Hộp thoại "Đổi ảnh" ở tab Bài đăng giữ nguyên hành vi (có "Chọn").
- Out of scope: API / backend thư viện, đổi chức năng nút nào, phân trang / lọc ảnh, xem ảnh đang dùng ở bài nào.

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P5 / P9 là canonical owner của thư viện ảnh và UI của nó; task này thêm vào P9 một dòng: "Trang `/images` (link 'Thư viện ảnh' ở thanh menu): cùng khu thư viện, không có 'Chọn'". HUMAN LEAD duyệt contract này = duyệt sửa đổi đó.
- **D1 — một nguồn markup:** phần thân thư viện (các nút, ô tìm, lưới ứng viên, lưới ảnh) chỉ có một nguồn — dựng bằng JS (vd. `buildImageLibrary(container)`) rồi gắn vào hộp thoại ở `posts.html` và vào trang `/images`; không chép ~35 dòng HTML sang file thứ hai. ID phần tử giữ như hiện tại để code JS cũ chạy nguyên.
- **D2 — chế độ trang:** ở `/images`, `closeImageDialog` / phím Esc không ẩn khu thư viện; poll "AI vẽ" chạy khi trang mở (điều kiện `$("#image-dialog").hidden` hiện tại phải tính đúng cho chế độ trang).

## Implementation approach

- `pages.py`: thêm `@router.get("/images")` như `/storage`.
- `app.js`: tách markup thân thư viện thành hàm dựng; `initImageDialog` dùng chung; thêm `initImages()` (gắn khu thư viện vào `<main>`, `imagePickCallback = null`, gọi `loadImageGrid()` + `latestImageGenerate()`), export trong object `AutoShort`.
- `images.html`: khung như `storage.html`, `<script>AutoShort.initImages();</script>`.

## Phải giữ nguyên

- Hộp thoại "Đổi ảnh" ở Bài đăng: mở / Chọn / Đóng / Esc / AI vẽ / chia lại / xóa như cũ.
- Mọi route `/api/post-images*`, `/files/post-images/*` không đổi.
- Trang khác ngoài topnav không đổi.

## Code bị thay / xóa

- Khối markup `.pane` trong `#image-dialog` của `posts.html` → thay bằng hàm dựng JS (D1); không để lại bản HTML cũ.

## Acceptance Criteria

1. `GET /images` có cookie → 200 HTML có `AutoShort.initImages`; không cookie → chuyển tới đăng nhập như các trang khác.
2. 9 trang có topnav đều có `<a href="/images">Thư viện ảnh</a>`.
3. `posts.html` không còn markup thân thư viện viết tay (D1); `app.js` có một hàm dựng duy nhất được cả `initPosts` và `initImages` dùng.
4. Trên `/images`: thấy lưới ảnh và đủ các nút (Tải ảnh lên, Tìm ảnh, Tìm theo từ khóa, AI vẽ 10 ảnh, Chia lại ảnh), ảnh không có nút "Chọn", không có "Đóng"; Esc không ẩn khu thư viện.
5. Tab Bài đăng: "Đổi ảnh" → hộp thoại, "Chọn" gán ảnh cho bài, "Đóng" / Esc đóng — như trước.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_web_image_library_page.py tests/test_post_images.py tests/test_web_imggen_img1.py tests/test_web_imgsearch_cp830.py -q` — AC1–AC3 (test HTML tĩnh / route).
- `node --check src/auto_short/web/static/app.js`.
- Full suite `python -m pytest -q` (ORCHESTRATOR chạy ngoài sandbox).
- ORCHESTRATOR mở `/images` và tab Bài đăng trên bản chạy thử (8081 hoặc 8080 theo thỏa thuận) — AC4, AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract → manual test là điểm danh sau automated verification.

- [ ] Bấm "Thư viện ảnh" trên menu (cả điện thoại) → thấy ảnh, tải thử 1 ảnh lên, xóa ảnh đó.
- [ ] Tab Bài đăng → "Đổi ảnh" → Chọn một ảnh → bài đổi ảnh.

## Result

- Main changes: thêm route `/images` trả `images.html` với `Cache-Control: no-cache`; trang thư viện dùng chung một nguồn markup JS với hộp thoại Bài đăng; thêm link sau Đọc Kinh ở cả 9 topnav; P9 thêm đúng một gạch đầu dòng đã duyệt. Không cần sửa CSS.
- Tests:
  - PASS: `node --check src/auto_short/web/static/app.js`.
  - PASS: `timeout 290s env PYTHONPATH=/home/ntnghia/projects/yas-img3/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_image_library_page.py -k 'not requires_login' tests/test_post_images.py` — **20 passed, 1 deselected** (1.10 s).
  - BLOCKED môi trường: `timeout 290s env PYTHONPATH=/home/ntnghia/projects/yas-img3/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_image_library_page.py tests/test_post_images.py tests/test_web_imggen_img1.py tests/test_web_imgsearch_cp830.py` — **exit 124** sau 290 s; in 10 dấu PASS rồi treo tại test route dùng TestClient (sandbox không có socket loopback theo delegation). Không claim PASS AC1 hay hai file HTTP imggen / imgsearch; ORCHESTRATOR cần chạy lại lệnh đầy đủ ngoài sandbox.
  - PASS: `git diff --check`.
  - Full suite và browser manual AC4 / AC5: chưa chạy, do ORCHESTRATOR chạy ngoài sandbox theo contract.
- AC → test:

  | AC | Test / evidence | Kết quả |
  |---|---|---|
  | AC1 | `test_images_page_requires_login_and_initializes_library` (cookie, 303 `/login?next=%2Fimages`, HTML, no-cache) | Chờ TestClient ngoài sandbox |
  | AC2 | `test_topnav_links_to_image_library` (9 trang) | PASS |
  | AC3 | `test_image_library_markup_has_one_shared_builder` | PASS |
  | AC4 | Browser `/images`: nút, không Chọn / Đóng, Esc, AI poll | ORCHESTRATOR chưa chạy |
  | AC5 | Browser Bài đăng: Đổi ảnh / Chọn / Đóng / Esc | ORCHESTRATOR chưa chạy |

- Diff + / − (app, test): app **+97 / −50** (gồm `images.html` mới 24 dòng); test **+54 / −0** (file mới). Tính bằng `git diff --numstat` cộng file mới chưa track; không tính docs.
- Helper mới (đã tìm, lý do không tái dùng): tìm bằng `rg -n 'initPosts|initImageDialog|return \{|initStorage|image-dialog|imagePickCallback' src/auto_short/web/static/app.js` và `rg -n 'buildImageLibrary|initImages|build.*\(container' src/auto_short/web/static/app.js`. Chưa có hàm dựng thư viện; thêm `buildImageLibrary(container)` để chuyển nguyên khối `.pane` từ posts.html vào một nguồn chung (D1); thêm entry point `initImages()` cho trang mới. Tái dùng `initImageDialog`, `loadImageGrid`, `latestImageGenerate`, `imageCard`; callback null sẵn có bỏ nút Chọn.
- Review: IMPLEMENTER đã đọc diff đối chiếu Owned paths / AC; không còn bản markup thân thư viện trong HTML; ID giữ nguyên; không thay API / dependency. Review độc lập của ORCHESTRATOR chưa chạy.
- Important findings / decisions: base thực tế `46fda23` trên đúng nhánh và worktree, sạch trước khi sửa; cập nhật metadata base theo delegation mới nhất. `imageLibraryPage` bảo vệ Esc / close và các nhánh poll / lỗi AI khi trang không có `#image-dialog`; hộp thoại giữ mặc định cũ.
- Known limitations: chưa đủ bằng chứng required verification để chuyển lifecycle READY; giữ IN_PROGRESS, bàn giao implementation cho ORCHESTRATOR chạy TestClient, full suite và browser manual ngoài sandbox.
- PR: không tạo; không commit / push / gọi agent / gọi mạng thật.
