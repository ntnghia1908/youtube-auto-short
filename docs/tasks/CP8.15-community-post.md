# Task: CP8.15 — Bài đăng cộng đồng YouTube từ Short

## Status / Approval

- Status: IN_PROGRESS
- BLOCKED note: implementation + toàn bộ test PASS, nhưng tỉ lệ qua validate P3 lần đầu trên dữ liệu thật (72 %) dưới ngưỡng 90 % của Q4 (xem Result) — chưa đặt READY, chờ quyết định HUMAN LEAD.
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `e138f30` (`origin/main`) / `feature/cp8.15-community-post` (implement trong worktree `../youtube-auto-short-cp815`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-29: APPROVE; Q1 ảnh chọn trong thư viện + upload + tìm ảnh từ link, ảnh tìm được vào thẳng thư viện; Q2–Q4 theo đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) artifact mới `work/<id>/posts.json` + log AI; (b) prompt AI mới (AI chỉ thêm dấu câu / chia đoạn) và validate; (c) config mới `[post]`; (d) route API / job web mới (CP8.3 W5, W7); (e) thư viện ảnh ngoài repo, upload ảnh và server tải ảnh từ link người dùng đưa (mở rộng security surface của web, P13). Không thêm dependency: upload bằng body thô (không `python-multipart`), tải / đọc HTML bằng stdlib `urllib` + `html.parser`, kích thước ảnh đọc từ header JPEG/PNG (không Pillow). YouTube không có API công khai cho bài đăng cộng đồng và CP8.4 upload đã bỏ qua → đăng tay, như Short.

## Bối cảnh

Đề xuất HUMAN LEAD (current-state, re-plan 2026-09-29): mỗi Short đã đăng có thêm một bài đăng cộng đồng: text = lời giảng nguyên văn của Short, AI chỉ thêm dấu câu / chia đoạn; ảnh HT. Tịnh Không từ thư viện riêng, không chèn chữ; ô dán link Short; tick "Đã đăng bài". 25 ảnh ứng viên 1080×1080 (kèm `sources.tsv`) ở `~/.cache/auto-short-post-images/`.

Caption YouTube tự động không có dấu câu và có chỗ nhận sai chữ; AI không được sửa chữ → cần sửa tay được.

## Goal

Trên thẻ mỗi Short (tập Short và khai thị): bấm "Soạn bài" → có bài đăng cộng đồng gồm lời giảng nguyên văn của Short được AI thêm dấu câu / chia đoạn (sửa tay được), một ảnh HT. Tịnh Không từ thư viện, link Short tùy chọn; "Sao chép bài" + "Tải ảnh" để đăng tay; tick "Đã đăng bài".

## Quyết định HUMAN LEAD (2026-09-29)

- **Q1. Ảnh:** chọn ảnh trong thư viện cho từng bài; thư viện khởi đầu = 25 ảnh ứng viên (`~/.cache/auto-short-post-images/`, chép tay vào `image_dir`); thêm nút **upload ảnh** và nút **tìm ảnh** (đưa link để tìm) → P5, P5a, P5b, P13.
- **Q2. Bố cục bài:** theo đề xuất P4 (title, dòng ghi nguồn, link, hashtag bộ kinh).
- **Q3. Lúc soạn:** theo đề xuất P1 (theo yêu cầu, không tự chạy sau render).
- **Q4. Model:** theo đề xuất, `qwen3:14b`; chạy thử ≥ 90 % bài qua validate P3 ngay, không thì báo lại trước READY.

## Quyết định

- **P1. Phạm vi bài:** một bài cho mỗi Short `rendered` chưa xóa (Short AI, Short thêm CP9; tập Short và khai thị). Soạn theo yêu cầu: nút "Soạn bài" từng Short, nút "Soạn bài cho mọi Short" (bỏ qua Short đã có bài còn hợp lệ). Chạy job ở làn `ai` (CP8.10), Ollama preflight như W4.
- **P2. Text nguồn** = đúng lời của Short hiện tại, một hàm dùng chung: clip AI không cut → `clip_text` (CP6 G3, bỏ `head_cut`); clip có cut tay / Short thêm → dòng caption thuộc khoảng (CP9 `lines_in`, như `added_titling_input`). `source_sha256` = sha256 của text nguồn → bài `stale` khi text đổi (sửa đầu/cuối, selection chạy lại).
- **P3. AI chỉ thêm dấu câu / chia đoạn:** prompt mới `post` `v1` (text trong code, có `prompt_sha256`), trả `{"paragraphs": ["…"]}`. Validate deterministic: nối mọi đoạn, tách token, chuẩn hóa như `normalize_word` (NFC, chữ thường, bỏ dấu câu đầu/cuối token) → phải **bằng đúng** dãy token nguồn (không thêm / bớt / đổi / đảo chữ); chỉ cho thêm dấu câu `. , ? ! : ; …` và ngoặc kép, đổi hoa/thường. Mỗi đoạn không rỗng. Sai → retry theo `retries`; hết lượt → bài `origin: raw` (một đoạn = text nguồn, viết hoa chữ đầu, thêm dấu chấm cuối), UI cảnh báo. Text dài (khai thị 4–7 phút): chia khối ≤ `[post] chunk_words` (mặc định 400) theo ranh giới dòng caption, mỗi khối một lần gọi, validate từng khối. Log mỗi lần gọi: `work/<id>/post_log.json` (append, không byte-stable, như CP9 C6).
- **P4. Bố cục text sao chép** (Q2):

  ```text
  <title Short đang dùng>

  <đoạn 1>

  <đoạn n>

  — HT. Tịnh Không, <Tên bộ kinh> tập <N>     (từ header CP6; không có header → bỏ dòng)
  ▶ Xem video: <link>                          (chỉ khi đã dán link)

  #<series> #TịnhKhông …                       (hashtags bộ kinh CP8.8, cùng hàm `hashtags`)
  ```

  UI hiện số ký tự. Giới hạn ký tự của bài đăng cộng đồng chưa kiểm → không cắt; HUMAN LEAD xác nhận khi đăng thử (manual test), nếu cần thì thêm cảnh báo ở task sau.
- **P5. Ảnh:** thư viện `[post] image_dir` (mặc định `~/.local/share/auto-short/post-images/`, ngoài repo, không commit ảnh); chỉ `.jpg`/`.jpeg`/`.png` ở cấp đầu, phục vụ nguyên file (không resize, không chèn chữ). Gán tự động khi soạn: ảnh được dùng ít nhất trong mọi `posts.json` của workspace, hòa → theo tên file. "Đổi ảnh" = lưới chọn từ thư viện. Ảnh không còn trong thư viện → bài hiện "thiếu ảnh", phải chọn lại; tick vẫn giữ. "Xóa khỏi thư viện" xóa file (bài đang dùng → "thiếu ảnh"; UI báo số bài đang dùng trước khi xóa).
- **P5a. Upload ảnh:** chọn file trên điện thoại / máy → gửi body thô (`Content-Type` `image/jpeg` | `image/png`, tên gốc ở query). Kiểm: magic bytes khớp JPEG/PNG, ≤ 15 MB, cạnh ngắn ≥ 600 px (đọc header). Tên lưu = tên gốc làm sạch (chữ, số, `-`, `_`, đuôi chuẩn), trùng tên → thêm `-2`, `-3`…; trùng nội dung (sha256) với ảnh đã có → không lưu lại, trả ảnh có sẵn. Ghi atomic. Không resize / crop.
- **P5b. Tìm ảnh từ link:** ô dán link (+ nút nhanh cho mỗi link trong `[post] image_sources`, mặc định rỗng). Link là ảnh → một ứng viên; link là trang HTML (≤ 5 MB) → lấy URL ảnh từ `<img src/data-src/srcset>` (bản lớn nhất của `srcset`) và `<meta property="og:image">`, bỏ trùng, tối đa 40. Tải từng ảnh theo luật P5a (JPEG/PNG, ≤ 15 MB, cạnh ngắn ≥ 600 px; khác → bỏ qua, đếm lý do). Ảnh đạt được **đưa thẳng vào thư viện** (HUMAN LEAD 2026-09-29; luật tên / trùng nội dung của P5a, không có bước chọn ứng viên); kết thúc job, UI hiện lưới ảnh vừa thêm (kích thước, URL nguồn) kèm "Xóa khỏi thư viện" để bỏ ảnh không muốn. Chạy như job nền làn `prepare` (CP8.10), không cần Ollama. URL nguồn của mỗi ảnh thêm từ link ghi vào `<image_dir>/sources.tsv` (`tên<TAB>URL`, append). Không tìm tự do trên search engine (cần dịch vụ ngoài → task khác nếu muốn).
- **P6. Link:** ô dán link, tùy chọn. Nhận `youtube.com/shorts/<id>`, `youtu.be/<id>`, `youtube.com/watch?v=<id>` (có/không `www.` / `m.`, bỏ query thừa) → lưu `https://youtube.com/shorts/<id>` (11 ký tự `[A-Za-z0-9_-]`); khác → 422. Rỗng = xóa link.
- **P7. `work/<id>/posts.json`** — state người dùng, **không** là input stage nào (như `publish.json` W8): ghi atomic, JSON indent 2, thứ tự key cố định, entry theo thứ tự `render_manifest.json`:

  ```json
  {"schema_version": 1, "episode_id": "<id>",
   "posts": [{"clip_id": "k01", "candidate_id": "c00077", "source_sha256": "<64 hex>",
              "paragraphs": ["…"], "origin": "ai", "image": "03.jpg", "link": null,
              "posted_at": null, "updated_at": "2026-09-29T10:05:27Z"}]}
  ```

  `origin` = `ai` | `raw` | `manual` (sửa tay text; không validate token, chỉ không rỗng). Khóa `(clip_id, candidate_id)` như CP8.2 T3. File hỏng → trang tập hiện `post_error`, không ghi đè. Soạn lại một bài đã có: thay `paragraphs` / `origin` / `source_sha256`, giữ `image`, `link`, `posted_at`. Ghi tuần tự bằng lock trong server; được cả khi job đang chạy (trừ ghi kết quả AI của chính job đó). Xóa tập → mất cùng workspace; tập archived (CP8.6) vẫn soạn được (không cần video nguồn).
