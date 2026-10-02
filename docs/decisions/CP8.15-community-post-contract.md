# CP8.15 — Community Post Contract (bài đăng cộng đồng YouTube từ Short)

| Metadata | Value |
|---|---|
| Status | ACCEPTED (chờ manual test HUMAN LEAD) |
| Accepted by | HUMAN LEAD 2026-09-29: APPROVE TASK; Q1 ảnh chọn trong thư viện + upload + tìm ảnh từ link (ảnh tìm được vào thẳng thư viện); Q2–Q4 theo đề xuất (P4 bố cục, soạn theo yêu cầu, model `qwen3:14b`). Sửa đổi HUMAN LEAD 2026-09-29 (ORCHESTRATOR review round 1, sau Q4 BLOCKED ở 72%): P3 đổi sang AI tự do + chiếu (projection) về chữ gốc bằng `difflib` (prompt `v2`), Q4 đổi tiêu chí (≥ 90% bài `ai` có ≥ 4 dấu câu / 100 từ); B1: bản đầu implement sai P2 (giữ nguyên từ nối bị `head_cut`, ghi nhầm là HUMAN LEAD đã chấp nhận) — sửa lại đúng P2 gốc (bỏ `head_cut` như CP6 G3). |
| Checkpoint | CP8.15 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8.15 |
| Task contract | `docs/tasks/CP8.15-community-post.md`; sửa đổi CP8.17: `docs/tasks/CP8.17-download-rules.md`; sửa đổi CP8.18: `docs/tasks/CP8.18-post-corrections.md`; sửa đổi CP8.19: `docs/tasks/CP8.19-post-doc-source.md` |
| Builds on | `docs/decisions/CP6-titling-contract.md` (G3 `clip_text`, G5 validate style); `docs/decisions/CP8.2-title-override-contract.md` (CP9: cut points, added Shorts, `review.cuts.lines_in`); `docs/decisions/CP8.3-web-contract.md` W4/W5/W7 (job model, API, auth); `docs/decisions/CP8.9-khai-thi-contract.md` (một Short/khai thị dùng chung route); CP1 §10 (dependency: không thêm) |

