# Task: CP8.15 — Bài đăng cộng đồng YouTube từ Short

## Status / Approval

- Status: READY
- Sửa đổi (HUMAN LEAD 2026-09-29, sau BLOCKED Q4, ORCHESTRATOR review round 1): P3 đổi sang AI tự do + chiếu dấu câu về chữ gốc (prompt `v2`), Q4 đổi tiêu chí; P2 giữ nguyên (bỏ `head_cut`) — bản đầu làm sai (giữ nguyên từ nối, ghi nhầm là HUMAN LEAD đã chấp nhận), đã sửa lại đúng P2 gốc + gỡ ghi nhận sai. Sau sửa: Q4 đạt 94,4% (xem Result).
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
- **Q4. Model:** `qwen3:14b`. **Sửa đổi 2026-09-29:** đạt khi chạy thật ≥ 90 % bài `origin: ai` có ≥ 4 dấu câu `. , ? ! : ; …` / 100 từ (đếm trên phần đoạn văn), trên cùng 18 bài của lần đo đầu; không đạt → báo lại trước READY. (Bản đầu: ≥ 90 % qua validate token-chặt lần đầu → đo 72 %, bài "qua" chỉ ~1 dấu / 100 từ.)

## Quyết định

- **P1. Phạm vi bài:** một bài cho mỗi Short `rendered` chưa xóa (Short AI, Short thêm CP9; tập Short và khai thị). Soạn theo yêu cầu: nút "Soạn bài" từng Short, nút "Soạn bài cho mọi Short" (bỏ qua Short đã có bài còn hợp lệ). Chạy job ở làn `ai` (CP8.10), Ollama preflight như W4.
- **P2. Text nguồn** = đúng lời của Short hiện tại, một hàm dùng chung: clip AI không cut → `clip_text` (CP6 G3, bỏ `head_cut`); clip có cut tay / Short thêm → dòng caption thuộc khoảng (CP9 `lines_in`, như `added_titling_input`). `source_sha256` = sha256 của text nguồn → bài `stale` khi text đổi (sửa đầu/cuối, selection chạy lại).
- **P3. AI chỉ thêm dấu câu / chia đoạn — chữ luôn là chữ gốc** (sửa đổi HUMAN LEAD 2026-09-29; prompt `v1` + validate token-chặt bị thay): prompt `post` `v2` (text trong code, có `prompt_sha256`), yêu cầu ngắn gọn "thêm dấu câu, chia đoạn, viết hoa đầu câu, giữ nguyên từ ngữ, chỉ trả văn bản"; trả **văn bản thường** (không JSON), đoạn cách nhau dòng trống. Chiếu deterministic (stdlib `difflib.SequenceMatcher`, `autojunk=False`): tách token output AI, chuẩn hóa như `normalize_word` (NFC, chữ thường, bỏ dấu câu đầu/cuối token), gióng với dãy token nguồn. Bài = **đúng dãy token nguồn**, mỗi token gốc nhận từ token AI khớp (khối `equal`): dấu câu đầu/cuối token (chỉ `. , ? ! : ; …` và ngoặc kép), chữ hoa ký tự đầu, ngắt đoạn sau token. Token nguồn không khớp (AI thêm / bớt / đổi chữ) → giữ chữ gốc, không dấu; token AI thừa → bỏ. Sau chiếu: chữ đầu mỗi đoạn và sau `. ? ! …` viết hoa, đoạn cuối kết thúc bằng dấu câu kết (thiếu → thêm `.`). Tỉ lệ khớp = token nguồn khớp / tổng; < 0.9, output rỗng hoặc lỗi HTTP/timeout → retry theo `retries`; hết lượt → `origin: raw` (một đoạn = text nguồn, viết hoa chữ đầu, dấu chấm cuối), UI cảnh báo. Bài `ai` có < 4 dấu / 100 từ → UI nhãn "ít dấu câu" (vẫn là `ai`). Text dài: chia khối ≤ `[post] chunk_words` (mặc định 400) theo ranh giới dòng caption, mỗi khối một lần gọi + chiếu riêng; khối `raw` → cả bài `raw`. Log mỗi lần gọi: `work/<id>/post_log.json` (append, không byte-stable, như CP9 C6) gồm output thô của AI và tỉ lệ khớp.
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
2. Chiếu P3: output AI thêm / bớt / đổi / đảo chữ → bài vẫn đúng dãy token nguồn, dấu câu / hoa / ngắt đoạn chỉ lấy từ token khớp; tỉ lệ khớp < 0.9 → retry, hết lượt → `raw`; nhãn "ít dấu câu"; text dài chia khối theo ranh giới dòng, nối lại đúng.
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
- Chạy thật với Ollama `qwen3:14b` trên bản sao (không ghi `work/` / `output/` chính): ≥ 10 Short từ ≥ 2 tập Short + 2 Short khai thị; ghi vào Result (cùng 18 bài lần đo đầu) số bài `ai` / `raw`, tỉ lệ khớp, dấu câu / 100 từ mỗi bài, thời gian, số ký tự; Q4 đạt theo tiêu chí sửa đổi.
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

