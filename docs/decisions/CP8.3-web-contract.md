# CP8.3 — Web MVP Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | — (W1–W7, P1–P4 duyệt cùng APPROVE TASK 2026-09-27; phase A review ACCEPTED 2026-09-27; phase B review ACCEPTED; manual test HUMAN LEAD đạt 2026-09-27). Sửa đổi HUMAN LEAD 2026-09-27 (CP8.5, APPROVE TASK X1–X4, P1–P4 + bổ sung lọc danh sách tập): W6, W7, W8 |
| Checkpoint | CP8.3 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8.3 |
| Task contract | `docs/tasks/CP8.3-web.md`; sửa đổi CP8.5: `docs/tasks/CP8.5-web-review.md` |
| Builds on | `docs/decisions/CP8-pipeline-contract.md` (run, preflight, resume); `docs/decisions/CP7-render-contract.md` (`render_manifest.json`); `docs/decisions/CP8.2-title-override-contract.md` (hàm dùng chung `auto_short.review`, `render_key` + tái dùng từng Short); `docs/decisions/CP2-workspace-contract.md` (manifest, stage status); CP1 §10 (dependency) |

File này là **canonical owner** của web boundary: lệnh `auto-short web`, config `[web]`, auth (mật khẩu + cookie phiên), input URL từ web, job model, API JSON, route phục vụ file và UI; từ CP8.5 cả tên file tải về, xóa tập và artifact `publish.json` (W8). Nơi khác chỉ trỏ tới đây. Web không đổi contract stage CP2–CP8.2: pipeline chạy qua `run_pipeline` / `ollama_preflight` (CP8 E7, E8); sửa title qua hàm dùng chung của `auto_short.review` + `run_render` (CP8.2). Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/web/` (`app.py` app factory + route, `auth.py`, `urls.py`, `jobs.py`, `episodes.py`, `server.py`, `static/`), `src/auto_short/cli.py` (`web`), `src/auto_short/config.py` (`WebConfig`).

**Phase:** phase A (mọi mục trừ sửa title) và phase B (sửa title một Short: W4 § Sửa title, W5 job `render`, W6 bộ sửa title, W7 hai endpoint `…/title`, `…/title/preview`; danh sách Short theo render cuối, W7) đã implement.

## W1. Dependency

- Optional extra `[web]` trong `pyproject.toml`: `fastapi==0.141.1` (kéo theo `starlette 1.7.0`, `pydantic 2.13.5`), `uvicorn==0.54.0` (không extra `[standard]`). Dev: `httpx` (TestClient). Danh sách canonical: CP1 §10.
- Chỉ `web/app.py` và `web/server.py` import FastAPI/uvicorn. CLI pipeline không phụ thuộc web; `auto-short web` khi chưa cài `[web]` → exit 1 `auto-short: error: the web server needs the [web] extra …`.
- Không dùng `python-multipart`: form đăng nhập được parse bằng `urllib.parse.parse_qs`.

## W2. Security (LAN)

- Bind theo `[web] host` / `port` (mặc định `0.0.0.0:8080`); `--host` / `--port` ghi đè. HTTP thường (không HTTPS), một người dùng.
- Mật khẩu chỉ từ biến môi trường `AUTO_SHORT_WEB_PASSWORD` (không từ config/repo). Không có hoặc rỗng → `auto-short web` exit 1 `auto-short: error: AUTO_SHORT_WEB_PASSWORD is not set; …` trước khi bind.
- Khóa bí mật: 32 byte ngẫu nhiên (hex) ở `<workspace.dir>/.web_secret`, tạo lần đầu với quyền `600` (sửa lại `600` nếu bị nới), dùng lại khi restart → restart không bắt đăng nhập lại. Xóa file = mọi cookie hết hiệu lực.
- Khóa ký cookie = `HMAC-SHA256(secret, "auto-short-web-session\0" + SHA256(password))` → đổi mật khẩu làm mọi cookie cũ hết hiệu lực.
- Cookie `auto_short_session` = `v1.<expires unix>.<hex HMAC-SHA256(khóa ký, "v1.<expires>")>`; `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age = [web] session_days × 86400` (mặc định 30 ngày). Kiểm: đúng định dạng, chữ ký `hmac.compare_digest`, chưa hết hạn. Không có `Secure` (HTTP trong LAN).
- `GET /login`: trang một ô mật khẩu (đã đăng nhập → chuyển `next`). `POST /login` (form urlencoded `password`, `next`; hoặc JSON): so bằng `hmac.compare_digest`; sai → chờ 1 s rồi 401 (trang login có thông báo / JSON), không set cookie; đúng → set cookie + 303 về `next`. `next` chỉ nhận path bắt đầu `/` (không `//`, `\`, ký tự điều khiển), ngược lại `/`. `POST /logout` → xóa cookie, 303 `/login`.
- Chỉ `/login` và `/static/style.css` công khai. Mọi route khác cần cookie hợp lệ: `/api/…`, `/files/…` và request không phải GET → 401 JSON; trang HTML (GET) → 303 `/login?next=<path>`.
- Header chung: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`; `/api/…` thêm `Cache-Control: no-store`. Không có docs/OpenAPI route.
- CSRF: dựa trên `SameSite=Lax` (trình duyệt không gửi cookie ở POST cross-site) + API POST nhận JSON.
- File: chỉ phục vụ Short `status = rendered` trong `<render.output_dir>/<episode_id>/render_manifest.json`, path lấy từ manifest (không từ client) và phải nằm đúng trong `<output_dir>/<episode_id>/shorts/`, đuôi `.mp4`, tồn tại. `episode_id` validate theo CP2 (`validate_episode_id`), `clip_id` theo `^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$`; sai → 404.

## W3. Input

- Chỉ URL một video YouTube: `youtube.com/watch?v=ID`, `youtu.be/ID`, `youtube.com/shorts/ID` (host `youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be`; http/https; thiếu scheme = https; không user/password/port). ID 11 ký tự `[A-Za-z0-9_-]`; `v` phải có đúng một giá trị.
- Bỏ mọi tham số khác (`si`, `t`, `feature`, `list`, `index`, …) và chuẩn hóa thành `https://youtu.be/<ID>`; episode id = video id (CP2 D3). `watch?v=ID&list=…` = một video (bỏ `list`); `youtube.com/playlist?list=…` → 422 "không nhận playlist". Domain khác / không có id / quá 2000 ký tự → 422 với message tiếng Việt.
- Không nhận đường dẫn file local từ web (CLI vẫn nhận).
- Form có ô tuỳ chọn `series` / `episode` (≤ 100 ký tự, trim, rỗng = không đặt) truyền thẳng vào titling (CP6 G2, như `--series` / `--episode`).