File này là **canonical owner** của: text nguồn một bài đăng cộng đồng của một Short (P2), prompt AI tự do + chiếu (projection) deterministic về chữ gốc (`post` `v2`, P3), schema `posts.json` (P7) + `post_log.json`, thư viện ảnh (P5) + upload (P5a) + tìm ảnh từ link (P5b), link Short (P6), bố cục text sao chép (P4), config `[post]` (P11), route web + job (P9) và security tải ảnh từ link (P13), bài lấy từ văn bản gốc bài giảng (P15, CP8.19). Nơi khác chỉ trỏ tới đây. Không đổi contract stage CP2–CP9: `posts.json` không phải input của stage nào (như `publish.json`, CP8.3 W8). Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/post/` (`source.py`, `validate.py`, `prompt.py`, `logic.py`, `store.py`, `stage.py`, `images.py`, `fetch.py`, `corrections.py`, `doc.py`), `src/auto_short/config.py` (`PostConfig`), `src/auto_short/web/app.py` (route), `src/auto_short/web/jobs.py` (`PostComposeTarget`, `ImageSearchTarget`), `src/auto_short/web/static/` (khu "Bài đăng cộng đồng", hộp thoại "Thư viện ảnh").

## P1. Phạm vi bài + khi soạn

Một bài cho mỗi Short `rendered` chưa xóa của một episode (Short AI, Short thêm CP9; tập Short và khai thị dùng chung route). Soạn theo yêu cầu (không tự chạy sau render): nút "Soạn bài" một Short, nút "Soạn bài cho mọi Short" (bỏ qua Short đã có bài còn hợp lệ — `source_sha256` khớp text nguồn hiện tại). Job chạy ở làn `ai` (CP8.10 W5); preflight Ollama trước khi chạy job (như W4) nhưng chỉ kiểm model `[post] model` (không kiểm `[selection]`/`[titling]`) — hàm riêng `post.stage.preflight`, dùng lại `PreflightError` của `pipeline.py` để route áp cùng luật 503. Một episode chỉ có tối đa một job đang `queued`/`running` (kể cả job soạn bài) — quy tắc chung của job runner (CP8.10); gửi soạn bài khi episode đang có job khác → 409.
- **Sửa đổi FIX-ollama-wait (HUMAN LEAD 2026-09-30, O4, O5):** route soạn bài không còn preflight trong request (bỏ 503): luôn 202 + job; preflight chạy ở làn `ai` và mất kết nối → job đợi GPU (CP8.3 W5). Canonical: `docs/tasks/FIX-ollama-wait.md`.

**Sửa đổi CP8.16** (task `docs/tasks/CP8.16-post-tab-auto.md`, HUMAN LEAD 2026-09-30 APPROVE R1–R5; canonical R2–R4 ở file task đó): (R2) bài được soạn **tự động** thay cho "theo yêu cầu" — sau mỗi job `pipeline` / `render` / `add` của episode kết thúc (`done` hoặc `failed`) server xếp job `post` `auto`; trang tab "Bài đăng" tự gửi `auto` một lần mỗi lần tải trang cho tập có bài thiếu / cần soạn lại; nút "Soạn bài cho mọi Short" thay bằng "Soạn bài còn thiếu" (`auto`). (R3) job `post` chạy dưới khóa runner riêng `<episode_id>#post` (làn `ai` như cũ): không còn chiếm khóa "một job mỗi episode" nên sửa title / cut / thêm / xóa Short không bị 409 vì nó; tối đa một job `post` đợi / chạy mỗi episode (gửi lại khi đang đợi → trả job đó; trigger tự động khi đang chạy → thêm một lượt `auto`); gửi tay khi episode có job `pipeline` → 409; xóa tập xét cả hai khóa. (R4) `clips: "auto"` = Short `rendered` chưa có bài, hoặc bài `stale` chưa tick "Đã đăng bài" và `origin` khác `manual` (`post.stage.auto_clips`); `"all"` và danh sách clip giữ nghĩa cũ.

**Sửa đổi FIX-post-doc-no-gpu (HUMAN LEAD 2026-10-02):** preflight Ollama của job `post` chạy trễ, ngay trước Short đầu tiên cần AI (bài lấy từ văn bản gốc không cần GPU). Canonical: `docs/tasks/FIX-post-doc-no-gpu.md`, `docs/tasks/FIX-ollama-wait.md` O5.

**Sửa đổi CP8.19 (HUMAN LEAD 2026-10-02):** bộ kinh có "Văn bản gốc" (P15) → bài chưa đăng `ai` / `raw` của các tập trong bộ được soạn lại ngay khi gắn link (xếp job `post` theo P15 D7); khi soạn, mỗi Short được thử lấy bài từ văn bản trước AI.

## P2. Text nguồn

Đúng lời của Short hiện tại, đọc trực tiếp artifact của episode (`clips.json`, `candidates.json`, `transcript.json`, `silences.json`, `review.json`; `post/source.py`, không sửa `review/`):

- Clip AI (`clips.json`) **không** có cut tay (`review.json` `cuts`): text = nối `text` mọi `units` (`candidates.json`) của `unit_ids`, **có** áp bước bỏ `head_cut` — đúng như CP6 G3 `clip_text` (từ nối đầu Short bị `head_cut`, CP5 B11, cắt khỏi video cũng bị bỏ khỏi text nguồn, vì đó không phải lời thật sự có trong Short). `post/source.py` dùng lại `titling.logic.clip_text` cho đúng bước bỏ + kiểm khớp (cùng thông báo lỗi khi `head_cut` không còn khớp đầu text, "chạy lại 'selection'"); phần chia theo unit (ranh giới khối P3) tự dựng lại nhưng cho cùng kết quả khi nối lại.
- Clip có cut tay, hoặc Short thêm tay (`review.json` `added`): text = nối `text` các dòng caption trong khoảng hiện tại (`review.cuts.lines_in`) — cùng luật `review.shorts.added_titling_input` dùng cho title AI của Short thêm tay.
- `source_sha256` = sha256 hex của text nguồn (UTF-8) → bài `stale` khi khác giá trị lưu trong `posts.json` (sửa đầu/cuối, selection chạy lại, hoặc Short không còn tồn tại).
- **Sửa đổi CP8.18 (HUMAN LEAD 2026-10-02):** khi soạn, luật `approved` của từ điển sửa lỗi (P14) được áp lên chữ nguồn **trước** AI; bài chứa chữ nguồn **sau** từ điển đã duyệt. `source_sha256` vẫn tính trên chữ nguồn chưa sửa (duyệt luật không làm bài `stale`).

## P3. AI thêm dấu câu / chia đoạn (sửa đổi HUMAN LEAD 2026-09-29, ORCHESTRATOR review round 1)

> **Sửa đổi CP8.19:** P3 chỉ là nhánh dự phòng. Tập có văn bản gốc dùng được (P15 D3) và Short gióng được vào đó (P15 D4) → bài là đoạn văn bản gốc (`origin: doc`), **không** gọi AI, **không** qua từ điển P14; còn lại (không link, khớp kém, lỗi tải, Short không gióng được) → P3 như cũ. `source_sha256` vẫn tính trên chữ nguồn P2.

> **Sửa đổi CP8.18:** "đúng chữ nguồn" ở mục này nghĩa là chữ nguồn **sau** luật `approved` của P14 (áp tất định trước khi gọi AI; chiếu và `raw` fallback dùng chữ đã sửa).

Bản đầu (prompt `v1` + validate token-chặt: dãy token AI phải bằng đúng dãy token nguồn) đo được 72% bài `ai` qua validate lần đầu trên dữ liệu thật (< 90% ngưỡng Q4 khi đó) — quá chặt với nhiễu caption thật (chỗ dính/tách từ do lỗi nhận dạng mà AI "sửa lại", vốn hợp lý nhưng validator cũ coi là đổi nội dung). Thay bằng: AI tự do diễn đạt lại dấu câu / hoa thường theo cách nó thấy hợp lý, rồi **chiếu (project) kết quả về đúng chữ nguồn** một cách xác định (không phụ thuộc AI) — nên bài luôn đúng từng chữ nguồn dù AI không được yêu cầu giữ nguyên chữ.
- **Sửa đổi FIX-ollama-wait (HUMAN LEAD 2026-09-30, O2):** lỗi mất kết nối Ollama (`ChatUnavailable`) dừng job ngay, không thử lại, **không** ghi bài `raw` (`posts.json` giữ nguyên); `raw` chỉ dành cho lỗi AI thật (retry hết lượt). Canonical: `docs/tasks/FIX-ollama-wait.md`.

- **Prompt `post` `v2`** (mặc định `[post] prompt_version`; `v1` giữ trong `post/prompt.py` làm tư liệu, không dùng): yêu cầu ngắn — thêm dấu câu, chia đoạn (xuống dòng giữa đoạn), viết hoa đầu câu, giữ nguyên từ ngữ, chỉ trả văn bản (không JSON, không giải thích). Gọi Ollama **không kèm `format`** (JSON schema) — trả lời tự do; `selection.client.ChatClient`/`OllamaClient`/`request_body` nhận `format: dict | None` (bỏ hẳn key `format` khi `None`/rỗng, thứ tự key giữ nguyên khi có `format` — không đổi hành vi của `[selection]`/`[titling]`).
- **Chiếu deterministic** (`post/validate.project_response`, stdlib `difflib.SequenceMatcher(None, norm_src, norm_ai, autojunk=False)`): tách token nguồn (`source_text.split()`) và token AI (tách theo dòng trống thành đoạn, rồi theo khoảng trắng), chuẩn hóa cả hai như `selection.logic.normalize_word` (NFC, chữ thường, bỏ dấu câu hai đầu) cho việc gióng hàng. Bài kết quả = **đúng dãy token nguồn**, không hơn không kém:
  - Token nguồn nằm trong khối `equal` (khớp với một token AI theo `SequenceMatcher`): nhận dấu câu đầu/cuối của token AI khớp (chỉ giữ `. , ? ! : ; …` và ngoặc kép `" " "`, bỏ ký tự khác), hoa/thường ký tự đầu theo token AI khớp, và một ngắt đoạn ngay sau nó nếu token AI khớp là token cuối của một đoạn AI (dòng trống).
  - Token nguồn không khớp (AI thêm / bớt / đổi / đảo chữ ở đúng vị trí đó): giữ nguyên chữ gốc, không dấu câu, không đổi hoa/thường.
  - Token AI thừa (không khớp token nguồn nào): bỏ, không dùng cho gì (kể cả tín hiệu ngắt đoạn của nó).
  - Sau chiếu: viết hoa chữ đầu mỗi đoạn và chữ đầu ngay sau mỗi dấu `. ? ! …`; đoạn cuối cùng phải kết bằng dấu câu kết (`. ? ! …`), thiếu thì thêm `.`.
  - **Tỉ lệ khớp** = số token nguồn nằm trong khối `equal` / tổng số token nguồn (0–1; không tính token AI thừa, nên AI thêm chữ không tự làm giảm tỉ lệ — chỉ AI bớt/đổi/đảo mới giảm).