### Round 1 (implementation + BLOCKED on Q4)

- Main changes: `src/auto_short/post/` mới (`source.py`, `validate.py`, `prompt.py`, `logic.py`, `store.py`, `stage.py`, `images.py`, `fetch.py`); `config.py` `PostConfig`; `web/jobs.py` (`PostComposeTarget`, `ImageSearchTarget`); `web/app.py` route P9; `web/static/` khu "Bài đăng cộng đồng" + hộp thoại "Thư viện ảnh"; docs P12.
- Tests round 1: `tests/test_post_backend.py`, `test_post_images.py`, `test_post_fetch.py`, `test_post_stage.py`, `test_web_post_cp815.py`; `test_config.py` +2. Toàn bộ suite: 2 lần `pytest -q -n auto` (1090 rồi 1091 passed, 1 fail không liên quan — flaky có sẵn `test_web_lanes_cp810.py::test_lanes_artifacts_identical_to_serial`).
- Bug tìm thấy khi chạy thật, đã sửa: `post/fetch.py` `fetch()` crash `UnicodeEncodeError` với URL có ký tự Unicode chưa mã hoá (link ảnh thật từ hwadzan.com) — sửa bằng `_iri_to_uri()`; test hồi quy `test_fetch_encodes_non_ascii_path`.
- **Q4 (tiêu chí cũ) — BLOCKED:** chạy thật `qwen3:14b` trên bản sao dữ liệu thật, 18 bài (2 tập Short + 2 khai thị): qua validate token-chặt lần đầu 72 % (< 90 %), 0 % qua sau retry, 28 % `raw`. Đọc `post_log.json`: 2 case `raw` là lỗi nội dung thật (AI thêm từ / tách một token dính do lỗi caption) — validator đúng, nhưng quá chặt để hữu dụng; một case "qua" hầu như không có dấu câu. Báo lại theo đúng chỉ dẫn (không tự đổi model/prompt) → ORCHESTRATOR review round 1 sửa contract (P3, Q4) bên dưới.

### Round 2 (ORCHESTRATOR review round 1: B1 head_cut + P3/Q4 amendment)