## W4. Luồng xử lý

- `POST /api/episodes`: parse URL (lỗi → 422, không job) → nếu episode đã có job `queued`/`running` → 200 `created: false` + job đó (không preflight, không job mới) → preflight Ollama (CP8 E8) ngay trong request (lỗi → 503 `ollama preflight: <lý do>`, không job) → tạo job pipeline → 202 `created: true`.
- Job pipeline gọi `run_pipeline(url, config, series, episode, preflight=ollama_preflight, on_stage=…)`: preflight chạy lại khi job bắt đầu (job có thể đã đợi trong hàng). Kết quả: `done` + `summary` `"<rendered>/<clips> Shorts"`; lỗi stage → `failed`, `error = "<stage>: <message>"` (CP8 E4); lỗi preflight → `failed`, `error = "ollama preflight: …"`.
- Gửi lại URL của episode đã xong / lỗi / bị ngắt → job mới; pipeline tự skip / resume (CP8 E3).
- Tiến độ: status từng stage đọc từ `manifest.json` (CP2) + stage hiện tại và thời gian từng stage (`on_stage`: `ran` / skip, giây) + log của job. Trang episode poll JSON mỗi 2,5 s khi có job đang chạy/đợi.
- Khi render chạy trong job, `summary` thêm `" (<e> encoded, <r> reused)"` từ `RenderResult.encoded` / `reused` (CP8.2 T5).

### Sửa title (phase B)

- Dùng đúng hàm dùng chung của CP8.2 (`preview_title`, `set_title`, `set_alternative` (1-based), `reset_title`, `list_titles`); luật validate, `review.json`, thứ tự nguồn title, `render_key` và tái dùng: `docs/decisions/CP8.2-title-override-contract.md` (canonical owner). Web không tự validate / ghi `review.json`.
- Xem trước: `preview_title` (không ghi, không job) — dùng được cả khi có job đang chạy.
- Ghi (`set` / `alternative` / `reset`): **từ chối 409** khi episode có job `queued`/`running` (pipeline hoặc render) → `review.json` không bị ghi giữa lúc render đọc nó. Kiểm "không có job" + ghi + tạo job nằm trong một lock của app (gửi URL cũng lấy lock đó khi tạo job) nên không lọt job giữa hai bước. `ReviewError` → 422 (message CP8.2), không ghi, không job.
- Ghi thành công → tạo job `render` (`clip_ids` = [clip vừa sửa]) gọi `run_render(episode_id, config)` không `force`: CP8.2 T5 chỉ encode Short có `render_key` đổi, các Short khác `reuse`. `reset` khi không có override vẫn tạo job (render skip ngay). Lỗi render → job `failed`, `error = "render: <message>"`; output lần render trước giữ nguyên (CP8.2 T5).