- **Retry / raw:** tỉ lệ khớp < 0.9, output rỗng, hoặc lỗi HTTP/timeout → retry theo `[post] retries`; hết lượt cho **một khối** → cả Short `origin: raw` (một đoạn = text nguồn, viết hoa chữ đầu, thêm dấu chấm cuối nếu chưa có dấu kết câu), UI cảnh báo.
- **Nhãn "ít dấu câu" (Q4):** bài `origin: ai` có < 4 dấu câu `. , ? ! : ; …` / 100 từ (đếm trên `paragraphs`, không tính ngoặc kép; `post/validate.marks_per_100_words`) → UI hiện nhãn cảnh báo riêng (vẫn là `ai`, không đổi `raw`).
- **Text dài** (khai thị 4–7 phút): chia khối theo ranh giới dòng caption / unit (không cắt ngang), mỗi khối ≤ `[post] chunk_words` (mặc định 400), mỗi khối một lần gọi AI + chiếu riêng; khối nào cũng qua (≥ 0.9) mới `origin: ai` (paragraphs nối theo thứ tự khối, tỉ lệ khớp trung bình các khối); một khối hỏng hẳn (hết lượt) → cả Short `raw` (áp lại toàn bộ text, không chỉ khối hỏng).
- `post_log.json`: mỗi lần gọi ghi cả `raw_output` (văn bản thô AI trả) và `match_ratio`, cùng `request`/`response`/lỗi/thời gian như trước; entry mỗi Short ghi `match_ratio` (trung bình khi `ai`, tỉ lệ của lần thử cuối khi `raw`).

Log mỗi lần gọi AI: `work/<id>/post_log.json` (append, không byte-stable — có timestamp mỗi entry, như `review_titling_log.json` CP9 C6): model, prompt, từng lần gọi (request/response/lỗi/valid), khối, `origin`, thời gian.

## P4. Bố cục text sao chép

**Sửa đổi CP8.16 (R5):** trong dòng nguồn, một dấu `.` đứng ngay trước chữ cái được chèn một dấu cách (`HT.Tịnh Không` → `HT. Tịnh Không`; đã có dấu cách thì giữ nguyên) — chỉ trong bài đăng (`post/logic.header_line`), không đổi `titles.json`, `[titling] speaker`, header video hay `render_key`; áp lúc đọc API nên không đổi `source_sha256` / `stale`.

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

