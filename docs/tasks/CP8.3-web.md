# Task: CP8.3 — Web MVP

## Status / Approval

- Status: APPROVED
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

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