## W5. Job model

- Một worker thread, hàng đợi FIFO trong bộ nhớ; tại một thời điểm chỉ một job chạy. Job: `id` (số tăng dần trong phiên server), `episode_id`, `kind` (`pipeline` | `render`), `clip_ids` (job `render`: Short vừa sửa title), `status` (`queued`, `running`, `done`, `failed`, `interrupted`), `created_at` / `started_at` / `finished_at` (UTC ISO), `stage`, `stages` [{`stage`, `ran`, `seconds`}], `error`, `summary`, `logs`.
- Một episode chỉ có tối đa một job `queued`/`running` (pipeline hoặc render); gửi URL trùng trả job đang có (kể cả job `render`), ghi title → 409.
- Log: mọi record của logger `auto_short` phát ra trên worker thread khi job chạy (level ≥ INFO) được chép vào vòng đệm 200 dòng cuối của job, dạng `HH:MM:SS [LEVEL ]message`; server vẫn log ra stderr như CLI. Không gồm stderr của tiến trình con (ffmpeg, yt-dlp).
- Lịch sử job chỉ trong bộ nhớ: restart server mất hàng đợi và log (manifest còn; gửi lại URL → resume).
- Tắt server (Ctrl-C / SIGINT / SIGTERM qua uvicorn) khi job đang chạy: worker nhận `KeyboardInterrupt` (inject vào thread) + tiến trình con trực tiếp nhận SIGINT; chờ tối đa 30 s. Stage đang chạy ghi `failed` + `error: "interrupted"` (CP2 `run_stage`), job `interrupted`. Nếu stage đang kẹt trong một lời gọi dài không trả về trong 30 s (vd request Ollama) thì server thoát, manifest giữ `running` — CP8 E3 coi là chưa up to date, gửi lại URL sẽ chạy lại stage đó.

## W6. UI

- HTML + CSS + JS thuần trong `src/auto_short/web/static/` (package data; không build step, không framework frontend), tiếng Việt, responsive (lưới Short 2 cột trên điện thoại).
- `/` : form URL (+ tuỳ chọn series / tập), lỗi (422 / 503) hiện ngay dưới form; danh sách episode (tên video, trạng thái: đang chạy stage / lỗi ở stage / N Shorts · đã đăng x/y — CP8.5) + bộ lọc Tất cả / Còn Short chưa đăng / Đã đăng hết (W8).
- `/episodes/<id>`: tên, kênh, thời lượng; trạng thái job; 6 stage (`chờ`, `đang chạy`, `xong`, `lỗi` + message, `cần chạy lại`) + thời gian hoặc "bỏ qua (đã có)"; nhật ký (mở sẵn khi đang chạy / lỗi); nút "Chạy tiếp / chạy lại" (gửi lại `source_url`, ẩn khi có job đang chạy); nút "Xóa tập này" (CP8.5, W8); lưới Short; nút "Tải tất cả (.zip)" (P3); bộ lọc Tất cả / Chưa đăng / Đã đăng + "Đã đăng x/y" + "Hiện Short đã xóa (n)" (CP8.5).
- Mỗi Short: `<video controls preload="metadata" playsinline>` (tua bằng Range), mã clip, nhãn nguồn title trong file (`AI` / `sửa tay` / `phương án AI khác`), thời lượng, title, "Tiêu đề mới … chưa render" khi title lần render tới khác file (vd render lỗi), nút "Tải về".
- Sửa title (`.title-edit`, chỉ khi `editable`): nút "Sửa tiêu đề" mở ô nhập (giá trị = title sẽ render) + bộ đếm `n/<max_title_chars>` (đỏ khi vượt), dropdown phương án AI khác (chọn → điền ô nhập; lưu gửi `alternative: n` nếu ô nhập còn đúng chữ đó, sửa thêm → `set`), xem trước (gọi preview sau 350 ms ngừng gõ: dòng hiển thị trên nền vàng + cỡ chữ, hoặc lỗi 422), "Lưu & render lại" (bật khi xem trước hợp lệ và không có job), "Khôi phục title AI" (khi có override). Khi episode có job: nút lưu tắt + ghi chú "Đang có job chạy — đợi xong để lưu"; Short đang render lại có viền + nhãn "đang render…" trên video.
- Mỗi thẻ Short chỉ dựng lại (thay tại chỗ) khi trạng thái của chính nó đổi (sha256, title, override, title chờ, đang render); danh sách clip đổi mới dựng lại cả lưới → poll không dừng video đang xem hay xóa chữ đang gõ ở thẻ khác; Short render xong tự thay bằng video mới (`video_url` đổi theo sha256).

