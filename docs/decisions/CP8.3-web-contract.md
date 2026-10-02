# CP8.3 — Web MVP Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | — (W1–W7, P1–P4 duyệt cùng APPROVE TASK 2026-09-27; phase A review ACCEPTED 2026-09-27; phase B review ACCEPTED; manual test HUMAN LEAD đạt 2026-09-27). Sửa đổi HUMAN LEAD 2026-09-27 (CP8.5, APPROVE TASK X1–X4, P1–P4 + bổ sung lọc danh sách tập): W6, W7, W8. Sửa đổi HUMAN LEAD 2026-09-27 (CP8.6, APPROVE TASK S1–S4, P1 7 ngày, P2 10 GB / 3 GB): W4, W7, W9. Sửa đổi HUMAN LEAD 2026-09-27 (CP8.7, APPROVE TASK L1–L5, P2 "Xong" tự động + bổ sung tải về = đã đăng): W3, W7, W8, W9, W10. Sửa đổi HUMAN LEAD 2026-09-27 (CP8.8, APPROVE TASK H1–H7, P1–P3): W6, W7, W10. Sửa đổi HUMAN LEAD 2026-09-28 (CP8.11, APPROVE D1–D7): W7, W10. Sửa đổi HUMAN LEAD 2026-09-28 (CP8.10, APPROVE Q1–Q4 + Q0, Q5–Q8): W4, W5, W7, config `[web]`. Sửa đổi HUMAN LEAD 2026-09-28 (CP8.12, APPROVE U1–U4 + A1): W6, W10. Sửa đổi HUMAN LEAD 2026-09-29 (CP9, APPROVE C1–C9): W5, W6, W7, W8 (thêm Short, sửa đầu/cuối). Sửa đổi HUMAN LEAD 2026-09-29 (CP8.15, APPROVE TASK P1–P13): W5, W6, W7 (bài đăng cộng đồng + thư viện ảnh — chi tiết canonical ở `docs/decisions/CP8.15-community-post-contract.md`). Sửa đổi HUMAN LEAD 2026-09-30 (CP8.17, APPROVE D1–D5, Q1 = a): W6, W7, W8 (zip không còn tick "Đã đăng", tên zip có tên bộ kinh, "Tải cả hai"). Sửa đổi HUMAN LEAD 2026-09-30 (FIX-ollama-wait, APPROVE O1–O8): W4 (không còn 503 lúc gửi link), W5 (đợi GPU), W6, W7 (`gpu`, `gpu_wait`) |
| Checkpoint | CP8.3 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8.3 |
| Task contract | `docs/tasks/CP8.3-web.md`; sửa đổi CP8.5: `docs/tasks/CP8.5-web-review.md`; sửa đổi CP8.6: `docs/tasks/CP8.6-storage.md`; sửa đổi CP8.7: `docs/tasks/CP8.7-playlist.md`; sửa đổi CP8.8: `docs/tasks/CP8.8-playlist-hashtags.md`; sửa đổi CP8.11: `docs/tasks/CP8.11-series-recognition.md`; sửa đổi CP8.10: `docs/tasks/CP8.10-queue-lanes.md`; sửa đổi CP9: `docs/tasks/CP9-clip-review.md`; sửa đổi CP8.15: `docs/tasks/CP8.15-community-post.md`; sửa đổi CP8.17: `docs/tasks/CP8.17-download-rules.md` |
| Builds on | `docs/decisions/CP8-pipeline-contract.md` (run, preflight, resume); `docs/decisions/CP7-render-contract.md` (`render_manifest.json`); `docs/decisions/CP8.2-title-override-contract.md` (hàm dùng chung `auto_short.review`, `render_key` + tái dùng từng Short); `docs/decisions/CP2-workspace-contract.md` (manifest, stage status); CP1 §10 (dependency) |

File này là **canonical owner** của web boundary: lệnh `auto-short web`, config `[web]`, auth (mật khẩu + cookie phiên), input URL từ web, job model, API JSON, route phục vụ file và UI; từ CP8.5 cả tên file tải về, xóa tập và artifact `publish.json` (W8); từ CP8.6 tab Bộ nhớ, dọn video nguồn và luật episode *archived* (`archive.json`, W9); từ CP8.7 bộ kinh (playlist), trạng thái "Xong" suy ra và tải về = đã đăng (W10). Nơi khác chỉ trỏ tới đây. Web không đổi contract stage CP2–CP8.2: pipeline chạy qua `run_pipeline` / `ollama_preflight` (CP8 E7, E8); sửa title qua hàm dùng chung của `auto_short.review` + `run_render` (CP8.2). Thay đổi cần decision gate mới với HUMAN LEAD.

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
- Bỏ mọi tham số khác (`si`, `t`, `feature`, `list`, `index`, …) và chuẩn hóa thành `https://youtu.be/<ID>`; episode id = video id (CP2 D3). Domain khác / không có id / quá 2000 ký tự → 422 với message tiếng Việt.
- **Sửa đổi CP8.7 (L2)** (trước đó: `watch?v=ID&list=…` = một video, `playlist?list=…` → 422): `youtube.com/playlist?list=<id>` → bộ kinh (W10); `watch?v=ID&list=<id>` → hỏi (`{kind: "ask"}`), gửi lại với `mode: "video"` (tập lẻ) hoặc `"playlist"` (cả bộ kinh). `list` là Mix (`RD…`), Xem sau (`WL`), Đã thích (`LL`, `LM`) → `playlist?list=` 422; cạnh một video (`watch?v=…&list=RD…`) → coi là video. Playlist id `[A-Za-z0-9_-]{10,64}`, đúng một `list`.
- Không nhận đường dẫn file local từ web (CLI vẫn nhận).
- **Sửa đổi CP8.9 (HUMAN LEAD 2026-09-28, A1):** link một video tạo Short và / hoặc video khai thị (`kinds`, mặc định cả hai; phút khai thị). Canonical: `docs/decisions/CP8.9-khai-thi-contract.md` K7.
- Form có ô tuỳ chọn `series` / `episode` (≤ 100 ký tự, trim, rỗng = không đặt) truyền thẳng vào titling (CP6 G2, như `--series` / `--episode`).

## W4. Luồng xử lý

- `POST /api/episodes`: parse URL (lỗi → 422, không job) → nếu episode đã có job `queued`/`running` → 200 `created: false` + job đó (không preflight, không job mới) → episode archived → 409 (CP8.6 W9) → ổ còn < 3 GB → 507 (CP8.6 W9) → preflight Ollama (CP8 E8) ngay trong request (lỗi → 503 `ollama preflight: <lý do>`, không job) → tạo job pipeline → 202 `created: true`.
- Job pipeline gọi `run_pipeline(url, config, series, episode, preflight=ollama_preflight, on_stage=…)`: preflight chạy lại khi job bắt đầu (job có thể đã đợi trong hàng). **Sửa đổi CP8.10:** ở `queue_mode = "lanes"` job gọi `run_pipeline(…, stages=<các stage của làn>)` một lần mỗi làn (W5); preflight chạy lại ở đầu làn `ai` (không ở đầu job: ingest / transcript / analysis vẫn chạy khi Ollama tắt, job lỗi `ollama preflight: …` ở làn `ai`, gửi lại URL chạy tiếp); `"serial"` như câu trước. Kết quả: `done` + `summary` `"<rendered>/<clips> Shorts"`; lỗi stage → `failed`, `error = "<stage>: <message>"` (CP8 E4); lỗi preflight → `failed`, `error = "ollama preflight: …"`.
- **Sửa đổi FIX-ollama-wait (HUMAN LEAD 2026-09-30, O4):** `POST /api/episodes` **không preflight Ollama trong request** (bỏ 503): luôn xếp job (202), trừ 409 / 422 / 507; Ollama tắt → job vào làn `ai` và đợi GPU (W5), thiếu model → `failed` `ollama preflight: …` ở làn `ai`. Ngoại lệ: "Thêm Short" (CP9) vẫn preflight + 503. Canonical: `docs/tasks/FIX-ollama-wait.md` O1–O7.
- Gửi lại URL của episode đã xong / lỗi / bị ngắt → job mới; pipeline tự skip / resume (CP8 E3).
- Tiến độ: status từng stage đọc từ `manifest.json` (CP2) + stage hiện tại và thời gian từng stage (`on_stage`: `ran` / skip, giây) + log của job. Trang episode poll JSON mỗi 2,5 s khi có job đang chạy/đợi.
- Khi render chạy trong job, `summary` thêm `" (<e> encoded, <r> reused)"` từ `RenderResult.encoded` / `reused` (CP8.2 T5).

### Sửa title (phase B)

- Dùng đúng hàm dùng chung của CP8.2 (`preview_title`, `set_title`, `set_alternative` (1-based), `reset_title`, `list_titles`); luật validate, `review.json`, thứ tự nguồn title, `render_key` và tái dùng: `docs/decisions/CP8.2-title-override-contract.md` (canonical owner). Web không tự validate / ghi `review.json`.
- Xem trước: `preview_title` (không ghi, không job) — dùng được cả khi có job đang chạy.
- Ghi (`set` / `alternative` / `reset`): **từ chối 409** khi episode có job `queued`/`running` (pipeline hoặc render) → `review.json` không bị ghi giữa lúc render đọc nó. Kiểm "không có job" + ghi + tạo job nằm trong một lock của app (gửi URL cũng lấy lock đó khi tạo job) nên không lọt job giữa hai bước. `ReviewError` → 422 (message CP8.2), không ghi, không job.
- Ghi thành công → tạo job `render` (`clip_ids` = [clip vừa sửa]) gọi `run_render(episode_id, config)` không `force`: CP8.2 T5 chỉ encode Short có `render_key` đổi, các Short khác `reuse`. `reset` khi không có override vẫn tạo job (render skip ngay). Lỗi render → job `failed`, `error = "render: <message>"`; output lần render trước giữ nguyên (CP8.2 T5).

## W5. Job model

**Sửa đổi CP8.10 (HUMAN LEAD 2026-09-28, `docs/tasks/CP8.10-queue-lanes.md` Q0–Q8)** — trước đó: một worker thread, một job chạy tại một thời điểm (nay là `queue_mode = "serial"`).