- **B1 (blocking, đã sửa):** `post/source.py` implement sai P2 — giữ nguyên từ nối bị `head_cut` (đúng ra phải bỏ, như `titling.logic.clip_text`), và tệ hơn: ghi nhầm trong docstring "HUMAN LEAD 2026-09-29 accepted this simplification" — **HUMAN LEAD không hề duyệt điều đó**. Đã sửa: `_full_clip_lines` dùng lại `titling.logic.clip_text` cho đúng bước bỏ `head_cut` + validate (cùng thông báo lỗi khi không khớp), tự dựng lại breakdown theo unit (cho ranh giới khối P3) sao cho nối lại cho đúng chuỗi của `clip_text`. Gỡ toàn bộ ghi nhận sai (docstring `source.py`, decision record P2, Result round 1 — không sửa lại bản round 1 phía trên, chỉ không lặp lại ở đây). Test mới: `test_source_text_ai_clip_drops_head_cut_words`, `test_source_text_head_cut_mismatch_raises`, `test_full_clip_lines_drops_head_cut_words_spanning_a_unit_boundary`, `test_full_clip_lines_no_head_cut_returns_unit_texts` (`post_helpers.make_post_episode` thêm tham số `head_cut_words`).
- **P3 amendment:** thay validate token-chặt bằng AI tự do (prompt `v2`, văn bản thường, không JSON/`format`) + chiếu deterministic (`post/validate.project_response`, `difflib.SequenceMatcher(autojunk=False)`) về đúng dãy token nguồn — dấu câu / hoa-thường / ngắt đoạn chỉ lấy từ token AI khớp, token không khớp giữ nguyên không dấu, token AI thừa bị bỏ. `selection/client.py`: `ChatClient`/`OllamaClient`/`request_body` nhận `format: dict | None` (bỏ key `format` khi rỗng; thứ tự key giữ nguyên khi có `format`, không đổi `[selection]`/`[titling]` — kiểm bằng `tests/test_selection_stage.py`, `tests/test_titling_stage.py` PASS không đổi). `[post] prompt_version` mặc định đổi `"v1"` → `"v2"` (`v1` giữ trong `post/prompt.py` làm tư liệu). UI: nhãn "Ít dấu câu" khi bài `ai` có < 4 dấu / 100 từ (`post_validate.marks_per_100_words`, field `low_punctuation` của `GET .../posts`).
- Tests round 2: viết lại `tests/test_post_backend.py` phần P3 (9 test `project_response` + `marks_per_100_words`, bỏ test JSON cũ), viết lại `FakeClient` của `tests/test_post_stage.py` (trả văn bản thường); `tests/test_config.py` cập nhật default `prompt_version` mong đợi. Tổng test file post hiện tại: `test_post_backend.py` 53, `test_post_images.py` 10, `test_post_fetch.py` 13, `test_post_stage.py` 11, `test_web_post_cp815.py` 44 (không đổi, không phụ thuộc JSON) — cộng `test_config.py` phần `[post]`.
- Toàn bộ suite: **1 lần** `pytest -q -n auto` sau round 2 (theo đúng "test policy: full suite một lần trước khi báo") — **1101 passed**, không fail nào (kể cả `test_lanes_artifacts_identical_to_serial` pass lần này — flaky, không do CP8.15).
- **Q4 (tiêu chí sửa đổi) — PASS:** chạy lại đúng 18 bài của lần đo đầu (cùng bản sao dữ liệu, cùng config, `qwen3:14b`, prompt `v2`):

  | Episode | Clip | origin | tỉ lệ khớp | dấu/100 từ | thời gian | ký tự |
  |---|---|---|---|---|---|---|
  | 4oOZz2CBz3g | k01 | ai | 0.993 | 7.5 | 5.6 s | 633 |
  | 4oOZz2CBz3g | k02 | ai | 0.994 | 14.2 | 2.8 s | 740 |
  | 4oOZz2CBz3g | k03 | ai | 1.000 | 11.8 | 3.2 s | 869 |
  | 4oOZz2CBz3g | k04 | ai | 0.991 | 13.5 | 2.0 s | 498 |
  | 4oOZz2CBz3g | k05 | ai | 0.987 | 12.8 | 3.8 s | 1076 |
  | 4oOZz2CBz3g | k06 | ai | 0.991 | 10.8 | 2.1 s | 532 |
  | 4oOZz2CBz3g | k07 | ai | 1.000 | 14.7 | 2.0 s | 509 |
  | c_6QuBGFzY4 | k01 | ai | 1.000 | 9.4 | 2.4 s | 592 |
  | c_6QuBGFzY4 | k02 | ai | 0.994 | 9.4 | 3.0 s | 753 |
  | c_6QuBGFzY4 | k03 | ai | 1.000 | 10.1 | 3.4 s | 909 |
  | c_6QuBGFzY4 | k04 | ai | 1.000 | 4.1 | 2.2 s | 528 |
  | c_6QuBGFzY4 | k05 | ai | 1.000 | **3.8** | 2.0 s | 431 |
  | c_6QuBGFzY4 | k06 | ai | 1.000 | 6.0 | 3.9 s | 790 |
  | c_6QuBGFzY4 | k07 | ai | 1.000 | 9.6 | 2.2 s | 498 |
  | c_6QuBGFzY4 | k08 | ai | 1.000 | 11.2 | 3.1 s | 730 |
  | c_6QuBGFzY4 | k09 | ai | 1.000 | 13.3 | 2.5 s | 582 |
  | 4oOZz2CBz3g.kt | k01 | ai | 0.998 | 9.6 | 9.7 s | 2674 |
  | c_6QuBGFzY4.kt | k01 | ai | 0.999 | 6.8 | 11.2 s | 2865 |

  - `origin: ai` 18/18 = 100 % (0 `raw` — so với 28 % ở round 1); tỉ lệ khớp trung bình 0.997.
  - Bài `ai` có ≥ 4 dấu / 100 từ: **17/18 = 94,4 %** ≥ 90 % ngưỡng Q4 sửa đổi → **ĐẠT**. Đúng 1 bài dưới ngưỡng (`c_6QuBGFzY4` k05, 3.8 dấu/100 từ) — text nguồn caption khá rối (giọng giảng nhanh, câu ngắn); UI sẽ hiện nhãn "Ít dấu câu" cho bài đó (vẫn `ai`, sửa tay được).
  - Thời gian: 2,0–11,2 s/bài (trung bình 3,7 s) — nhanh hơn round 1 (9,0 s) vì không còn multi-chunk-retry ở các case trước đây `raw`.
  - Đọc `post_log.json`: không còn thấy hiện tượng "qua nhưng gần như không có dấu câu" của round 1 (case `4oOZz2CBz3g` k01 trước kia 0 dấu câu, giờ 7.5 dấu/100 từ, đọc tự nhiên).
