# Task: FIX-web-shutdown-slow — Restart 8080 mất 7–8 phút khi tắt server

## Status / Approval

- Status: BLOCKED
- Type: BUG
- Change class: S1 — không đổi architecture / dependency / API; chỉ cách các vòng nền dừng khi tắt + log chẩn đoán
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-08: "Task sửa lỗi restart chậm làm ngay" (sau đề xuất: ghi log thời gian từng bước tắt + sửa việc làm chậm để dừng ngay, làm tiếp sau khi chạy lại)
- Parallel group: P1 (song song LISTEN1, path rời: LISTEN1 không sửa phần lifespan / vòng nền của `app.py`)
- Owned paths: `src/auto_short/web/app.py` (chỉ lifespan + các vòng nền `_source_backup_loop`, `_offload_loop`, `_shorts_offload_loop`, `_redownload_loop`, `_store_retry_loop`, `_auto_archive_loop`, `_post_link_loop` và hàm pass chúng gọi), `src/auto_short/web/server.py`, các module thực thi việc nền đó khi cần thêm điểm dừng (`src/auto_short/store/*.py`, `src/auto_short/review/backup*.py`, downloader dùng cho redownload), `src/auto_short/theme_render/sources.py` (validator / băm / wrapper tải), `src/auto_short/ingest/probe.py` (ffprobe), `src/auto_short/web/post_links.py`, `src/auto_short/publish/youtube.py` (chỉ điểm dừng HTTP / vòng sync) — ORCHESTRATOR bổ sung 2026-11-08 theo boundary "module thực thi việc nền đó", tests tương ứng (`tests/test_web_shutdown.py` mới + test sẵn có của module bị sửa), file này
- Dependencies: none
- Base commit / branch: `bc2ee68` (origin/main) / `fix/web-shutdown-slow` (worktree `~/projects/yas-shutdown`)
- Human Lead approval: accepted 2026-11-08 ("làm ngay")
- Implementation authorized: YES

## Bằng chứng (2026-11-08)

- 2 lần restart liên tiếp (script `auto-short-web-restart`, làn prepare / ai / render = 0): chờ ~420 s và ~480 s từ Ctrl-C tới khi tiến trình thoát. Các lần restart sáng cùng ngày: vài giây.
- Log tmux: `Shutting down` → `Waiting for connections to close` → `Cancel 1 running task(s), timeout graceful shutdown exceeded` (stream video của điện thoại, ~5 s) → `Waiting for application shutdown` → … → `Application shutdown complete`. Không có giờ trên dòng log → không biết bước nào lâu.
- `store.shorts.candidates(...)` lúc đó = 0 → không phải đẩy Short. Còn lại: `_offload_loop` (bản dọc / HD, băm + tải lên), `_redownload_loop` (tải lại nguồn YouTube), `_source_backup_loop` / `_store_retry_loop` (không được await nhưng thread `asyncio.to_thread` vẫn giữ tiến trình: executor join lúc thoát), `sampler.stop`, `runner.stop`.
- Không có py-spy; `ptrace_scope = 1` → không chụp được stack tiến trình đang chạy từ ngoài.

## Goal

Ctrl-C trên 8080 (làn rảnh) → tiến trình thoát trong ≤ 30 s, dù đang có việc nền (băm, tải lên kho, tải lại nguồn); việc dở được làm tiếp / làm lại an toàn sau khi chạy lại. Lần tắt nào > 15 s thì log tự cho biết đang chờ gì.

## Scope

