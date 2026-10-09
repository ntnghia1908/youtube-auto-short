# Task: CP8.31 — Zip tick "Đã đăng", xuất bài đăng .docx, nút tải trên trang bộ kinh, gọn nút trên mobile, enhance sang Theo dõi

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `de4cd53` (`main`) / `feature/cp8.31-downloads-mobile` (worktree `../youtube-auto-short-cp831`)
- Human Lead approval: APPROVED 2026-10-09 ("APPROVE TASK", nguyên bản D1–D6)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đảo luật CP8.17 D3 (zip không tick) ở `docs/decisions/CP8.3-web-contract.md` W8; thêm dependency (`python-docx`, kéo theo `lxml`) vào danh sách canonical `docs/decisions/CP1-product-contract.md` §10; thêm luật xuất bài đăng vào `docs/decisions/CP8.15-community-post-contract.md`.

## Bối cảnh (HUMAN LEAD 2026-10-09)

1. Tải tất cả Short + khai thị → tick "Đã đăng" cả tập.
2. Cần tải tất cả bài đăng (sau này đóng thành sách); trang Bài đăng phải ẩn nút "Từ điển sửa lỗi".
3. Nút tải tất cả đưa ra trang bộ kinh, trên từng dòng tập (không phải vào từng tập).
4. Trang bộ kinh, mobile: "Chuẩn bị + HD", "Chạy tiếp cả bộ", "Ưu tiên cả bộ", "Enhance lại" mỗi nút một dòng → gọn lại.
5. Trang tập (Short / khai thị), mobile: "Tải bản ngang", "Tải bản dọc", … mỗi nút một dòng → gọn lại.
6. Khối "Enhance video (máy GPU)" ở tab Bộ nhớ chuyển sang tab Theo dõi.

Lựa chọn của HUMAN LEAD (2026-10-09): (1) mọi zip đều tick; (2) định dạng Word `.docx`, thêm `python-docx`; phạm vi cả bộ kinh + từng tập, không tick "Đã đăng bài".

Nguyên nhân đã kiểm cho (2) và (4)/(5):
- `#corr-open` có thuộc tính `hidden` (CP8.21 D5, `[web] show_advanced = false`) nhưng vẫn hiện vì `style.css` `.btn { display: inline-block }` đè `display: none` mặc định của `[hidden]`. Các `.btn` khác có `hidden` cũng bị ảnh hưởng nếu không có luật `…[hidden]` riêng.
- `style.css` `@media (max-width: 640px) { .actions .btn { flex: 1 1 100%; } }` → mọi nút trong `.actions` chiếm trọn một dòng.

## Goal

HUMAN LEAD tải được Short + khai thị của một tập và bài đăng (Word) của một tập hoặc cả bộ kinh ngay trên trang bộ kinh; tải zip là tick "Đã đăng"; trên điện thoại các hàng nút gọn hơn; trạng thái enhance nằm ở tab Theo dõi.

## Scope