- `[web] queue_mode = "lanes"` (mặc định): ba **làn**, mỗi làn một worker thread + hàng đợi FIFO trong bộ nhớ, mỗi làn chạy tối đa một job:
  - `prepare` = ingest → transcript → analysis; `ai` = preflight Ollama → selection → titling; `render` = render.
  - Job `pipeline` vào cuối hàng `prepare`; xong một làn → vào cuối hàng làn kế; lỗi / bị ngắt ở làn nào → job kết thúc ở đó (`failed` / `interrupted`, W4). Mỗi làn gọi `run_pipeline(…, stages=<các stage của làn>)` (CP8 E7); làn sau dùng episode id mà ingest trả về. Stage tự skip khi up to date (CP8 E3).
  - Job `render` (sửa title / xóa / khôi phục Short) vào thẳng cuối hàng làn `render`, không ưu tiên (FIFO với render của job pipeline).
  - **Sửa đổi CP9** (C6, C7): sửa đầu/cuối một Short = job `render` như sửa title. Thêm Short = job `add`: làn `ai` (preflight Ollama rồi title AI của đúng Short đó, `titling.added.title_added`, `stage` = `preflight` → `titling`), rồi cuối hàng làn `render` (render, Short khác tái dùng). AI không cho title (preflight lỗi, không lần nào đúng schema, không option hợp lệ) → Short ở lại `untitled`, render vẫn chạy (Short hiện ra, chờ title tay), job `failed` với `error` = lỗi AI + "gõ tiêu đề tay". `serial`: hai bước liền trong một lần chạy.
  - Giới hạn tải trước: làn `prepare` không bắt đầu job mới khi đã có **2** job xong `prepare` đang đợi làn `ai` (hằng trong code `PREFETCH_LIMIT`, không phải config).
  - Ngay trước ingest ở làn `prepare`: kiểm lại ngưỡng ổ W9 (< 3 GB) → job `failed`, `error` = message 507 của W9, không tải.
  - Short + khai thị cùng video (CP8.9 K5): không có cơ chế phụ thuộc riêng; hai job đi qua làn `prepare` FIFO (Short trước, W4 / K7) nên ingest của `<id>.kt` luôn chạy sau transcript của `<id>` và dùng lại nguồn.
  - Mỗi stage chỉ thuộc một làn nên một stage không bao giờ chạy song song với chính nó; analysis (CPU) có thể chạy cùng lúc với render (CPU) của tập khác, transcript Whisper (khi không có phụ đề YouTube) cùng lúc với AI (GPU) của tập khác.
- `queue_mode = "serial"`: một worker thread chạy trọn job (6 stage, preflight đầu job) — hành vi trước CP8.10; không kiểm lại ổ trước ingest.
- Job: `id` (số tăng dần trong phiên server), `episode_id`, `kind` (`pipeline` | `render` | `add` — CP9), `clip_ids` (job `render`: Short vừa sửa title / điểm cắt; job `add`: Short vừa thêm), `status` (`queued`, `running`, `done`, `failed`, `interrupted`), `created_at` / `started_at` / `finished_at` (UTC ISO), `stage`, `stages` [{`stage`, `ran`, `seconds`}], `error`, `summary`, `logs`; CP8.10: `lane`, `waiting`.
  - `status`: `queued` khi chưa vào làn nào; `running` từ lúc làn đầu tiên bắt đầu tới khi kết thúc, **kể cả lúc đợi giữa hai làn**.
  - `lane`: làn đang chạy job hoặc làn job đang đợi (`"prepare"` | `"ai"` | `"render"`); `null` khi `queued`, đã kết thúc, hoặc `queue_mode = "serial"`. `waiting`: `true` khi job `running` đang đợi giữa hai làn.
  - `stage`: stage đang chạy (`"preflight"` trong lúc preflight), hoặc stage đầu của làn kế khi đang đợi.
- Một episode chỉ có tối đa một job `queued`/`running` (pipeline hoặc render; kể cả job đang đợi giữa hai làn); gửi URL trùng trả job đang có (kể cả job `render`), ghi title / xóa / khôi phục Short / dọn nguồn / xóa tập → 409.
- **Sửa đổi CP8.15 (HUMAN LEAD 2026-09-29, P1, P5b):** job soạn bài đăng cộng đồng (`kind: "post"`) vào thẳng làn `ai` (preflight riêng chỉ kiểm `[post] model`, không kiểm `[selection]`/`[titling]`); cùng luật một job mỗi episode ở trên. Job tìm ảnh từ link (`kind: "post_search"`) vào làn `prepare`, không cần Ollama, chạy dưới id `_post_images` (không phải episode id: không cạnh tranh với job pipeline/render/soạn bài của episode nào, chỉ một job tìm ảnh một lúc trên toàn server). Canonical chi tiết: `docs/decisions/CP8.15-community-post-contract.md` P1, P5b.
- **Sửa đổi CP8.16 (HUMAN LEAD 2026-09-30, R2, R3):** job `post` chạy dưới khóa riêng `<episode_id>#post` (không chiếm khóa job của episode; sửa Short không bị 409 vì nó) và được server tự xếp sau job `pipeline` / `render` / `add` kết thúc. Canonical: `docs/tasks/CP8.16-post-tab-auto.md` R2–R4, `docs/decisions/CP8.15-community-post-contract.md` P1.
- **Sửa đổi FIX-ollama-wait (HUMAN LEAD 2026-09-30, O5, O6):** `queue_mode = "lanes"`: mất kết nối Ollama (`OllamaUnavailable` / `ChatUnavailable`, phân biệt với thiếu model / lỗi khác) ở làn `ai` **không** làm job `failed`: job (`pipeline`, `post`) về **đầu** hàng `ai` (`running` + `waiting` + `gpu_wait`), làn vào trạng thái `gpu_down`, kiểm lại preflight job đầu hàng mỗi `GPU_RETRY_SECONDS` = 60 s (hằng trong code, ngủ bằng `Condition.wait`) rồi chạy tiếp FIFO khi Ollama có lại (log `web: ollama is back`); stage lỗi giữa chừng mà preflight kiểm lại là mất kết nối → cũng về hàng đợi (lần sau chạy lại từ stage lỗi), preflight được → lỗi thật, `failed`. Job `add` (CP9) không đợi (Short `untitled` + render + `failed`, như CP9). `_can_start(prepare)` bỏ `PREFETCH_LIMIT` khi `gpu_down`. Dừng server khi đợi GPU → `interrupted` `"interrupted while waiting for GPU"`. `serial`: không đợi (`failed` như cũ). Không giới hạn thời gian đợi; không fallback Ollama CPU / host khác. Canonical: `docs/tasks/FIX-ollama-wait.md` O1–O8.
- Log: mọi record của logger `auto_short` phát ra trên worker thread của làn đang chạy job (level ≥ INFO) được chép vào vòng đệm 200 dòng cuối của job đó, dạng `HH:MM:SS [LEVEL ]message`; server vẫn log ra stderr như CLI. Không gồm stderr của tiến trình con (ffmpeg, yt-dlp).
- Lịch sử job chỉ trong bộ nhớ: restart server mất hàng đợi và log (manifest còn; gửi lại URL → resume).
- Tắt server (Ctrl-C / SIGINT / SIGTERM qua uvicorn) khi job đang chạy: thread của mọi làn đang chạy job nhận `KeyboardInterrupt` (inject vào thread) + tiến trình con trực tiếp nhận SIGINT; chờ tối đa 30 s tổng. Stage đang chạy ghi `failed` + `error: "interrupted"` (CP2 `run_stage`), job `interrupted` (`"interrupted during <stage>"`); job đang đợi giữa hai làn → `interrupted` (`"interrupted while waiting for <lane>"`). Nếu stage đang kẹt trong một lời gọi dài không trả về trong 30 s (vd request Ollama) thì server thoát, manifest giữ `running` — CP8 E3 coi là chưa up to date, gửi lại URL sẽ chạy lại stage đó.

## W6. UI