`origin` = `ai` | `raw` (P3) | `doc` (CP8.19, P15: đoạn văn bản gốc) | `manual` (sửa tay text qua `PUT`; không validate token, chỉ không rỗng). Khóa `(clip_id, candidate_id)` như CP8.2 T3 (không dùng ở đây để bỏ qua entry — mỗi `clip_id` một entry, `candidate_id` chỉ để đối chiếu khi debug). Soạn lại một bài đã có: thay `paragraphs` / `origin` / `source_sha256`, giữ `image`, `link`, `posted_at` (`post.store.with_compose`). File hỏng (JSON lỗi / sai schema) → API trả `post_error`, không ghi đè (`post.store.read_posts` raise, không có fallback ghi). Ghi tuần tự bằng một `threading.Lock` trong server (`post_lock`, tương tự `publish_lock` CP8.5); các route sửa tay (`PUT`, `posted`) **không** bị khóa bởi job đang chạy (không qua `submit_lock`/`_busy`, khác title/cut CP8.2/CP9) — chỉ khóa lẫn nhau và với chính job soạn bài qua `post_lock`. Xóa tập → mất cùng workspace (không xử lý riêng); tập archived (CP8.6) vẫn soạn được (đọc artifact, không cần video nguồn).

**Sửa đổi CP8.18:** `PUT …/posts/{clip}` có `paragraphs` còn rút đề xuất sửa từ + ghi nhật ký sửa (P14 D2, D6) dưới `post_lock` và trả thêm `proposed`; schema `posts.json` không đổi. Duyệt một luật (P14 D4) sửa `paragraphs` của bài `ai` / `raw` chưa đăng, mỗi `posts.json` read-modify-write dưới `post_lock`.

## P8. "Đã đăng bài"

`posted_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`) | `null`, qua `POST /api/episodes/{id}/posts/{clip}/posted {value: bool}`; độc lập với tick "Đã đăng" Short (`publish.json`, CP8.5 X4) và **không** ảnh hưởng "Xong" (CP8.7 L4) hay gợi ý dọn (CP8.6 S1/S2). Bài đã tick mà text nguồn đổi → vẫn giữ tick, hiện `stale` (P2).

**Sửa đổi CP8.17 (D1, D2 — tự tick, chỉ ở trình duyệt, route `posted` và `posts.json` không đổi):** trang Bài đăng ghi nhớ trong `localStorage` (`autoShort.postMarks`, dự phòng bộ nhớ trang khi không dùng được) cho từng bài `<episode_id>/<clip_id>`: dấu *đã sao chép* (kèm text đã sao chép; chỉ đặt khi sao chép thành công, không tính ô dự phòng "Giữ vào ô để copy") và dấu *đã tải ảnh* (kèm tên ảnh; đặt khi bấm "Tải ảnh"). Cả hai còn hiệu lực (text / ảnh hiện tại của bài trùng lúc ghi) và bài chưa tick → trang gọi `POST …/posted {value: true}`, thứ tự hai thao tác tùy ý; xong thì xóa dấu (bỏ tick tay không tự tick lại cho tới khi làm lại cả hai). Bài không có ảnh tải được (`image` rỗng / `image_missing`) → chỉ cần sao chép thành công. Bài đã tick: không ghi gì. Dấu theo từng thiết bị / trình duyệt.

## P9. Web

