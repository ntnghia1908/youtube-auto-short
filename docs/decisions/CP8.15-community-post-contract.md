# CP8.15 — Community Post Contract (bài đăng cộng đồng YouTube từ Short)

| Metadata | Value |
|---|---|
| Status | ACCEPTED (chờ manual test HUMAN LEAD) |
| Accepted by | HUMAN LEAD 2026-09-29: APPROVE TASK; Q1 ảnh chọn trong thư viện + upload + tìm ảnh từ link (ảnh tìm được vào thẳng thư viện); Q2–Q4 theo đề xuất (P4 bố cục, soạn theo yêu cầu, model `qwen3:14b`) |
| Checkpoint | CP8.15 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8.15 |
| Task contract | `docs/tasks/CP8.15-community-post.md` |
| Builds on | `docs/decisions/CP6-titling-contract.md` (G3 `clip_text`, G5 validate style); `docs/decisions/CP8.2-title-override-contract.md` (CP9: cut points, added Shorts, `review.cuts.lines_in`); `docs/decisions/CP8.3-web-contract.md` W4/W5/W7 (job model, API, auth); `docs/decisions/CP8.9-khai-thi-contract.md` (một Short/khai thị dùng chung route); CP1 §10 (dependency: không thêm) |

File này là **canonical owner** của: text nguồn một bài đăng cộng đồng của một Short (P2), prompt AI "chỉ thêm dấu câu / chia đoạn" (`post` `v1`, P3) và validate token, schema `posts.json` (P7) + `post_log.json`, thư viện ảnh (P5) + upload (P5a) + tìm ảnh từ link (P5b), link Short (P6), bố cục text sao chép (P4), config `[post]` (P11), route web + job (P9) và security tải ảnh từ link (P13). Nơi khác chỉ trỏ tới đây. Không đổi contract stage CP2–CP9: `posts.json` không phải input của stage nào (như `publish.json`, CP8.3 W8). Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/post/` (`source.py`, `validate.py`, `prompt.py`, `logic.py`, `store.py`, `stage.py`, `images.py`, `fetch.py`), `src/auto_short/config.py` (`PostConfig`), `src/auto_short/web/app.py` (route), `src/auto_short/web/jobs.py` (`PostComposeTarget`, `ImageSearchTarget`), `src/auto_short/web/static/` (khu "Bài đăng cộng đồng", hộp thoại "Thư viện ảnh").

## P1. Phạm vi bài + khi soạn

Một bài cho mỗi Short `rendered` chưa xóa của một episode (Short AI, Short thêm CP9; tập Short và khai thị dùng chung route). Soạn theo yêu cầu (không tự chạy sau render): nút "Soạn bài" một Short, nút "Soạn bài cho mọi Short" (bỏ qua Short đã có bài còn hợp lệ — `source_sha256` khớp text nguồn hiện tại). Job chạy ở làn `ai` (CP8.10 W5); preflight Ollama trước khi chạy job (như W4) nhưng chỉ kiểm model `[post] model` (không kiểm `[selection]`/`[titling]`) — hàm riêng `post.stage.preflight`, dùng lại `PreflightError` của `pipeline.py` để route áp cùng luật 503. Một episode chỉ có tối đa một job đang `queued`/`running` (kể cả job soạn bài) — quy tắc chung của job runner (CP8.10); gửi soạn bài khi episode đang có job khác → 409.

## P2. Text nguồn

Đúng lời của Short hiện tại, đọc trực tiếp artifact của episode (`clips.json`, `candidates.json`, `transcript.json`, `silences.json`, `review.json`; `post/source.py`, không sửa `review/`):

- Clip AI (`clips.json`) **không** có cut tay (`review.json` `cuts`): text = nối `text` mọi `units` (`candidates.json`) của `unit_ids` — như CP6 G3 `clip_text` nhưng **không** áp bước bỏ `head_cut`: từ nối đầu Short bị `head_cut` (CP5 B11) cắt khỏi *video* vẫn còn trong text nguồn của bài đăng. Đơn giản hóa có chủ đích (HUMAN LEAD 2026-09-29, xem Known limitations của task): tối đa một từ nối ở đầu, sửa tay được (`origin: manual`) nếu thấy sai.
- Clip có cut tay, hoặc Short thêm tay (`review.json` `added`): text = nối `text` các dòng caption trong khoảng hiện tại (`review.cuts.lines_in`) — cùng luật `review.shorts.added_titling_input` dùng cho title AI của Short thêm tay.
- `source_sha256` = sha256 hex của text nguồn (UTF-8) → bài `stale` khi khác giá trị lưu trong `posts.json` (sửa đầu/cuối, selection chạy lại, hoặc Short không còn tồn tại).

## P3. AI chỉ thêm dấu câu / chia đoạn

Prompt mới `post` `v1` (text trong `post/prompt.py`, có `prompt_sha256`); user prompt = text nguồn (P2) hoặc một khối (dưới); trả `{"paragraphs": ["…"]}`.

Validate deterministic (`post/validate.py`), hai lớp:

1. Nội dung từ: nối mọi đoạn bằng dấu cách, tách token theo khoảng trắng, chuẩn hóa mỗi token như `selection.logic.normalize_word` (NFC, chữ thường, bỏ dấu câu hai đầu) — dãy token phải **bằng đúng** dãy token nguồn (không thêm / bớt / đổi / đảo).
2. Dấu câu thêm: so ký tự (đã hạ chữ thường) của text nối với text nguồn (đa tập ký tự, không theo vị trí) — ký tự dư ra chỉ được thuộc `. , ? ! : ; …` và ngoặc kép (`"` `"` `"`).

