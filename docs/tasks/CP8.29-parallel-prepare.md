# Task: CP8.29 — Làn chuẩn bị chạy song song nhiều tập

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `8de06c9` (`main`) / `feature/cp8.29-parallel-prepare` (worktree `../youtube-auto-short-pprep`)
- Human Lead approval: APPROVED 2026-10-04 ("Làm B ngay" — phương án B ORCHESTRATOR đề xuất cùng ngày: 2–3 tập chuẩn bị song song, chia luồng Whisper)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: mở rộng số worker của một làn trong khuôn CP8.10 (làn vẫn là `prepare` / `ai` / `render`), thêm khóa config; không đổi dependency, security model, public API.

## Bối cảnh (2026-10-04)

- VM nay 32 nhân, 125 GB RAM (dùng ~9 GB). Làn `prepare` (ingest → transcript → analysis) chạy **một job một lúc**; 86 tập Địa Tạng ("Chuẩn bị + HD", CP13.2) cần Whisper CPU (`large-v3-turbo`, int8, `[transcript.whisper] cpu_threads = 24`) ~20–25 phút / tập → ~30–36 giờ tuần tự; 3090 rảnh trong lúc đó.
- Whisper không tăng tuyến tính theo luồng: CP11 đo 24 luồng nhanh hơn 48 trên máy 48 nhân → chạy 2–3 tập song song với ít luồng hơn mỗi tập thường cho tổng thông lượng cao hơn.
- `transcript/whisper.py` cache model theo khóa có `effective_cpu_threads`.

## Amendment 1 (HUMAN LEAD 2026-10-04, làm rõ)

"Không phải khóa cứng 4 core, mà phải bảo đảm web mượt cho người dùng và khi tải xuống." → **không** giới hạn cứng số nhân; việc nặng (Whisper của job chuẩn bị, ffmpeg render / tải / ghép, phân tích) được dùng hết CPU nhưng chạy ở **ưu tiên thấp**: tiến trình con nặng chạy với `nice` (ví dụ 10–15) + `ionice` lớp idle / best-effort thấp; luồng Whisper trong tiến trình web hạ ưu tiên theo luồng (Linux `setpriority` trên native thread id) — tiến trình web (uvicorn, request, tải file) giữ ưu tiên thường. Kiểm: khi làn chuẩn bị + render chạy đầy CPU, request trang web và tải file (`Range`) vẫn nhanh (đo thời gian phản hồi trang + tốc độ tải một file lớn trước / sau, ghi Result).

## Goal

Làn `prepare` chạy tối đa N job cùng lúc (khóa config, mặc định 1 = như cũ), mỗi job Whisper dùng số luồng đã chia; đo và đặt N + luồng tối ưu cho 32 nhân để 86 tập Địa Tạng chuẩn bị nhanh hơn ≥ 1,8 lần.

## Scope

- In scope:
  - **P1 Config.** `[web] prepare_workers` (1–8, mặc định 1) và `[transcript.whisper] cpu_threads_per_job` (0 = `cpu_threads` / `prepare_workers`, làm tròn xuống, tối thiểu 1) hoặc cách tương đương IMPLEMENTER chọn (ghi Result). `cpu_threads` không đổi nghĩa khi `prepare_workers = 1`; không đổi hash transcript (thực thi, như CP11 R2).
  - **P2 Hàng đợi.** Làn `prepare` có N thread worker; giữ đúng các luật hiện có: thứ tự + ưu tiên (CP8.26), tạm dừng toàn cục (CP8.22), đợi YouTube (chỉ job cần tải bị chặn; nhiều worker cùng thấy chặn), prefetch (`PREFETCH_LIMIT` theo job đã chuẩn bị đợi làn `ai`; job prepare-only CP13.2 không tính), đợi GPU, bền qua khởi động lại, CP8.28 monitor (hiện N job đang chạy của làn), log job theo thread. Một episode không chạy hai job cùng lúc (khóa episode sẵn có); Short và `.kt` cùng video có thể chạy song song nếu an toàn (ingest `.kt` dùng nguồn gốc — đợi ingest gốc xong, nếu cần thì không chạy cùng lúc).
  - **P3 Whisper.** Model cache an toàn khi nhiều thread (mỗi thread / mỗi số luồng một instance hoặc khóa — IMPLEMENTER chọn, đo RAM); `cpu_threads` cho mỗi job theo P1.
  - **P4 Đo.** Trên bản sao 3–4 tập Địa Tạng (audio thật, không ghi `work/` chính): đo thời gian chuẩn bị tổng cho N = 1 / 2 / 3 / 4 với luồng chia tương ứng (và một mức luồng khác nếu rẻ), ghi load; chọn mặc định đề xuất cho `config.toml` (ORCHESTRATOR áp dụng sau merge, ghi trong Result). Chạy đo khi các thí nghiệm khác đã xong hoặc ghi rõ nhiễu.
  - Test + README / Test policy nếu cần.