- HTML + CSS + JS thuần trong `src/auto_short/web/static/` (package data; không build step, không framework frontend), tiếng Việt, responsive (lưới Short 2 cột trên điện thoại).
- `/` : form URL (+ tuỳ chọn series / tập), lỗi (422 / 503) hiện ngay dưới form; danh sách episode (tên video, trạng thái: đang chạy stage / lỗi ở stage / N Shorts · đã đăng x/y — CP8.5) + bộ lọc Tất cả / Còn Short chưa đăng / Đã đăng hết (W8).
- `/episodes/<id>`: tên, kênh, thời lượng; trạng thái job; 6 stage (`chờ`, `đang chạy`, `xong`, `lỗi` + message, `cần chạy lại`) + thời gian hoặc "bỏ qua (đã có)"; nhật ký (mở sẵn khi đang chạy / lỗi); nút "Chạy tiếp / chạy lại" (gửi lại `source_url`, ẩn khi có job đang chạy); nút "Xóa tập này" (CP8.5, W8); lưới Short; nút "Tải tất cả Short (.zip)" (view Shorts) / "Tải tất cả khai thị (.zip)" (view Khai thị) (P3; **sửa đổi CP8.17 D4**) và "Tải cả hai (.zip)" (**CP8.17 D5**: ẩn khi `zip_all_url` là `null`; bấm zip không làm mới trang — zip không còn đổi trạng thái, D3); bộ lọc Tất cả / Chưa đăng / Đã đăng + "Đã đăng x/y" + "Hiện Short đã xóa (n)" (CP8.5).
- Mỗi Short: `<video controls preload="metadata" playsinline>` (tua bằng Range), mã clip, nhãn nguồn title trong file (`AI` / `sửa tay` / `phương án AI khác`), thời lượng, title, "Tiêu đề mới … chưa render" khi title lần render tới khác file (vd render lỗi), nút "Tải về".
- **Sửa đổi CP8.7 — nút "Copy" tiêu đề (bổ sung HUMAN LEAD 2026-09-27):** ngay cạnh title mỗi Short (khi có title), copy đúng title trong file (`render_manifest.json` `title`), báo "Đã copy" 1,5 s; lý do: app YouTube trên điện thoại không điền title từ tên file / metadata MP4. Site HTTP trong LAN không phải secure context: dùng `navigator.clipboard.writeText` chỉ khi `window.isSecureContext`; còn lại (hoặc khi nó lỗi) `<textarea>` tạm (readonly, contenteditable cho iOS, ngoài màn hình, cỡ chữ 16 px tránh iOS phóng to) + `focus` + `select()` + `setSelectionRange(0, len)` + `document.execCommand("copy")` trong handler bấm; trả `false` / lỗi → hiện ô chứa title đã chọn sẵn + "Giữ vào ô để copy". Không tự copy khi tải về.
- **Sửa đổi CP8.7 — hashtag (bổ sung HUMAN LEAD 2026-09-27):** nút Copy copy `copy_text` do server tính = `<title trong file> <hashtags>`; hashtags = `#<series>` (`titles.json` `header.fields.series`, không có → bỏ) rồi `[web] hashtags` (mặc định `["TịnhKhông", "LờiPhậtDạy", "TịnhĐộ", "NiệmPhật"]`, thứ tự giữ nguyên); mỗi hashtag = `#` + các ký tự chữ / số của chuỗi (NFC, giữ dấu tiếng Việt, bỏ khoảng trắng / dấu câu / `#` đầu), vd "Thập Thiện Nghiệp Đạo Kinh" → `#ThậpThiệnNghiệpĐạoKinh`; bỏ trùng không phân biệt hoa thường; cả chuỗi ≤ 100 ký tự (giới hạn title YouTube): bỏ hashtag từ cuối tới khi vừa, không bao giờ cắt title. Dòng hashtag (nhỏ, xám) hiện dưới title. `[web] hashtags` là config thực thi, không vào hash stage nào.
- **Sửa đổi CP8.8 — hashtag riêng từng bộ kinh (H2, H4, H7):** tập thuộc bộ kinh có danh sách riêng (W10) → hashtags = đúng danh sách đó theo thứ tự (thay cả `#<series>` lẫn `[web] hashtags`; danh sách rỗng = chỉ title); cùng rule chuẩn hóa / bỏ trùng / ≤ 100 ký tự ở trên. Tập thuộc nhiều bộ kinh có danh sách riêng → bộ có `playlist_id` nhỏ nhất (thứ tự tên file). Không có → mặc định như trên. Trang bộ kinh: khung thu gọn "Hashtag khi Copy tiêu đề (mặc định | riêng bộ kinh này)" — mỗi hashtag một dòng với ↑ ↓ ✕, ô thêm (hiện dạng sẽ lưu), xem trước chuỗi copy (title dài nhất trong file Short `rendered` của bộ kinh, không có → câu mẫu 60 ký tự; ghi hashtag bị bỏ vì quá 100 ký tự), "Lưu", "Khôi phục mặc định" (xác nhận); mở lần đầu điền sẵn danh sách đang áp dụng; poll trang không ghi đè khung đang sửa. Có hiệu lực ngay cho mọi Short (kể cả đã đăng) vì `copy_text` tính lúc xem; không đổi file, tick, hash.
- **Sửa đổi CP8.7 — màn hình ≤ 640 px (bổ sung HUMAN LEAD 2026-09-27):** tab Bộ nhớ: bảng từng tập (màn hình rộng, thêm cột "Gợi ý" với nút hành động) đổi thành thẻ — title tối đa 2 dòng (…), nhãn trạng thái, tổng dung lượng chữ lớn, dòng "Nguồn … · Short … · Khác …", "Đã đăng x/y", nút gợi ý rộng hết thẻ; gợi ý dạng thẻ, nút rộng hết; thanh ổ đĩa rộng hết, số liệu dòng riêng. Mọi nút ≥ 40 px, không cuộn ngang; áp cho trang bộ kinh (nút xuống dòng riêng), trang chủ (Bộ kinh / Tập lẻ / Đã xóa). Dung lượng hiển thị theo đơn vị 1024 (MB; GB 1 chữ số thập phân), vd 678 949 583 B = 648 MB.
- Sửa title (`.title-edit`, chỉ khi `editable`): nút "Sửa tiêu đề" mở ô nhập (giá trị = title sẽ render) + bộ đếm `n/<max_title_chars>` (đỏ khi vượt), dropdown phương án AI khác (chọn → điền ô nhập; lưu gửi `alternative: n` nếu ô nhập còn đúng chữ đó, sửa thêm → `set`), xem trước (gọi preview sau 350 ms ngừng gõ: dòng hiển thị trên nền vàng + cỡ chữ, hoặc lỗi 422), "Lưu & render lại" (bật khi xem trước hợp lệ và không có job), "Khôi phục title AI" (khi có override). Khi episode có job: nút lưu tắt + ghi chú "Đang có job chạy — đợi xong để lưu"; Short đang render lại có viền + nhãn "đang render…" trên video.
- **Sửa đổi CP8.12 (HUMAN LEAD 2026-09-28):** trang tập có thanh ghim [Shorts | Khai thị] (thay link chữ CP8.9 K7), khung 6 bước thu gọn (summary = dòng trạng thái job) và thông báo khi tập đích / tập không còn — chi tiết: `docs/tasks/CP8.12-episode-ui.md` U1–U4.
- **Sửa đổi CP8.13 G5 (HUMAN LEAD 2026-09-28):** mỗi thẻ Short có video (trang tập, cả Short lẫn khai thị) có nút bật / tắt "🔁 Lặp lại" (`aria-pressed`) cạnh "Tải về": bật → `video.loop = true` (xem hết tự phát lại từ đầu). Trạng thái theo từng video (`clip_id`), giữ khi thẻ được dựng lại trong lúc trang còn mở; mặc định tắt; không lưu qua lần mở trang; không gọi API. Thẻ không có video (đã xóa / bỏ qua) không có nút.
- **Sửa đổi CP9 (HUMAN LEAD 2026-09-29, C7):** trang tập (Short và khai thị) có nút "+ Thêm Short" / "+ Thêm video khai thị" (khi có render, titles đọc được, không archived; tắt khi có job) → hộp thoại toàn màn hình trên điện thoại, hai tab: "Đề xuất AI (n)" (topic, điểm, lý do, khoảng + thời lượng, dòng đầu/cuối, lỗi C4, chồng lấn Short nào, "Nghe thử", "Thêm đoạn này") và "Chọn trên transcript" (mọi dòng caption + mốc thời gian, dòng thuộc Short đã có tô vàng + mã Short ở dòng đầu, nhãn / ngoài nội dung mờ không chọn được, ô tìm chữ bỏ dấu; bấm dòng đầu rồi dòng cuối → thanh dưới hiện chữ hai dòng, mốc, thời lượng, lỗi / cảnh báo ngay qua `cut/preview`, "Nghe thử", "Bỏ chọn", "Thêm đoạn này"). Mỗi thẻ Short sửa được (không xóa, không archived) có "Sửa đầu/cuối": chữ dòng đầu / cuối + mốc, [+ dòng] [− dòng] [−0.2 s] [+0.2 s] mỗi đầu (tối đa ±2.0 s; đổi dòng đặt lại tinh chỉnh), thời lượng mới + lỗi / cảnh báo (xem trước mỗi lần bấm), "▶ Nghe 5 s đầu" / "▶ Nghe 5 s cuối" (video nguồn, chưa rút khoảng lặng), "Lưu + render lại" (bật khi hợp lệ, có thay đổi, không có job), "Về như AI chọn" (khi đang có cut). "Nghe thử" phát `GET /files/{id}/source.mp4#t=<a>,<b>` (media fragment, dừng ở b) trong trình phát nổi góc dưới, gọi `play()` ngay trong thao tác bấm. Nhãn thẻ: "thêm tay" (`origin: added`), "đã sửa đầu/cuối" (`cut`). Mọi nút ≥ 40 px trên điện thoại.
- Mỗi thẻ Short chỉ dựng lại (thay tại chỗ) khi trạng thái của chính nó đổi (sha256, title, override, title chờ, đang render); danh sách clip đổi mới dựng lại cả lưới → poll không dừng video đang xem hay xóa chữ đang gõ ở thẻ khác; Short render xong tự thay bằng video mới (`video_url` đổi theo sha256).
- **Sửa đổi CP8.15 (HUMAN LEAD 2026-09-29):** mỗi thẻ Short `rendered` có khu thu gọn "Bài đăng cộng đồng" (soạn / sửa đoạn / đổi ảnh / link / sao chép / tick "Đã đăng bài") và trang tập có nút "Soạn bài cho mọi Short" + đếm đã đăng; hộp thoại "Thư viện ảnh" (upload, tìm ảnh từ link, xóa) mở từ "Đổi ảnh". Canonical chi tiết: `docs/decisions/CP8.15-community-post-contract.md` P4, P9.
- **Sửa đổi CP8.16 (HUMAN LEAD 2026-09-30, R1):** thanh chuyển thành [Shorts | Khai thị | Bài đăng] (nút thứ ba link tới `/episodes/<id>/posts`); khu bài đăng rời thẻ Short sang trang tab "Bài đăng". Canonical: `docs/tasks/CP8.16-post-tab-auto.md` R1, `docs/decisions/CP8.15-community-post-contract.md` P9.
- **Sửa đổi FIX-ollama-wait (O7):** trang chủ, trang tập, trang bộ kinh, tab Bài đăng: khi `gpu.state = "down"` hiện dải cảnh báo "Mất kết nối GPU (Ollama) từ HH:MM — tập vẫn được tải / chuẩn bị, phần AI tự chạy tiếp khi GPU có lại (kiểm lại mỗi 60 s)"; nhãn job `gpu_wait` = "đợi GPU (mất kết nối)" (nhãn "đợi GPU" của hàng đợi thường giữ nguyên); form gửi link không còn hiển thị lỗi 503 Ollama.

## W7. API và file

Mọi route cần cookie (W2). JSON UTF-8.

**Sửa đổi CP8.18 (HUMAN LEAD 2026-10-02):** route từ điển sửa lỗi bài đăng `GET|POST /api/post-corrections`, `PUT|DELETE /api/post-corrections/{id}`; `PUT /api/episodes/{id}/posts/{clip}` có `paragraphs` trả thêm `proposed` — canonical ở `docs/decisions/CP8.15-community-post-contract.md` P14.

**Sửa đổi CP8.9 (HUMAN LEAD 2026-09-28):** `POST /api/episodes` nhận thêm `kinds`, `min_minutes`, `max_minutes` và trả thêm `episodes: […]`; `GET /api/episodes`, `GET /api/episodes/{id}` thêm `kind`, `min_minutes`, `max_minutes`, `base_episode_id`, `khaithi_episode_id`; entry bộ kinh thêm trạng thái khai thị. Canonical: `docs/decisions/CP8.9-khai-thi-contract.md` K7, K8.