Sai (một trong hai lớp, hoặc lỗi HTTP/JSON/schema) → retry theo `[post] retries`; hết lượt cho **một khối** → cả Short `origin: raw` (một đoạn = text nguồn, viết hoa chữ đầu, thêm dấu chấm cuối nếu chưa có dấu kết câu), UI cảnh báo.

Text dài (khai thị 4–7 phút): chia khối theo ranh giới dòng caption / unit (không cắt ngang), mỗi khối ≤ `[post] chunk_words` (mặc định 400), mỗi khối một lần gọi AI + validate riêng; khối nào cũng qua mới `origin: ai` (paragraphs nối theo thứ tự khối), một khối hỏng hẳn → cả Short `raw` (P3 trên, trên toàn bộ text, không phải chỉ khối hỏng).

Log mỗi lần gọi AI: `work/<id>/post_log.json` (append, không byte-stable — có timestamp mỗi entry, như `review_titling_log.json` CP9 C6): model, prompt, từng lần gọi (request/response/lỗi/valid), khối, `origin`, thời gian.

## P4. Bố cục text sao chép

Server tính (`post/logic.compose_copy_text`; API `text`/`chars` của một bài, P7), UI hiện số ký tự (giới hạn ký tự bài đăng cộng đồng chưa kiểm — không cắt, HUMAN LEAD xác nhận khi đăng thử):

```text
<title Short đang dùng>

<đoạn 1>

<đoạn n>

— <speaker>, <series> tập <episode>     (titles.json header.fields; không có header → bỏ dòng)
▶ Xem video: <link>                     (chỉ khi đã dán link)

#<series> #TịnhKhông …                  (hashtags CP8.8 riêng bộ kinh, hoặc #<series> + [web] hashtags)
```

## P5. Thư viện ảnh

`[post] image_dir` (mặc định `~/.local/share/auto-short/post-images/`, ngoài repo, không commit ảnh); chỉ `.jpg`/`.jpeg`/`.png` ở cấp đầu (`post/images.py`), phục vụ nguyên file (không resize, không chèn chữ). Gán tự động khi soạn **một bài mới** (không phải soạn lại): ảnh được dùng ít nhất trong mọi `posts.json` của workspace (mọi episode), hòa → theo tên file (`images.least_used`); soạn lại giữ `image` cũ. "Đổi ảnh" = lưới chọn từ thư viện (hộp thoại dùng chung mọi Short). Ảnh không còn trong thư viện → bài hiện `image_missing` (đọc lúc trả API, không sửa `posts.json`); tick "Đã đăng bài" vẫn giữ. "Xóa khỏi thư viện" xóa file; API trả số bài đang dùng ảnh đó để UI xác nhận trước.

## P5a. Upload ảnh

`POST /api/post-images?name=<tên gốc>`, body thô (`Content-Type: image/jpeg` | `image/png`). Kiểm (`images.validate`): magic bytes JPEG (`FFD8`, đọc `SOF0…SOF3/C5-C7/C9-CB/CD-CF` cho kích thước) hoặc PNG (`89504E47…`, `IHDR`) — không dùng Pillow; ≤ 15 MB; cạnh ngắn ≥ 600 px. Tên lưu = tên gốc làm sạch (NFKD bỏ dấu, giữ chữ/số/`-`/`_`, đuôi chuẩn theo magic bytes thật, không theo đuôi client gửi); trùng tên → `-2`, `-3`…; trùng nội dung (sha256) với ảnh có sẵn → không lưu lại, trả ảnh có sẵn (`duplicate: true`). Ghi atomic (`workspace.atomic_write_bytes`).

## P5b. Tìm ảnh từ link