- Out of scope: Whisper trên GPU (CP14); song song làn `ai` / `render` (`[render] jobs` đã có); đổi model Whisper.

## Authority / key decisions

- `docs/tasks/CP8.10-queue-lanes.md`, `docs/tasks/CP8.22-queue-pause-persist.md`, `docs/tasks/CP8.26-priority.md`, `docs/tasks/CP8.28-monitor.md`, `docs/tasks/FIX-youtube-botcheck-wait.md`, `docs/tasks/CP13.2-hd-first.md`, `docs/tasks/CP11-performance-measure.md` + `docs/decisions/CP11-performance-report.md` (R2 luồng Whisper).

## Acceptance Criteria

1. `prepare_workers = 1`: hành vi giống hệt trước (test hiện có PASS).
2. `prepare_workers = 3`, 6 job giả: tối đa 3 chạy cùng lúc, thứ tự bắt đầu theo hàng đợi + ưu tiên; tạm dừng / đợi YouTube / khởi động lại đúng.
3. Whisper mỗi job nhận đúng số luồng chia; transcript giống hệt (byte) với chạy tuần tự cùng tham số model (hoặc ghi rõ nếu số luồng khác làm đổi kết quả và hash không đổi).
4. Đo P4: bảng thời gian N = 1..4; mức đề xuất nhanh hơn N = 1 ≥ 1,8 lần (hoặc ghi lý do + số tốt nhất).
5. Monitor (CP8.28) hiện mọi job đang chạy của làn `prepare`.
6. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–3, 5, 6.
- Đo P4 thật (bảng trong Result) — AC 3, 4.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080 sau khi đặt config: tab Theo dõi thấy N job chuẩn bị chạy cùng lúc; CPU VM dùng nhiều hơn.

## Result

- Main changes:
  - P1 config: `[web] prepare_workers` (1-8, default 1), `[transcript.whisper] cpu_threads_per_job` (0 = `cpu_threads` (or CPU count) / workers, rounded down, min 1; `cpu_threads` unchanged when workers = 1; `config.whisper_threads_per_job`); `create_app` hands every job the per-job value (execution-only, not in the transcript hash: test).
  - P2 `web/jobs.py`: worker "slots" (`prepare`, `prepare#1`, ..; other lanes keep one). Rules kept: priority order, pause after / now (every running job is cut and requeued), persistence (all running jobs saved at the head), prefetch (`PREFETCH_LIMIT` on the ai queue, as before; up to N more may land), per-thread job logs. Added: jobs of the same video (`<id>`, `<id>.kt`) never prepare at once; YouTube block: at the retry time only one job makes the try (`Job.probe`), the other download jobs wait for its outcome, a job that was already running when another got the block returns without counting a second failure; no-download jobs still start. Monitor: `lanes[lane].running_all` + `workers` (`running` = the first), UI lists all; `lane_tids` / process rows use the slot (`prepare#1`) -> job.
  - P3 Whisper: each job builds its own `FasterWhisperBackend` (own model instance), so no sharing between workers; the model cache also got a lock. One instance per job: ~2.3 GB RSS per job (int8 large-v3-turbo).
  - Amendment 1: `lower_thread_priority` (os.setpriority on the native tid + ioprio_set best-effort level 7); `[web] worker_nice` (0-19, default 10) is applied to every worker thread of the prepare / render lanes (not `ai`). Priority is per thread on Linux and inherited, so ffmpeg / yt-dlp children and the Whisper thread pool (checked: 50 threads nice 10, main thread 0) are low priority with no change to the stages; uvicorn / requests keep normal priority. No `[render] threads` change was needed (exists).
- Tests: `tests/test_prepare_parallel_cp829.py` (14: 3 workers / 6 jobs order + max concurrency, priority, N = 1 old behaviour, same-video clash, pause after / now, YouTube block + single try, persistence, monitor, per-thread logs, config + hash, app threads per job, nice per thread + child inheritance). Full suite `pytest -q -n 8`: 1516 passed, 1 skipped (CPU of the VM was shared). `node scripts/framework-check.mjs`: PASS.
- P4 measurement (Whisper large-v3-turbo int8, no nice; 4 clips of 150 s from 4 Dia Tang episodes = 10 min of audio, a new model per clip like production, N workers pull from the queue). Noise: production Whisper (~4.5 cores) + another IMPLEMENTER (enhance bench ~10 cores) + later other jobs; load average 22-60 during the runs, so absolute times are about 2.5x slower than an idle VM; compare back-to-back rows only.