| Route | Kết quả |
|---|---|
| `POST /api/episodes` `{url, series?, episode?, mode?}` | video: 202 `{kind: "video", created: true, episode_id, job}`; 200 `{kind: "video", created: false, …}` (đã có job đang chạy/đợi); 422 `{detail}` (URL / field sai); 503 `{detail: "ollama preflight: …"}`. CP8.7: playlist → 201 `{kind: "playlist", created: true, playlist_id, title, count}` / 200 `created: false` (đã lưu, không liệt kê lại); 502 liệt kê lỗi / quá 60 s; `watch?v&list` không `mode` → 200 `{kind: "ask", video_id, playlist_id}`; `mode` ∈ `video`, `playlist` |
| `GET /api/episodes` | `{episodes: [{id, title, stages_done, stages_total, running, failed, shorts, job}]}` — mọi workspace có manifest (mới nhất trước) + job đang đợi chưa có workspace; `job` không kèm `logs` |
| `GET /api/episodes/{id}` | `{id, title, channel, duration, source_url, stages: [{stage, status, started_at, finished_at, error}], render_status, header, shorts, rendered, zip_url, zip_name, zip_all_url, zip_all_name (CP8.17 D5: `null` khi `all.zip` sẽ 404), max_title_chars, titles_error, titles_ignored, job}`; 404 khi không có manifest và không có job |
| `POST /api/episodes/{id}/shorts/{clip}/title/preview` `{text}` | 200 `{clip_id, title, origin: "manual", display_lines, font_size, panel_height, chars}`; 422 `{detail}` (`ReviewError`: title sai, clip không có, titling chưa `done`); không ghi |
| `POST /api/episodes/{id}/shorts/{clip}/title` `{set: text}` \| `{alternative: n}` \| `{reset: true}` | đúng một hành động, không thì 422; 202 `{preview, job}` (`preview` như trên với `origin` thật, `null` khi reset clip `untitled`; `job` = job `render` mới); 409 `{detail, job}` khi có job đang chạy/đợi; 422 `ReviewError`, không ghi |
| `GET /files/{id}/{clip}.mp4` | `video/mp4`, hỗ trợ `Range` (206 + `Content-Range`), `Cache-Control: private, no-cache` |
| `GET /files/{id}/{clip}.mp4?download=1` | như trên + `Content-Disposition` với tên W8 (CP8.5; trước đó `<id>_<clip>.mp4`) |
| `GET /files/{id}/shorts.zip` | zip stream (`ZIP_STORED`, không nén) mọi Short `rendered` theo thứ tự manifest, entry tên W8 (cờ UTF-8); `Content-Disposition` tên `[<series>_]Tập<episode>_Shorts.zip` (CP8.5, **sửa đổi CP8.17 D4** thêm tên bộ kinh; trước đó `<id>_shorts.zip` / `<id>_<clip>.mp4`); **không tick "Đã đăng"** (CP8.17 D3); 404 khi chưa có Short |
| `GET /files/{id}/all.zip` | **CP8.17 D5:** `id` = `<vid>` hoặc `<vid>.kt` (cùng kết quả); zip stream `ZIP_STORED`, entry `Shorts/<tên W8>` (mọi Short `rendered` của `<vid>`, thứ tự manifest) rồi `KhaiThị/<tên W8>` (của `<vid>.kt`), cờ UTF-8; tên `[<series>_]Tập<episode>_Shorts+KhaiThị.zip`; không tick; 404 khi một trong hai tập không có Short `rendered`; cùng auth / validate id như `shorts.zip` |
| `POST /api/episodes/{id}/shorts/{clip}/delete` \| `…/restore` | CP8.5 X2: 202 `{changed, job}` (`job` = job `render`, `clip_ids` = [clip]); 409 `{detail, job}` khi có job đang chạy/đợi; 422 `ReviewError` (clip không có, titling chưa `done`), không ghi |
| `POST /api/episodes/{id}/shorts/{clip}/published` `{value: true\|false}` | CP8.5 X4: 200 `{clip_id, published, stale, at}`; không job, được cả khi job đang chạy; `value` phải là JSON boolean (khác → 422); tick Short không có file → 422 |
| `POST /api/episodes/{id}/archive` | CP8.6 S3 (W9): 200 `{archived: id, changed, freed, removed}` (`changed: false`, `freed: 0` khi đã dọn); 404 id sai / không có workspace; 409 `{detail, job}` khi có job đang chạy/đợi; 422 nguồn local / render chưa `done` |
| `GET /api/storage` | CP8.6 S1, S2, S4 (W9): `{computed_at, disks: [{label, path, total, used, free}], free, warn, block, warn_bytes, warn_ratio, block_bytes, episodes: [{id, title, state, source_kind, source, shorts_bytes, other, total, shorts, published, render_finished_at, last_activity, archived_at}], totals: {source, shorts, other, episodes}, caches: [{name, path, bytes}], recommendations: [{episode_id, title, rule, age_days?, actions: [{action: archive\|delete, frees}]}], old_days}`; cache ≤ 30 s |
| `GET /api/storage/status` | CP8.6 S4: `{disks, free, warn, block, warn_bytes, warn_ratio, block_bytes}` (không cache) |
| `GET /storage` | CP8.6: trang "Bộ nhớ" |
| `GET /api/playlists` | CP8.7: `{playlists: [{id, title, count, fetched_at, processed, complete, running, failed, doing, deleted}]}` (CP8.13 G3: `running` / `failed` / `doing` = số tập nhóm tương ứng, W10) |
| `GET /api/deleted` | CP8.7: `{episodes: [bia mộ W8]}` — tập lẻ đã xóa (không thuộc bộ kinh đã lưu, không có workspace), mới nhất trước |
| `DELETE /api/deleted/{id}` | CP8.7: 200 `{removed}` (chỉ bia mộ); 404 |
| `GET /api/playlists/{pid}` | CP8.7: `{id, title, url, fetched_at, count, counts: {all, todo, running, failed, doing, done}, entries: [{index, video_id, title, duration, episode, available, state, stage, error, shorts, published, archived, complete, deleted_at, group, action, job}], hashtags, hashtags_custom, series, series_suggested, unrecognized}` (CP8.8: `hashtags` = danh sách đang áp dụng, có `#`; CP8.11: `series` = "Tên bộ kinh" đã đặt \| `null`, `series_suggested` = `series` của pattern (CP6 G2) trên title entry khả dụng đầu tiên được nhận dạng \| `null`, `unrecognized` = số entry `available` không khớp pattern nào); 404 |
| `POST /api/playlists/{pid}/refresh` | CP8.7: 200 `{playlist_id, count, added: [video_id]}`; 404; 502 |
| `PUT /api/playlists/{pid}/hashtags` | CP8.8: body `{hashtags: [str]}` (≤ 100 phần tử) → mỗi mục chuẩn hóa như `#<series>` (W6); rỗng sau chuẩn hóa, trùng (không phân biệt hoa thường), > 15 mục, sai kiểu → 422, không ghi; 200 `{playlist_id, hashtags: ["#…"], hashtags_custom: true}`; 404. Không tạo job, gọi được khi có job chạy |
| `DELETE /api/playlists/{pid}/hashtags` | CP8.8: bỏ danh sách riêng → 200 `{playlist_id, hashtags, hashtags_custom: false}` (danh sách mặc định: `#<series>` của tập đầu tiên đã xử lý + `[web] hashtags`); 404 |
| `PUT /api/playlists/{pid}/series` | CP8.11 D7: body `{series: str}` → chuẩn hóa NFC + gộp khoảng trắng, 1–100 ký tự; sai kiểu / thiếu / rỗng / > 100 ký tự → 422, không ghi; 200 `{playlist_id, series, series_custom: true}`; 404. Không tạo job, gọi được khi có job chạy |
| `DELETE /api/playlists/{pid}/series` | CP8.11 D7: bỏ tên → 200 `{playlist_id, series: null, series_custom: false}`; 404 |
| `POST /api/playlists/{pid}/hashtags/preview` | CP8.8: cùng body, không ghi → `{hashtags, title, title_is_real, copy_text, chars, max_chars, dropped}`; 404; 422 |
| `DELETE /api/playlists/{pid}` | CP8.7: 200 `{deleted}` (chỉ bản ghi danh sách); 404 |
| `GET /playlists/{pid}` | CP8.7: trang bộ kinh |
| `GET /api/episodes/{id}/transcript` | CP9 C7: `transcript_view` (CP8.2 § Hàm dùng chung): dòng caption, `content`, `min_duration` / `max_duration`, khoảng hiện tại của mọi Short (dòng đầu/cuối, `cut`, `rejected`); 404 id sai; 422 `ReviewError` (titling chưa `done`, artifact không khớp). Chỉ đọc, được khi có job |
| `GET /api/episodes/{id}/proposals` | CP9 C7: `list_proposals`: đề xuất AI `overlapped` / `over_limit` / `ineligible` có candidate (topic, điểm, lý do, khoảng, thời lượng, lỗi C4, chồng lấn, `added_as`); 422 như trên |
| `POST /api/episodes/{id}/cut/preview` `{clip_id?, start_segment, end_segment, start_nudge?, end_nudge?}` | CP9 C7: 200 `preview_cut` (quyết định khi implement: vi phạm C4 trả trong `error` với HTTP 200 để UI hiện thời lượng + lỗi cùng lúc; `clip_id` = Short đang sửa, không có = Short mới); 422 chỉ khi input sai (dòng không có / không phải lời nói, dòng cuối trước dòng đầu, nudge không phải bội 0.2 hoặc quá ±2.0, vượt giới hạn C3); không ghi, được khi có job |
| `POST /api/episodes/{id}/shorts/{clip}/cut` `{start_segment, end_segment, start_nudge, end_nudge}` \| `{reset: true}` | CP9 C7: đúng một dạng, không thì 422; 202 `{preview, job}` (job `render`, `clip_ids` = [clip]); 409 `{detail, job}` khi có job đang chạy/đợi, 409 tập archived (W9); 422 `ReviewError` (đoạn không hợp lệ C4 …), `review.json` không đổi |
| `POST /api/episodes/{id}/shorts` `{candidate_id}` \| `{start_segment, end_segment, start_nudge?, end_nudge?}` | CP9 C7: 409 job / archived → 503 preflight Ollama (như W4) → ghi `added` → 202 `{clip_id, preview, job}` (job `add`, `clip_ids` = [clip]); 422 đề xuất không còn / đoạn không hợp lệ, không ghi |
| `GET /files/{id}/source.mp4` | CP9 C7: video nguồn cho "Nghe thử" — `source.path` của manifest, chỉ khi là file `source.*` ngay trong `work/<id>/` (nguồn local ngoài workspace không phục vụ) và tập chưa archived; `Range`; `Content-Type` theo đuôi; không tick "Đã đăng"; còn lại 404 |
| `DELETE /api/episodes/{id}` | CP8.5 X3: 200 `{deleted: id}`; 404 id sai / traversal / không có; 409 `{detail, job}` khi có job đang chạy/đợi; 500 khi xóa lỗi |

- `job` = các field W5 + `queue_position` (vị trí trong hàng, `null` khi không đợi). **Sửa đổi CP8.10:** thêm `lane`, `waiting` (W5); `queue_position` = vị trí 1-based trong hàng của làn job đang đợi (kể cả đợi giữa hai làn), `null` khi đang chạy / đã kết thúc; `job` trong `GET /api/episodes` và entry bộ kinh (`GET /api/playlists/{pid}`) cũng có `queue_position`. UI (W6): "đang tải trước" (làn `prepare` đang chạy), "đợi GPU" (đợi làn `ai`), "đợi render" (đợi làn `render`) ở trang tập, danh sách tập và trang bộ kinh.
- **Sửa đổi FIX-ollama-wait (O7):** `job` thêm `gpu_wait: bool` (đang đợi ở làn `ai` lúc `gpu_down`); `GET /api/episodes`, `GET /api/episodes/{id}`, `GET /api/playlists/{pid}` thêm `gpu: {state: "ok" | "down", since, error, next_check}` (phản ánh lần kiểm gần nhất của làn `ai`; `since` / `next_check` UTC ISO, `null` khi `ok`). `POST /api/episodes` và `POST /api/episodes/{id}/posts` không còn trả 503 Ollama.
- `shorts[]` = `{clip_id, status (rendered | skipped), skip_reason, duration, source_start, source_end, title: {text, origin, display_lines}, sha256, video_url, download_url, download_name, deleted, rejected, published, published_stale, published_at, editable, ai_title, alternatives: [{n, title}], override: {title, origin} | null, pending_title: {text, origin} | null, rendering}` (CP8.5 thêm `download_name` … `published_at`; episode thêm `deleted`, `published` (số Short `rendered` đã tick), `publish_error`, `zip_name`; `GET /api/episodes` mỗi item thêm `published`, `publish_group`; CP8.6: episode thêm `archived: {at, freed} | null`, item danh sách thêm `archived: bool`; CP8.7: episode + item danh sách thêm `complete` ("Xong", W10), item thêm `in_playlist`).
  - CP8.5: `deleted` = render cuối bỏ qua Short vì `rejected` (file đã xóa); `rejected` = `review.json` đang xóa (khác `deleted` trong lúc job render chạy); `download_name` = tên W8 (`null` khi không có file).
  - `title` = title **trong file** (`render_manifest.json` `title` / `title_origin` / `title_display_lines`; manifest trước CP8.2 không có `title_origin` → `ai`). `video_url` = `/files/<id>/<clip>.mp4?v=<sha256[:12]>` (đổi khi file đổi), `null` khi Short bị bỏ qua.
  - `ai_title`, `alternatives`, `override` từ `list_titles` (CP8.2); `pending_title` = title lần render tới khi khác title trong file (title hoặc origin), `null` nếu giống; `editable` = `list_titles` đọc được (titling `done`, `review.json` hợp lệ), không thì `titles_error` = message và không sửa được. `titles_ignored` = cảnh báo T3 (override bị bỏ qua).
  - `rendering` = episode có job `render` (CP9: hoặc `add`) đang chạy/đợi và clip nằm trong `clip_ids`.
  - CP9: mỗi Short thêm `origin` (`"ai"` | `"added"`, render manifest; thiếu → `"ai"`) và `cut` (`null` | `{start, end}` trong file) — key cuối.
- **Danh sách Short = render cuối đã commit** (quyết định phase B, thay luật phase A "chỉ khi render `done`"): `shorts`, file và zip lấy từ `render_manifest.json` hiện có (đúng `episode_id`) **bất kể** status stage render (`running`, `stale`, `failed`, `pending`); `render_status` cho UI ghi chú "Đang hiển thị bản dựng trước". Lý do: CP8.2 T5 — render mới encode vào `.part`, chỉ thay mp4 + manifest ở bước commit, lỗi / bị ngắt trước commit giữ nguyên render trước (mp4 khớp manifest); nên trong lúc render lại một Short (hoặc cả pipeline), mọi Short cũ vẫn xem / tải được. Khoảng nhỏ trong lúc commit (file đã thay, manifest chưa ghi) có thể cho sha256 cũ với file mới — chấp nhận. Lỗi giữa commit → CP8.2 xóa manifest → danh sách rỗng.
- **Sửa đổi CP8.15 (HUMAN LEAD 2026-09-29):** route bài đăng cộng đồng (`GET`/`POST /api/episodes/{id}/posts`, `PUT`/`POST .../posts/{clip}[/posted]`) và thư viện ảnh (`GET`/`POST /api/post-images`, `DELETE /api/post-images/{name}`, `GET`/`POST /api/post-images/search[/{job}]`, `GET /files/post-images/{name}`) — canonical schema, mã lỗi và security tải ảnh từ link: `docs/decisions/CP8.15-community-post-contract.md` P7, P9, P13 (không lặp lại ở đây).
- **Sửa đổi CP8.16 (HUMAN LEAD 2026-09-30, R1, R3, R4):** route trang `GET /episodes/{id}/posts`; `POST .../posts` nhận `clips: "auto"`; `GET /api/episodes/{id}` thêm `post_job`. Canonical: `docs/tasks/CP8.16-post-tab-auto.md`, `docs/decisions/CP8.15-community-post-contract.md` P9.

## W8. Review workflow (sửa đổi CP8.5, HUMAN LEAD 2026-09-27)

Quyết định: `docs/tasks/CP8.5-web-review.md` X1–X4, P1–P4. Hàm thuần / theo episode ở `auto_short.review` (`names.py`, `publish.py`, `delete.py`, `titles.reject_clip` / `restore_clip`), web chỉ gọi.

### Tên file tải về

- Short: `Tập<episode>_S<NN>_<title>.mp4`. `<episode>` = `titles.json` `header.fields.episode` (vd `29`), không có → `<episode_id>` (vd `TậptHtxw6ykUmM_S01_…`). `<NN>` = vị trí clip trong `render_manifest.json` `shorts` (= thứ tự `clips.json`, CP7 R9; Short đã xóa vẫn giữ chỗ nên số không dịch), hai chữ số, ba chữ số khi ≥ 100 clip. `<title>` = `title` trong `render_manifest.json` (title trong file).
- Làm sạch (cả `<episode>` và `<title>`): NFC; bỏ `/ \ : * ? " < > |` và ký tự điều khiển / định dạng (Unicode `Cc`, `Cf`; tab, xuống dòng → khoảng trắng); gộp khoảng trắng liên tiếp thành một, bỏ hai đầu; **giữ** khoảng trắng và dấu tiếng Việt. `<title>` cắt ≤ 150 byte UTF-8 ở ranh giới từ (một từ dài hơn → cắt ở ranh giới ký tự). Title rỗng sau khi làm sạch → `Tập<episode>_S<NN>.mp4`.
- Zip: `Tập<episode>_Shorts.zip`, entry cùng quy tắc (Short đã xóa không có trong zip). **Sửa đổi CP8.17 (D4):** thêm tên bộ kinh phía trước: `<series>_Tập<episode>_Shorts.zip` / `…_KhaiThị.zip`; `<series>` = `titles.json` `header.fields.series` của chính tập đó (tập khai thị: `titles.json` của `<id>.kt`, không có thì của tập Short gốc), làm sạch như `<title>` (giữ dấu + khoảng trắng), cắt ≤ 80 byte UTF-8 ở ranh giới từ; không có / rỗng → tên không có tiền tố. Tên entry và tên Short tải lẻ không đổi. **Tải cả hai (CP8.17 D5):** `<series>_Tập<episode>_Shorts+KhaiThị.zip` (`<series>` / `<episode>` của tập Short gốc), entry `Shorts/…` và `KhaiThị/…`.
- Sửa đổi CP8.9: tập khai thị dùng `Tập<episode>_KT<NN>_<title>.mp4` / `Tập<episode>_KhaiThị.zip` (`docs/decisions/CP8.9-khai-thi-contract.md` K8).
- Sửa đổi CP9 (C2): Short thêm tay nằm sau mọi clip của `clips.json` trong `render_manifest.json` `shorts` → nhận số tiếp theo (vd `S14`, `KT07`); số của Short đã có không đổi; zip gồm cả Short thêm (trừ đã xóa). Short thêm có "Đã đăng", xóa / khôi phục, tải về = đã đăng như Short AI (khóa `(clip_id, candidate_id)`, `candidate_id` `"manual"` khi chọn trên transcript). Giới hạn: khi tổng số Short vượt 99 do thêm, độ rộng số (`S<NN>` → `S<NNN>`) đổi cho mọi Short.
- `Content-Disposition: attachment; filename="<ASCII>"; filename*=UTF-8''<percent-encoded>` (RFC 6266 + RFC 5987): ASCII = bỏ dấu (NFKD, `đ` → `d`), bỏ ký tự ngoài ASCII (rỗng → `download`). File trên đĩa không đổi tên (`shorts/<clip_id>.mp4`). UI đặt thuộc tính `download` của link = tên này.

### Xóa / khôi phục một Short

- Web gọi `reject_clip` / `restore_clip` (`review.json` `rejected`, canonical CP8.2 T7) rồi tạo job `render` như sửa title (W4): cùng lock, 409 khi có job đang chạy/đợi, `ReviewError` → 422. Job render tái dùng các Short khác (CP8.2 T5); xóa → mp4 bị xóa ở commit (vài giây); khôi phục → encode lại Short đó.
- UI: nút "Xóa Short" (hộp xác nhận: file bị xóa ngay, khôi phục được) chỉ khi `editable`; Short đã xóa ẩn khỏi lưới, "Hiện Short đã xóa (n)" hiện chúng (mờ) với nút "Khôi phục"; Short đang xử lý có nhãn "đang xóa…" / "đang khôi phục…". Nút tắt khi episode có job.

### Xóa tập

- `DELETE /api/episodes/{id}` gọi `delete_episode(id, config)`: `episode_id` validate theo CP2 (sai → 404); đường dẫn chỉ từ config: `<workspace.dir>/<id>` và `<render.output_dir>/<id>`; mỗi thư mục phải là thư mục thật (không symlink) có `resolve()` là con trực tiếp của `resolve()` gốc tương ứng, không thì từ chối (500, không xóa gì). Không thư mục nào tồn tại → 404. Xóa output trước, workspace sau (tập chỉ biến mất khỏi danh sách khi manifest đã bị xóa); `workspace.dir` = `output_dir` → xóa một lần.
- Nguồn local nằm ngoài workspace (CP2 D4) không bao giờ bị xóa: chỉ hai thư mục trên bị `rmtree`, `rmtree` không đi theo symlink. `<workspace.dir>/.web_secret` giữ nguyên.
- Kiểm "không có job" + xóa nằm trong lock gửi URL / ghi review (W4) → 409 khi có job đang chạy/đợi. Xóa xong: job cũ của tập bị quên trong bộ nhớ (`JobRunner.forget`) → `GET /api/episodes/{id}` 404, tập biến mất khỏi danh sách. Gửi lại URL = chạy lại từ đầu.
- UI: nút "Xóa tập này" (ẩn khi không có manifest, tắt khi có job) → `confirm` ghi tên tập + id + "KHÔNG khôi phục được" → về `/`.
- **Sửa đổi CP8.7 — bia mộ (bổ sung HUMAN LEAD 2026-09-27):** `delete_episode` (mọi đường: trang tập, nút "Làm" tab Bộ nhớ) trước khi xóa ghi `<workspace.dir>/_deleted/<episode_id>.json` (atomic; tên bắt đầu `_` không là episode id) khi workspace có manifest: `{"schema_version": 1, "episode_id", "title" (metadata), "source_url" (YouTube: `https://youtu.be/<id>`), "deleted_at", "shorts" (Short rendered, không tính đã xóa), "published" (đã tick đúng file hiện tại), "complete" (Xong L4 lúc xóa), "header": {"series", "episode"}}`. Không tự xóa. Bị bỏ qua khi có workspace cùng id (tập được xử lý lại; file bia mộ giữ nguyên, workspace thắng). Tập lẻ đã xóa (không thuộc bộ kinh đã lưu, không có workspace): mục thu gọn "Đã xóa (n)" trên trang chủ (title, id, Xong / chưa xong, Short, đã đăng, lúc xóa) + "Xóa khỏi lịch sử" (`DELETE /api/deleted/{id}` → chỉ xóa bia mộ; `GET /api/deleted` → `{episodes: [bia mộ]}`). Tập archived vẫn có workspace nên không bị ảnh hưởng.

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
- **Sửa đổi CP8.7 — tải về = đã đăng (bổ sung HUMAN LEAD 2026-09-27):** `GET /files/{id}/{clip}.mp4?download=1` (nút "Tải về") tick Short đó với `sha256` của file trong `render_manifest.json` (file được phục vụ, R9 đã kiểm) **trước khi** gửi file; ~~`shorts.zip` ("Tải tất cả") tick mọi Short trong zip~~ — **sửa đổi CP8.17 D3: zip (`shorts.zip`, `all.zip`) không tick nữa**, chỉ nút "Tải về" từng Short tick (tick có sẵn, kể cả do zip trước đây, giữ nguyên; "Xong" / gợi ý dọn `all_published` cần tick từng Short hoặc tick tay); một lần ghi atomic (`mark_downloaded`). Idempotent: Short đã tick đúng file → không đổi (giữ `at`; tải tiếp bằng `Range` không ảnh hưởng); file khác (render lại) → tick lại với `sha256` mới. Phát video (không `download=1`) không bao giờ tick. Bỏ tick vẫn được, chỉ tải lại mới tick lại. Tập archived vẫn tick. Lỗi ghi `publish.json` chỉ log, không chặn tải. Tick tay cùng file cũng idempotent (không đổi `at`). UI làm mới trang tập 1,5–2 s sau khi bấm "Tải về" một Short (không làm mới sau khi bấm zip, CP8.17 D3).
- Danh sách tập (**bổ sung HUMAN LEAD 2026-09-27**): `publish_group` — **sửa đổi CP8.7:** `done` ("Xong — đã đăng hết") = tập "Xong" (W10 L4) và không có job đang chạy/đợi; còn lại `todo` ("Còn Short chưa đăng") khi có Short `rendered` hoặc còn việc đang chờ (job `queued`/`running`, pipeline chưa xong: còn stage không `done`, gồm lỗi / bị ngắt), không thì `null` (chỉ ở "Tất cả"). (CP8.5 cũ: `done` khi x = y, kể cả bản cũ.)

## W9. Bộ nhớ + dọn video nguồn (sửa đổi CP8.6, HUMAN LEAD 2026-09-27)

Quyết định: `docs/tasks/CP8.6-storage.md` S1–S4, P1 (7 ngày), P2 (10 GB / 3 GB). Code: `auto_short.web.storage` (đo, gợi ý, ngưỡng; stdlib), `auto_short.review.archive` (dọn nguồn, cờ archived). Không có gì bị xóa tự động.

### Tab Bộ nhớ (S1)

- `/storage` (link "Bộ nhớ" trên thanh trên mọi trang). Ổ: `shutil.disk_usage` của ổ chứa `workspace.dir`, thêm `output_dir` nếu khác ổ (`st_dev`).
- Mỗi episode có manifest: `source` = tổng `work/<id>/source.*` (lstat), `other` = phần còn lại của `work/<id>/`, `shorts_bytes` = cả `output/<id>/`, `total`; đã đăng / tổng Short `rendered` (W8); trạng thái `processing` (job đang chạy/đợi hoặc stage `running`) > `archived` > `done` (6 stage `done`) > `failed` > `incomplete`. Thư mục `output/<id>` không có workspace → dòng `orphan`. Sắp theo `total` giảm dần.
- Kích thước = tổng `st_size` file thường (`os.scandir`, không theo symlink, không tính thư mục; không gọi `du`). Cache: `GET /api/storage` tính lại tối đa 30 s một lần (theo tập job đang chạy), bị xóa sau khi dọn / xóa tập qua web.
- "Cache khác": thư mục `[transcript.whisper] models_dir` (model Whisper). **Sửa CP8.7:** hiển thị đường dẫn tuyệt đối — đường dẫn tương đối tính theo thư mục làm việc của server, **đúng như stage transcript** dùng (`download_root`), kèm `exists`; thư mục không có → UI ghi "chưa có thư mục" và gợi ý đặt `models_dir` tuyệt đối. (Server chạy từ worktree khác với thư mục chứa `models/` sẽ thấy 0 byte / không có — cấu hình, không phải lỗi đo.)

### Gợi ý (S2)

Mỗi tập tối đa một gợi ý, luật đầu tiên khớp; bỏ qua tập `processing` / `orphan`; mỗi hành động ghi số byte giải phóng; nút "Làm" hỏi xác nhận rồi gọi `POST …/archive` hoặc `DELETE /api/episodes/{id}` (W8).

1. `all_published`: **sửa CP8.7:** tập "Xong" (W10 L4: render `done`, mọi Short `rendered` đã tick đúng file hiện tại; không còn Short nào cũng tính) → "Dọn video nguồn" (`source`, chỉ khi dọn được: `done`, nguồn YouTube, còn file) + "Xóa cả tập" (`total`). (CP8.6 cũ: mọi Short đã tick, kể cả bản cũ, và có ≥ 1 Short.)
2. `old_source`: dọn được và `render.finished_at` cũ hơn 7 ngày → "Dọn video nguồn".
3. `stale_unfinished`: `failed` / `incomplete` và lần hoạt động cuối (max `started_at` / `finished_at` các stage; không có → mtime manifest) cũ hơn 7 ngày → "Xóa cả tập".

"Bây giờ" lấy từ `clock` của app (tiêm được trong test).

### Dọn video nguồn, episode archived (S3)

- `archive_source(id, config)`: chỉ nguồn `youtube` (`source.kind`) có stage `render` `done`, không thì `ReviewError` (422, không xóa gì). Ghi cờ `work/<id>/archive.json` trước (atomic: `{"schema_version": 1, "episode_id", "archived_at": "<UTC ISO>", "removed": [{"path": "source.mp4", "size": 678949583}]}`), rồi xóa `work/<id>/source.*` (file / symlink ngay trong thư mục tập, không theo symlink). Nguồn local nằm ngoài workspace không bao giờ bị xóa. Đã archived → không làm gì (`changed: false`). `manifest.json` không đổi (stage vẫn `done`).
- **Cờ archived = sự tồn tại của `archive.json`** (quyết định khi implement; tách khỏi `publish.json` vì là trạng thái pipeline, không phải lựa chọn người dùng). File hỏng vẫn tính là archived.
- Episode archived: vẫn xem / tải / zip / tick "Đã đăng" / xóa Short / xóa tập. Không được: sửa title (`set`, `alternative`, `reset`), khôi phục Short, gửi lại URL → 409 `{"detail": "tập <id>: đã dọn video nguồn; muốn sửa thì xóa tập rồi chạy lại"}`; ngoài web: `ingest` và `render` từ chối trước khi đụng manifest (CP2 D4, CP7 R10), hàm `review` raise `ArchivedError` (CP8.2).
- Xóa Short trên tập archived (không render được): `reject_archived_clip` ghi `review.json` `rejected` (CP8.2 T7) rồi áp thẳng vào render cuối: entry → `skipped` / `rejected` (các field như CP7 R11), cập nhật `stats`, ghi `render_manifest.json` atomic, xóa mp4, bỏ path khỏi `artifacts` của stage `render`. Trả 200 `{changed, job: null}` (không job). Không khôi phục được.
- UI: ghi chú "Đã dọn video nguồn …" trên trang tập; ẩn bộ sửa title, nút khôi phục và "Chạy tiếp / chạy lại"; hộp xác nhận xóa Short nói không khôi phục được; danh sách tập ghi "đã dọn video nguồn".

### Cảnh báo ổ đầy (S4)

- `warn` khi một ổ còn < 10 GB **hoặc** < 10 % trống → banner đỏ trên mọi trang (gọi `GET /api/storage/status` khi mở trang) kèm link tab Bộ nhớ.
- `block` khi ổ trống ít nhất < 3 GB → `POST /api/episodes` trả 507 "Ổ đĩa server còn dưới 3 GB trống: không nhận video mới. Dọn bớt ở tab Bộ nhớ rồi thử lại." trước preflight (áp cho mọi lần gửi URL cần job mới, kể cả gửi lại tập cũ; gửi trùng khi đã có job vẫn trả 200 job đó). Ngưỡng là hằng trong code (P2), không phải config.

## W10. Bộ kinh (playlist) + "Xong" (sửa đổi CP8.7, HUMAN LEAD 2026-09-27)