- In scope:
  - Log có thời gian (`time.monotonic`) cho từng bước trong `finally` của lifespan và `runner.stop` / `sampler.stop`: "tắt: <bước> xong sau X s".
  - Watchdog: nếu shutdown chưa xong sau 15 s → ghi stack mọi thread (`faulthandler.dump_traceback(all_threads=True)` vào stderr / log), lặp mỗi 60 s. `faulthandler.register(signal.SIGUSR1, all_threads=True)` để ops chụp stack bất kỳ lúc nào (`kill -USR1 <pid>`).
  - Rà mọi việc nền chạy trong `asyncio.to_thread` / thread riêng: mỗi việc phải dừng trong ≤ 5 s sau khi có cờ dừng (`offload_stop`, `shorts_stop`, cờ mới cho redownload / source backup / store retry nếu chưa có): kiểm cờ trong vòng đọc / băm / tải lên / tải xuống theo khối; ngắt tiến trình con (yt-dlp, ffmpeg) bằng terminate → kill sau 3 s.
  - Việc bị ngắt giữa chừng phải an toàn: không để bản ghi `store.json` / `backup.json` sai, file tạm được dọn ở lần chạy sau (tái dùng sweep có sẵn `_sweep_store_temps`, `app_sweep`), lần chạy sau làm lại từ đầu việc đó.
  - Kết quả rà ghi vào Result: bảng việc nền → cách dừng → thời gian dừng đo được trong test.
- Out of scope: đổi lịch / logic của việc nền, đổi định dạng file trạng thái, `timeout_graceful_shutdown` của uvicorn (giữ 5 s), job trong làn (script restart đã từ chối khi làn bận).

## Phải giữ nguyên

- Hành vi bình thường của mọi vòng nền (offload, shorts offload, redownload, source backup, store retry, auto archive, post link) khi không tắt.
- Thứ tự khởi động trong lifespan, `runner.begin_stop()` trong `handle_exit`.
- Đảm bảo an toàn khi crash đã có (SHO1 / HD2b: file local thắng, xác minh sha256 trước khi giải phóng).

## Code bị thay / xóa

- Các `await asyncio.gather(<task>)` chờ không giới hạn trong `finally` của lifespan → chờ có giới hạn + log (sau khi việc nền đã dừng được thật).

## Acceptance Criteria

1. Mỗi bước tắt ghi log có thời gian; tắt > 15 s → stack mọi thread trong log; `SIGUSR1` → stack.
2. Test: mỗi việc nền dài (giả lập băm file lớn / tải lên chậm / tải xuống chậm / tiến trình con chạy lâu) dừng ≤ 5 s sau cờ dừng; lifespan shutdown tổng ≤ 10 s với tất cả cùng chạy.
3. Test: việc bị ngắt không ghi trạng thái "đã xong / đã giải phóng"; lần chạy sau làm lại được (file tạm được dọn).
4. Chạy thật 8080: restart khi có việc nền đang chạy (hoặc ít nhất khi làn rảnh như 2 lần bằng chứng) → thoát ≤ 30 s; log ghi thời gian từng bước.

## Required verification

- `PYTHONPATH=~/projects/yas-shutdown/src conda run -n auto-short pytest tests/test_web_shutdown.py <test module bị sửa> -q`
- Full suite `pytest -n auto -q`.
- AC 4: `auto-short-web-restart --ref <commit>` trên 8080 (ORCHESTRATOR), đọc log tmux. 8080 hiện ghim nhánh LISTEN1 → chạy thật sau khi gộp / hoặc ghim tạm commit fix rồi ghim lại LISTEN1.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API → điểm danh.

- [ ] Restart 8080 nhanh (≤ 30 s) trong ngày sau merge.

## Result

- Implementation 2026-11-08 vòng 1: BLOCKED (cần thêm Owned paths) → ORCHESTRATOR bổ sung, vòng 2 tiếp tục. Phần Owned paths đã sửa và tự review; còn điểm dừng trong validator nguồn / ffprobe / post-link ngoài danh sách file rõ ràng của contract. Đã hỏi bổ sung boundary, chưa nhận trả lời; không tự sửa các file đó. Required verification chuẩn và AC4 cũng chưa PASS.
- Main changes:
  - Lifespan đặt `background_stop`, `offload_stop`, `shorts_stop` trước mọi bước chờ; giữ thứ tự startup, `runner.begin_stop()` và uvicorn grace 5 s. Thay gather vô hạn bằng một `asyncio.wait` với deadline chung 9,5 s; log từng vòng, worker, sampler, runner, tổng lifespan và tên bước quá hạn.
  - `_background_call` shield + theo dõi task chạy `to_thread`, để hủy vòng ngoài không làm mất dấu worker thật. Một stop scope riêng cho mỗi worker truyền event tới StoreClient / backup mà không đặt cờ toàn tiến trình hoặc làm ảnh hưởng thread khác.
  - Watchdog dump mọi thread sau 15 s, lặp 60 s. `serve` giữ watchdog qua cả giai đoạn executor join của `asyncio.run`; đăng ký SIGUSR1 và gỡ khi server kết thúc.
  - Store PUT / replace kiểm cờ ở mỗi lần đọc; fetch kiểm mỗi block đọc/băm và trước rename. Request đang kẹt được watcher shutdown socket; giữ timeout HTTP thông thường. Kiểm cờ trước ghi confirmation / release. Sửa `open_stream` để giữ và đóng đúng response context sau thay đổi quản lý request.
  - Tái dùng `OffloadStopped`, stop events và hàm băm theo block (chuyển implementation từ offload sang `store/cancellation.py`, re-export ở offload). Backup / redownload không đánh dấu xong khi bị ngắt; Short không tính lại snapshot tốn công trong shutdown.
  - Downloader yt-dlp chỉ trong stop scope chạy library hiện có trong process group riêng; terminate → kill sau 3 s, bao gồm ffmpeg/node con. Download bình thường ngoài scope tiếp tục đường library cũ. TemporaryDirectory hiện có dọn việc redownload bị ngắt; startup tiếp tục gọi `app_sweep` / `_sweep_store_temps` như trước.

### Rà việc nền

Thời gian dưới đây là thời gian **worker thật kết thúc sau đặt cờ**, không phải thời gian hủy coroutine. Fake không gọi Store / YouTube / Ollama thật. Đo toàn lifespan có ghi chú harness bên dưới.

| Việc | Chạy ở đâu / thao tác dài trước sửa | Cờ trước sửa | Cách dừng đã thêm / phần còn thiếu | Thời gian test |
|---|---|---|---|---|
| `_offload_loop` | `to_thread`: băm GB, PUT, HEAD, confirm/release bản dọc + HD | Băm có `offload_stop`; HTTP không có | Tái dùng cờ; kiểm block + shutdown socket đang chờ | Băm/PUT fake < 0,001 s; socket kẹt 0,042 s |
| `_shorts_offload_loop` | `to_thread`: băm từng Short, PUT/HEAD, ghi store.json, unlink; finally tính snapshot | `shorts_stop` có ở băm/giữa clip; HTTP không có | Scope cờ cho upload; bỏ snapshot khi đã dừng; không ghi release khi upload bị ngắt | Primitive fake < 0,001 s; interruption + retry PASS |
| `_source_backup_loop` | `to_thread`: inventory, validator workspace/cache băm GB, PUT/HEAD, memo | Không | Stop scope, từng video, HTTP, hash trực tiếp trong backup; **validator nhập từ theme_render/sources vẫn chưa dừng được giữa băm** | HTTP fake < 0,001 s; toàn pass chưa chứng minh ≤ 5 s |
| `_redownload_loop` | `to_thread`: validator inventory, yt-dlp Python, ffmpeg merge, ffprobe subprocess, băm, PUT/HEAD | Không | Stop scope + process group yt-dlp/ffmpeg + Store I/O; **ffprobe và hash trong theme_render/sources chưa có điểm dừng** | Process 0,022 s; bỏ qua TERM 3,022 s; toàn pass chưa chứng minh ≤ 5 s |
| `_store_retry_loop` | `to_thread`: HEAD nhiều video/Short, submit lại job | Không | Stop scope tới HTTP, kiểm từng job và trước submit dưới lock | HEAD fake < 0,001 s; test 7 worker xác nhận không submit sau dừng |
| `_auto_archive_loop` | `to_thread`: inventory, backup_state(path) HEAD + băm nguồn trước archive/unlink | Không | Kiểm giữa video/tập; backup_state dùng hash theo block + HTTP có stop scope | Primitive băm/HEAD fake < 0,001 s; toàn worker trong harness dừng cùng nhóm 0,013 s |
| `_post_link_loop` | `to_thread`: sync_all → nhiều YouTube/OAuth request, quét và ghi bài/journal | Không | Theo dõi worker + deadline/log; **HTTP YouTube và vòng sync thật chưa nhận cờ** | Fake hợp tác dừng cùng nhóm 0,013 s; sync thật chưa chứng minh ≤ 5 s |
| `runner.stop` | Thread làn riêng; ngắt job/descendants, join, lưu queue; timeout cũ 30 s + cleanup | `_stopping`, interrupt và signal con có sẵn | Gọi `begin_stop` trước; `stop(timeout=5)` cùng deadline lifespan (hàm có thêm tối đa ~4 s cleanup) | Runner thật, làn rảnh: 0,003 s |
| `sampler.stop` | Thread daemon riêng quét /proc/disk; join tối đa 5 s | `_stop` có sẵn | Giữ stop hiện có, chạy join đồng thời và log riêng | Sampler thật: 0,001 s |