## W7. API và file

Mọi route cần cookie (W2). JSON UTF-8.

| Route | Kết quả |
|---|---|
| `POST /api/episodes` `{url, series?, episode?}` | 202 `{created: true, episode_id, job}`; 200 `{created: false, episode_id, job}` (đã có job đang chạy/đợi); 422 `{detail}` (URL / field sai); 503 `{detail: "ollama preflight: …"}` |
| `GET /api/episodes` | `{episodes: [{id, title, stages_done, stages_total, running, failed, shorts, job}]}` — mọi workspace có manifest (mới nhất trước) + job đang đợi chưa có workspace; `job` không kèm `logs` |
| `GET /api/episodes/{id}` | `{id, title, channel, duration, source_url, stages: [{stage, status, started_at, finished_at, error}], render_status, header, shorts, rendered, zip_url, max_title_chars, titles_error, titles_ignored, job}`; 404 khi không có manifest và không có job |
| `POST /api/episodes/{id}/shorts/{clip}/title/preview` `{text}` | 200 `{clip_id, title, origin: "manual", display_lines, font_size, panel_height, chars}`; 422 `{detail}` (`ReviewError`: title sai, clip không có, titling chưa `done`); không ghi |
| `POST /api/episodes/{id}/shorts/{clip}/title` `{set: text}` \| `{alternative: n}` \| `{reset: true}` | đúng một hành động, không thì 422; 202 `{preview, job}` (`preview` như trên với `origin` thật, `null` khi reset clip `untitled`; `job` = job `render` mới); 409 `{detail, job}` khi có job đang chạy/đợi; 422 `ReviewError`, không ghi |
| `GET /files/{id}/{clip}.mp4` | `video/mp4`, hỗ trợ `Range` (206 + `Content-Range`), `Cache-Control: private, no-cache` |
| `GET /files/{id}/{clip}.mp4?download=1` | như trên + `Content-Disposition` với tên W8 (CP8.5; trước đó `<id>_<clip>.mp4`) |
| `GET /files/{id}/shorts.zip` | zip stream (`ZIP_STORED`, không nén) mọi Short `rendered` theo thứ tự manifest, entry tên W8 (cờ UTF-8); `Content-Disposition` tên `Tập<episode>_Shorts.zip` (CP8.5; trước đó `<id>_shorts.zip` / `<id>_<clip>.mp4`); 404 khi chưa có Short |
| `POST /api/episodes/{id}/shorts/{clip}/delete` \| `…/restore` | CP8.5 X2: 202 `{changed, job}` (`job` = job `render`, `clip_ids` = [clip]); 409 `{detail, job}` khi có job đang chạy/đợi; 422 `ReviewError` (clip không có, titling chưa `done`), không ghi |
| `POST /api/episodes/{id}/shorts/{clip}/published` `{value: true\|false}` | CP8.5 X4: 200 `{clip_id, published, stale, at}`; không job, được cả khi job đang chạy; `value` phải là JSON boolean (khác → 422); tick Short không có file → 422 |
| `DELETE /api/episodes/{id}` | CP8.5 X3: 200 `{deleted: id}`; 404 id sai / traversal / không có; 409 `{detail, job}` khi có job đang chạy/đợi; 500 khi xóa lỗi |