`POST /api/post-images/search {url}` → job nền làn `prepare` (không cần Ollama), id job runner riêng `_post_images` (không phải episode id — một job tìm ảnh một lúc, 409 khi đang chạy); `GET /api/post-images/search/{job}` đọc kết quả (`ImageSearchTarget.result`).

Link là ảnh (Content-Type hoặc magic bytes) → một ứng viên; link là trang HTML (≤ 5 MB) → `html.parser` (stdlib) lấy URL từ `<img src>`/`<img data-src>`/`<img srcset>` (bản lớn nhất theo mô tả `w`, không có mô tả → bản cuối) và `<meta property="og:image">`, resolve tương đối theo `base_url`, bỏ trùng, tối đa 40. Mỗi ứng viên tải theo luật P5a (≤ 15 MB, cạnh ngắn ≥ 600 px); đạt → **vào thẳng thư viện** (không có bước chọn ứng viên, HUMAN LEAD 2026-09-29), URL nguồn ghi `<image_dir>/sources.tsv` (`tên<TAB>URL`, append); không đạt → đếm lý do (`skipped`), tiếp tục. Nút nhanh mỗi link trong `[post] image_sources` (mặc định rỗng) chỉ điền + chạy tìm, không tự tìm trên search engine.

## P6. Link Short

Ô dán link (tùy chọn). Nhận `youtube.com/watch?v=<id>`, `youtu.be/<id>`, `youtube.com/shorts/<id>` (có/không `www.`/`m.`, bỏ query khác `v`) → chuẩn hóa `https://youtube.com/shorts/<id>` (`post/logic.normalize_link`, độc lập với `web/urls.py` — không thêm import ngược từ `post/` vào `web/`); dạng khác → `LinkError` (route 422). Rỗng (`null` hoặc chuỗi trắng) = xóa link.

## P7. `work/<id>/posts.json`

State người dùng, **không** là input stage nào (như `publish.json`, CP8.3 W8): ghi atomic, JSON indent 2, thứ tự key cố định, entry theo thứ tự `render_manifest.json` (`shorts[]` `status: "rendered"`):

```json
{"schema_version": 1, "episode_id": "<id>",
 "posts": [{"clip_id": "k01", "candidate_id": "c00077", "source_sha256": "<64 hex>",
            "paragraphs": ["…"], "origin": "ai", "image": "03.jpg", "link": null,
            "posted_at": null, "updated_at": "2026-09-29T10:05:27Z"}]}
```

`origin` = `ai` | `raw` (P3) | `manual` (sửa tay text qua `PUT`; không validate token, chỉ không rỗng). Khóa `(clip_id, candidate_id)` như CP8.2 T3 (không dùng ở đây để bỏ qua entry — mỗi `clip_id` một entry, `candidate_id` chỉ để đối chiếu khi debug). Soạn lại một bài đã có: thay `paragraphs` / `origin` / `source_sha256`, giữ `image`, `link`, `posted_at` (`post.store.with_compose`). File hỏng (JSON lỗi / sai schema) → API trả `post_error`, không ghi đè (`post.store.read_posts` raise, không có fallback ghi). Ghi tuần tự bằng một `threading.Lock` trong server (`post_lock`, tương tự `publish_lock` CP8.5); các route sửa tay (`PUT`, `posted`) **không** bị khóa bởi job đang chạy (không qua `submit_lock`/`_busy`, khác title/cut CP8.2/CP9) — chỉ khóa lẫn nhau và với chính job soạn bài qua `post_lock`. Xóa tập → mất cùng workspace (không xử lý riêng); tập archived (CP8.6) vẫn soạn được (đọc artifact, không cần video nguồn).

## P8. "Đã đăng bài"

`posted_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`) | `null`, qua `POST /api/episodes/{id}/posts/{clip}/posted {value: bool}`; độc lập với tick "Đã đăng" Short (`publish.json`, CP8.5 X4) và **không** ảnh hưởng "Xong" (CP8.7 L4) hay gợi ý dọn (CP8.6 S1/S2). Bài đã tick mà text nguồn đổi → vẫn giữ tick, hiện `stale` (P2).

## P9. Web

- Thẻ mỗi Short `rendered` (tập Short + khai thị): khu thu gọn "Bài đăng cộng đồng" — chưa có bài: "Soạn bài"; có bài: nhãn `raw` / `stale` / `image_missing`, textarea các đoạn (đoạn cách nhau dòng trống) + "Lưu đoạn" (→ `manual`), ảnh thu nhỏ + "Đổi ảnh" (mở thư viện), ô link + "Lưu link", số ký tự (P4), "Sao chép bài" (dùng fallback clipboard hiện có, CP8.3 W6), "Soạn lại", tick "Đã đăng bài".
- Trang tập: nút "Soạn bài cho mọi Short" (ẩn khi không có Short `rendered`), đếm "Bài đăng cộng đồng đã đăng: x/y".
- Hộp thoại "Thư viện ảnh" (mở từ "Đổi ảnh"): lưới ảnh (kích thước, số bài dùng), "Tải ảnh lên", ô dán link + nút nhanh (`[post] image_sources`) + "Tìm ảnh", "Xóa khỏi thư viện".
- Route (cookie CP8.3 W2; 422 lỗi dữ liệu; 503 Ollama khi preflight lỗi; 409 khi episode đang có job — kể cả job khác, cùng luật job runner CP8.10):
  - `GET /api/episodes/{id}/posts` → `{posts: [{clip_id, paragraphs, origin, stale, image, image_missing, link, posted, posted_at, text, chars}], post_error}` (`text`/`chars` = bài đầy đủ P4, không phải chỉ `paragraphs`).
  - `POST /api/episodes/{id}/posts {clips: [clip_id…] | "all"}` → 202 `{job}` (làn `ai`).
  - `PUT /api/episodes/{id}/posts/{clip} {paragraphs?, image?, link?}` → 200 bài (P7 view); cần đã có bài (chưa soạn → 422); `image` phải là tên ảnh có trong thư viện (không → 404, như path traversal AC4).
  - `POST /api/episodes/{id}/posts/{clip}/posted {value: bool}` → 200 `{clip_id, posted, posted_at}`.
  - `GET /api/post-images` → `{images: [{name, width, height, bytes, used, source}], image_sources}`; `GET /files/post-images/{name}` (`?download=1` → tải về; tên ngoài thư viện / path traversal → 404).
  - `POST /api/post-images?name=<tên gốc>` (body thô P5a) → 200 `{image, duplicate}`; `DELETE /api/post-images/{name}` → 200 `{used}` (404 tên không có / path traversal).
  - `POST /api/post-images/search {url}` → 202 `{job}` (job runner id `_post_images`); `GET /api/post-images/search/{job}` → `{status, found, added: [tên], duplicate: [tên có sẵn], skipped: {reason: count}}`; 409 khi đang có job tìm ảnh; 404 job id không có / không phải job tìm ảnh.

## P10. Không CLI mới

Như CP8.5 / CP9: chỉ web gọi `post/`.

## P11. Config `[post]`

`model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `retries`, `chunk_words`, `image_dir`, `image_sources` + execution-only (`ollama_host`, `timeout`, `retry_backoff`, như `[titling]`). Không vào `config_hash` của stage nào (`posts.json` không phải artifact stage). `model` mặc định `qwen3:14b` (Q4, HUMAN LEAD 2026-09-29).

## P12. Tài liệu

Canonical: file này. Trỏ tới: `docs/decisions/CP8.3-web-contract.md` W5 (job model), W6 (UI), W7 (API); `docs/ai/project-profile.md` (authority list + dòng module `post/`); `README.md` (config `[post]`, chép ảnh vào thư viện); `AUTO_SHORT_CHECKPOINT_PLAN.md`; `docs/workflow/current-state.md`.

## P13. Security (tải từ link, P5b)

Chỉ sau đăng nhập (CP8.3 W2 cookie, kiểm ở middleware auth chung, không riêng route này); chỉ `http`/`https`; phân giải host (`socket.getaddrinfo`) và từ chối địa chỉ loopback / private / link-local / multicast / reserved / unspecified (`ipaddress`, stdlib) — kiểm lại sau **mỗi** redirect (tối đa 3, `urllib.request.HTTPRedirectHandler` tùy biến), không kiểm một lần rồi tin AI theo; timeout 20 s mỗi request; giới hạn byte đọc (trang 5 MB, ảnh 15 MB) kể cả khi thiếu `Content-Length` (đọc `limit + 1` byte, dư → lỗi, không đọc tiếp); không gửi cookie web đi (gọi `urllib.request` riêng, không dùng session của web); không thực thi / phục vụ HTML tải về (chỉ ảnh JPEG/PNG đã kiểm magic bytes qua P5a, phục vụ với `Content-Type` theo đuôi tên tệp; `X-Content-Type-Options: nosniff` đã áp cho mọi response qua middleware CP8.3 W2). Không thêm dependency: `urllib.request`, `ipaddress`, `socket`, `html.parser` (stdlib).

## Acceptance Criteria

Xem `docs/tasks/CP8.15-community-post.md` AC 1–12 (test `tests/test_post_*.py`, `tests/test_web_post_cp815.py`).

## Result

Xem task contract `docs/tasks/CP8.15-community-post.md` mục Result (verification, review, quyết định khi implement, known limitations, PR).
