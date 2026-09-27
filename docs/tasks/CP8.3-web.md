# Task: CP8.3 — Web MVP

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `bb5c37c` (`feature/cp8-pipeline` READY, stacked; phần sửa title ghép sau khi CP8.2 READY) / `feature/cp8.3-web`; rebase lên `main` sau khi CP8–CP8.2 merge
- Human Lead approval: accepted (APPROVE TASK, 2026-09-27; W1–W7; P1 trang đăng nhập + cookie 30 ngày; P2 port 8080; P3 có zip; P4 `tHtxw6ykUmM`)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì chạm các gate: **scope** (web chưa có trong CP1; re-plan HUMAN LEAD 2026-09-27), **dependency** (FastAPI + uvicorn — proposal W1), **security model** (server nghe trên LAN, có mật khẩu — W2), **architecture** (tiến trình server chạy job nền). Không đổi contract stage CP2–CP8.2; web chỉ gọi `run_pipeline`/preflight (CP8), `review` + render (CP8.2).

## Goal

Từ trình duyệt trong LAN (máy tính hoặc điện thoại), người dùng đăng nhập bằng mật khẩu, dán URL YouTube, theo dõi tiến độ từng stage, xem và tải từng Short, sửa title một Short và render lại đúng Short đó — không cần CLI.

## Scope

- In scope:
  - Package `src/auto_short/web/` (app FastAPI, job runner, API JSON, trang HTML + JS thuần tĩnh — không build step, không framework frontend).
  - Lệnh `auto-short web [--host H] [--port P] [--config PATH]`; config `[web]`.
  - Tính năng (W4): nhập URL YouTube; danh sách episode; trang episode: tiến độ stage, log tóm tắt, lỗi; lưới Short (xem trực tiếp, tua được; tải về; title hiện tại + nguồn; sửa title: gõ tay / chọn alternative / reset, xem trước dòng hiển thị, lưu & render lại Short đó).
  - Tests (TestClient): auth, validate URL, API episode/short, job runner (stage giả), sửa title → gọi render; phát video có `Range`.
  - Chạy thật: server trên máy này, bind LAN; từ trình duyệt/`curl` gửi video YouTube mới `tHtxw6ykUmM` (P4) chạy hết pipeline; sửa title một Short qua web; tải Short về.
  - Docs: decision record `docs/decisions/CP8.3-web-contract.md` (canonical owner: web boundary, auth, job model, API); CP1 §10 (dependency mới), §2/scope (web); project profile (module map `web/`), README (chạy web), contract Result.
