# Task: CP8.10 — Tối ưu hàng đợi (làn prepare / ai / render)

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `a463cdb` (`main`) / `feature/cp8.10-queue-lanes` (worktree `../youtube-auto-short-cp810`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE; Q1–Q4 theo đề xuất — xem Q1–Q4 dưới đây)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi job model web (`docs/decisions/CP8.3-web-contract.md` W5: "một worker, một job tại một thời điểm"), thêm trường API (W7: `lane`, `waiting`), thêm tham số `stages` cho `run_pipeline` (CP8 E7 — web gọi pipeline), thêm config `[web] queue_mode`. Không thêm dependency, không đổi security model, không đổi contract / hash / artifact của stage nào.

## Goal

Khi nhiều tập xếp hàng trên web, tập sau được tải video + phụ đề + tính candidate trước, và phần AI (GPU: selection, titling) của một tập chạy chồng với render (CPU) của tập khác, thay vì chạy trọn pipeline từng tập một. Hàng đợi dài xong sớm hơn; kết quả từng tập giống hệt chạy nối tiếp.

## Scope

- In scope:
  - `src/auto_short/web/jobs.py`: 3 làn, mỗi làn một worker thread + hàng đợi FIFO; job pipeline đi qua làn theo thứ tự; job `render` vào thẳng làn render; log handler theo thread; `stop()` ngắt mọi làn; `wait_idle` chờ mọi làn; `queue_mode = "serial"` giữ hành vi W5 cũ.
  - `src/auto_short/pipeline.py`: tham số tùy chọn `stages` cho `run_pipeline` (mặc định cả 6; CLI không đổi).
  - `src/auto_short/web/app.py` (+ `episodes.py` / `playlists.py` / `storage.py` nếu cần): trường job `lane`, `waiting`, `queue_position` theo làn; "đang có job" = job `queued`/`running` bất kể đang ở làn nào hay đang đợi giữa hai làn.
  - `src/auto_short/web/static/`: nhãn "đợi GPU" / "đợi render" / "đang tải trước" ở trang tập, danh sách, bộ kinh.
  - `src/auto_short/config.py`: `[web] queue_mode`.
  - Docs: `docs/decisions/CP8.3-web-contract.md` (W5 viết lại + W7 trường mới + Giới hạn đã biết, pointer tới task này), `docs/decisions/CP8-pipeline-contract.md` (pointer `stages` ở E7 hoặc chỗ tương ứng), `AUTO_SHORT_CHECKPOINT_PLAN.md` (CP8.10 bỏ "planned", trỏ task), `config.example.toml`, `docs/ai/project-profile.md` (module map web nếu cần), `docs/workflow/current-state.md`, Result của contract này.
  - Tests + chạy thật trên web scratch.
- Out of scope:
  - Hai job GPU song song; nhiều job trong một làn; hàng đợi lưu trên đĩa (restart vẫn mất hàng đợi); đổi luật stage / hash / artifact; tự xử lý hàng loạt (CP9); CLI `run` chạy theo làn; sửa web đang chạy ở worktree `../youtube-auto-short-web` (8080).

## Authority / key decisions