- Thẻ mỗi Short `rendered` (tập Short + khai thị): khu thu gọn "Bài đăng cộng đồng" — chưa có bài: "Soạn bài"; có bài: nhãn `raw` / `stale` / `image_missing`, textarea các đoạn (đoạn cách nhau dòng trống) + "Lưu đoạn" (→ `manual`), ảnh thu nhỏ + "Đổi ảnh" (mở thư viện), ô link + "Lưu link", số ký tự (P4), "Sao chép bài" (dùng fallback clipboard hiện có, CP8.3 W6), "Soạn lại", tick "Đã đăng bài" (tự tick khi đã sao chép + tải ảnh, **sửa đổi CP8.17** P8).
- Trang tập: nút "Soạn bài cho mọi Short" (ẩn khi không có Short `rendered`), đếm "Bài đăng cộng đồng đã đăng: x/y".
- Hộp thoại "Thư viện ảnh" (mở từ "Đổi ảnh"): lưới ảnh (kích thước, số bài dùng), "Tải ảnh lên", ô dán link + nút nhanh (`[post] image_sources`) + "Tìm ảnh", "Xóa khỏi thư viện".
- Route (cookie CP8.3 W2; 422 lỗi dữ liệu; 503 Ollama khi preflight lỗi; 409 khi episode đang có job — kể cả job khác, cùng luật job runner CP8.10):
- **Sửa đổi FIX-ollama-wait (O4):** `POST /api/episodes/{id}/posts` không trả 503 Ollama nữa (luôn 202 + job).
  - `GET /api/episodes/{id}/posts` → `{posts: [{clip_id, paragraphs, origin, stale, image, image_missing, link, posted, posted_at, text, chars}], post_error}` (`text`/`chars` = bài đầy đủ P4, không phải chỉ `paragraphs`).
  - `POST /api/episodes/{id}/posts {clips: [clip_id…] | "all"}` → 202 `{job}` (làn `ai`).
  - `PUT /api/episodes/{id}/posts/{clip} {paragraphs?, image?, link?}` → 200 bài (P7 view); cần đã có bài (chưa soạn → 422); `image` phải là tên ảnh có trong thư viện (không → 404, như path traversal AC4).
  - `POST /api/episodes/{id}/posts/{clip}/posted {value: bool}` → 200 `{clip_id, posted, posted_at}`.
  - `GET /api/post-images` → `{images: [{name, width, height, bytes, used, source}], image_sources}`; `GET /files/post-images/{name}` (`?download=1` → tải về; tên ngoài thư viện / path traversal → 404).
  - `POST /api/post-images?name=<tên gốc>` (body thô P5a) → 200 `{image, duplicate}`; `DELETE /api/post-images/{name}` → 200 `{used}` (404 tên không có / path traversal).
  - `POST /api/post-images/search {url}` → 202 `{job}` (job runner id `_post_images`); `GET /api/post-images/search/{job}` → `{status, found, added: [tên], duplicate: [tên có sẵn], skipped: {reason: count}}`; 409 khi đang có job tìm ảnh; 404 job id không có / không phải job tìm ảnh.

**Sửa đổi CP8.18:** route từ điển sửa lỗi (`/api/post-corrections`, P14 D5) và nút "Từ điển sửa lỗi" trên tab Bài đăng (P14 D7); `PUT …/posts/{clip}` có `paragraphs` trả thêm `proposed`.

**Sửa đổi CP8.16 (R1, R3):** khu "Bài đăng cộng đồng" trên thẻ Short và "Soạn bài cho mọi Short" của trang tập được thay bằng tab "Bài đăng": trang `GET /episodes/{id}/posts` (cùng HTML cho tập Short `<vid>` và khai thị `<vid>.kt`), thanh chuyển [Shorts | Khai thị | Bài đăng] ở cả ba view, hai nhóm Short / Khai thị, editor mở sẵn, hộp thoại "Thư viện ảnh" chuyển sang trang này. `POST /api/episodes/{id}/posts` nhận thêm `clips: "auto"`; `GET /api/episodes/{id}` thêm `post_job` (job `post` mới nhất, hoặc `null`); 409 khi episode có job `pipeline` (không phải mọi job) — thay câu "409 khi episode đang có job — kể cả job khác" ở trên.

**Sửa đổi CP8.19:** `PUT /api/playlists/{id}/doc` (CP8.3 W7, P15 D1); `GET …/posts` trả `origin: "doc"`; nhãn "Văn bản gốc" trên tab Bài đăng, bài `doc` không có nhãn "ít dấu câu"; sửa tay bài `doc` → `manual` như mọi bài (từ điển P14 vẫn học từ bản sửa).

## P10. Không CLI mới

Như CP8.5 / CP9: chỉ web gọi `post/`.

## P11. Config `[post]`