- Out of scope:
  - Upload YouTube / nút share (CP8.4); approve/reject clip, batch playlist (CP9); sửa header, điểm cắt.
  - Nhập **đường dẫn file local** từ web (W3 — đọc file tùy ý trên server là rủi ro bảo mật); CLI vẫn nhận path.
  - HTTPS, nhiều user / phân quyền, truy cập internet public.
  - Chạy nhiều pipeline song song (W5).

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` CP8.3 (re-plan 2026-09-27); `docs/decisions/CP8-pipeline-contract.md` (run, preflight, resume); `docs/decisions/CP8.2-title-override-contract.md` (review, cache Short); `docs/decisions/CP7-render-contract.md` (output); CP1 §10 (dependency policy).
- Dữ kiện: conda env `auto-short` đã có `httpx 0.28.1` (transitive); chưa có `fastapi`, `uvicorn`. PyPI hiện tại: `fastapi 0.141.1`, `uvicorn 0.54.0`. IP LAN máy: `10.8.102.101`.
- Quyết định (DECIDE cùng APPROVE TASK):
  - **W1 Dependency proposal:**

    ```text
    Library: fastapi (pin bản ổn định hiện hành khi cài, kéo theo starlette + pydantic), uvicorn (pin, không extra [standard]); dev: httpx (TestClient; đã có transitive, khai báo explicit ở extra dev)
    Purpose: HTTP server + API JSON + phát file video (Range) + job nền cho web MVP
    Why current stack is insufficient: stdlib http.server không có routing, không hỗ trợ Range (tua video), không phù hợp chạy job nền + request đồng thời; tự viết tốn thời gian và dễ lỗi bảo mật
    Alternative: stdlib http.server (tự viết Range/routing/auth); Flask (+ WSGI server)
    Impact: 2 dependency runtime (+ transitive starlette, pydantic, anyio, h11, click); khai báo ở optional extra `[web]` của pyproject (`pip install -e ".[dev,web]"`), CLI pipeline không phụ thuộc web
    ```

  - **W2 Security (LAN):**
    - Bind mặc định `[web] host = "0.0.0.0"`, `port = 8080`; `--host 127.0.0.1` để chỉ chạy local.
    - Mật khẩu một người dùng từ biến môi trường `AUTO_SHORT_WEB_PASSWORD` (không lưu trong config/repo). Không có biến → server **từ chối khởi động**.
    - Đăng nhập (P1, HUMAN LEAD 2026-09-27: chỉ hỏi mật khẩu 1–2 lần mỗi thiết bị): trang `/login` (một ô mật khẩu) → đúng thì đặt cookie phiên ký HMAC-SHA256 (`HttpOnly`, `SameSite=Lax`, hết hạn **30 ngày**, `[web] session_days`); mọi route khác (HTML, API, file video/tải về) cần cookie hợp lệ — HTML chưa đăng nhập chuyển về `/login`, API/file trả 401. So mật khẩu bằng `hmac.compare_digest`; sai → chờ 1 s (chống dò). Khóa ký: sinh ngẫu nhiên lần đầu, lưu `<workspace.dir>/.web_secret` (quyền 600, gitignored cùng `work/`) để **restart server không bắt đăng nhập lại**; đổi mật khẩu → cookie cũ hết hiệu lực (khóa ký trộn hash mật khẩu). Có nút Đăng xuất.
    - Chỉ phục vụ file nằm trong `output/<episode_id>/shorts/` theo `render_manifest.json` (không nhận path từ client; `episode_id`/`clip_id` validate regex), chống path traversal.
  - **W3 Input:** chỉ URL YouTube video (`youtube.com/watch?v=…`, `youtu.be/…`, `youtube.com/shorts/…`; parse ra video id, từ chối playlist/khác domain). Header titling lấy tự động (`title_pattern`); form có ô tuỳ chọn `series`/`episode` khi title video không khớp pattern.
  - **W4 Luồng xử lý:** Submit → preflight Ollama (CP8 E8) chạy ngay, lỗi trả về form → tạo job → `run_pipeline` trong job runner. Tiến độ: đọc `manifest.json` (status từng stage) + stage hiện tại + log stderr của job (vòng đệm cuối ~200 dòng). Trang poll JSON mỗi 2–3 s. Sửa title → gọi `review.set_title`/`reset_title` (validate T2 trả lỗi ngay) → job render (chỉ Short đổi được encode, CP8.2).
  - **W5 Job model:** một worker thread, hàng đợi FIFO trong bộ nhớ; tại một thời điểm chỉ một job (pipeline hoặc render) chạy — tránh tranh CPU/GPU và ghi đồng thời cùng manifest. Job của episode đang chạy/đợi → không nhận job trùng cho episode đó. Restart server mất hàng đợi (manifest vẫn còn; gửi lại URL → resume, CP8 E3). Tắt server khi job đang chạy → stage `failed interrupted` (CP2), resume sau.
  - **W6 UI:** tiếng Việt, responsive (dùng được trên điện thoại), HTML + CSS + JS thuần trong `web/static/` (package data). Mỗi Short: `<video controls preload="metadata">`, title (+ `ai | manual | alternative`), nút Tải về (`Content-Disposition` tên `<episode>_<clip>.mp4`), sửa title (ô nhập đếm ký tự ≤ 60, dropdown alternatives, xem trước dòng hiển thị qua API validate, nút Lưu & render lại / Khôi phục title AI). Trạng thái "đang render" trên Short đang chờ.
  - **W7 API** (JSON, dưới `/api`): `POST /api/episodes` {url, series?, episode?}; `GET /api/episodes`; `GET /api/episodes/{id}` (stages, job, shorts); `POST /api/episodes/{id}/shorts/{clip}/title` {set | alternative | reset}; `POST …/title/preview` (validate + dòng hiển thị, không ghi); `GET /files/{id}/{clip}.mp4` (Range) và `?download=1`. Chi tiết field chốt trong decision record.
- Đề xuất cần HUMAN LEAD chốt:
  - **P1 Auth — chốt (HUMAN LEAD 2026-09-27):** trang đăng nhập + cookie nhớ 30 ngày (W2); không dùng HTTP Basic (trình duyệt hỏi lại mỗi lần mở).
  - **P2 Port:** 8080 (chốt).
  - **P3 Tải tất cả:** thêm nút "Tải tất cả (.zip)" (zip stdlib, không nén, stream) — **có** (chốt).
  - **P4 Video chạy thật (chốt HUMAN LEAD 2026-09-27):** `https://youtu.be/tHtxw6ykUmM?si=R1TwdI4gh0sPcVHB` (dán nguyên link chia sẻ; W3 bỏ tham số `si`/query khác, lấy video id `tHtxw6ykUmM`).