### AC → test / verification

| AC | Test / bằng chứng | Trạng thái |
|---|---|---|
| 1 | `test_watchdog_repeats_until_closed_and_server_registers_usr1`; `test_lifespan_waits_for_all_seven_workers_and_logs_steps` | Watchdog/đăng ký signal PASS chuẩn; log lifecycle PASS trong harness chẩn đoán |
| 2 | `test_slow_io_stops_real_worker_within_five_seconds` (6 phase); `test_long_subprocess_terminates_then_kills_within_five_seconds` (2 phase); test lifespan; `test_http_watchdog_interrupts_a_blocked_socket_without_shortening_timeout`; `test_idle_runner_and_sampler_stop_within_budget` | Primitive/idle PASS; lifespan fake 0,013 s trong harness. **Chưa đạt toàn AC** vì các đường thật còn thiếu điểm dừng |
| 3 | `test_interruption_does_not_confirm_release_or_finish_and_can_retry` (source/vertical/shorts/redownload); test cũ `test_store_temp_report_and_safe_startup_sweep`; tests lỗi dọn temp redownload | PASS các đường đã sửa; không claim các đường còn thiếu |
| 4 | Restart 8080 + đọc log tmux | Chưa chạy; ORCHESTRATOR thực hiện sau gộp / ghim ref phù hợp |

AC2 dùng 5 hàm test thay ngân sách mặc định 3 vì cần phân biệt fake đọc block, socket bị kẹt thật về mặt transport, process TERM/KILL, lifecycle giả lập đủ 7 worker và runner/sampler thật khi rảnh. Các nhánh giống nhau đã parametrize; reuse artifact builders/fake store có sẵn trong test module.

- Tests đã chạy bằng `PYTHONPATH=/home/ntnghia/projects/yas-shutdown/src conda run --no-capture-output -n auto-short ...`:
  - `pytest tests/test_web_shutdown.py -q -x --tb=short -s -k 'not lifespan'`: **15 passed, 1 deselected**, 4,22 s.
  - `pytest tests/test_store_offload.py tests/test_store_shorts.py tests/test_store_backup.py tests/test_store_redownload.py tests/test_ingest_youtube.py -q -x --tb=short -k 'not test_loop_uses_thread_and_short_success_delay and not test_lifespan_stops_hash_worker and not test_background_io_uses_thread_and_waits_retry_seconds and not test_background_thread_sleep_snapshot_and_lifespan_cancellation'`: **153 passed, 4 deselected**, 11,76 s.
  - Nhóm StoreClient không socket (`-k 'test_client_token_from_env_only or test_config_store_section or test_put_streams or test_put_maps or test_put_heads or test_put_existing or test_put_rejects or test_short_client or test_hdi1_replace'`): **35 passed, 14 deselected**, 0,95 s; đã sửa regression open_stream tìm thấy ở lần chạy đầu.
  - Lệnh chuẩn gồm lifecycle treo tại `selectors.select`, worker executor đã idle; timeout 35/60/90 s (exit 124). Stack chẩn đoán từ pytest `faulthandler_timeout=10` xác nhận event loop không được đánh thức trong sandbox. **Không claim PASS**.
  - Chẩn đoán bổ sung ngoài repo: `/tmp/fix-shutdown-related-check.py` chỉ đặt event-loop policy thêm timer 10 ms để xử lý lỗi đánh thức ở sandbox rồi gọi pytest trên 7 module trên + test_hd_backup: **192 passed**, 21,11 s (trước khi thêm test idle cuối); không thay source/test để né lỗi và **không thay thế required verification chuẩn**. Riêng harness lifecycle: **5 passed**, cả 7 worker dừng trong 0,011–0,013 s.
  - Full suite `pytest -n auto -q`: đã chạy, timeout 90 s, có lỗi, chưa hoàn tất. Lần kiểm sau sửa open_stream dùng `-x --tb=short` cũng timeout 40 s do worker khác treo; không PASS. Log `/tmp/fix-web-shutdown-full.log`, `/tmp/fix-web-shutdown-full-first-error.log`.
  - Tách lỗi socket: `pytest tests/test_store_client.py::test_client_index_head_fetch -q --tb=short`: **ERROR**, `PermissionError: [Errno 1] Operation not permitted` tại tạo socket fake server 127.0.0.1. Cần ORCHESTRATOR chạy lại module đầy đủ và full suite ngoài sandbox.
  - `git diff --check`: PASS. Compile các module store/app/server: PASS.