- `job` = các field W5 + `queue_position` (vị trí trong hàng, `null` khi không đợi).
- `shorts[]` = `{clip_id, status (rendered | skipped), skip_reason, duration, source_start, source_end, title: {text, origin, display_lines}, sha256, video_url, download_url, download_name, deleted, rejected, published, published_stale, published_at, editable, ai_title, alternatives: [{n, title}], override: {title, origin} | null, pending_title: {text, origin} | null, rendering}` (CP8.5 thêm `download_name` … `published_at`; episode thêm `deleted`, `published` (số Short `rendered` đã tick), `publish_error`, `zip_name`; `GET /api/episodes` mỗi item thêm `published`, `publish_group`).
  - CP8.5: `deleted` = render cuối bỏ qua Short vì `rejected` (file đã xóa); `rejected` = `review.json` đang xóa (khác `deleted` trong lúc job render chạy); `download_name` = tên W8 (`null` khi không có file).
  - `title` = title **trong file** (`render_manifest.json` `title` / `title_origin` / `title_display_lines`; manifest trước CP8.2 không có `title_origin` → `ai`). `video_url` = `/files/<id>/<clip>.mp4?v=<sha256[:12]>` (đổi khi file đổi), `null` khi Short bị bỏ qua.
  - `ai_title`, `alternatives`, `override` từ `list_titles` (CP8.2); `pending_title` = title lần render tới khi khác title trong file (title hoặc origin), `null` nếu giống; `editable` = `list_titles` đọc được (titling `done`, `review.json` hợp lệ), không thì `titles_error` = message và không sửa được. `titles_ignored` = cảnh báo T3 (override bị bỏ qua).
  - `rendering` = episode có job `render` đang chạy/đợi và clip nằm trong `clip_ids`.
- **Danh sách Short = render cuối đã commit** (quyết định phase B, thay luật phase A "chỉ khi render `done`"): `shorts`, file và zip lấy từ `render_manifest.json` hiện có (đúng `episode_id`) **bất kể** status stage render (`running`, `stale`, `failed`, `pending`); `render_status` cho UI ghi chú "Đang hiển thị bản dựng trước". Lý do: CP8.2 T5 — render mới encode vào `.part`, chỉ thay mp4 + manifest ở bước commit, lỗi / bị ngắt trước commit giữ nguyên render trước (mp4 khớp manifest); nên trong lúc render lại một Short (hoặc cả pipeline), mọi Short cũ vẫn xem / tải được. Khoảng nhỏ trong lúc commit (file đã thay, manifest chưa ghi) có thể cho sha256 cũ với file mới — chấp nhận. Lỗi giữa commit → CP8.2 xóa manifest → danh sách rỗng.

## W8. Review workflow (sửa đổi CP8.5, HUMAN LEAD 2026-09-27)

Quyết định: `docs/tasks/CP8.5-web-review.md` X1–X4, P1–P4. Hàm thuần / theo episode ở `auto_short.review` (`names.py`, `publish.py`, `delete.py`, `titles.reject_clip` / `restore_clip`), web chỉ gọi.

### Tên file tải về

- Short: `Tập<episode>_S<NN>_<title>.mp4`. `<episode>` = `titles.json` `header.fields.episode` (vd `29`), không có → `<episode_id>` (vd `TậptHtxw6ykUmM_S01_…`). `<NN>` = vị trí clip trong `render_manifest.json` `shorts` (= thứ tự `clips.json`, CP7 R9; Short đã xóa vẫn giữ chỗ nên số không dịch), hai chữ số, ba chữ số khi ≥ 100 clip. `<title>` = `title` trong `render_manifest.json` (title trong file).
- Làm sạch (cả `<episode>` và `<title>`): NFC; bỏ `/ \ : * ? " < > |` và ký tự điều khiển / định dạng (Unicode `Cc`, `Cf`; tab, xuống dòng → khoảng trắng); gộp khoảng trắng liên tiếp thành một, bỏ hai đầu; **giữ** khoảng trắng và dấu tiếng Việt. `<title>` cắt ≤ 150 byte UTF-8 ở ranh giới từ (một từ dài hơn → cắt ở ranh giới ký tự). Title rỗng sau khi làm sạch → `Tập<episode>_S<NN>.mp4`.
- Zip: `Tập<episode>_Shorts.zip`, entry cùng quy tắc (Short đã xóa không có trong zip).
- `Content-Disposition: attachment; filename="<ASCII>"; filename*=UTF-8''<percent-encoded>` (RFC 6266 + RFC 5987): ASCII = bỏ dấu (NFKD, `đ` → `d`), bỏ ký tự ngoài ASCII (rỗng → `download`). File trên đĩa không đổi tên (`shorts/<clip_id>.mp4`). UI đặt thuộc tính `download` của link = tên này.

### Xóa / khôi phục một Short

- Web gọi `reject_clip` / `restore_clip` (`review.json` `rejected`, canonical CP8.2 T7) rồi tạo job `render` như sửa title (W4): cùng lock, 409 khi có job đang chạy/đợi, `ReviewError` → 422. Job render tái dùng các Short khác (CP8.2 T5); xóa → mp4 bị xóa ở commit (vài giây); khôi phục → encode lại Short đó.
- UI: nút "Xóa Short" (hộp xác nhận: file bị xóa ngay, khôi phục được) chỉ khi `editable`; Short đã xóa ẩn khỏi lưới, "Hiện Short đã xóa (n)" hiện chúng (mờ) với nút "Khôi phục"; Short đang xử lý có nhãn "đang xóa…" / "đang khôi phục…". Nút tắt khi episode có job.