## Implementation approach

- `web/app.py` (FastAPI app factory nhận config + deps injectable), `web/jobs.py` (queue + worker + log capture qua logging handler gắn theo job), `web/static/{index.html, episode.html, app.js, style.css}`.
- `cli.py`: subcommand `web` import lazy (không cài `[web]` thì báo lỗi rõ ràng, exit 1).
- Tests dùng `fastapi.testclient` + deps giả (không chạy pipeline thật).

## Acceptance Criteria

1. Không đặt `AUTO_SHORT_WEB_PASSWORD` → `auto-short web` exit 1 với message rõ. Có mật khẩu: chưa đăng nhập → HTML chuyển `/login`, API/file 401; sai mật khẩu → không có cookie; đúng → cookie 30 ngày; restart server vẫn còn đăng nhập; cookie giả/sửa → 401.
2. Từ một máy khác trong LAN (hoặc `curl` tới `10.8.102.101:8080`): gửi URL YouTube mới → job chạy hết pipeline → trang episode hiện 6 stage `done` và danh sách Short; preflight lỗi (Ollama tắt/sai host) báo ngay trên form, không tạo job.
3. Video phát và tua được (`Range` → 206); tải về đúng file (sha256 = `render_manifest.json`); (P3) zip chứa đủ Short.
4. Sửa title một Short trên web → xem trước dòng hiển thị → Lưu & render lại → chỉ Short đó encode lại (log `reuse` các Short khác), trang cập nhật title + video mới; title không hợp lệ → báo lỗi, không ghi. Khôi phục title AI hoạt động.
5. URL không hợp lệ / playlist / domain khác → 422, không job; `episode_id`/`clip_id` lạ hoặc path traversal → 404/422.
6. Gửi lại URL của episode đang chạy → không tạo job trùng; gửi URL episode đã xong → pipeline skip hết (CP8), xong trong vài giây.
7. Mọi test hiện có PASS + test web mới PASS; `node scripts/framework-check.mjs` PASS; docs cập nhật.

## Required verification

- `pytest -q` — AC1 (phần auth), AC3–AC7 (test).
- Chạy thật `AUTO_SHORT_WEB_PASSWORD=… auto-short web` + `curl` qua IP LAN: 401, submit URL mới, poll tới xong, `Range` 206, tải + so sha256, sửa title qua API + đo — AC1–AC6.
- HUMAN LEAD mở web từ máy/điện thoại khác trong LAN (manual) — AC2, AC4.
- `node scripts/framework-check.mjs` — AC7.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

**Chạm security model** (server mở trên LAN, auth mật khẩu) → manual test là **gate** trước integration.

- [ ] Mở `http://10.8.102.101:8080` từ máy/điện thoại khác: hiện trang đăng nhập; sai mật khẩu bị chặn; đăng nhập xong, đóng mở lại trình duyệt không bị hỏi lại.
- [ ] Dán URL, theo dõi tiến độ tới khi có Short.
- [ ] Xem, tua, tải một Short; tải tất cả.
- [ ] Sửa title một Short, render lại, xem kết quả.