- Tìm ảnh thật (không đổi so với round 1, không phụ thuộc P2/P3): link ảnh trực tiếp trong `sources.tsv` (`…/1淨空老法師01.jpg`) → 1 ảnh, 5,8 s; trang HTML thật cùng site (`https://www.hwadzan.com/`) → 40 ứng viên, 20,5 s, 10 ảnh đạt vào thư viện + `sources.tsv`, 14 bị bỏ (nhỏ hơn 600 px, lý do ghi rõ).
- Mẫu đọc (P4, kèm ảnh thật) — round 1: `…/scratchpad/cp815-verify/samples/` (5 mẫu, 3 `ai` + 2 `raw`, tiêu chí cũ). Round 2 (bài mới sau sửa P3): `…/scratchpad/cp815-verify/samples-v2/` (5 mẫu, đều `ai`; toàn văn 2 mẫu tiêu biểu đã in trong transcript agent nếu thư mục scratch không còn khi đọc report này) — gồm `4oOZz2CBz3g` k01 (case cũ 0 dấu câu, giờ đã tốt), `4oOZz2CBz3g` k05, `c_6QuBGFzY4` k04 (gần ngưỡng 4 dấu/100 từ), và 2 Short khai thị. Sample `c_6QuBGFzY4` k04 lộ rõ giới hạn không liên quan CP8.15: caption ASR của đoạn đó khá lộn xộn (giọng nhanh / thuật ngữ) — AI giữ đúng chữ nguồn (đúng P3) nhưng câu khó đọc; đây là hạn chế chất lượng transcript, không phải lỗi tính năng.
- Review: round 1 (ORCHESTRATOR) — 1 blocking (B1) + amendment P3/Q4, đã xử lý xong ở trên; chưa có review round 2.
- Known limitations:
  - `c_6QuBGFzY4` k05 dưới ngưỡng 4 dấu/100 từ (3.8) — UI nhãn "Ít dấu câu", sửa tay được.
  - Chất lượng caption ASR gốc (không liên quan CP8.15) ảnh hưởng độ tự nhiên của một số bài (case k04 trên) — AI đúng luật (giữ nguyên chữ), chỉ là nguồn khó đọc.
  - Prompt `v1` (JSON + validate token-chặt) không còn được dùng (mặc định `v2`); giữ trong code làm tư liệu, không có test riêng cho pipeline JSON cũ (đã gỡ theo amendment).
  - Manual test checklist (điện thoại, đăng thử thật) chưa chạy — cần HUMAN LEAD / Tech Lead trước khi merge.
  - Chưa có review round 2.
- PR: chưa tạo (theo `docs/ai/project-profile.md` §5, PR chỉ sau READY + HUMAN LEAD approval — Status vừa chuyển READY ở round 2, tạo PR là quyết định của HUMAN LEAD/ORCHESTRATOR). Commit cục bộ trên `feature/cp8.15-community-post`, chưa push.