### Xóa tập

- `DELETE /api/episodes/{id}` gọi `delete_episode(id, config)`: `episode_id` validate theo CP2 (sai → 404); đường dẫn chỉ từ config: `<workspace.dir>/<id>` và `<render.output_dir>/<id>`; mỗi thư mục phải là thư mục thật (không symlink) có `resolve()` là con trực tiếp của `resolve()` gốc tương ứng, không thì từ chối (500, không xóa gì). Không thư mục nào tồn tại → 404. Xóa output trước, workspace sau (tập chỉ biến mất khỏi danh sách khi manifest đã bị xóa); `workspace.dir` = `output_dir` → xóa một lần.
- Nguồn local nằm ngoài workspace (CP2 D4) không bao giờ bị xóa: chỉ hai thư mục trên bị `rmtree`, `rmtree` không đi theo symlink. `<workspace.dir>/.web_secret` giữ nguyên.
- Kiểm "không có job" + xóa nằm trong lock gửi URL / ghi review (W4) → 409 khi có job đang chạy/đợi. Xóa xong: job cũ của tập bị quên trong bộ nhớ (`JobRunner.forget`) → `GET /api/episodes/{id}` 404, tập biến mất khỏi danh sách. Gửi lại URL = chạy lại từ đầu.
- UI: nút "Xóa tập này" (ẩn khi không có manifest, tắt khi có job) → `confirm` ghi tên tập + id + "KHÔNG khôi phục được" → về `/`.

### Đã đăng (publish.json)

- `work/<episode_id>/publish.json` — state người dùng, **không** là input stage nào (tick không làm render stale, không tạo job, được cả khi job đang chạy). Ghi atomic, JSON indent 2, thứ tự key cố định, entry theo thứ tự `render_manifest.json`:

```json
{"schema_version": 1, "episode_id": "tHtxw6ykUmM",
 "published": [{"clip_id": "k01", "candidate_id": "c00077", "sha256": "<sha256 Short lúc tick>", "at": "2026-09-27T10:05:27Z"}]}
```

- Kiểm khi đọc: đúng 3 key, `schema_version` 1, `episode_id` khớp, entry đúng 4 key chuỗi không rỗng, `sha256` 64 hex thường, `at` `YYYY-MM-DDTHH:MM:SSZ`, `clip_id` không trùng. Hỏng → trang tập hiện `publish_error`, mọi Short coi như chưa tick; tick → 422.
- Tick (`set_published(…, True)`): lấy `candidate_id` + `sha256` của Short trong `render_manifest.json` đã commit; Short không `rendered` → lỗi. Tick lại một Short đã tick = ghi `sha256` / `at` mới ("đánh dấu bản này"). Bỏ tick luôn được (kể cả Short đã xóa); không có tick → file không ghi lại.
- Trạng thái (`publish_status`): tick chỉ tính khi cùng `(clip_id, candidate_id)` (selection chạy lại → chưa đăng); `stale` ("đã đăng bản cũ") = file hiện tại có `sha256` khác lúc tick (vd sửa title); Short đã xóa giữ tick, không `stale`.
- Đếm: `published` = số Short `rendered` đã tick (tính cả bản cũ) / `rendered`. Trang tập: Tất cả / Chưa đăng / Đã đăng (lọc phía client, không dựng lại thẻ).
- Danh sách tập (**bổ sung HUMAN LEAD 2026-09-27**): `publish_group` — y = số Short `rendered` (không tính đã xóa), x = đã tick trong đó. y > 0: `done` ("Đã đăng hết") khi x = y, không thì `todo` ("Còn Short chưa đăng"). y = 0: `todo` chỉ khi còn việc đang chờ — có job `queued`/`running` hoặc pipeline chưa xong (còn stage không `done`, gồm lỗi / bị ngắt); pipeline đã xong mà không có Short (xóa hết / không title) → `null`, chỉ hiện ở "Tất cả".

## Config `[web]`

| Key | Mặc định | Ghi chú |
|---|---|---|
| `host` | `"0.0.0.0"` | `"127.0.0.1"` = chỉ máy này |
| `port` | `8080` | 1–65535 |
| `session_days` | `30` | 1–365, tuổi cookie đăng nhập |

Execution-only: không stage nào dùng, không vào config hash.

## Số đo (máy dev, curl qua `10.8.102.101:8080`)