## Result

### Phase A (mọi thứ trừ sửa title; 2026-09-27)

- Main changes:
  - `src/auto_short/web/`: `app.py` (FastAPI app factory: auth middleware, `/login` `/logout`, trang `/` và `/episodes/<id>`, `/api/episodes[/{id}]`, `/files/{id}/{clip}.mp4` có Range + `?download=1`, `/files/{id}/shorts.zip` stream `ZIP_STORED`), `auth.py` (mật khẩu env, `.web_secret` 600, cookie HMAC-SHA256 30 ngày, khóa ký trộn hash mật khẩu), `urls.py` (W3: chỉ URL một video, bỏ `si`/tham số khác, chuẩn hóa `https://youtu.be/<id>`), `jobs.py` (W5: một worker, FIFO, không trùng job theo episode, log vòng đệm 200 dòng, stop → `KeyboardInterrupt` cho stage đang chạy; job pipeline qua `run_pipeline` + preflight), `episodes.py` (đọc manifest / metadata / `render_manifest.json`, chỉ trả file Short trong `shorts/`), `server.py` (uvicorn), `static/` (login, index, episode, `app.js`, `style.css`; thẻ Short có chỗ `.title-edit` cho phase B).
  - `cli.py`: `auto-short web [--host] [--port] [--config]` (thiếu mật khẩu → exit 1; thiếu extra `[web]` → exit 1). `config.py` + `config.example.toml`: `[web] host/port/session_days`.
  - `pyproject.toml`: extra `[web]` = `fastapi==0.141.1`, `uvicorn==0.54.0`; `httpx` ở `dev`. Đã cài vào env `auto-short` (kéo `starlette 1.7.0`, `pydantic 2.13.5`), không `pip install -e`.
  - Docs: `docs/decisions/CP8.3-web-contract.md` (PROPOSED), CP1 §10 (3 dòng dependency + ghi chú scope), project profile (module map `web/`, authority), README (Web UI).
- Tests: `pytest -q` → 422 passed (60 test mới: `test_web_urls.py`, `test_web_auth.py`, `test_web_jobs.py`, `test_web_app.py`, `test_cli.py`/`test_config.py` bổ sung), 1 warning (starlette: `httpx` với TestClient deprecated, khuyên `httpx2`). `node scripts/framework-check.mjs` → PASS.
- Chạy thật (server `auto-short web --config config.toml` của worktree, workspace/output trỏ repo chính; `curl` qua `10.8.102.101:8080`): bảng số đo ở `docs/decisions/CP8.3-web-contract.md` § Số đo. AC1 (thiếu mật khẩu exit 1; 303/401; sai mật khẩu 401 sau 1 s không cookie; cookie 30 ngày; restart vẫn đăng nhập; cookie sửa → 401), AC2 (`tHtxw6ykUmM` → 6 stage `done`, 20/20 Short trong 1500 s; preflight lỗi → 503, không job), AC3 (Range 206; sha256 20/20 khớp; zip 20 entry khớp), AC5 (422 URL sai; 404 id lạ / traversal), AC6 (gửi trùng khi đang chạy → cùng job; gửi lại khi xong → 6 skip, 0,1 s) — PASS. Mật khẩu chạy thật sinh ngẫu nhiên, chỉ ở biến môi trường của tiến trình (không lưu trong repo). Server đã tắt.
- Review: ORCHESTRATOR review phase A ACCEPTED (2026-09-27), không finding chặn.
- Important findings / decisions:
  - W3: `watch?v=<id>&list=…` được hiểu là một video (bỏ `list`); chỉ `/playlist?list=…` bị từ chối — ghi trong decision record.
  - Tắt server khi job đang chạy: stage ghi `failed interrupted` nếu stage trả quyền về Python trong 30 s (test đơn vị); request Ollama dài có thể giữ manifest `running` → resume theo CP8 E3. Chưa đo trên server thật (không có job dài an toàn để ngắt).
  - Kết quả tập mới: 20 clip (header "Thập Thiện Nghiệp Đạo Kinh (tập 29)"), cả 20 có title AI; clip dài nhất 116,6 s (k14), ngắn nhất 31,8 s (k15); render dùng renderer CP7 (hard cut) vì CP8.1 chưa merge.
- Known limitations: xem decision record § Giới hạn đã biết.

### Phase B (sửa title; 2026-09-27, trên merge CP8.1 + CP8.2 `31af948`)

- Main changes:
  - `web/app.py`: `POST /api/episodes/{id}/shorts/{clip}/title/preview` và `…/title` (`set` / `alternative` / `reset`, đúng một hành động) qua hàm dùng chung `auto_short.review`; 409 khi episode có job đang chạy/đợi (kiểm + ghi + tạo job trong một lock, dùng chung với gửi URL); `ReviewError` → 422. `render` injectable.
  - `web/jobs.py`: job `render` (`clip_ids`) gọi `run_render` (CP8.2 T5 chỉ encode Short đổi); `summary` ghi `(<e> encoded, <r> reused)` cho cả job pipeline.
  - `web/episodes.py`: Short view thêm `title.origin` (thay `source`), `editable`, `ai_title`, `alternatives`, `override`, `pending_title`, `rendering`; episode thêm `render_status`, `max_title_chars`, `titles_error`, `titles_ignored`. **Đổi luật phase A**: Short / file / zip lấy từ `render_manifest.json` đã commit bất kể status stage render (CP8.2 T5 giữ render trước tới commit / khi lỗi) — ghi trong decision record W7.
  - UI: bộ sửa title trong `.title-edit` (đếm ký tự, dropdown phương án AI, xem trước debounce 350 ms, "Lưu & render lại", "Khôi phục title AI", khóa khi có job), nhãn "đang render…", thẻ Short thay tại chỗ; ghi chú "Đang hiển thị bản dựng trước".
  - Docs: decision record (phase B: W4 § Sửa title, W5, W6, W7, số đo, giới hạn; vẫn PROPOSED), README (Web UI), project profile (module map `web/`).
- Tests: `pytest -q` → 496 passed (sau merge 474 + 22 test web mới/đổi: `test_web_titles.py` gồm 1 test render thật bằng ffmpeg — sửa `k01` → `1 encoded, 1 reused`, `k02` byte không đổi, reset → byte-identical), 1 warning (như phase A). `node scripts/framework-check.mjs` → PASS.
- Chạy thật (`curl` qua `10.8.102.101:8080`, server mới + mật khẩu ngẫu nhiên mới, không lưu): bảng phase B ở decision record § Số đo.
  - Render lại 2 tập trong thư mục repo chính bằng renderer mới (dissolve 0.15 s, `render_key`) qua web: `tHtxw6ykUmM` 20/20 encode 509 s; `rbjfCfFq3Dk` (xếp hàng sau) 13/13 encode 310 s. ffprobe 33 mp4: \|`nb_frames` − `duration`×fps\| ≤ 0,49 frame, `dissolves` có ở 204/209 và 150/157 điểm nối, sha256 = manifest.
  - AC4: preview hợp lệ (3 dòng, 88 px) / 4 title sai → 422; `set` tay `k04` → 1 encoded + 19 reused (16,3 s), 19 file khác sha256 không đổi, file mới được phục vụ đúng sha256; `alternative: 2` → như trên, origin `alternative`; `reset` → 20/20 mp4 byte-identical bản AI; 409 khi job pipeline chạy và khi job render của Short khác chạy.
  - Server đã tắt; mật khẩu và cookie jar đã xóa.
- Review:
- Important findings / decisions:
  - Luật "danh sách Short theo render cuối đã commit" thay luật phase A (xem trên).
  - Sửa title bị từ chối (409) cả khi job render của **Short khác** đang chạy; UI khóa nút lưu tới khi job xong.
  - `title.source` (phase A) đổi tên `title.origin` theo CP8.2.
- Known limitations: decision record § Giới hạn đã biết. UI chỉ kiểm cú pháp (`node --check`) và qua API; manual test trên thiết bị khác trong LAN (gate HUMAN LEAD) chưa làm.
- PR:
