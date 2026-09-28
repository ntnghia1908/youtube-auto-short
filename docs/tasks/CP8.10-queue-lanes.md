# Task: CP8.10 — Tối ưu hàng đợi (làn prepare / ai / render)

## Status / Approval

- Status: APPROVED
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
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