Quyết định: `docs/tasks/CP8.7-playlist.md` L1–L5, P1–P4. Code: `auto_short.web.playlists` (liệt kê, lưu, trạng thái), `auto_short.web.urls.classify_url` (L2), `auto_short.review.publish.episode_complete` / `mark_downloaded`. Phần "batch" của CP9 kéo lên ở mức này: người dùng bấm từng tập, không tự xử lý cả playlist.

### Lưu bộ kinh (L1)

- `<workspace.dir>/_playlists/<playlist_id>.json` (tên bắt đầu `_` không bao giờ là episode id, CP2 D3; `iter_manifests` / xóa tập không đụng), ghi atomic, thứ tự key cố định:

```json
{"schema_version": 1, "playlist_id": "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp", "title": "Thập Thiện Nghiệp Đạo Kinh [trọn bộ 149 tập] - PS Tịnh Không",
 "url": "https://www.youtube.com/playlist?list=PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp", "fetched_at": "2026-09-27T10:48:48Z",
 "entries": [{"index": 1, "video_id": "TjltCyW244Y", "title": "Thập Thiện Nghiệp Đạo Kinh tập 1/149 - Pháp Sư Tịnh Không",
              "duration": 1770.0, "episode": "1", "available": true}]}
```

- Liệt kê: `yt-dlp` `extract_flat: "in_playlist"`, `skip_download` (không tải video, không tạo `work/<id>`), `socket_timeout` 30 s, `js_runtimes` như ingest; chạy trong request, trong luồng phụ, chờ tối đa 60 s (L5) → quá hạn / lỗi → 502 message tiếng Việt, không ghi file. `index` = `playlist_index` hoặc thứ tự (1-based); `episode` = nhóm `episode` của pattern đầu tiên khớp trong CP6 `[titling.header] title_patterns` trên title (G2; vd "tập 1/149" → `"1"`, CP8.11: `Tập 11/128: Giảng "…"` → `"11"`; áp khi liệt kê / "Cập nhật danh sách", file đã lưu không tự ghi lại); `available` = false khi id không phải 11 ký tự, title `[Private video]` / `[Deleted video]` / `[Unavailable video]` hoặc `availability` private / cần đăng nhập. Playlist trống → 502, không lưu.
- CP8.8 (H1, H5): trường tùy chọn `"hashtags": ["ThậpThiện", "TịnhĐộTông"]` sau `entries` — danh sách riêng đã chuẩn hóa, không `#`, đúng thứ tự; không có trường (hoặc không phải danh sách chuỗi) = mặc định; `schema_version` giữ 1. Ghi atomic dưới lock của store. "Cập nhật danh sách" giữ trường này (đọc lại dưới lock ngay trước khi ghi); "Xóa bộ kinh" xóa luôn.
- CP8.11 (D5): trường tùy chọn `"series": "Thái Thượng Cảm Ứng Thiên"` sau `hashtags` (thứ tự key cố định `…, entries, hashtags, series`) — "Tên bộ kinh" do người dùng đặt, chuẩn hóa NFC + gộp khoảng trắng, 1–100 ký tự; không có trường / không phải chuỗi / rỗng / quá dài = chưa đặt; `schema_version` giữ 1. Ghi atomic dưới lock của store; "Cập nhật danh sách" giữ trường (như `hashtags`); "Xóa bộ kinh" xóa luôn. Nguồn header dự phòng của titling khi không pattern nào khớp tiêu đề video — canonical: `docs/decisions/CP6-titling-contract.md` G2 (Sửa đổi CP8.11).
- Thêm playlist đã lưu → trả bản đã lưu (`created: false`, không liệt kê lại). "Cập nhật danh sách" liệt kê lại và **thay** `entries` + `fetched_at` (thứ tự theo YouTube), trả `added` (video id mới). "Xóa bộ kinh" chỉ xóa file này; tập đã xử lý giữ nguyên (về mục "Tập lẻ").
- Trạng thái xử lý **không** lưu ở đây: đọc từ `work/<video_id>/manifest.json`, `render_manifest.json`, `publish.json`, `archive.json` (cache ≤ 5 s mỗi tập, xóa khi tick / tải / xóa tập / gửi URL qua web) + job runner (không cache).

### Trạng thái tập trong bộ kinh

`state`: `new` (chưa có workspace, không bia mộ) · `deleted` (không có workspace, có bia mộ `_deleted/<id>.json`: "✔ Xong (đã xóa dữ liệu)" khi `complete`, không thì "Đã xóa dữ liệu (chưa xong)"; `shorts` / `published` / `complete` / `deleted_at` từ bia mộ; nhóm `done` khi `complete`, không thì `todo`) · `queued` / `processing` (job đang đợi / chạy, `stage` = stage hiện tại; hoặc stage `running` trong manifest) · `failed` (stage `failed` trong manifest, hoặc job cuối `failed` / `interrupted` — `error` = message của job / stage, vd lỗi YouTube 403) · `rendered` (render `done`, chưa Xong) · `incomplete` (dở dang, không job) · `complete` ("Xong") · `unavailable`. Kèm `shorts`, `published` (đã tick, tính cả bản cũ), `archived`. Nhóm lọc (`group`; sửa đổi CP8.13 G1, HUMAN LEAD 2026-09-28): `todo` = Chưa xử lý (`new`; `deleted` chưa Xong), `running` = Đang xử lý (`queued`, `processing`), `failed` = Lỗi / dở dang (`failed`, `incomplete`), `doing` = Đang làm (chỉ `rendered`: đã render, chưa đăng hết), `done` = Xong (`complete`; `deleted` đã Xong); `unavailable` chỉ ở "Tất cả". `counts` và tóm tắt bộ kinh dùng cùng bảng nhóm (`GROUPS` trong `src/auto_short/web/playlists.py`).

### Xử lý tập (L3)

Mỗi tập có `action`: `process` ("Xử lý", `new`), `resume` ("Chạy tiếp", `failed`, `incomplete`), `reprocess` ("Xử lý lại", `deleted`: hộp xác nhận — tải lại video, chạy lại từ đầu, AI có thể chọn khác), `null`. Tóm tắt bộ kinh thêm `deleted` (số tập đã xóa dữ liệu; vẫn tính vào `processed`, `complete` khi Xong). Nút = `POST /api/episodes {url: "https://youtu.be/<video_id>", mode: "video"}`: đúng luồng tập lẻ (W4: preflight Ollama, không job trùng, 409 archived, 507 ổ < 3 GB), header lấy từ title video (CP6). Bấm nhiều tập → xếp hàng FIFO (W5). Tập đã xử lý xong → pipeline skip từng stage (CP8 E3).

**Sửa đổi CP8.9 (HUMAN LEAD 2026-09-28, A1.2, A1.4):** tập có khai thị `work/<video_id>.kt/` → trạng thái dòng tập gộp Short + khai thị, "Xong" cần cả hai Xong, "Chạy tiếp" gửi `kinds` của phần chưa xong, "Xử lý" / "Xử lý lại" tạo cả hai. Canonical: `docs/decisions/CP8.9-khai-thi-contract.md` K8.

### "Xong" (L4, suy ra, không lưu)

Tập **Xong** ⇔ stage `render` `done` **và** mọi Short `rendered` trong `render_manifest.json` (Short đã xóa là `skipped`, không tính) có tick với cùng `(clip_id, candidate_id)` **và** `sha256` = file hiện tại (Short "đã đăng bản cũ" chưa tính). Không còn Short `rendered` (xóa hết) → Xong. Bỏ tick / sửa title (render lại) → hết Xong. Không có nút tick Xong riêng. Áp cho tập trong bộ kinh và tập lẻ (`complete` ở trang tập + danh sách, bộ lọc W8, gợi ý dọn W9 mục 1).

### UI

- Trang chủ: form nhận link video hoặc playlist; link `watch?v&list` → hộp hỏi "Chỉ tập này (tập lẻ)" / "Cả bộ kinh (playlist)"; mục "Bộ kinh" (tên, số tập, đã xử lý x, Xong y, rồi "đang xử lý a · lỗi / dở dang b · đang làm c" — CP8.13 G3, mục = 0 bỏ); mục "Tập lẻ" = tập không nằm trong bộ kinh đã lưu nào (tập của bộ kinh chỉ hiện ở trang bộ kinh). Tập Xong ghi "Xong ·".
- `/playlists/<pid>`: tên, số tập, lúc lấy danh sách, link YouTube; "Cập nhật danh sách", "Xóa bộ kinh" (xác nhận: không xóa tập đã xử lý); bộ lọc Tất cả / Chưa xử lý / Đang xử lý / Lỗi / dở dang / Đang làm / Xong (đếm, theo `group` của server; mặc định "Đang làm", lựa chọn lưu ở trình duyệt `autoShort.plFilter`; tab "Đang xử lý" / "Lỗi / dở dang" rỗng có dòng "Không có tập nào …" — CP8.13 G2); mỗi tập theo thứ tự playlist: số thứ tự, title (link trang tập khi đã có), "tập N", thời lượng, trạng thái (+ stage / lỗi / số Short, đã đăng a/n, đã dọn nguồn), nút "Xử lý" / "Chạy tiếp". Poll 5 s khi có tập đang đợi / chạy.
- **Sửa đổi CP8.12 A1 (HUMAN LEAD 2026-09-28):** trang bộ kinh thêm bộ lọc "Đang xử lý" (tập có job Short hoặc khai thị đang đợi / chạy) — chi tiết: `docs/tasks/CP8.12-episode-ui.md` Sửa đổi A1. **Sửa đổi CP8.13 (HUMAN LEAD 2026-09-28):** tab này dùng nhóm server `running` (không còn lọc phía client); thêm tab "Lỗi / dở dang"; dòng tập không còn link "Khai thị" (vào trang khai thị qua thanh [Shorts | Khai thị] của trang tập) — chi tiết: `docs/tasks/CP8.13-playlist-groups-loop.md` G1–G4.
- CP8.11 (D7): khung thu gọn "Tên bộ kinh (tự nhận từ tiêu đề | đã đặt)" trên trang bộ kinh — ô nhập (placeholder = `series_suggested`), "Lưu", "Bỏ tên" (xác nhận); dòng giải thích "Chỉ dùng cho tập mà tiêu đề video không nhận ra tên bộ kinh / số tập (hiện: n tập). Đổi tên sau khi tập đã xử lý → lần chạy sau tạo lại tiêu đề AI của tập đó." (n = `unrecognized`); tự mở khi có tập không nhận dạng và chưa đặt tên. Poll trang không ghi đè ô đang sửa; ≤ 640 px: nút rộng hết, ≥ 40 px.
- Trang tập: "✔ Xong (đã đăng hết)" trong dòng thông tin.

## Config `[web]`

| Key | Mặc định | Ghi chú |
|---|---|---|
| `host` | `"0.0.0.0"` | `"127.0.0.1"` = chỉ máy này |
| `port` | `8080` | 1–65535 |
| `session_days` | `30` | 1–365, tuổi cookie đăng nhập |
| `hashtags` | `["TịnhKhông", "LờiPhậtDạy", "TịnhĐộ", "NiệmPhật"]` | CP8.7: hashtag sau `#<series>` khi Copy title (W6); bộ kinh có danh sách riêng (CP8.8) không dùng |
| `queue_mode` | `"lanes"` | CP8.10: `"lanes"` (làn prepare / ai / render, W5) \| `"serial"` (một job chạy trọn tại một thời điểm); giá trị khác → lỗi load config |

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

CP8.7 (2026-09-27, bản sao scratch hardlink của `tHtxw6ykUmM`, playlist thật `PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp`, server worktree `127.0.0.1:8081`, curl):

| Bước | Kết quả |
|---|---|
| gửi `https://www.youtube.com/playlist?list=PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp&si=abc` | 201 trong 1,98 s: "Thập Thiện Nghiệp Đạo Kinh [trọn bộ 149 tập] - PS Tịnh Không", 149 tập; thứ tự 1…149, `episode` = số thứ tự cho cả 149, 149 thời lượng (tổng 79,8 h); không thư mục `work/<id>` mới (chỉ `_playlists/`); 149 `new` |
| `tHtxw6ykUmM` có trong playlist? | không (tập 29 của playlist là `nOvMD6aQSt8`, bản 29 phút khác) → AC2 dùng một bộ kinh giả trong scratch (`_playlists/PLscratchFake29test.json`: `tHtxw6ykUmM` + 2 tập thật) |
| bộ kinh giả | `tHtxw6ykUmM` `rendered`, 20 Short, đã đăng 0/20; 2 tập `new` |
| "Xử lý" `tHtxw6ykUmM` | 202 trong 0,04 s; lúc chạy `processing` (stage `preflight`); job pipeline `20/20 Shorts`, 6 stage bỏ qua (dưới 1 s) |
| phát `k01` / tải `k01`–`k03` (`?download=1`) | phát: không tạo `publish.json`; tải: 3 tick với `sha256` file; `Range: bytes=1000000-` + `download=1` → 206, `at` không đổi |
| `shorts.zip` (317 MB, 0,58 s) | 20/20 đã đăng → `complete: true`; bộ kinh giả: `complete`, counts `done` 1; danh sách tập `publish_group` `done`; tab Bộ nhớ gợi ý `all_published` (dọn 678 949 583 B / xóa 999 329 250 B) |
| bỏ tick `k05` / tick lại | `complete` false (19/20) / true |
| restart server | vẫn `complete: true` |
| sửa title `k02` | job 26,7 s (1 encoded); `k02` `published_stale`, `complete: false`, bộ kinh `rendered` 20/20 |
| tải lại `k02` | tick lại `sha256` mới → `complete: true` |
| "Cập nhật danh sách" (không đổi / sau khi cắt 2 tập cuối khỏi file lưu) | 200 trong 1,85 s `added: []` / `added: ["zbvUXm-ekYY", "Kkzcr0m_gDs"]`, 149 tập đúng thứ tự (148, 149 ở cuối) |
| `playlist?list=WL` / `LL` / `RDnOvMD6aQSt8` | 422 `không nhận danh sách Mix / Xem sau / Đã thích …` |
| `watch?v=nOvMD6aQSt8&list=PLOy…&index=29` / + `mode: "playlist"` | 200 `{kind: "ask", …}` / 200 `created: false` (đã lưu) |
| "Xóa bộ kinh" giả | 200; `tHtxw6ykUmM` còn nguyên, `in_playlist: false` (về Tập lẻ) |

CP8.6 (2026-09-27, bản sao scratch hardlink của `tHtxw6ykUmM` (tập 29) + `rbjfCfFq3Dk` + 2 workspace giả, server worktree `127.0.0.1:8081`, curl):

| Bước | Kết quả |
|---|---|
| `GET /api/storage` | 200 trong 0,008 s (lần hai trong 30 s: 0,001 s, cache); ổ 105,1 GB / dùng 32,7 GB / trống 67,0 GB = `shutil.disk_usage`; không cảnh báo |
| so với `du -sb` (`work/<id>` + `output/<id>`) | `tHtxw6ykUmM` 999 325 412 B (nguồn 678 949 583, Short 317 230 528, khác 3 145 301) = `du`; `rbjfCfFq3Dk` 885 861 835 = `du`; tập giả lỗi 5 000 399 = `du` (lệch 0 %); model Whisper 1 621 667 291 B, `du` 1 621 667 654 (lệch < 0,001 %) |
| gợi ý | tập giả `failed` từ 2026-09-10 → `stale_unfinished` (17 ngày, Xóa cả tập 5,0 MB); tick 20/20 Short tập 29 → (sau khi hết cache 30 s) `all_published`: Dọn video nguồn 678 949 583 B + Xóa cả tập 999 329 250 B |
| `POST /api/episodes/tHtxw6ykUmM/archive` | 200 trong 0,003 s, `freed` 678 949 583 B (≈ 648 MiB), `removed: ["source.mp4"]`; lần hai `changed: false`; 20/20 mp4 sha256 không đổi; tải 20 Short: sha256 = manifest; zip 20 entry |
| trên tập archived: sửa title / alternative / reset / khôi phục / gửi lại URL | 409 `tập tHtxw6ykUmM: đã dọn video nguồn; muốn sửa thì xóa tập rồi chạy lại`; không job |
| trên tập archived: bỏ tick, xóa Short `k20` | 200; xóa Short: `{changed: true, job: null}`, `k20` `skipped`/`rejected`, còn 19 mp4; bảng: `archived`, nguồn 0, 19/19 đã đăng → gợi ý chỉ còn "Xóa cả tập" |
| `archive` tập giả nguồn local (`input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4`) / `nope` / `..%2Fwork` / không cookie | 422 `nguồn là file local …` (file nguồn sha256 không đổi) / 404 / 404 / 401 |
| "Làm" gợi ý 3 (`DELETE` tập giả) | 200 |

Dung lượng trống của ổ thật không tăng trong lần thử vì `source.mp4` bản sao là hardlink của bản trong thư mục chính (bản chính giữ nguyên); `freed` là kích thước file đã xóa.

## Giới hạn đã biết

- HTTP không mã hóa: mật khẩu và cookie đi dạng rõ trong LAN (HTTPS ngoài scope).
- Không giới hạn số lần đăng nhập sai ngoài độ trễ 1 s mỗi lần.
- Job và log chỉ trong bộ nhớ; log không gồm output của ffmpeg / yt-dlp.
- CP8.10: mỗi làn một job tại một thời điểm; job dài ở một làn (selection ~8 phút) vẫn chặn làn đó cho episode khác (không có 2 job GPU song song). Hàng đợi / làn chỉ trong bộ nhớ (restart mất). Analysis / render và Whisper / Ollama của hai tập khác nhau có thể tranh CPU / GPU khi chạy chồng (số đo: `docs/tasks/CP8.10-queue-lanes.md` Result). Không có làn cho CLI `run` (vẫn tuần tự, CP8).
- Danh sách episode đọc lại toàn bộ manifest mỗi lần gọi (đủ cho vài chục episode).
- Sửa title một Short phải đợi job của episode xong (409), kể cả job render của Short khác; không có hàng đợi nhiều lần sửa.
- `titles.json` / `review.json` / `clips.json` được đọc lại mỗi lần poll trang episode (`list_titles`, vài chục KB).
- Ghi `review.json` đồng thời từ CLI `auto-short title` và web không có khóa chung (CP8.2 § Quyết định khi implement): lần ghi sau thắng.
- UI chưa được kiểm trên trình duyệt thật trong môi trường agent (không có browser); manual test HUMAN LEAD là gate.
- CP8.5: tên có dấu dựa vào `filename*` (RFC 5987) và thuộc tính `download`; chưa kiểm trên điện thoại thật trong môi trường agent (manual test HUMAN LEAD). Công cụ chỉ hiểu `filename=` (vd `curl -OJ`) lưu tên ASCII không dấu.
- CP8.5: xóa tập là `rmtree` đồng bộ trong request, không thùng rác; thời gian trên dữ liệu thật chưa đo (bản thử scratch dùng hardlink: 0,01 s cho tập 29 ~950 MB).
- CP8.5: `publish.json` ghi từ nhiều request được tuần tự hóa bằng một lock trong server; CLI không ghi file này.
- CP8.6: kích thước là dung lượng biểu kiến (`st_size`), file hardlink được tính ở mọi nơi nó xuất hiện; `freed` có thể lớn hơn dung lượng trống tăng thêm thật (hardlink, file thưa).
- CP8.6: tab Bộ nhớ cache 30 s theo server; thay đổi ngoài web (CLI) hiện sau tối đa 30 s. Quét cả `work/` + `output/` + `models/` mỗi lần tính (vài ms cho vài tập; chưa đo với vài trăm tập).
- CP8.6: chưa có CLI cho dọn nguồn; `auto-short run`/`ingest`/`render` trên tập archived báo lỗi, muốn chạy lại phải xóa workspace.
- CP8.7: liệt kê playlist gọi YouTube trong request (≈ 2 s cho 149 tập); luồng phụ quá 60 s bị bỏ (chạy nốt nền, không ghi). Không có CLI cho bộ kinh. Một tập nằm trong nhiều bộ kinh hiện ở mọi bộ kinh đó.
- CP8.7: tick khi tải về dựa trên yêu cầu tới server, không biết trình duyệt có lưu xong file hay không (tải hỏng vẫn tính đã tải); bấm "Tải về" rồi hủy cũng tick.
- CP8.7: bia mộ không tự xóa (vài trăm byte / tập); "Xử lý lại" không xóa bia mộ cũ (bị bỏ qua khi có workspace). Ngưỡng cảnh báo ổ (W9) tính theo 10⁹ byte còn hiển thị theo 1024 (10 GB ≈ 9,3 GB trên UI).
- CP8.7: trạng thái `failed` từ job chỉ còn trong bộ nhớ (restart server → trạng thái đọc lại từ manifest).