| Bước | Kết quả |
|---|---|
| `auto-short web` không có `AUTO_SHORT_WEB_PASSWORD` | exit 1, `auto-short: error: AUTO_SHORT_WEB_PASSWORD is not set; …` |
| chưa đăng nhập: `/`, `/episodes/<id>` / `/api/episodes`, `/files/…mp4`, `/files/…zip` | 303 `/login?next=…` / 401 / 401 / 401 |
| mật khẩu sai / đúng | 401 sau 1,003 s, không cookie / 303 + `Set-Cookie … HttpOnly; Max-Age=2592000; Path=/; SameSite=lax` |
| cookie sửa hạn / sửa chữ ký | 401 / 401 |
| SIGINT server rồi khởi động lại, dùng cookie cũ | 200 (`.web_secret` quyền 600 giữ nguyên) |
| URL playlist / vimeo / `/etc/passwd` / `youtu.be/abc` | 422 (không job, không workspace) |
| server thứ hai với `OLLAMA_HOST=http://127.0.0.1:1` | 503 `ollama preflight: cannot reach Ollama …` trong 0,03 s, không job, không workspace |
| gửi `https://youtu.be/tHtxw6ykUmM?si=R1TwdI4gh0sPcVHB` (video 58,6 phút, "Thập Thiện Nghiệp Đạo Kinh tập 29") | 202 trong 0,05 s; job 1500 s: ingest 63 s, transcript 2 s (caption YouTube auto), analysis 126 s, selection 791 s (qwen3:30b think, 19 lời gọi), titling 55 s, render 463 s → 6 stage `done`, 20/20 Short (1396 s) |
| gửi lại (dạng `watch?v=`) khi đang chạy | 200 `created: false`, cùng job 1 |
| `Range: bytes=0-1023` | 206, `Content-Range: bytes 0-1023/13626648` |
| tải 20 Short `?download=1` | sha256 cả 20 = `render_manifest.json`; `Content-Disposition: attachment; filename="tHtxw6ykUmM_k20.mp4"` |
| `shorts.zip` | 315 MB trong 0,7 s, 20 entry `ZIP_STORED` đúng thứ tự, sha256 từng entry = manifest |
| gửi lại khi đã xong | job 2 xong trong 0,1 s (6 stage skip), mp4 + `render_manifest.json` không đổi |

Phase B (2026-09-27, sau merge CP8.1 dissolve + CP8.2; server mới, mật khẩu mới):

| Bước | Kết quả |
|---|---|
| gửi lại `https://youtu.be/tHtxw6ykUmM` (render `run (config changed)` vì `[render] dissolve`) | job pipeline 509 s: 5 stage skip, render 20/20 `(20 encoded, 0 reused)`; trong lúc chạy: 20 Short vẫn liệt kê (`render_status` `running`), `Range` → 206 |
| ghi title `k01` khi job pipeline đang chạy | 409, `review.json` không được tạo |
| gửi `https://youtu.be/rbjfCfFq3Dk` khi job trên đang chạy | 202, `queue_position` 1; chạy sau đó: render 13/13 `(13 encoded, 0 reused)` trong 310 s |
| kiểm 33 mp4 mới (ffprobe) | 1080×1920; \|`nb_frames` − `duration`×fps\| ≤ 0,49 frame; `encode.dissolve` 0.15; điểm nối có dissolve: 204/209 (`tHtxw6ykUmM`), 150/157 (`rbjfCfFq3Dk`); `render_key` đủ; sha256 = manifest |
| preview `k04` "Giữ miệng không nói xấu người khác thế nào" | 200 trong 0,005 s: 3 dòng, 88 px, panel 353 px, 42 ký tự |
| preview 61 ký tự / emoji / HOA toàn bộ / `!` | 422 `invalid title: too long (61 > 60 chars)` / `emoji/pictograph` / `all caps` / `exclamation mark`; không ghi |
| `set` title tay `k04` | 202; trong lúc render: `rendering` = [`k04`], ghi `k05` → 409; job render 16,3 s `20/20 Shorts (1 encoded, 19 reused)`, 19 dòng `reuse (render_key unchanged)`; chỉ `k04.mp4` đổi sha256; file tải về = manifest; `title.origin` `manual` |
| `alternative: 2` | 202, 16,2 s, 1 encoded / 19 reused, `origin` `alternative`, `review.json` entry `alternative` |
| `reset` | 202, 16,3 s, 1 encoded / 19 reused; 20/20 mp4 **byte-identical** bản AI trước khi sửa; `review.json` `titles: []` |
| gửi lại URL khi đã xong | 6 stage skip |