- Authority: CP8.3 W4, W5, W7, W9 (507), W10 L3; CP8 E2–E8; CP8.9 K5, A1.1 (thứ tự Short → khai thị); CP2 D6 (skip / stale).
- Quyết định (HUMAN LEAD 2026-09-28):
  - **Q0 Làn:** `prepare` = ingest → transcript → analysis; `ai` = preflight Ollama → selection → titling; `render` = render. Mỗi làn đúng một worker, FIFO. Job pipeline: vào hàng `prepare`; xong làn → vào cuối hàng làn kế; lỗi / ngắt ở làn nào → job kết thúc ở đó (`failed` / `interrupted`, như W4/W5 hiện tại). Mỗi làn gọi `run_pipeline(..., stages=<các stage của làn>)`; stage tự skip khi up to date.
  - **Q1 analysis ở làn `prepare`** (làn `ai` chỉ còn GPU; chấp nhận analysis tranh CPU với render của tập khác, ghi số đo).
  - **Q2 Giới hạn tải trước:** làn `prepare` không bắt đầu job mới khi đã có **2** job pipeline xong `prepare` đang đợi làn `ai` (hằng trong code). Trước khi chạy ingest ở làn `prepare`, kiểm lại ngưỡng ổ W9 (< 3 GB) → job `failed` với message 507 của W9 (không tải).
  - **Q3 Làn render FIFO**, không ưu tiên job sửa title / xóa Short.
  - **Q4 `[web] queue_mode`** = `"lanes"` (mặc định) | `"serial"` (một worker chạy trọn job như W5 cũ); execution-only, không vào hash; giá trị khác → lỗi load config.
  - **Q5 Preflight:** vẫn chạy trong request `POST /api/episodes` (W4); preflight của job chuyển sang đầu làn `ai` (ingest vẫn chạy khi Ollama tắt; job lỗi `ollama preflight: …` ở làn `ai`, resume được). Chế độ `serial`: như cũ (đầu job).
  - **Q6 Một job active / tập:** job ở trạng thái `running` từ lúc làn đầu tiên bắt đầu tới khi kết thúc, **kể cả lúc đợi giữa hai làn** (`waiting: true`); `queued` chỉ khi chưa vào làn nào. Mọi luật W4/W8/W9 dựa trên "job queued/running" (job trùng → 200 `created: false`, sửa title / xóa / archive / xóa tập → 409) giữ nguyên.
  - **Q7 Thứ tự Short → khai thị (K5):** không thêm cơ chế phụ thuộc; hai job cùng đi qua làn `prepare` FIFO nên ingest của `<id>.kt` luôn sau transcript của `<id>` khi hai job được gửi cùng lúc.
  - **Q8 API (thêm, không bỏ):** job thêm `lane` (`"prepare"` | `"ai"` | `"render"` | `null` khi chưa vào làn / đã kết thúc; `serial` → `null`), `waiting` (bool); `queue_position` = vị trí 1-based trong hàng của làn job đang đợi (kể cả đợi giữa hai làn), `null` khi đang chạy / kết thúc. `stage` = stage đang chạy, hoặc stage kế tiếp khi đang đợi.

## Implementation approach

- `JobRunner` giữ một lock / condition chung; mỗi làn một `deque` + một thread; `current` theo làn; ánh xạ thread ident → job cho `_JobLogHandler`.
- Target job pipeline tách thành các bước theo làn (callable nhận `Job` + tên làn), dùng lại `pipeline_target` với `stages`; job `render` = một bước làn render.
- `stop()`: đặt cờ dừng, inject `KeyboardInterrupt` vào mọi thread làn đang có job, SIGINT tiến trình con, join tối đa 30 s tổng.
- Test: stage giả (sleep / event) để kiểm chồng làn và thứ tự một cách deterministic.

## Acceptance Criteria

1. Chồng làn: với stage giả, khi job A đang ở làn `render` thì job B chạy `prepare` rồi `ai`; mỗi làn không bao giờ có 2 job cùng lúc; thứ tự FIFO trong từng làn.
2. Q2: không quá 2 job đã xong `prepare` đợi làn `ai`; ổ < 3 GB trước ingest → job `failed` message W9, không gọi downloader.
3. Q7 / K5: gửi một video mặc định (Short + khai thị) → ingest `.kt` chạy sau transcript tập Short, dùng lại nguồn (downloader chỉ được gọi một lần).
4. Q6: job đợi giữa hai làn → gửi trùng 200 `created: false`; sửa title / xóa Short / archive / xóa tập → 409; `GET` trả `status: "running"`, `waiting: true`, `lane`, `queue_position` đúng.
5. Lỗi ở làn nào kết thúc job ở làn đó (`error` như W4: `"<stage>: <message>"` / `ollama preflight: …`), job khác không bị ảnh hưởng.
6. `stop()` khi nhiều làn đang chạy → mọi job đang chạy thành `interrupted`, stage ghi `failed`/`interrupted`; log từng job chỉ chứa record của thread làn chạy job đó.
7. `queue_mode = "serial"` → một job chạy tại một thời điểm, trọn 6 stage (test W5 cũ pass ở chế độ này); giá trị sai → lỗi load config.
8. Kết quả artifact của một tập chạy theo làn giống hệt chạy nối tiếp (stage giả / fixture: cùng manifest status + artifact sha256).
9. Mọi test cũ pass (chỉ sửa test khi nó kiểm đúng hành vi W5 đã đổi — ghi lý do trong Result); CLI `run` không đổi.

## Required verification

- `pytest -q` — toàn bộ, gồm test mới AC1–AC9.
- `node scripts/framework-check.mjs` — PASS.
- Chạy thật web scratch (cổng ≠ 8080, config trỏ thư mục tạm, Ollama `127.0.0.1:11437`, mật khẩu qua env; không đụng `work/` / `output/` chính và web 8080): gửi ≥ 3 video thật (vd 3 tập liền của một bộ kinh, chỉ Short hoặc Short + khai thị) ở `queue_mode = "lanes"`. Ghi: thời gian từng stage từng tập, wall time tổng, so với tổng thời gian stage (= chạy nối tiếp), khoảng thời gian làn chồng nhau, analysis / render chậm đi bao nhiêu khi chạy chồng; `GET` trong lúc đợi có `lane` / `waiting`. sha256 `work/` chính trước / sau không đổi.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (trường job mới) và đổi job model — manual test là gate trước integration. Không chạm database, không đổi security model.

- [ ] Trang bộ kinh: bấm "Xử lý" 2–3 tập → thấy "đang tải trước" / "đợi GPU" / "đợi render" hợp lý; tập sau có Short sớm hơn so với chạy nối tiếp.
- [ ] Trong lúc tập A render, sửa title một Short của tập đã xong → job render đợi sau render của A rồi chạy đúng.
- [ ] Short + khai thị cùng video: khai thị không tải lại video.
- [ ] Tắt / bật server khi đang chạy nhiều làn → gửi lại URL chạy tiếp được.

## Result

- Main changes:
  - `pipeline.py`: `run_pipeline(…, stages=None)` — tập con khác rỗng của `PIPELINE_STAGES`, đúng thứ tự, không trùng (sai → `PipelineError`, không stage nào chạy); không có `ingest` thì bắt buộc `episode_id`; preflight chạy trước stage đầu của tập con; dòng log "review is not run" chỉ khi có `render`. CLI không đổi.
  - `config.py`: `[web] queue_mode` = `"lanes"` (mặc định) | `"serial"`, giá trị khác → `ConfigError`; execution-only.
  - `web/jobs.py`: `JobRunner(mode)` — 3 làn `prepare` / `ai` / `render` (`LANE_STAGES`), mỗi làn một thread + `deque` FIFO, một `Condition` chung; job đi theo `Step` (lane, callable), xong làn → cuối hàng làn kế (`waiting = true`, `stage` = stage đầu làn kế); `PREFETCH_LIMIT = 2`; `PipelineTarget` (gọi trực tiếp = chế độ serial, `lane_steps()` = 3 bước làn; làn sau dùng episode id ingest trả về; `disk_blocked` kiểm W9 ngay trước ingest; preflight đầu làn `ai`); job `render` / callable thường = một bước ở làn `render` / `prepare`; log handler theo thread ident → làn → job; `stop()` inject `KeyboardInterrupt` vào mọi thread làn đang chạy job + SIGINT tiến trình con, join tổng ≤ timeout, job đang đợi giữa hai làn → `interrupted` (`"interrupted while waiting for <lane>"`); `wait_idle` gồm mọi làn + job đợi giữa làn. Job thêm `lane`, `waiting`; `queue_position` theo hàng của làn.
  - `web/storage.py`: `BLOCK_MESSAGE` (message 507 W9, dùng chung) + `StorageCache.block_message()`. `web/app.py`: `JobRunner(config.web.queue_mode)`, truyền `disk_blocked`; `queue_position` cũng có trong `job` của `GET /api/episodes` và entry bộ kinh.
  - `web/static/app.js`: nhãn "đang tải trước" (làn `prepare` chạy), "đợi GPU (vị trí n)", "đợi render (vị trí n)" ở trang tập (dòng trạng thái job; stage kế hiện "đang đợi" thay vì "đang chạy" khi job đợi giữa làn), danh sách tập lẻ, trang bộ kinh (Short trước, khai thị ghi "khai thị …").
  - Docs: CP8.3 W4 (preflight đầu làn `ai`), W5 viết lại, W7 (`lane`, `waiting`, `queue_position`), bảng `[web]`, Giới hạn đã biết; CP8 E7 (`stages`); `AUTO_SHORT_CHECKPOINT_PLAN.md` CP8.10; `config.example.toml`; project-profile (module map web); `current-state.md`.
- Tests:
  - `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q` → **868 passed** (base `0e66a68`: 854 passed; +14 trong `tests/test_web_lanes_cp810.py`). Lưu ý: bản editable install của env trỏ repo chính, nên phải đặt `PYTHONPATH` tới `src` của worktree.
  - AC1 `test_lanes_overlap_fifo_and_render_job`, `test_plain_callable_pipeline_job_runs_in_prepare`; AC2 `test_prefetch_limit`, `test_disk_block_before_ingest_fails_without_download`, `test_disk_block_rechecked_in_prepare_lane`; AC3 `test_khaithi_ingest_after_short_transcript_reuses_download` (ingest thật + downloader giả: gọi 1 lần, hardlink); AC4 `test_waiting_between_lanes_is_active`; AC5 `test_errors_end_job_in_their_lane`; AC6 `test_stop_interrupts_every_lane` (3 làn chạy + 1 job đợi); AC7 `test_serial_mode_one_job_at_a_time`, `test_serial_preflight_failure_runs_no_stage`, `test_queue_mode_config_and_app`; `stages`: `test_run_pipeline_stages_argument`; AC8 `test_lanes_artifacts_identical_to_serial` (stage thật, Ollama giả, ffmpeg thật: manifest (bỏ `started_at` / `finished_at`, path output chuẩn hóa) + sha256 mọi file `work/<id>/` và `output/<id>/` giống hệt serial).
  - AC9: không sửa test cũ nào; mọi test web cũ chạy ở chế độ `lanes` (mặc định) và pass. Test mới + `test_web_jobs.py` chạy lặp 15 lần: 15/15 pass.
  - `node scripts/framework-check.mjs` → PASS (exit 0).
  - Chạy thật (web scratch `127.0.0.1:8095`, worktree `src`, config bản sao với `work/` / `output/` trong thư mục tạm, `models/` repo chính chỉ đọc, Ollama `127.0.0.1:11437`, mật khẩu qua env; `queue_mode = "lanes"`): bộ kinh "Thái Thượng Cảm Ứng Thiên" tập 1 (Short + khai thị), tập 2, tập 3 (chỉ Short), gửi cùng lúc 13:43:26. Tập 3 lần đầu lỗi `ingest: … HTTP Error 403: Forbidden` sau 2 s (YouTube; job khác không ảnh hưởng), gửi lại 14:58:07 → xong.

    | Tập (thời lượng) | ingest | transcript | analysis | selection | titling | render | tổng stage | Short |
    |---|---|---|---|---|---|---|---|---|
    | `4oOZz2CBz3g` tập 1 (61:12) | 46,5 | 1728,3 (Whisper CPU) | 143,4 | 250,0 | 20,0 | 229,6 | 2417,9 | 7 |
    | `4oOZz2CBz3g.kt` | 1,3 (K5 hardlink) | 0,02 (K5 copy) | 143,1 | 206,5 | 20,6 | 838,2 | 1209,7 | 6 |
    | `Irmcm5Ep478` tập 2 (54:55) | 71,3 | 1862,1 (Whisper CPU) | 57,8 | 203,1 | 27,1 | 276,8 | 2498,2 | 10 |
    | `E4QhRRXFbIM` tập 3 (56:41), lần 2 | 55,0 | 2,3 (phụ đề YouTube) | 69,8 | 168,4 | 27,8 | 251,1 | 574,5 | 10 |

    - Tổng thời gian stage (= chạy nối tiếp) 6700 s (111,7 phút); wall time 13:43:26 → 15:07:42 = 5056 s (84,3 phút), gồm cả 7 phút tập 3 lỗi 403 chờ gửi lại → nhanh hơn 1644 s (≈ 25 %). Làn `prepare` là nút cổ chai (Whisper CPU ~29–31 phút / tập khi YouTube caption bị loại).
    - Thời gian theo số làn chạy đồng thời (snapshot 2 s): chỉ `prepare` 2763 s; `prepare`+`ai` 273 s; cả 3 làn 228 s; `prepare`+`render` 919 s; chỉ `ai` 425 s; chỉ `render` 448 s → ≥ 2 làn chồng nhau 1420 s (28 % wall). Cửa sổ chính: 14:15:24–14:17:50 analysis khai thị ∥ selection tập 1; 14:19:55–14:23:45 Whisper tập 2 ∥ AI khai thị ∥ render tập 1; 14:23:45–14:37:43 Whisper tập 2 ∥ render khai thị; 14:58:08–14:59:27 prepare tập 3 ∥ render tập 2.
    - Chậm đi khi chạy chồng (so với chạy riêng bằng CLI `--force` trên cùng workspace scratch sau khi tắt server): render khai thị 838,2 s (chồng Whisper tập 2) vs 700,9 s riêng → +20 %; analysis tập 3 69,8 s (chồng render tập 2) vs 61,5 s riêng → +13 %; render tập 2 276,8 s (chồng 79 s ingest / analysis tập 3) vs 274,2 s → +1 %; analysis khai thị 143,1 s (chồng selection, GPU ở Ollama) ≈ analysis tập 1 chạy riêng 143,4 s → không chậm. Whisper tập 2 0,565 s / giây audio (chồng render khai thị 838 s) vs tập 1 chạy riêng 0,471 → ≈ +20 % (audio khác nhau, chỉ tham khảo). Load average cao nhất 33,5 / 48 CPU.
    - `GET` trong lúc đợi (14:17:50): `/api/episodes/4oOZz2CBz3g.kt` và `/api/episodes` → `{"status": "running", "lane": "ai", "waiting": true, "queue_position": 1, "stage": "selection"}`; tập 3 lúc đầu `{"status": "queued", "lane": null, "queue_position": 3}` rồi 2, 1 (hàng `prepare`).
    - K5 thật: khai thị ingest 1,3 s (hardlink), transcript 0,02 s (copy), không tải lại.
    - Mật khẩu: server nhận qua env; script poll đọc từ file scratch quyền 600 (`realrun/.pw`, đã xóa sau khi chạy).
    - Tắt server (SIGINT) khi không có job: thoát sạch. Cổng 8080 / worktree web không bị đụng. `work/` repo chính: danh sách `sha256sum` 256 file trước / sau giống hệt (sha256 của danh sách `7db5f3a7…61bd` cả hai lần).
- Review: chưa (chờ ORCHESTRATOR).
- Important findings / decisions:
  - Race tìm thấy khi test: làn `ai` lấy job khỏi hàng làm hàng ngắn lại nhưng không `notify` → làn `prepare` có thể ngủ mãi dù dưới giới hạn tải trước; đã sửa (`notify_all` sau khi lấy job) + `test_prefetch_limit` bắt được.
  - Quyết định nhỏ khi implement (trong boundary Q0–Q8, cần ORCHESTRATOR xác nhận): `queue_position` thêm vào `job` của `GET /api/episodes` và entry bộ kinh (additive, để nhãn "đợi GPU (vị trí n)"); job đợi giữa làn khi tắt server → `interrupted` (`"interrupted while waiting for <lane>"`), job `queued` giữ `queued` như cũ; kiểm ổ W9 chạy ở đầu làn `prepare` cả khi ingest sẽ skip; chế độ `serial` không kiểm lại ổ (giữ đúng hành vi cũ); `stages` là tập con đúng thứ tự (không bắt buộc liền nhau), `force_from` ngoài `stages` không có tác dụng; callable job thường ở chế độ lanes = một bước (làn `render` cho job `render`, còn lại làn `prepare`).
  - Ngoài scope (có sẵn trước CP8.10): fixture `cfg` trong `tests/conftest.py` để `render.output_dir` mặc định `output` (tương đối) nên `tests/test_web_jobs.py::test_pipeline_target_success_and_failure` ghi `output/abcdefghijk/` vào thư mục đang chạy pytest — chạy `pytest` trong checkout chính sẽ ghi vào `output/` thật (gitignored). Chưa sửa (ngoài scope); test mới của CP8.10 dùng `output_dir` tạm.
- Known limitations:
  - Whisper ở máy này chạy CPU (`device = "cpu"`, int8) trong làn `prepare`: làn này là nút cổ chai khi YouTube caption bị loại, và tranh CPU với render của tập khác (+20 % đo được). Hai job GPU không bao giờ chạy song song (Ollama chỉ ở làn `ai`).
  - Hàng đợi / làn chỉ trong bộ nhớ (restart mất); không có ưu tiên job sửa title (Q3); tải trước tối đa 2 tập đợi AI + 1 tập đang chuẩn bị chiếm thêm dung lượng ổ trước khi render.
  - Trong khoảnh khắc kết thúc job, `status` có thể đã `done` trong khi `lane` chưa về `null` (một lần poll).
  - UI (nhãn làn) chỉ kiểm bằng API + `node --check`; chưa kiểm trên trình duyệt / điện thoại (manual test checklist). Tắt server khi nhiều làn đang chạy chỉ kiểm bằng test (AC6), chưa trên server thật.
- PR: chưa (push / PR sau READY + HUMAN LEAD approval).
