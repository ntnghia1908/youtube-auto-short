# CP8.3 — Web MVP Contract

| Metadata | Value |
|---|---|
| Status | PROPOSED |
| Accepted by | — (W1–W7, P1–P4 duyệt cùng APPROVE TASK 2026-09-27; chờ review) |
| Checkpoint | CP8.3 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8.3 |
| Task contract | `docs/tasks/CP8.3-web.md` |
| Builds on | `docs/decisions/CP8-pipeline-contract.md` (run, preflight, resume); `docs/decisions/CP7-render-contract.md` (`render_manifest.json`); `docs/decisions/CP2-workspace-contract.md` (manifest, stage status); CP1 §10 (dependency) |

File này là **canonical owner** của web boundary: lệnh `auto-short web`, config `[web]`, auth (mật khẩu + cookie phiên), input URL từ web, job model, API JSON, route phục vụ file và UI. Nơi khác chỉ trỏ tới đây. Web không đổi contract stage CP2–CP8: pipeline chạy qua `run_pipeline` / `ollama_preflight` (CP8 E7, E8). Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/web/` (`app.py` app factory + route, `auth.py`, `urls.py`, `jobs.py`, `episodes.py`, `server.py`, `static/`), `src/auto_short/cli.py` (`web`), `src/auto_short/config.py` (`WebConfig`).

**Phase:** phase A (mọi mục dưới đây trừ sửa title) đã implement. Sửa title một Short (W4 phần title, W6 ô sửa title, W7 hai endpoint `…/title`, `…/title/preview`) ghép ở phase B sau khi CP8.2 (`review`, render cache từng Short) READY; chỗ cắm đã chừa sẵn (W5 job `render`, W6 `.title-edit`, W7 `title.source`).

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

## W5. Job model

- Một worker thread, hàng đợi FIFO trong bộ nhớ; tại một thời điểm chỉ một job chạy. Job: `id` (số tăng dần trong phiên server), `episode_id`, `kind` (`pipeline`; phase B thêm `render`), `status` (`queued`, `running`, `done`, `failed`, `interrupted`), `created_at` / `started_at` / `finished_at` (UTC ISO), `stage`, `stages` [{`stage`, `ran`, `seconds`}], `error`, `summary`, `logs`.
- Một episode chỉ có tối đa một job `queued`/`running`; gửi trùng trả job đang có.
- Log: mọi record của logger `auto_short` phát ra trên worker thread khi job chạy (level ≥ INFO) được chép vào vòng đệm 200 dòng cuối của job, dạng `HH:MM:SS [LEVEL ]message`; server vẫn log ra stderr như CLI. Không gồm stderr của tiến trình con (ffmpeg, yt-dlp).
- Lịch sử job chỉ trong bộ nhớ: restart server mất hàng đợi và log (manifest còn; gửi lại URL → resume).
- Tắt server (Ctrl-C / SIGINT / SIGTERM qua uvicorn) khi job đang chạy: worker nhận `KeyboardInterrupt` (inject vào thread) + tiến trình con trực tiếp nhận SIGINT; chờ tối đa 30 s. Stage đang chạy ghi `failed` + `error: "interrupted"` (CP2 `run_stage`), job `interrupted`. Nếu stage đang kẹt trong một lời gọi dài không trả về trong 30 s (vd request Ollama) thì server thoát, manifest giữ `running` — CP8 E3 coi là chưa up to date, gửi lại URL sẽ chạy lại stage đó.

## W6. UI

- HTML + CSS + JS thuần trong `src/auto_short/web/static/` (package data; không build step, không framework frontend), tiếng Việt, responsive (lưới Short 2 cột trên điện thoại).
- `/` : form URL (+ tuỳ chọn series / tập), lỗi (422 / 503) hiện ngay dưới form; danh sách episode (tên video, trạng thái: đang chạy stage / lỗi ở stage / N Shorts).
- `/episodes/<id>`: tên, kênh, thời lượng; trạng thái job; 6 stage (`chờ`, `đang chạy`, `xong`, `lỗi` + message, `cần chạy lại`) + thời gian hoặc "bỏ qua (đã có)"; nhật ký (mở sẵn khi đang chạy / lỗi); nút "Chạy tiếp / chạy lại" (gửi lại `source_url`, ẩn khi có job đang chạy); lưới Short; nút "Tải tất cả (.zip)" (P3).
- Mỗi Short: `<video controls preload="metadata" playsinline>` (tua bằng Range), mã clip, nhãn nguồn title (`AI` / `sửa tay` / `phương án khác`), thời lượng, title, nút "Tải về". Chỗ `<div class="title-edit">` (ẩn) dành cho phase B (sửa title). Lưới chỉ dựng lại khi danh sách / sha256 / title đổi (poll không làm dừng video đang xem).

## W7. API và file

Mọi route cần cookie (W2). JSON UTF-8.

| Route | Kết quả |
|---|---|
| `POST /api/episodes` `{url, series?, episode?}` | 202 `{created: true, episode_id, job}`; 200 `{created: false, episode_id, job}` (đã có job đang chạy/đợi); 422 `{detail}` (URL / field sai); 503 `{detail: "ollama preflight: …"}` |
| `GET /api/episodes` | `{episodes: [{id, title, stages_done, stages_total, running, failed, shorts, job}]}` — mọi workspace có manifest (mới nhất trước) + job đang đợi chưa có workspace; `job` không kèm `logs` |
| `GET /api/episodes/{id}` | `{id, title, channel, duration, source_url, stages: [{stage, status, started_at, finished_at, error}], header, shorts, rendered, zip_url, job}`; 404 khi không có manifest và không có job |
| `GET /files/{id}/{clip}.mp4` | `video/mp4`, hỗ trợ `Range` (206 + `Content-Range`), `Cache-Control: private, no-cache` |
| `GET /files/{id}/{clip}.mp4?download=1` | như trên + `Content-Disposition: attachment; filename="<id>_<clip>.mp4"` |
| `GET /files/{id}/shorts.zip` | zip stream (`ZIP_STORED`, không nén) mọi Short `rendered` theo thứ tự manifest, tên `<id>_<clip>.mp4`; `Content-Disposition: attachment; filename="<id>_shorts.zip"`; 404 khi chưa có Short |

- `job` = các field W5 + `queue_position` (vị trí trong hàng, `null` khi không đợi).
- `shorts[]` = `{clip_id, status (rendered | skipped), skip_reason, duration, source_start, source_end, title: {text, source, display_lines}, sha256, video_url, download_url}`; `video_url` = `/files/<id>/<clip>.mp4?v=<sha256[:12]>` (đổi khi file đổi), `null` khi Short bị bỏ qua. Phase A: `title.source = "ai"` (title lấy từ `titles.json`, CP7 R2); phase B lấy từ CP8.2 (`ai | manual | alternative`) và thêm field sửa title.
- `shorts` chỉ có khi stage `render` = `done` (render đang chạy ghi đè manifest và file) — file cũng 404 lúc đó.
- Phase B (sau CP8.2): `POST /api/episodes/{id}/shorts/{clip}/title` `{set | alternative | reset}` và `POST …/title/preview` — field chốt khi ghép.

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

## Giới hạn đã biết

- HTTP không mã hóa: mật khẩu và cookie đi dạng rõ trong LAN (HTTPS ngoài scope).
- Không giới hạn số lần đăng nhập sai ngoài độ trễ 1 s mỗi lần.
- Job và log chỉ trong bộ nhớ; log không gồm output của ffmpeg / yt-dlp.
- Một job tại một thời điểm; job dài (selection ~8 phút) chặn job khác của episode khác.
- Danh sách episode đọc lại toàn bộ manifest mỗi lần gọi (đủ cho vài chục episode).