`model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `retries`, `chunk_words`, `image_dir`, `image_sources`, `corrections_path` (CP8.18, mặc định `~/.local/share/auto-short/post-corrections.json`, ngoài repo) + execution-only (`ollama_host`, `timeout`, `retry_backoff`, như `[titling]`). Không vào `config_hash` của stage nào (`posts.json` không phải artifact stage). `model` mặc định `qwen3:14b` (Q4, HUMAN LEAD 2026-09-29).

## P12. Tài liệu

Canonical: file này. Trỏ tới: `docs/decisions/CP8.3-web-contract.md` W5 (job model), W6 (UI), W7 (API); `docs/ai/project-profile.md` (authority list + dòng module `post/`); `README.md` (config `[post]`, chép ảnh vào thư viện); `AUTO_SHORT_CHECKPOINT_PLAN.md`; `docs/workflow/current-state.md`.

## P13. Security (tải từ link, P5b)

Chỉ sau đăng nhập (CP8.3 W2 cookie, kiểm ở middleware auth chung, không riêng route này); chỉ `http`/`https`; phân giải host (`socket.getaddrinfo`) và từ chối địa chỉ loopback / private / link-local / multicast / reserved / unspecified (`ipaddress`, stdlib) — kiểm lại sau **mỗi** redirect (tối đa 3, `urllib.request.HTTPRedirectHandler` tùy biến), không kiểm một lần rồi tin AI theo; timeout 20 s mỗi request; giới hạn byte đọc (trang 5 MB, ảnh 15 MB) kể cả khi thiếu `Content-Length` (đọc `limit + 1` byte, dư → lỗi, không đọc tiếp); không gửi cookie web đi (gọi `urllib.request` riêng, không dùng session của web); không thực thi / phục vụ HTML tải về (chỉ ảnh JPEG/PNG đã kiểm magic bytes qua P5a, phục vụ với `Content-Type` theo đuôi tên tệp; `X-Content-Type-Options: nosniff` đã áp cho mọi response qua middleware CP8.3 W2). Không thêm dependency: `urllib.request`, `ipaddress`, `socket`, `html.parser` (stdlib).

## P14. Từ điển sửa lỗi (CP8.18, HUMAN LEAD 2026-10-02: APPROVE D1–D7)

Canonical owner của từ điển sửa lỗi bài đăng; chi tiết từng quyết định D1–D7 ở `docs/tasks/CP8.18-post-corrections.md` (task contract đã duyệt), implementation `src/auto_short/post/corrections.py`. Tóm tắt luật chuẩn:

- **D1** Một file JSON dùng chung mọi tập, ngoài repo: `[post] corrections_path` (`{"schema_version": 1, "rules": [{id, from, to, status, count, examples, created_at, updated_at}]}`, `status` = `proposed` | `approved` | `rejected`, `from` / `to` là token chuẩn hóa `selection.logic.normalize_word`). Không vào `config_hash`. Ghi atomic dưới `post_lock`; file hỏng → API báo lỗi, không ghi đè; soạn bài chạy như không có từ điển.
- **D2** `PUT …/posts/{clip}` có `paragraphs`: so bản cũ / mới theo token chuẩn hóa (`difflib`, `autojunk=False`); chỉ khối `replace` ≤ 3 / ≤ 3 token, thêm 1 token ngữ cảnh mỗi bên nếu nằm trong khối `equal`; trùng cặp → `count + 1`, luật `rejected` không đề xuất lại; lỗi từ điển không làm hỏng việc lưu bài.
- **D3** Soạn bài áp luật `approved` lên chữ nguồn trước AI (cả cụm, trái → phải, không chồng lấn, `from` dài nhất thắng; hoa/thường chữ đầu theo token gốc; ranh giới dòng caption giữ theo vị trí token); `post_log.json` ghi `corrections: [{rule_id, at_token}]`.
- **D4** Duyệt / thêm tay một luật → áp tất định lên `paragraphs` của bài `ai` / `raw` chưa tick "Đã đăng bài" ở mọi tập; giữ dấu câu đầu / cuối cụm; không áp qua ngắt đoạn; `manual` và bài đã đăng không đổi; xóa / bỏ duyệt không hoàn tác.
- **D5** Route `GET|POST /api/post-corrections`, `PUT|DELETE /api/post-corrections/{id}` (1–8 token, `from ≠ to`, không trùng `from` giữa hai luật `approved`).
- **D6** Nhật ký `post-edit-log.jsonl` cạnh `corrections_path` (`{at, episode_id, clip_id, words, changed_words}` mỗi lần lưu `paragraphs`); `stats` = số lần lưu + trung bình % từ phải sửa của 20 lần gần nhất.
- **D7** Hộp thoại "Từ điển sửa lỗi" trên tab Bài đăng (đề xuất: Duyệt / Sửa / Bỏ qua; đã duyệt: Bỏ duyệt / Xóa; thêm luật tay; dòng số đo).

Ngoài phạm vi: dấu câu / viết hoa, sửa transcript / title / render, tự duyệt luật, luật chèn / xóa từ.

## P15. Văn bản gốc bài giảng (CP8.19, HUMAN LEAD 2026-10-02: APPROVE D1–D8, Q1–Q4)

Canonical owner của bài đăng lấy từ văn bản đã biên tập của `ph.tinhtong.vn`; chi tiết D1–D8 ở `docs/tasks/CP8.19-post-doc-source.md`, implementation `src/auto_short/post/doc.py`. Tóm tắt luật chuẩn:

- **D1** Bộ kinh có field tùy chọn `doc_url` (`<workspace>/_playlists/<pid>.json`, sau `series`; giữ khi "Cập nhật danh sách"): chỉ nhận `https://ph.tinhtong.vn/Home/<Code>?d=<Code>_<số>.html`. Link tập N = thay `<số>` bằng N giữ độ rộng đệm số 0. Số tập = `episode` của entry bộ kinh (CP8.11); tập `<id>.kt` dùng link của video gốc. Nhiều bộ cùng có `doc_url` → bộ có `playlist_id` nhỏ nhất (như CP8.8 H4).
- **D2** Tải trang (+ phần gzip `/html-end/…gz.z` cùng host) bằng `post.fetch.fetch`, **áp P13** (chỉ host công khai, kiểm lại mỗi redirect, thêm: redirect sang host khác `ph.tinhtong.vn` → lỗi; trang ≤ 5 MB; gzip ≤ 5 MB cả sau giải nén). Đoạn = `<p>` của `<div id="bodytext">`, bỏ `text-center` và đoạn toàn chữ `<b>` (tiêu đề).
- **D3** Cache `work/<id>/doc.json` (`schema_version`, `url`, `fetched_at`, `paragraphs`, `match`); `match` = token transcript nằm trong khối khớp `difflib` với văn bản / tổng token transcript; `< 0.6` → tập không dùng văn bản (cache vẫn lưu). Dùng lại khi `url` trùng; lỗi tải không ghi cache.
- **D4** Gióng chữ nguồn P2 (chưa áp từ điển) vào văn bản: khối khớp ≥ 4 token, cụm khối dày nhất (khoảng cách ≤ 30 token), `ratio ≥ 0.6` mới dùng.
- **D5** Đoạn bài mở rộng ra trọn câu hai đầu (tối đa 60 token mỗi phía, vượt → dừng ở điểm gióng + `…`), giữ ngắt đoạn của văn bản, `“ X ”` → `“X”`, viết hoa chữ đầu.
- **D6** `compose_posts`: nhánh `doc` trước AI; `post_log.json` ghi `origin: doc`, `doc_url`, `doc_match`, `ratio`, `span`, `expanded`, không có `ai_calls`; lỗi tải chỉ cảnh báo, cả tập đi nhánh cũ. `store.ORIGINS` thêm `doc`, `schema_version` giữ 1.
- **D7** `PUT …/doc` với link mới → xếp job `post` (khóa `<id>#post`, CP8.16) cho từng tập (Short + khai thị) của bộ có `posts.json`, clip = bài `ai` / `raw` chưa đăng; `manual` và bài đã đăng không đổi.
- **D8** Nhãn "Văn bản gốc" (`doc`) trên tab Bài đăng.

Ngoài phạm vi: dùng văn bản cho title / transcript / phụ đề / chọn clip, site khác, `.docx` / PDF, tập không nhận dạng được số tập, từ điển P14 lên bài `doc`.

## Acceptance Criteria

Xem `docs/tasks/CP8.15-community-post.md` AC 1–12 (test `tests/test_post_*.py`, `tests/test_web_post_cp815.py`).

## Result

Xem task contract `docs/tasks/CP8.15-community-post.md` mục Result (verification, review, quyết định khi implement, known limitations, PR).