CP8.5 (2026-09-27, bản sao scratch của `tHtxw6ykUmM` tập 29 (20 Short) + `rbjfcffq3dk-7271326dbe93`, server worktree CP8.5 `127.0.0.1:8081`, curl):

| Bước | Kết quả |
|---|---|
| `k01.mp4?download=1` | 200, 12,5 MB trong 0,05 s; `Content-Disposition: attachment; filename="Tap29_S01_Xa hoi hien nay dung sai lan lon.mp4"; filename*=UTF-8''T%E1%BA%ADp29_S01_X%C3%A3%20h%E1%BB%99i…` → `Tập29_S01_Xã hội hiện nay đúng sai lẫn lộn.mp4` (title `…lẫn lộn?` bỏ `?`); sha256 = manifest |
| `shorts.zip` | 317 MB trong 0,57 s, `filename*` `Tập29_Shorts.zip`; 20 entry `Tập29_S01_…` … `Tập29_S20_Chánh niệm là vì tất cả chúng sanh.mp4`, cờ UTF-8, `ZIP_STORED`, sha256 = manifest |
| xóa `k05` | 202 trong 0,004 s; job 2,4 s `19/20 Shorts (0 encoded, 19 reused)`; `k05.mp4` không còn, manifest `skipped`/`rejected`, 19 sha256 không đổi, zip 19 entry, `GET k05.mp4` 404; xóa `k06` trong lúc job → 409 |
| khôi phục `k05` | job 26,9 s `20/20 (1 encoded, 19 reused)`; 20/20 sha256 = trước khi xóa (byte-identical); `review.json` byte-identical bản gốc |
| tick `k01`, `k02` | 200 trong 0,005 s; không job; `manifest.json` + `render_manifest.json` sha256 không đổi; restart server → vẫn tick, `đã đăng 2/20`; `{"value": "yes"}` → 422 |
| sửa title `k02` (đã tick) thành `Không thành thật thì sao dạy "con trẻ"?` | tick `k03` trong lúc job render chạy → 200; job 26,9 s (1 encoded); `k02` `published_stale: true`; tên tải `Tập29_S02_Không thành thật thì sao dạy con trẻ.mp4` (bỏ `"`, `?`); gửi lại URL → 6 stage skip |
| `DELETE` tập khi job đang chạy / `nope`, `..%2Fwork`, `%2E%2E`, `..%2F..%2Fetc`, `.hidden`, `a%2Fb` / không cookie | 409 / 404 / 401 |
| `DELETE /api/episodes/rbjfcffq3dk-7271326dbe93` | 200 trong 0,002 s; `work/<id>` bị xóa (không có output); `input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` sha256 `7271326d…` không đổi; biến mất khỏi danh sách; `GET` → 404 |

## Giới hạn đã biết

- HTTP không mã hóa: mật khẩu và cookie đi dạng rõ trong LAN (HTTPS ngoài scope).
- Không giới hạn số lần đăng nhập sai ngoài độ trễ 1 s mỗi lần.
- Job và log chỉ trong bộ nhớ; log không gồm output của ffmpeg / yt-dlp.
- Một job tại một thời điểm; job dài (selection ~8 phút) chặn job khác của episode khác.
- Danh sách episode đọc lại toàn bộ manifest mỗi lần gọi (đủ cho vài chục episode).
- Sửa title một Short phải đợi job của episode xong (409), kể cả job render của Short khác; không có hàng đợi nhiều lần sửa.
- `titles.json` / `review.json` / `clips.json` được đọc lại mỗi lần poll trang episode (`list_titles`, vài chục KB).
- Ghi `review.json` đồng thời từ CLI `auto-short title` và web không có khóa chung (CP8.2 § Quyết định khi implement): lần ghi sau thắng.
- UI chưa được kiểm trên trình duyệt thật trong môi trường agent (không có browser); manual test HUMAN LEAD là gate.
- CP8.5: tên có dấu dựa vào `filename*` (RFC 5987) và thuộc tính `download`; chưa kiểm trên điện thoại thật trong môi trường agent (manual test HUMAN LEAD). Công cụ chỉ hiểu `filename=` (vd `curl -OJ`) lưu tên ASCII không dấu.
- CP8.5: xóa tập là `rmtree` đồng bộ trong request, không thùng rác; thời gian trên dữ liệu thật chưa đo (bản thử scratch dùng hardlink: 0,01 s cho tập 29 ~950 MB).
- CP8.5: `publish.json` ghi từ nhiều request được tuần tự hóa bằng một lock trong server; CLI không ghi file này.