| N x threads | total s | load1 at start / end |
|---|---|---|
| 1 x 24 | 539.6 | 26.7 / 22.1 |
| 2 x 12 | 271.9 | 22.1 / 26.1 |
| 3 x 8 (4 clips: 2 rounds) | 263.6 | 25.7 / 26.4 |
| 4 x 6 | 300.2 | 26.4 / 44.7 |
| 6 x 4 (4 clips: = 4 jobs) | 384.1 | 44.7 / 58.2 |
| 1 x 24 (repeat, later) | 843.7 | ~50 / 45 |
| 4 x 6 (repeat, later) | 309.2 | ~45 / 50 |

  Speedup vs 1 x 24: 2.0x (N=2), 2.0x (N=3, limited by 4 clips / 3 workers), 1.8x and 2.7x (N=4: vs the first / the repeat 1 x 24 run, which ran under much heavier load). A single 24-thread job used only ~4-5 cores (production job: ~450 % CPU), so more jobs is the lever, not more threads. AC4 met (>= 1.8x at N = 2..4). With 86 episodes the 4 clips / 3 workers rounding does not apply. Not measured: N=4 with 8 threads each; N > 4 gets slower under this load (6 x 4 = 384 s).
- AC3 transcript identity: 3 of 4 clips gave identical word-level output for every N / thread count (also vs the 24-thread run). Clip `LeqFAlSS2oA` varied between runs (5 distinct outputs over 7 runs, including two 24-thread runs), i.e. int8 decoding is not bit-reproducible there regardless of N; the config hash does not change with threads / workers (test), as with CP11 R2. Not a regression of this task.
- A1 check (test server on 8081, own workspace, a 209 MB source served with Range; 3 prepare jobs x 16 + 4 render jobs x 8 busy child processes for 50 s on top of the shared VM at load 50-70; 25 x 2 page requests `/api/monitor/queue` + `/api/episodes`):

| | idle page median / p95 | saturated page median / p95 | Range idle -> saturated |
|---|---|---|---|
| `worker_nice = 0` (before) | 5 / 8-9 ms | 14-16 / 37-42 ms | 142-148 -> 76-86 MiB/s |
| `worker_nice = 10` (after) | 6 / 9-11 ms | 6-7 / 13-15 ms | 183-226 -> 130-151 MiB/s |

  The VM was already loaded by other sessions, so the "idle" rows are not truly idle; with the priority change, saturation costs the web ~25-30 % of the download speed instead of ~45 %, and page latency stays flat. I did not add `ionice`/`nice` wrappers around individual children (inherited from the thread; ionice effect not measured separately).
- Recommended `config.toml` (ORCHESTRATOR applies after merge): `[web] prepare_workers = 4`, `worker_nice = 10`; `[transcript.whisper] cpu_threads_per_job = 8` (leave `cpu_threads = 24` for N = 1). 4 x 8 = 32 threads in the pool but each job uses ~4-5 cores, ~18-20 cores in total, ~10 GB RAM, all at nice 10 so web and downloads win any contention. `[render] jobs = 4` stays; render now also runs niced. If the 3090 (CP14 later) or other jobs need CPU, `prepare_workers = 3` is nearly as fast in the table. Re-measure on an idle VM if exact numbers matter.
- Review: ORCHESTRATOR 2026-10-04 — ACCEPTED, không có blocking finding. Đã kiểm: N slot làn prepare giữ luật ưu tiên / tạm dừng / YouTube / bền; cùng video không chuẩn bị song song; mỗi job một backend Whisper; nice theo luồng (prepare + render), web giữ ưu tiên thường; số đo A1 (trang 14→6 ms, tải 76→130 MiB/s khi bão hòa); chạy lại 79 test liên quan PASS. Ghi chú: commit `efcb17c` của ORCHESTRATOR (`git commit -am`) lỡ gom cả WIP code của IMPLEMENTER cùng branch — nội dung đúng, chỉ lịch sử commit lẫn. Lưu ý vận hành: `config.toml` hiện `[render] jobs = 2` (không phải 4).
- Important findings / decisions: `worker_nice` default 10 changes the default behaviour (heavy lanes at low priority) even with `prepare_workers = 1`; set 0 to disable. A restart restores the saved queue jobs of any slot into the lane in order; `prepare_workers` can change between restarts.
- Known limitations: downloads of several prepare jobs may overlap (one YouTube download per worker); `.kt` waits only for a *running* base job (as in serial order); prefetch can overshoot `PREFETCH_LIMIT` by up to N - 1 jobs; ioprio_set only on x86_64 / aarch64.
- PR: #72