- **P8. "Đã đăng bài":** `posted_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`) | `null`; độc lập với tick "Đã đăng" Short (`publish.json`) và **không** ảnh hưởng "Xong" (W10 L4) hay gợi ý dọn (W9). Bài đã tick mà text nguồn đổi → vẫn giữ tick, hiện `stale`.
- **P9. Web:**
  - Thẻ Short (tập Short + khai thị): khu thu gọn "Bài đăng cộng đồng": "Soạn bài" / "Soạn lại"; textarea các đoạn (đoạn cách nhau dòng trống) + "Lưu" (→ `manual`); ảnh thu nhỏ + "Đổi ảnh" + "Tải ảnh"; ô link; "Sao chép bài" (text P4, dùng fallback clipboard hiện có); tick "Đã đăng bài"; nhãn `raw` / `stale` / thiếu ảnh.
  - Trang tập: nút "Soạn bài cho mọi Short", đếm "Bài đã đăng x / y".
  - Route mới (cookie W2; 422 lỗi dữ liệu; 503 Ollama khi preflight lỗi; 409 khi đã có job soạn bài của tập):
    - `GET /api/episodes/{id}/posts` → `{posts: [{clip_id, paragraphs, origin, stale, image, image_missing, link, posted, posted_at, text, chars}], post_error}`
    - `POST /api/episodes/{id}/posts` `{clips: [clip_id…] | "all"}` → 202 `{job}`
    - `PUT /api/episodes/{id}/posts/{clip}` `{paragraphs?, image?, link?}` → 200 bài
    - `POST /api/episodes/{id}/posts/{clip}/posted` `{value: bool}` → 200
    - `GET /api/post-images` → `{images: [{name, width, height, bytes, used, source}]}`; `GET /files/post-images/{name}` (`?download=1` → tải về; tên chỉ trong thư viện, chặn path traversal).
    - `POST /api/post-images?name=<tên gốc>` (body thô P5a) → 200 `{image, duplicate}`; `DELETE /api/post-images/{name}` → 200 `{used}`.
    - `POST /api/post-images/search` `{url}` → 202 `{job}`; `GET /api/post-images/search/{job}` → `{status, found, added: [tên], duplicate: [tên có sẵn], skipped: {reason: count}}` (job runner hiện khóa theo episode → job tìm ảnh dùng id riêng không phải episode id, vd `_post_images`; một job tìm ảnh một lúc, 409 khi đang chạy).
  - Tab / hộp thoại "Thư viện ảnh" (mở từ "Đổi ảnh"): lưới ảnh + số bài dùng, "Tải ảnh lên", "Tìm ảnh từ link", "Xóa khỏi thư viện".
- **P10. Không CLI mới** (như CP8.5 / CP9).
- **P11. Code:** package mới `src/auto_short/post/` (text nguồn, prompt, validate, AI, `posts.json`, ảnh, link) — web chỉ gọi. `[post]` trong `config.example.toml`: `model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `retries`, `chunk_words`, `image_dir`, `image_sources` + phần execution-only như `[titling]` (`ollama_host`, `timeout`, `retry_backoff`).
- **P13. Security (tải từ link):** chỉ sau đăng nhập (cookie W2); chỉ `http`/`https`; phân giải host và từ chối IP loopback / private / link-local / multicast (kiểm lại sau mỗi redirect, ≤ 3 redirect); timeout 20 s mỗi request; giới hạn byte đọc (trang 5 MB, ảnh 15 MB) kể cả khi thiếu `Content-Length`; không gửi cookie web đi; không thực thi / phục vụ HTML tải về (chỉ ảnh JPEG/PNG đã kiểm magic bytes, phục vụ với `Content-Type` đúng + `X-Content-Type-Options: nosniff`).
- **P12. Tài liệu canonical:** decision record mới `docs/decisions/CP8.15-community-post-contract.md` (P1–P8, P5a, P5b, P11, P13, prompt `v1`, schema); CP8.3 W5 / W7 / UI trỏ tới nó; project profile (authority list + dòng module `post/`); `README.md` (config `[post]`, chép ảnh vào thư viện); `AUTO_SHORT_CHECKPOINT_PLAN.md`; current-state.

## Scope

- In scope: `src/auto_short/post/` (mới), `src/auto_short/config.py` (`[post]`), `src/auto_short/web/` (route, job, UI thẻ Short + trang tập), tests, `config.example.toml`, docs theo P12.
- Out of scope: đăng tự động lên YouTube; xử lý / crop / chèn chữ vào ảnh; tìm ảnh tự do qua search engine (chỉ từ link P5b); nhập sẵn 25 ảnh ứng viên bằng code (chép tay khi setup); sửa chữ caption sai bằng AI; tự soạn trong pipeline; CLI; bài đăng cho cả tập (không theo Short); đổi prompt selection / titling; đổi `publish.json` / "Xong".

## Acceptance Criteria

1. Text nguồn P2 đúng cho clip AI (có `head_cut`), clip có cut tay và Short thêm; đổi cut → bài `stale`.
2. Validate P3: chấp nhận output chỉ thêm dấu câu / chia đoạn / đổi hoa-thường; từ chối thêm, bớt, đổi, đảo chữ; hết lượt → `raw`. Text dài chia khối theo ranh giới dòng, nối lại đúng.
3. `posts.json` đọc / ghi / validate đúng P7; soạn lại giữ `image`, `link`, `posted_at`; file hỏng → `post_error`, không ghi đè.
4. Ảnh P5: gán ảnh ít dùng nhất, đổi ảnh, ảnh thiếu, tải ảnh, xóa ảnh; tên ngoài thư viện / path traversal → 404.
5. Link P6: các dạng hợp lệ chuẩn hóa đúng, dạng khác → 422.
6. Text sao chép theo P4 (bố cục theo Q2), có / không link, có / không header.
7. Tick "Đã đăng bài" không đổi `publish.json`, "Xong", gợi ý dọn.
8. Route P9: 202 job ở làn `ai`, 409 / 422 / 503 đúng; tập khai thị làm được như tập Short.
9. Toàn bộ test suite PASS (tính cả AC 10–12).
10. Upload P5a: JPEG/PNG hợp lệ được lưu (tên làm sạch, trùng tên, trùng nội dung); sai magic bytes / quá lớn / quá nhỏ → 422.
11. Tìm ảnh P5b: trang HTML (fixture local) → ứng viên đúng (`img`, `srcset`, `og:image`, bỏ trùng, lọc kích thước), ảnh đạt được thêm thẳng vào thư viện + `sources.tsv`, trùng nội dung không lưu lại; link ảnh trực tiếp.
12. Security P13: URL scheme khác, host phân giải ra IP private / loopback (cả qua redirect), vượt giới hạn byte → bị từ chối, không ghi file.

## Required verification

- `conda run -n auto-short python -m pytest -q -n auto` — toàn bộ PASS (AC 1–12; test mới cho P2, P3, P5–P7, P5a, P5b, P13, route; test tìm ảnh dùng HTTP server local / opener giả, không ra Internet).
- Chạy thật với Ollama `qwen3:14b` trên bản sao (không ghi `work/` / `output/` chính): ≥ 10 Short từ ≥ 2 tập Short + 2 Short khai thị; ghi vào Result tỉ lệ qua validate lần đầu / sau retry / `raw`, thời gian mỗi bài, số ký tự (Q4).
- Tìm ảnh thật từ 2 link (một trang trong `sources.tsv`, một link ảnh trực tiếp): ghi số ứng viên / bỏ qua theo lý do, thời gian.
- Mẫu đọc (theo thói quen HUMAN LEAD): gửi text P4 của 3–5 bài (kèm ảnh) để HUMAN LEAD đọc, quyết chất lượng dấu câu / chia đoạn.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (route web mới) → manual test là gate trước integration. Server test riêng (8081), dữ liệu bản sao.

- [ ] Điện thoại: soạn bài một Short, sửa một chữ caption sai, đổi ảnh, dán link, "Sao chép bài" + "Tải ảnh" → đăng thử một bài cộng đồng trên YouTube (kiểm giới hạn ký tự, hiển thị đoạn / hashtag).
- [ ] Thư viện ảnh trên điện thoại: tải ảnh lên từ máy, tìm ảnh từ một link (ảnh vào thẳng thư viện), xóa một ảnh vừa thêm.
- [ ] "Soạn bài cho mọi Short" một tập; tick "Đã đăng bài"; tick Short / "Xong" không đổi.
- [ ] Sửa đầu/cuối một Short đã có bài → hiện `stale`, "Soạn lại" giữ ảnh + link + tick.
- [ ] Tập khai thị làm được như trên.

## Result

- Main changes:
  - `src/auto_short/post/` (mới): `source.py` (P2 text nguồn, đọc trực tiếp artifact — không sửa `review/`), `validate.py` (P3: parse response + validate token/dấu câu + `raw_fallback`), `prompt.py` (prompt `post` `v1`), `logic.py` (P6 `normalize_link`, P3 `chunk_lines`, P4 `compose_copy_text`/`header_line`), `store.py` (P7 `posts.json` schema/read/write/merge), `stage.py` (P1/P3 orchestration: AI call + retry, `post_log.json`, `preflight`, `rendered_clip_ids`, `compute_stale`), `images.py` (P5/P5a: sniff JPEG/PNG bằng magic bytes, validate, save/list/delete, `least_used`), `fetch.py` (P5b/P13: `check_url` (SSRF-safe, resolver injectable cho test), `fetch` (giới hạn byte, redirect có kiểm lại), HTML parser stdlib, `search_images`).
  - `src/auto_short/config.py`: `PostConfig` + `_post()` parser + wire vào `Config`/`from_dict`; `config.example.toml` `[post]`.
  - `src/auto_short/web/jobs.py`: `PostComposeTarget`/`post_compose_target` (lane `ai`), `ImageSearchTarget`/`image_search_target` (lane `prepare`, id `_post_images`), `KIND_POST`, `KIND_POST_SEARCH`, `POST_IMAGES_KEY`, `JobRunner.job(job_id)` (tra job theo id, cần cho route trạng thái tìm ảnh).
  - `src/auto_short/web/app.py`: route P9 đầy đủ (`GET`/`POST /api/episodes/{id}/posts`, `PUT`/`POST .../posts/{clip}[/posted]`, `GET`/`POST /api/post-images`, `DELETE /api/post-images/{name}`, `GET`/`POST /api/post-images/search[/{job}]`, `GET /files/post-images/{name}`); `create_app` thêm `post_compose`/`post_preflight`/`post_search` (injectable, mặc định hàm thật).
  - `src/auto_short/web/static/`: khu "Bài đăng cộng đồng" mỗi thẻ Short (`postPanel`), nút "Soạn bài cho mọi Short" + đếm đã đăng (`refreshPostsHead`), hộp thoại "Thư viện ảnh" dùng chung (`initImageDialog` + upload / tìm ảnh từ link / xóa).
  - Docs (P12): decision record `docs/decisions/CP8.15-community-post-contract.md`; pointer ở `CP8.3-web-contract.md` (metadata, W5, W6, W7); `project-profile.md` (authority list + dòng module `post/` + dòng `web/`); `README.md`; `AUTO_SHORT_CHECKPOINT_PLAN.md`.
- Tests: `tests/test_post_backend.py` (44), `tests/test_post_images.py` (10), `tests/test_post_fetch.py` (13, HTTP server local `127.0.0.1` + `resolver` giả — không ra Internet), `tests/test_post_stage.py` (11), `tests/test_web_post_cp815.py` (44, FastAPI `TestClient`, AI/search giả); `tests/test_config.py` thêm `test_post_config` + `test_post_config_invalid`. Toàn bộ suite: **2 lần** `pytest -q -n auto` — lần 1 sau khi xong backend + web (1090 passed, 1 fail); lần 2 sau khi sửa lỗi `fetch.py` bên dưới (1091 passed, 1 fail, +1 test hồi quy). Cả hai lần, fail duy nhất là `tests/test_web_lanes_cp810.py::test_lanes_artifacts_identical_to_serial` — **không liên quan CP8.15** (file không đụng tới, dùng render/pipeline thật, không dùng `post/`); chạy lại một mình PASS ngay (`1 passed in 10.21s`) → flaky có sẵn dưới tải `-n auto` song song, không phải hồi quy của task này.
- Review: chưa qua vòng review (single pass, chưa có review round riêng).
- Important findings / decisions:
  - **P2 "bỏ head_cut" (quyết định khi implement):** với clip AI không cut tay, text nguồn = toàn bộ text của `unit_ids` (không áp bước bỏ `head_cut` như `titling.logic.clip_text` làm) — từ nối đầu bị cắt khỏi *video* vẫn còn trong text bài đăng. Đọc lại P2 nhiều lần vẫn thấy đây là cách hợp lý nhất để "dùng lại `clip_text` (CP6 G3), bỏ `head_cut`" theo đúng câu chữ; ghi lại ở Known limitations để HUMAN LEAD xác nhận hướng đọc này đúng ý.
  - **`text`/`chars` của `GET .../posts` = bài đầy đủ P4** (title + đoạn + header + link + hashtag), không phải chỉ `paragraphs` — khớp câu "UI hiện số ký tự" của P4 (giới hạn ký tự nói tới cả bài, không phải riêng đoạn văn). Textarea sửa tay dùng trực tiếp `paragraphs` (join bằng dòng trống), không dùng `text`.
  - **`GET /api/post-images` thêm field `image_sources`** (danh sách link nhanh từ `[post] image_sources`) — bản JSON trong P9 không liệt kê field này, nhưng cần để UI vẽ nút nhanh (P5b); coi là bổ sung tương thích xuôi (additive), không đổi field đã liệt kê.
  - **409 khi soạn bài / khi tìm ảnh:** dùng lại đúng luật "một job mỗi episode" của job runner có sẵn (`_busy`, CP8.10) cho soạn bài — nghĩa là soạn bài cũng bị 409 khi episode có job pipeline/render khác đang chạy, không chỉ khi có job soạn bài khác. Tìm ảnh dùng id giả `_post_images` (không phải episode id) nên không cạnh tranh với job của episode nào, chỉ với chính nó.
  - **`PUT`/`posted` không qua `submit_lock`:** đúng P7 ("được cả khi job đang chạy"), chỉ khóa qua `post_lock` (giống `publish_lock` CP8.5) — khác hẳn title/cut (CP8.2/CP9) vốn bị 409 khi có job.
  - **Bug tìm thấy khi chạy thật, đã sửa:** `post/fetch.py` `fetch()` gọi `urllib.request.Request(url, …)` với `url` gốc (có thể chứa ký tự Unicode chưa mã hoá, ví dụ tên file tiếng Trung trong link ảnh thật từ hwadzan.com) → `UnicodeEncodeError` khi gửi request line. Sửa bằng `_iri_to_uri()` (percent-encode path/query/fragment, giữ nguyên `%XX` đã có). Thêm test hồi quy `test_fetch_encodes_non_ascii_path`. Chỉ phát hiện được nhờ chạy thật với link ảnh thật (test giả trước đó toàn dùng URL ASCII).
  - **Q4 — BLOCKED (không tự đổi model/prompt):** chạy thật với Ollama `qwen3:14b` trên **bản sao** dữ liệu thật (không đụng `work/`/`output/` chính; scratch dir, config riêng trỏ về đó) — 2 tập Short thật (`4oOZz2CBz3g` 7 Short, `c_6QuBGFzY4` 9 Short, tổng 16) + 1 Short khai thị mỗi tập `.kt` tương ứng (2 Short khai thị, 2 khối mỗi khối do text dài) = **18 bài** composed:
    - Qua validate lần đầu (không cần retry): **13/18 = 72 %** (Short thường: 12/16 = 75 %; khai thị: 1/2 = 50 %).
    - Qua validate sau retry (attempt 2/3 thành công mà attempt 1 thất bại): **0/18 = 0 %** — mọi lần thất bại lặp lại cùng lỗi ở mọi attempt (đọc `post_log.json` xác nhận: model tái tạo gần như cùng một lỗi nội dung ở `temperature 0`, retry không sửa được).
    - `origin: raw` (hết lượt): **5/18 = 28 %** (`retries = 2`, 3 lượt mỗi khối).
    - Thời gian: 2,1–35,6 s một Short (trung bình 9,0 s); Short thường 2,1–21,1 s, khai thị (2 khối) 9,7–35,2 s.
    - Số ký tự đoạn văn (không kể title/header/hashtag): 427–2821, trung bình 887.
    - Đọc `post_log.json` của 2 trường hợp `raw`: cả hai là lỗi nội dung thật (không phải bug validator) — một lần AI thêm từ "Sẽ" không có trong nguồn, một lần AI tách "dịchvụ" (một token dính liền do lỗi caption) thành "dịch vụ" (hai token) — đúng loại "sửa lỗi chính tả / nhận dạng sai" mà P3 cấm rõ. Một lần khác (`4oOZz2CBz3g` k02, đã qua validate) AI trả lại gần như y nguyên, không thêm dấu câu nào (chỉ viết hoa chữ đầu) — không vi phạm P3 (không cấm "thêm ít") nhưng cho thấy chất lượng-hữu-dụng không đều dù validator chấp nhận.
    - **72 % < 90 % ngưỡng Q4** → theo đúng chỉ dẫn task, KHÔNG tự đổi `[post] model` hay prompt; báo lại đây để HUMAN LEAD quyết (chấp nhận ngưỡng thấp hơn / đổi model trong `[post]` (không cần code mới, chỉ đổi config) / sửa prompt `v2` (cần task/S1 riêng vì đổi prompt text) / thêm bước sửa tay nổi bật hơn trong UI).
  - Tìm ảnh thật từ 2 link (không qua opener giả, gọi Internet thật): link ảnh trực tiếp trong `~/.cache/auto-short-post-images/sources.tsv` (`…/1淨空老法師01.jpg`) → 1 ảnh, 5,8 s. `sources.tsv` chỉ có link ảnh trực tiếp (không có link trang) → dùng trang HTML thật cùng site (`https://www.hwadzan.com/`, có `<img data-src>` lazy-load + `<meta property="og:image">`) làm ví dụ "trang chứa ảnh": 40 ứng viên tìm được, 20,5 s, 10 ảnh đạt (≥ 600 px) vào thư viện + `sources.tsv`, 14 ảnh bị bỏ vì nhỏ hơn 600 px (lý do ghi rõ theo kích thước). Không ảnh nào trùng nội dung trong lần chạy này.
  - Mẫu đọc (P4, kèm ảnh thật từ thư viện) — 5 mẫu ở `/tmp/claude-*/…/scratchpad/cp815-verify/samples/` (đường dẫn phụ thuộc phiên; nội dung cũng in trong log agent) gồm 3 `ai` + 2 `raw`, để HUMAN LEAD đọc và so hai loại.
- Known limitations:
  - Q4 dưới ngưỡng — xem trên; UI đã có nhãn cảnh báo (`raw`) nhưng không có cảnh báo cho trường hợp "qua validate nhưng gần như không thêm dấu câu".
  - P2 lấy full text khi không có cut tay bao gồm cả từ nối bị `head_cut` cắt khỏi video (không khớp 100 % lời trong video); ảnh hưởng tối đa một từ ở đầu Short, sửa tay được (`manual`).
  - `retries`/`retry_backoff` ít tác dụng với lỗi nội dung hệ thống (model lặp lại cùng lỗi ở `temperature 0`); chỉ giúp lỗi tạm thời (mạng, JSON hỏng).
  - Manual test checklist (điện thoại, đăng thử thật) chưa chạy — cần HUMAN LEAD.
  - Chưa review vòng nào (mới một lượt implement).
- PR: chưa tạo (chưa READY; theo `docs/ai/project-profile.md` §5, PR chỉ sau READY + HUMAN LEAD approval). Commit cục bộ trên `feature/cp8.15-community-post`, chưa push.