- Diff + / − (bao gồm file source/test mới chưa tracked, không tính contract): application **+450 / −74**, tests **+414 / −57**. `app.py` riêng **+132 / −30**. Không commit / push / PR.
- File đổi: `web/app.py`, `web/server.py`; `store/cancellation.py` mới, `store/{backup,client,offload,redownload,shorts}.py`; `review/backup.py`; `ingest/youtube.py`; `tests/test_web_shutdown.py` mới và `tests/test_store_{backup,offload,redownload}.py`; contract này. Không sửa LISTEN1 hoặc file ngoài Owned paths.
- Helper mới (đã tìm, lý do không tái dùng):
  - Tìm bằng `rg -n 'OffloadStopped|_check_stop|sha256|stop|terminate|kill|dump_traceback' src/auto_short/{store,ingest,web}` và đọc runner/sampler/sweep. Chuyển/re-export helper stop/hash có sẵn; không giữ hai implementation băm theo block.
  - `stop_scope/current_stop/cancellable`: truyền cờ qua hàm lồng nhau và các callback chỉ trong worker hiện tại. `urlopen` theo dõi socket + `_UploadStream`: urllib/file hiện có chưa có cơ chế ngắt socket/đọc block khi shutdown.
  - `_background_call`: giữ worker thật sau cancel coroutine. `_ShutdownWatchdog` + `stop_step`: chưa có watchdog/timing shutdown, cần sống qua executor join.
  - `run_process`, `_ytdlp_process`, `_download_worker`: giữ options và phân loại lỗi yt-dlp hiện có nhưng sở hữu được process group; cleanup toàn descendants trong runner dành cho lane, không dùng cho từng lần download riêng.
- Review: tự rà diff/AC; regression response context đã sửa và test lại. Chưa có review ORCHESTRATOR; không gọi agent khác.
- Important findings / decisions: cancel `asyncio.to_thread` chỉ bỏ await, không dừng thread; timeout lifespan đơn độc không bảo đảm process thoát vì Python còn join executor. Không coi test fake 7 worker là bằng chứng các hàm thật ngoài boundary đã hợp tác dừng.
- Known limitations / next action:
  - Cần xác nhận thêm Owned paths tối thiểu cho `theme_render/sources.py` (validator/hash/download wrapper), `ingest/probe.py` (ffprobe), `web/post_links.py` và `publish/youtube.py` (HTTP/loop post-link); giữ `review/archive.py` chưa sửa vì điểm dừng HEAD/hash đang đi qua backup_state đã được sửa. Các điểm này còn có thể giữ executor quá 30 s.
  - Context stop không tự ngắt validator / API client không kiểm nó. Không âm thầm monkeypatch hàm dùng chung, nhân bản validator hoặc bỏ join executor để che thiếu sót.
  - ORCHESTRATOR chạy required verification chuẩn/full suite và AC4; HUMAN LEAD/ORCHESTRATOR chốt boundary trước phần còn lại. Không đủ điều kiện READY theo mục Required verification của contract.
- PR: không tạo theo yêu cầu.