- In scope:
  - **D1. Zip tick "Đã đăng"** (đảo CP8.17 D3; quay lại CP8.7 "tải về = đã đăng" cho zip). `GET /files/{id}/shorts.zip` tick mọi Short `rendered` có trong zip (tập Short hoặc khai thị); `GET /files/{id}/all.zip` tick mọi Short `rendered` của `<vid>` và `<vid>.kt`. Dùng chung `_mark_downloaded` / `mark_downloaded` (như "Tải về" một Short: tick theo file hiện tại, Short "đã đăng bản cũ" thành đã đăng bản hiện tại; lỗi ghi `publish.json` không chặn tải). UI: sau khi bấm zip thì làm mới số "đã đăng" (trang tập, trang bộ kinh).
  - **D2. Xuất bài đăng `.docx`** (P16 mới trong decision CP8.15):
    - Route `GET /files/{id}/posts.docx` (một video: bài của `<vid>` rồi `<vid>.kt`, `id` = `<vid>` hoặc `<vid>.kt`, cùng kết quả) và `GET /files/playlists/{playlist_id}/posts.docx` (cả bộ kinh, theo thứ tự tập của danh sách bộ kinh; tập chưa có bài nào thì bỏ qua). Cookie + validate id như các route file khác. 404 khi không có bài nào.
    - Nội dung: tiêu đề tài liệu (tên bộ kinh, hoặc tên tập khi tải một tập); mỗi tập một heading (`<series> tập <N>` + tiêu đề video); trong tập, mục "Shorts" rồi "Khai thị" (chỉ mục có bài); mỗi bài: heading = dòng title (viết hoa như P4), ảnh của bài (rộng vừa trang), các đoạn, dòng nguồn P4. **Không** có link video và hashtag (dùng cho sách). Thứ tự bài theo manifest. Bài lấy từ `posts.json` (cả bài đã / chưa đăng, cả bài sửa tay); Short đã xóa / không `rendered` bị bỏ; bài stale vẫn xuất (text đang lưu).
    - Ảnh: file trong thư viện ảnh (`[post] image_dir`); ảnh thiếu → bỏ ảnh, giữ text. Ảnh trùng giữa các bài chỉ nhúng một lần (python-docx tự dùng chung theo sha).
    - Tên file: `[<series>_]Tập<N>_BaiDang.docx` (một tập) / `<series>_BaiDang.docx` (cả bộ; không có tên bộ kinh → `<playlist_id>_BaiDang.docx`), bỏ ký tự không hợp lệ như W8.
    - Không tick "Đã đăng bài", không đổi `posts.json`. Tạo file trong thread (không chặn event loop), file tạm tự xóa sau khi gửi.
  - **D3. Nút tải trên trang bộ kinh.** Mỗi dòng tập (cạnh nút tải HD hiện có, dạng icon CP8.21 D6, có `title` + `aria-label`): "Tải Short + khai thị (.zip)" — `all.zip` khi có cả hai, không thì `shorts.zip` của loại đang có; "Tải bài đăng (.docx)" khi tập có bài. Đầu trang bộ kinh: nút "Tải bài đăng cả bộ (.docx)". API danh sách bộ kinh trả thêm url + tên file cho mỗi dòng (như `hd_url` / `hd_name`). Trang Bài đăng của một tập: nút "Tải bài đăng (.docx)".
  - **D4. Ẩn đúng phần tử `hidden`.** Thêm luật chung `[hidden] { display: none !important; }` vào `style.css` (sửa lỗi CP8.21 D5: "Từ điển sửa lỗi" vẫn hiện); không đổi `[web] show_advanced`.
  - **D5. Gọn nút trên mobile (≤ 640 px).** Thay `.actions .btn { flex: 1 1 100% }` bằng bố cục 2 cột (mỗi nút ~nửa hàng, nút lẻ cuối kéo rộng), giữ nút ≥ 40 px, không cuộn ngang. Áp cho: hàng nút cả bộ (`#pl-bulk`), đầu trang bộ kinh, hàng tải HD / tạo bản dọc (`#hd-video`), hàng "Chạy tiếp / Ưu tiên / Xóa" của trang tập, hàng nút enhance (`.enhance-box .edit-actions`), hàng zip (`.head-actions`). Nhãn dài có thể rút gọn trên mobile (vd "Chạy tiếp / chạy lại (bước đã xong được bỏ qua)" → "Chạy tiếp / chạy lại", phần giải thích chuyển vào `title`). Sửa đổi dòng "nút xuống dòng riêng" của W6 (CP8.7, màn hình ≤ 640 px).
  - **D6. Enhance sang tab Theo dõi.** Bỏ khối `#enhance-card` khỏi `storage.html`; tab Theo dõi gộp tóm tắt hàng đợi enhance + danh sách worker + nút "Tạm dừng / Chạy tiếp enhance" vào khối "GPU enhance (máy Windows)" (không trùng thông tin worker với `#mon-gpu`). Route `/api/enhance/status`, `/api/enhance-pause` không đổi.
  - **Dependency:** `python-docx==1.2.0` vào extra `[web]` của `pyproject.toml` (kéo theo `lxml`); cài vào env `auto-short`; thêm dòng vào CP1 §10.
  - Cập nhật decision: CP8.3 W6 / W7 / W8 (+ "Accepted by"), CP8.15 P9 + P16 mới, CP1 §10; README (zip tick, xuất bài đăng); CP8.13/8.17 không sửa (file lịch sử).
  - Test cho D1–D3, D6 (route, tick, nội dung docx đọc lại bằng python-docx, thứ tự, ảnh thiếu, 404, auth).
- Out of scope: xuất PDF / Markdown; dàn trang sách (khổ giấy, mục lục, đánh số trang) — HUMAN LEAD chỉnh trong Word; tick "Đã đăng bài" khi xuất; đổi `show_advanced`; thay đổi UI khác ngoài các hàng nút nêu trên; nút tải zip cả bộ kinh.

## Authority / key decisions

- `docs/decisions/CP8.3-web-contract.md` W6, W7, W8 (canonical owner zip / tick / UI) — sửa.
- `docs/decisions/CP8.15-community-post-contract.md` P4 (bố cục text), P9 (web) — thêm P16 xuất `.docx`.
- `docs/decisions/CP1-product-contract.md` §10 — thêm `python-docx`.
- `docs/tasks/CP8.17-download-rules.md` D3 (bị đảo), `docs/tasks/CP8.21-ui-names-watched.md` D5 / D6.
- K1: tiêu đề bài trong docx dùng cùng hàm với "Sao chép bài" (`post/logic`) để không lệch text; chỉ bỏ dòng link + hashtag.

## Implementation approach

- D1: thêm `_mark_downloaded` vào 2 nhánh zip của `files()` (`app.py`), tick theo danh sách clip trong zip; test CP8.17 D3 sửa đúng chỗ hành vi đổi (ghi lý do trong Result).
- D2: module mới `post/export.py` (dựng docx từ list bài đã sắp xếp + thư mục ảnh), không phụ thuộc web; `web` gom bài theo tập / bộ kinh rồi gọi; trả `FileResponse` với `BackgroundTask` xóa file tạm.
- D3 / D5 / D6: `app.js`, `playlist.html`, `posts.html`, `episode.html`, `monitor.html`, `storage.html`, `style.css`.

## Acceptance Criteria

1. D1: tải `shorts.zip` của tập Short → mọi Short `rendered` của tập đó "Đã đăng" (file hiện tại); `shorts.zip` của `.kt` → chỉ khai thị; `all.zip` → cả hai tập; Short đã xóa không bị tick; lỗi ghi `publish.json` vẫn trả zip.
2. D2: `posts.docx` một video có heading tập, mục Shorts rồi Khai thị, mỗi bài đúng title viết hoa / ảnh / đoạn / dòng nguồn, không link, không hashtag, đúng thứ tự manifest; ảnh thiếu → bài vẫn có text; `posts.json` và `posted_at` không đổi; không có bài → 404; id sai / chưa đăng nhập → 404 / 401 như route file khác.
3. D2: `posts.docx` cả bộ kinh theo thứ tự tập, bỏ tập không có bài; tên file đúng quy tắc; ảnh dùng chung chỉ nhúng một lần (số ảnh trong `word/media` = số ảnh khác nhau).
4. D3: API danh sách bộ kinh trả url zip (`all.zip` khi có cả hai, không thì `shorts.zip`) và url docx cho đúng các dòng; trang bộ kinh hiện nút icon tương ứng + nút "Tải bài đăng cả bộ"; trang Bài đăng có nút tải docx.
5. D4: với `show_advanced = false`, "Từ điển sửa lỗi" không hiện ở trang Bài đăng (kiểm trên trình duyệt / ảnh chụp).
6. D5: ở bề rộng 390 px, `#pl-bulk` (4 nút) nằm trên ≤ 2 hàng; `#hd-video` (2–3 nút) ≤ 2 hàng; không cuộn ngang; nút ≥ 40 px (ảnh chụp trước / sau).
7. D6: tab Bộ nhớ không còn khối enhance; tab Theo dõi có tóm tắt hàng đợi enhance, worker, nút tạm dừng hoạt động.
8. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–4, 7, 8.
- `node scripts/framework-check.mjs`.
- Server test 8081 trên bản sao dữ liệu (vài tập có Short + khai thị + bài đăng, không đụng 8080 / dữ liệu thật): tải zip → kiểm `publish.json`; tải docx một tập + một bộ kinh, mở lại bằng python-docx (đếm heading / ảnh) và gửi 1 file mẫu cho HUMAN LEAD; ảnh chụp mobile 390 px trang bộ kinh, trang tập, trang Bài đăng, tab Theo dõi / Bộ nhớ (headless browser nếu có trong env; không có thì ghi rõ và để HUMAN LEAD kiểm trên điện thoại).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model; route file mới dùng cùng auth như route có sẵn; public API JSON chỉ thêm field. Manual test sau automated verification là điểm danh.

- [ ] Điện thoại: trang bộ kinh — hàng nút cả bộ gọn; mỗi dòng tập có nút tải zip + bài đăng; bấm zip → "đã đăng" tăng.
- [ ] Điện thoại: trang tập — hàng tải bản ngang / dọc, chạy tiếp / ưu tiên gọn.
- [ ] Trang Bài đăng: không còn "Từ điển sửa lỗi"; tải docx mở được trong Word / Google Docs, đúng ảnh + chữ.
- [ ] Tải "bài đăng cả bộ" một bộ kinh lớn: thời gian chờ chấp nhận được.
- [ ] Tab Theo dõi có khối enhance, nút tạm dừng chạy; tab Bộ nhớ không còn.

## Amendment 1 + 2 (HUMAN LEAD 2026-10-09, trong lúc manual test trên 8080)

Yêu cầu trực tiếp của HUMAN LEAD (sửa D2 / D3; thêm D7). Không chạm decision gate mới (cùng dependency, cùng route family).

- **A1. Bài đăng theo khoảng 10 tập + có / không hình** (thay "cả bộ một file" của D2 / D3 — HUMAN LEAD: cả bộ quá nhiều bài, không thiết thực):
  - Bỏ tải nguyên cả bộ. Route bộ kinh nhận khoảng: `GET /files/playlists/{pid}/posts.docx?from=<N>&to=<M>` (theo số tập; bắt buộc; `to - from` ≤ 9 → tối đa 10 tập) và `?other=1` cho tập không nhận số tập. Khoảng rỗng → 404; tham số sai → 422.
  - API bộ kinh trả danh sách khoảng có bài: `posts_ranges: [{from, to, label "Tập 1–10", episodes, posts, url}]` chia cố định theo bội 10 (1–10, 11–20, …; chỉ khoảng có ít nhất một bài), cộng mục "Tập chưa rõ số" nếu có.
  - Tham số `images=0|1` (mặc định 1) cho mọi route docx (một video + khoảng). `images=0`: không nhúng ảnh. Tên file: `[<series>_]Tập<N>-<M>_BaiDang.docx` (khoảng), `…_BaiDang_KhongHinh.docx` khi không hình (cả một video).
  - UI trang bộ kinh: thay nút "Tải bài đăng cả bộ" bằng khối "Tải bài đăng (.docx)": danh sách khoảng (nhãn + số bài, mỗi khoảng một nút / link tải) + ô "Có hình" (mặc định bật, nhớ ở trình duyệt, try/catch). Ô "Có hình" áp cho cả icon docx trên từng dòng tập; trang Bài đăng có ô "Có hình" riêng (cùng khóa nhớ).
- **A2 (D7). Tiến độ đăng dễ nhìn trên dòng tập** (HUMAN LEAD chọn "huy hiệu màu" + có "Bài"):
  - Mỗi dòng tập hiện huy hiệu riêng: `Short x/y`, `Khai thị x/y`, `Bài x/y` (x = đã đăng; Short / khai thị như số hiện có; Bài: y = số Short `rendered` của `<vid>` + `<vid>.kt`, x = bài có `posted_at`). Màu: xanh lá = x = y > 0, cam = 0 < x < y, xám = x = 0. Huy hiệu có y = 0 thì ẩn. Màu đủ tương phản, có chữ (không chỉ dựa vào màu).
  - Dòng chữ trạng thái còn lại (xử lý / lỗi / HD / đã dọn nguồn / ưu tiên) giữ ở dòng nhỏ dưới huy hiệu, bỏ phần "N Short, đã đăng x/y" / "N video khai thị, đã đăng x/y" khỏi dòng chữ đó.
  - API bộ kinh thêm `posts_total`, `posts_posted` mỗi dòng (đọc `posts.json` như D3, không gọi thêm AI / mạng).
- AC bổ sung: A1 — khoảng đúng theo số tập, tối đa 10 tập, `images=0` không có `word/media`, tên file đúng; A2 — số và màu đúng cho 3 trường hợp (hết / dở / chưa), y = 0 ẩn; test API + static.

## Amendment 3 (HUMAN LEAD 2026-10-09, manual test 8080)

- **A3. Huy hiệu ở trang chủ cho từng bộ kinh** (HUMAN LEAD: "huy hiệu dễ nhìn hơn nên áp dụng luôn cho trang chủ"): dòng chữ `playlistSummary` (CP8.13 G3) đổi thành huy hiệu cùng kiểu A2 (`.badge.prog`, chữ + màu): `Đã xử lý a/N` (cam khi 0 < a < N, xanh khi a = N, xám khi 0), `Xong b` (xanh), `Đang xử lý c` (xanh dương / màu busy hiện có), `Lỗi / dở dang d` (đỏ), `Đang làm e` (cam). Huy hiệu số 0 ẩn (trừ `Đã xử lý`). Không đổi API (`/api/playlists` đã có `count`, `processed`, `complete`, `running`, `failed`, `doing`) và không đổi nghĩa các nhóm (CP8.13). Sửa CP8.3 W6 dòng trang chủ.
- AC bổ sung: A3 — static test (hàm vẽ huy hiệu, ẩn 0); không còn dòng chữ ghép "·".

## Result

- Main changes:
  - D1 `web/app.py` `files()`: `shorts.zip` / `all.zip` gọi `_mark_downloaded` (all.zip: `<vid>` và `<vid>.kt` riêng); JS trang tập + trang bộ kinh làm mới sau khi bấm zip.
  - D2 `post/export.py` (python-docx) + `post/logic.text_parts` (dùng chung với `compose_copy_text`) + `review/names.posts_docx_name`; route `GET /files/{id}/posts.docx`, `GET /files/playlists/{pid}/posts.docx` (handler sync = chạy thread pool, file tạm xóa bằng `BackgroundTask`). Tiêu đề bài lấy từ `list_titles`, lỗi thì title trong `render_manifest.json`.
  - D3 API bộ kinh: `zip_url/zip_name`, `posts_docx_url/posts_docx_name` mỗi entry + `posts_docx_url/name` cả bộ; icon `zip` / `doc` (CP8.21 D6) trên từng dòng tập, nút "Tải bài đăng cả bộ (.docx)", nút "Tải bài đăng (.docx)" ở trang Bài đăng.
  - D4 `[hidden] { display: none !important; }`. D5 CSS ≤ 640 px: `flex: 1 1 calc(50% - .5rem)` cho `.actions`, `.head-actions`, `.enhance-box .edit-actions`; nhãn "Chạy tiếp / chạy lại" rút gọn (phần còn lại `.long` + `title`); hàng nút của dòng tập dùng flex-wrap.
  - D6 `#enhance-card` bỏ khỏi `storage.html`; `monitor.html` khối "GPU enhance" có `#enhance-summary` + `#enhance-pause`; `loadEnhance()` chuyển sang `initMonitor` (danh sách worker `#enhance-workers` bỏ vì trùng `#mon-gpu`; cảnh báo "worker cần cập nhật" giữ trong dòng tóm tắt).
  - Dependency `python-docx==1.2.0` (extra `[web]`, đã cài vào env `auto-short`, kéo `lxml`); decision CP8.3 W6/W7/W8 + Accepted-by, CP8.15 P9 + P16 + Accepted-by, CP1 §10, project-profile, README.
- Tests:
  - `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`): 1595 passed, 1 skipped. `node scripts/framework-check.mjs`: PASS (0 FAIL). `node --check app.js`: OK.
  - Test mới `tests/test_web_cp831.py` (docx một video / cả bộ: heading, thứ tự manifest, không link / hashtag, ảnh thiếu, ảnh chung nhúng một lần, `posts.json` không đổi, 404, auth, file tạm được xóa, tên file, API bộ kinh, static D3–D6).
  - Test CP8.17 D3 / CP8.7 sửa vì hành vi đổi (zip tick): `tests/test_web_cp817.py::test_shorts_zip_does_not_tick_but_single_download_does` thay bằng 4 test D1 (tick từng loại, all.zip, Short đã xóa / stale, lỗi ghi `publish.json`); `test_static_ui_labels_and_no_refresh_after_zip` bỏ assert "không làm mới sau zip"; `tests/test_playlist_cp87.py::test_download_ticks_published` đoạn zip giờ kỳ vọng tick cả 3 Short.
  - Không có trình duyệt headless (không chromium / playwright trong env): AC5 / AC6 chưa có ảnh chụp 390 px; ORCHESTRATOR kiểm trên server test 8081 hoặc HUMAN LEAD trên điện thoại.
- Review:
  - Round 2 (ORCHESTRATOR): điện thoại vẫn hiện layout cũ vì `/static/*` chỉ có Last-Modified/ETag, không có Cache-Control (cache heuristic). Sửa: middleware đặt `Cache-Control: no-cache` cho `/static/*` và `/login` khi route chưa tự đặt; test `test_static_and_pages_revalidate`.
  - ORCHESTRATOR round 1: 2 blocking — tên docx cả bộ rơi về playlist id khi bộ kinh không lưu series (Địa Tạng); heading tập lặp tên bộ kinh. Sửa ở `40330bf` (fallback series của tập đầu; chỉ nối tên video khi không chứa series). Retest: `pytest -q -n auto` 1596 passed, 1 skipped (ORCHESTRATOR chạy lại). Round 2: ACCEPTED, không còn blocking.
  - Kiểm dữ liệu thật (app tạm, workspace symlink chỉ đọc, không gọi zip): docx Địa Tạng 7,0 s / 44,4 MB (11 tập, 154 bài, 114 ảnh khác nhau), Vô Lượng Thọ 11,5 s / 44,7 MB (19 tập, 285 bài); API bộ kinh 0,17 s (374 dòng). Tên file `Kinh Địa Tạng Bồ Tát Bổn Nguyện_BaiDang.docx`.
  - 8080 ghim `40330bf` (theo yêu cầu HUMAN LEAD "test trên 8080"); manual test checklist + ảnh mobile do HUMAN LEAD trên điện thoại.
  - Amendment 1 + 2 (round 3): route bộ kinh `?from&to` / `?other=1` + `images=0|1` (bỏ file cả bộ), `posts_ranges`, `posts_total/posted/count` mỗi entry (một lần đọc `posts.json` mỗi tập), khối "Tải bài đăng (.docx)" + ô "Có hình" (`localStorage`), huy hiệu `Short/Khai thị/Bài x/y`; decision CP8.15 P16, CP8.3 W6/W7, README cập nhật; test mới trong `tests/test_web_cp831.py`. Tên không-hình: `…_BaiDang_KhongHinh.docx`; `other=1`: `Tập chưa rõ`.
  - Round 4 (HUMAN LEAD, điện thoại): nút dòng tập lệch tên tập — CSS ≤ 640 px: hàng nút lùi `calc(2.2rem + .5rem)` (thẳng cột với tên), `align-items: center`, mọi nút cao 2.75rem; desktop không đổi; test `test_mobile_row_actions_aligned_with_name`.
  - Amendment 3 (round 5): trang chủ `playlistBadges(p)` thay `playlistSummary` (huy hiệu `.badge.prog` + lớp `busy` / `err`, ẩn 0 trừ `Đã xử lý`); CP8.3 W6 dòng trang chủ cập nhật; test CP8.13 `test_playlist_groups_*` (assert dòng chữ `playlistSummary`) sửa vì hành vi đổi; test mới `test_home_playlist_badges_static`.
  - Round 6 (HUMAN LEAD, điện thoại): số "đã đăng" không tăng sau khi bấm zip vì chỉ làm mới một lần sau 2,5 s, request tải trên mobile tới server trễ hơn. Sửa: `zipAfterClick(refresh)` làm mới ở 2 / 5 / 10 / 20 s (không chồng timer khi bấm lại) + làm mới khi trang hiện lại / lấy focus trong 60 s; dùng cho zip dòng tập (trang bộ kinh) và 2 nút zip (trang tập, kể cả "Tải cả hai"); test `test_zip_click_refreshes_repeatedly_and_on_return`.
- Important findings / decisions:
  - Thứ tự tập trong file cả bộ: số tập (như `_by_episode_order` của CP13.2), tập không nhận số tập xếp sau theo thứ tự danh sách.
  - Cột tiêu đề: bài đã xóa khỏi `render_manifest` (không `rendered`) không xuất; bài stale vẫn xuất.
- Known limitations:
  - File cả bộ ~44 MB vì ảnh nhúng nguyên cỡ (non-blocking).
  - Chưa kiểm bằng trình duyệt thật (bố cục 2 cột mobile, mở docx trong Word / Google Docs); chưa đo thời gian "bài đăng cả bộ" với bộ kinh lớn (dựng tuần tự một lần, ảnh nhúng nguyên file).
- PR:
