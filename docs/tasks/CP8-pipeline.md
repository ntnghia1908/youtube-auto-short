# Task: CP8 — End-to-End Auto Short MVP

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `3aa86d9` (main, sau merge PR #9) / `feature/cp8-pipeline`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-27; E1–E8; P1, P2 theo đề xuất; P3 theo re-plan; P4 sửa: có preflight Ollama)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP8: (a) thêm lệnh CLI mới `auto-short run` (mở rộng CP2 D8, additive); (b) tạo rule điều phối pipeline (thứ tự stage, dừng khi lỗi, resume, force, exit code khi ngắt) mà CP9 (batch) dùng lại → cần canonical owner (decision record CP8); (c) chốt cách CP8 xử lý stage `review` chưa có (CP1 §8: MVP render mọi clip AI chọn). Quyết định E1–E8 dưới đây duyệt cùng APPROVE TASK. Không thêm dependency; không đổi contract/schema của stage CP2–CP7.

Re-plan HUMAN LEAD 2026-09-27 (`AUTO_SHORT_CHECKPOINT_PLAN.md`): CP8 rút gọn → CP8.1 dissolve → CP8.2 sửa title + render lại một Short → CP8.3 Web → (CP8.4 upload YouTube, sau). `run_pipeline()` + preflight của CP8 là thứ web gọi để xử lý nền. Chạy thật trên video mới (URL nhập từ web) chuyển sang verification của CP8.3.

## Goal

Một lệnh `auto-short run <youtube-url|path>` đưa một video nguồn qua toàn bộ pipeline `ingest → transcript → analysis → selection → titling → render` và cho ra các Short trong `output/<episode_id>/shorts/` + mọi artifact trung gian inspectable trong `work/<episode_id>/` (roadmap §4 CP8 Success). Chạy lại cùng lệnh sau khi lỗi/ngắt tiếp tục từ stage đầu tiên chưa up to date; chạy lại khi mọi thứ đã xong thì skip hết.

## Scope

- In scope:
  - Module điều phối `src/auto_short/pipeline.py` (E7): gọi lần lượt các `run_*` hiện có, không sửa logic stage.
  - CLI `auto-short run …` (E1, E5, E6); tách phần in dòng kết quả của từng lệnh stage thành hàm dùng chung để `run` và lệnh lẻ in giống nhau (không đổi output lệnh lẻ).
  - Tests `pytest`: điều phối với stage giả (thứ tự, dừng khi lỗi, resume, `--force-from`, ngắt), và **test end-to-end không mạng**: video lavfi vài giây + subtitle `.srt` sidecar + Ollama client giả (selection + titling) + `ffmpeg` render thật → ra Short.
  - Chạy thật trên `rbjfCfFq3Dk` (P3): chạy lại → skip hết; `--force-from render` rồi ngắt giữa render → chạy lại → resume.
  - Docs: decision record `docs/decisions/CP8-pipeline-contract.md` (ACCEPTED sau review); project profile (authority order, module map `pipeline.py` → implemented, stage); README (usage `run`, current stage); current-state.
- Out of scope:
  - Review approve/reject/edit, `review.json`, `title_source = "review"` (CP9); render clip `untitled` (CP6 P3).
  - Batch nhiều video / playlist, cô lập lỗi từng item, song song (CP9).
  - Preflight `node`/`ffmpeg`/Whisper (chỉ Ollama có preflight, E8).
  - Chạy thật trên video mới (verification CP8.3); dissolve (CP8.1); sửa title tay + render lại một Short (CP8.2); web (CP8.3); upload YouTube (CP8.4).
  - Đánh giá chất lượng (CP10); tối ưu thời gian/GPU (CP11).
  - Sửa hành vi / schema / config của stage CP2–CP7. Finding ở stage cũ phát hiện khi chạy thật → ghi nhận, báo HUMAN LEAD, không tự sửa.

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8; `docs/decisions/CP1-product-contract.md` §8 (thứ tự stage, "MVP CP8 render mọi clip AI chọn", auto-approve chỉ là config explicit); `docs/decisions/CP2-workspace-contract.md` D6 (skip/stale/force), D8 (CLI, exit code); `docs/decisions/CP3-transcript-contract.md` … `docs/decisions/CP7-render-contract.md` (stage giữ nguyên; CP7 R2/P1 `title_source = "titles"`).
- Dữ kiện đo (main `3aa86d9`, `work/rbjfCfFq3Dk`, số từ decision record CP4–CP7):
  - Mỗi stage đã có `run_<stage>(episode_id, config, *, force, …)` trả `…Result(ran, …)` và raise `<Stage>Error`; skip/stale do `run_stage` (CP2 D6). `run_stage` bắt `KeyboardInterrupt` → stage `failed` (`error: "interrupted"`), xóa artifact trong workspace, raise lại; CLI hiện không bắt `KeyboardInterrupt` (in traceback).
  - Dependency injection có sẵn: ingest `downloader`, transcript `fetcher`/`backend`, analysis `analyzer`, selection/titling `client`, render `run` → test end-to-end không mạng được mà không sửa stage.
  - Thời gian trên video test 1 giờ (từng stage): analysis ≈ 90 s; selection `qwen3:30b` think ≈ 8 min; titling ≈ 35 s; render ≈ 5 min (13 clip, 48 thread); ingest YouTube ≈ tải 700 MB; transcript từ caption YouTube vài giây (Whisper CPU chậm hơn nhiều, CP11).
  - Titling header cho nguồn YouTube lấy từ `title_pattern` trên title video; nguồn local không có title cần `--series`/`--episode` (CP6).
  - Stage `review` nằm trong `STAGES` (CP1 §8) nhưng chưa implement; `status` hiển thị `pending`.
- Quyết định (DECIDE cùng APPROVE TASK):
  - **E1 Lệnh (P1):** `auto-short run <url|path> [--episode-id ID] [--subtitle PATH] [--speaker S] [--series S] [--episode N] [--force-from STAGE] [--no-preflight] [--config PATH]`. Tham số truyền nguyên cho stage tương ứng (ingest: `--episode-id`; transcript: `--subtitle`; titling: `--speaker`/`--series`/`--episode`). Episode id lấy từ kết quả ingest. Lệnh lẻ hiện có giữ nguyên.
  - **E2 Thứ tự:** `ingest → transcript → analysis → selection → titling → render` (CP1 §8). Stage `review` **không chạy** ở CP8 (giữ `pending`); render dùng `[render] title_source = "titles"` (auto-approve title AI, CP7 P1) — `run` log một dòng nói rõ title AI được auto-approve.
  - **E3 Resume:** không có state/artifact mới; mỗi stage tự skip khi up to date (CP2 D6). Chạy lại cùng lệnh sau lỗi/ngắt → các stage đã `done` + khớp input/config skip, chạy tiếp từ stage đầu tiên chưa up to date. Stage bị kill cứng (còn `running`) chạy lại theo D6.
  - **E4 Lỗi:** dừng ở stage lỗi đầu tiên, không chạy stage sau; exit `1`, stderr `auto-short: error: <message của stage>` (message đã nêu stage) + gợi ý chạy lại cùng lệnh để resume. Không retry thêm ngoài retry sẵn có của stage.
  - **E5 Force (P2):** `--force-from STAGE` (một trong 6 stage của E2) = chạy stage đó với `force=True`; stage sau chạy lại vì bị đánh `stale` (D6), không cần force. Không có `--force` trơn (tránh vô tình tải lại video / chạy lại Whisper). Stage trước STAGE vẫn theo rule skip.
  - **E6 Output / exit code:** stdout: mỗi stage một dòng đúng định dạng của lệnh lẻ tương ứng (vd `<id>\tskipped (up to date)\t<path>`), cuối cùng `<episode_id>\tdone (<rendered>/<clips> Shorts)\t<output/<episode_id>/>`. stderr: log của stage như hiện tại + bảng tổng kết thời gian từng stage (ran/skip, giây). Exit: `0` thành công (kể cả có clip `untitled` bị bỏ qua — cảnh báo), `1` lỗi (E4), `2` sai cú pháp (CP2 D8), **`130` khi Ctrl-C**: in `auto-short: interrupted during <stage>; re-run the same command to resume`, không traceback. Thời điểm chạy từng stage vẫn nằm ở `manifest.json` (`started_at`/`finished_at`) — không thêm artifact.
  - **E7 Code:** `src/auto_short/pipeline.py` — `run_pipeline(target, config, *, episode_id, subtitle, speaker, series, episode, force_from, <deps injectable>) -> PipelineResult` (kết quả từng stage + thời gian); CLI chỉ parse + in. Không sửa `workspace.run_stage` và module stage (ngoại lệ: nếu bắt buộc phải có hook nhỏ → báo ORCHESTRATOR trước).
  - **E8 Preflight Ollama (P4, HUMAN LEAD 2026-09-27):** trước ingest, `run` gọi `GET <host>/api/tags` (timeout 10 s) cho host của `[selection]` và `[titling]` (qua `resolve_host`, `OLLAMA_HOST` ghi đè) và kiểm `[selection] model`, `[titling] model` có trong danh sách. Lỗi (không kết nối, HTTP lỗi, thiếu model) → exit 1, `auto-short: error: ollama preflight: <lý do>`, không stage nào chạy. `--no-preflight` bỏ qua (vd episode đã xong selection/titling khi Ollama tắt). Hàm preflight đặt ở `pipeline.py` (hoặc cạnh client selection) để CP8.3 web dùng lại; không sửa `OllamaClient.chat`.
- Đề xuất đã chốt (HUMAN LEAD 2026-09-27, re-plan; theo đề xuất trừ P3):
  - **P1 Tên lệnh:** `run`.
  - **P2 Force:** chỉ `--force-from STAGE` (E5).
  - **P3 Video chạy thật:** CP8 chạy thật trên `rbjfCfFq3Dk` (skip hết + ngắt/resume); video mới do người dùng nhập URL trên web → verification CP8.2.
  - **P4 Preflight:** **có** — kiểm Ollama + model trước khi chạy (E8), sửa so với đề xuất ban đầu.

## Implementation approach

- `pipeline.py`: danh sách stage cố định (E2); mỗi bước gọi `run_<stage>` với tham số tương ứng, đo `time.monotonic()`; `force = (stage == force_from)`; bắt `<Stage>Error` → dừng (E4); `KeyboardInterrupt` → ghi nhận stage đang chạy rồi raise lại để CLI trả 130.
- `cli.py`: subparser `run`; hàm format dòng kết quả dùng chung cho lệnh lẻ + `run`; bảng tổng kết stderr; `KeyboardInterrupt` → 130 (chỉ cho `run`, hoặc cho mọi lệnh nếu không đổi output lệnh lẻ — implement chọn, ghi Result).
- Test end-to-end: dựng video lavfi (≈ 60–90 s để analysis ra được candidate đủ dài — hoặc hạ `[analysis]` min duration trong config test), `.srt` sidecar tiếng Việt, client Ollama giả trả JSON hợp lệ theo schema selection/titling (tái dùng helpers `tests/selection_helpers.py`, `tests/titling_helpers.py` nếu hợp), render `ffmpeg` thật; kiểm Short tồn tại + chạy lại skip hết.
- Tái dùng `workspace`, `config`, helpers test hiện có; không đổi config keys.

## Acceptance Criteria

1. Test end-to-end không mạng (video lavfi + `.srt` + client Ollama giả + `ffmpeg` thật): `run` từ workspace trống → exit 0, đủ artifact CP2–CP7, ≥ 1 Short hợp lệ, 6 stage `done`, `review pending`, stdout đúng E6; lần chạy thứ hai 6 stage `skipped (up to date)`.
2. `auto-short run https://youtu.be/rbjfCfFq3Dk` trên workspace hiện có: 6 stage skip, không gọi Ollama/không render, exit 0, xong trong vài giây; output CP7 không đổi (sha256 mp4 giữ nguyên).
3. `auto-short run https://youtu.be/rbjfCfFq3Dk --force-from render`, ngắt (`SIGINT`) giữa render: exit 130, message E6, không traceback; manifest render `failed` `interrupted`; chạy lại không `--force-from` → stage trước skip, render chạy lại, xong đủ 13 Short.
4. Lỗi ở một stage (test: stage giả raise): exit 1, stage sau không chạy, stage trước giữ `done`; chạy lại sau khi hết lỗi → resume (E3/E4).
5. Preflight (test với HTTP giả): Ollama không kết nối được hoặc thiếu model → exit 1, message E8, manifest không đổi (không stage nào chạy); `--no-preflight` bỏ qua. Thật: `OLLAMA_HOST=http://127.0.0.1:1 auto-short run https://youtu.be/rbjfCfFq3Dk` → exit 1 ngay.
6. `--force-from titling` (test): ingest…selection skip, titling + render chạy lại; `--force-from` giá trị lạ → exit 2.
7. Lệnh lẻ (`ingest` … `render`, `status`) giữ nguyên hành vi + output: mọi test hiện có PASS không sửa.
8. Docs cập nhật (decision record CP8 ACCEPTED sau review, project profile, README, current-state); `node scripts/framework-check.mjs` PASS.

## Required verification

- `pytest -q` (toàn bộ; gồm test pipeline + end-to-end mới) — AC1, AC4, AC5, AC6, AC7.
- `time auto-short run https://youtu.be/rbjfCfFq3Dk` + so sha256 `output/rbjfCfFq3Dk/shorts/*.mp4` trước/sau — AC2.
- `auto-short run https://youtu.be/rbjfCfFq3Dk --force-from render` + `SIGINT` giữa render, rồi chạy lại + `auto-short status rbjfCfFq3Dk` — AC3.
- `OLLAMA_HOST=http://127.0.0.1:1 auto-short run https://youtu.be/rbjfCfFq3Dk` → exit 1 — AC5.
- `node scripts/framework-check.mjs` — AC8.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model. Public interface: chỉ **thêm** lệnh CLI `run` (không breaking, lệnh cũ giữ nguyên). Manual test sau automated verification là điểm danh.

- [ ] Tự chạy `auto-short run <URL>` lần hai thấy skip hết; thử Ctrl-C rồi chạy lại.

## Result

- Main changes:
  - `src/auto_short/pipeline.py` (mới): `PIPELINE_STAGES` (E2), `run_pipeline()` → `PipelineResult` (từng stage: `ran`, giây, `…Result`; `failed_stage`/`error`; `rendered`/`clips`/`output_dir`), `StageDeps` (dependency injectable + thay hàm `run_<stage>` cho test), callback `on_stage`, `ollama_preflight()` (E8, `urllib`, opener injectable), `PreflightError`, `PipelineInterrupted` (subclass `KeyboardInterrupt`, mang tên stage). Không sửa `workspace.run_stage` hay module stage.
  - `src/auto_short/cli.py`: subparser `run` (E1; `--force-from` = `choices` 6 stage → exit 2); `stage_line()` dùng chung cho lệnh lẻ và `run` (output lệnh lẻ không đổi byte nào); dòng cuối `done (<r>/<c> Shorts)`, bảng tổng kết stderr, exit 1/130 (E4, E6). Bắt Ctrl-C → 130 **chỉ cho `run`** (lệnh lẻ giữ hành vi cũ).
  - Docs: `docs/decisions/CP8-pipeline-contract.md` (PROPOSED, chờ review → ACCEPTED), project profile (authority order, module map `pipeline.py`, stage), README (current stage, usage `run`).
- Tests: `pytest -q` → 362 passed (342 test cũ không sửa + 20 mới), 68 s.
  - `tests/test_pipeline.py` (19): stage giả — thứ tự + tham số truyền đúng stage, resume/skip hết, dừng khi lỗi + resume, `force_from` chỉ force đúng stage, stage lạ → `PipelineError`, ngắt nêu đúng stage, preflight chạy trước và chặn mọi stage; preflight với opener giả (một lần/host, hai host, `OLLAMA_HOST` ghi đè, `:latest`, thiếu model selection/titling, không kết nối, HTTP 500, timeout, JSON lỗi); CLI `run` (stdout 6 dòng + dòng cuối, bảng stderr, exit 1 + gợi ý resume, exit 130 không traceback, `--force-from titling`, `--force-from review` → exit 2); preflight với HTTP server thật trên localhost (thiếu model, cổng đóng, env ghi đè → exit 1, `manifest.json` byte-identical; `--no-preflight` chạy stage).
  - `tests/test_pipeline_e2e.py` (1, ≈ 15 s): video lavfi 30 s (tone 4.5 s / lặng 1.5 s) + `.vi.srt` sidecar tiếng Việt + client Ollama giả + `ffmpeg` thật (preset ultrafast), `[analysis]` hạ `min_duration` 4 s …: (1) selection lỗi → exit 1, 3 stage đầu `done`, selection `failed`, titling/render không chạy; (2) chạy lại → resume từ selection, 2 Short, đủ artifact CP2–CP7, 6 stage `done`, `review pending`; (3) chạy lại → 6 `skipped (up to date)`, không gọi AI, mp4 không đổi, 6 lệnh lẻ in đúng dòng như `run`; (4) `--force-from titling` → 4 skip, titling + render chạy; (5) `--force-from render` + Ctrl-C ở lệnh `ffmpeg` → exit 130, render `failed` `interrupted`; (6) chạy lại → render lại, mp4 byte-identical.
- Review:
- Verification (máy dev, conda `auto-short`, Ollama `127.0.0.1:11437`, `work/rbjfCfFq3Dk`):
  - `pytest -q` → 362 passed in 67.9 s — AC1, AC4–AC7.
  - AC2: `time auto-short run https://youtu.be/rbjfCfFq3Dk` → preflight ok, 6 stage `skipped (up to date)`, `rbjfCfFq3Dk\tdone (13/13 Shorts)\t…/output/rbjfCfFq3Dk`, exit 0, real 0.32 s; sha256 13 mp4 trước/sau giống hệt, `manifest.json` byte-identical.
  - AC3: `auto-short run https://youtu.be/rbjfCfFq3Dk --force-from render`, SIGINT cả process group (như Ctrl-C) sau 60 s (k01, k02 đã render) → exit 130, stderr `auto-short: interrupted during render; re-run the same command to resume`, không traceback; `status`: render `failed … error: interrupted`, `shorts/` rỗng, không file tạm sót. Chạy lại không `--force-from` → 5 stage skip, `render: run (previous status is failed)`, `rendered (13/13 clips)`, render 301.4 s, exit 0; `status` render `done`; sha256 13 mp4 giống hệt trước khi force.
  - AC5: `OLLAMA_HOST=http://127.0.0.1:1 auto-short run https://youtu.be/rbjfCfFq3Dk` → `auto-short: error: ollama preflight: cannot reach Ollama at http://127.0.0.1:1: [Errno 111] Connection refused`, exit 1, real 0.18 s, manifest không đổi. Thêm: cùng lệnh với `--no-preflight` → 6 skip, exit 0; `--force-from bogus` → exit 2.
  - AC8: `node scripts/framework-check.mjs` → PASS (gồm decision record CP8).
- Important findings / decisions:
  - Dòng cuối stdout dùng đường dẫn thư mục output (`<output_dir>/<episode_id>`, không dấu `/` cuối); số Short lấy từ `render_manifest.json` `stats` khi render skip.
  - Lỗi stage được trả về trong `PipelineResult` (không raise) để CLI in bảng tổng kết trước message lỗi; preflight lỗi và Ctrl-C raise.
  - Finding ngoài scope (không sửa): dòng stdout của lệnh lẻ in path theo `workspace.dir` (tương đối với config mặc định, vd `work/rbjfCfFq3Dk/transcript.json`) còn render in path tuyệt đối — có từ CP2–CP7, `run` giữ nguyên để byte-identical với lệnh lẻ.
  - Render dọn đúng khi bị ngắt: mp4 đã render trong lần chạy bị xóa, không file tạm sót (đã kiểm trên video thật).
- Known limitations:
  - Lệnh lẻ vẫn in traceback khi Ctrl-C (chọn chỉ bắt cho `run`, không đổi hành vi lệnh lẻ).
  - Timeout preflight 10 s là hằng số; preflight không kiểm `node` / `ffmpeg` / Whisper (ngoài scope E8).
  - Chưa chạy thật trên video mới từ đầu (ingest YouTube → render): chuyển sang verification CP8.3 theo P3.
- PR:
