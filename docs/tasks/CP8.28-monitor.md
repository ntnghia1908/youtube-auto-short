# Task: CP8.28 — Tab "Theo dõi": hàng đợi chi tiết, CPU VM, GPU

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `10b4185` (`main`, gồm CP8.26) / `feature/cp8.28-monitor` (worktree `../youtube-auto-short-monitor`)
- Human Lead approval: APPROVED 2026-10-04 ("Duyệt và giao cho implementer" — phạm vi ORCHESTRATOR đề xuất cùng ngày: hàng đợi chi tiết + CPU VM + GPU; CP8.28 trước CP8.27)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: mở rộng giao thức worker enhance đã chốt ở `docs/decisions/CP13.1-enhance-worker-contract.md` (heartbeat / lease mang thêm số liệu GPU) — sửa decision đó + `tools/enhance_worker/` (cài lại trên 2 máy Windows).

## Bối cảnh

HUMAN LEAD 2026-10-04: thanh hàng đợi chỉ ghi "đang chạy 3, chờ 102", không biết 3 job nào; muốn một tab theo dõi CPU / GPU đang dùng bao nhiêu %, chạy task nào. VM 32 nhân; GPU: RTX 3090 (Ollama 11437 + worker enhance `rtx3090`), RTX 3050 (worker `rtx3050`), cả hai Windows qua SSH tunnel; VM không đọc trực tiếp được GPU.

## Goal

Trang "Theo dõi" (link trên thanh điều hướng, cạnh "Bộ nhớ"), tự làm mới vài giây, cho biết: job nào đang chạy ở làn nào / bước nào / bao lâu; job nào đang đợi (HD / GPU / YouTube) và vì sao; thứ tự chờ; CPU / RAM / đĩa VM và tiến trình nặng; Ollama đang nạp model nào; % GPU / VRAM / nhiệt độ / tập đang enhance của từng máy GPU.

## Scope

- In scope:
  - **M1 Hàng đợi chi tiết.** API (ví dụ `GET /api/monitor/queue`): mỗi làn — job đang chạy (tập: bộ kinh / tập N / Short hay khai thị / id; loại job; bước hiện tại; bắt đầu lúc / đã chạy; tiến độ nếu có, ví dụ render k/n clip, enhance đoạn k/n); job đang đợi không giữ làn (đợi HD, đợi GPU, đợi YouTube — lý do, hạn thử lại); danh sách chờ đúng thứ tự sẽ chạy (thứ tự ưu tiên CP8.26), mặc định 20 / làn, có tham số xem thêm; dấu ★ ưu tiên; trạng thái tạm dừng. Thanh tóm tắt hàng đợi hiện có ở các trang: bấm → mở tab "Theo dõi".
  - **M2 CPU VM.** % CPU tổng + theo nhân (gọn), load 1/5/15, RAM, đĩa `work/`; top tiến trình theo CPU (≤ 10) với gợi ý job (whisper / ffmpeg / yt-dlp thuộc job nào nếu suy được từ cây tiến trình). Đọc `/proc` (không thêm dependency — `psutil` không có trong env); lịch sử ngắn (≈ 1 giờ, mẫu mỗi vài giây, chỉ trong RAM) để vẽ biểu đồ nhỏ.
  - **M3 Ollama.** `GET /api/ps` của Ollama (cổng cấu hình hiện có): model đang nạp, kích thước / VRAM, hết hạn; trạng thái kết nối (dùng trạng thái GPU sẵn có của hàng đợi); job làn `ai` đang gọi.
  - **M4 GPU worker.** Worker enhance (`tools/enhance_worker/worker.py`) gửi kèm số liệu `nvidia-smi` (tên GPU, % GPU, VRAM dùng / tổng, nhiệt độ, công suất; lấy mỗi lần heartbeat / may-run / lease, lỗi thì bỏ qua) — trường mới **tùy chọn**, VM cũ / worker cũ vẫn chạy (tương thích hai chiều). VM lưu số liệu mới nhất theo worker (trong RAM) + thời điểm; hiển thị cùng tập / đoạn đang làm (có sẵn từ registry worker). Worker chưa cập nhật → "chưa có số liệu GPU". Cập nhật `docs/decisions/CP13.1-enhance-worker-contract.md` (bảng API) + hướng dẫn cài lại worker (`docs/guides/enhance-worker-windows.md`: chỉ cần chạy lại setup / auto-fix — ghi rõ).
  - **M5 UI.** Trang `monitor` (HTML + JS như các trang hiện có), làm mới 3–5 s khi tab mở; biểu đồ nhỏ SVG / canvas tự vẽ (không thư viện ngoài); dùng được trên điện thoại.
  - Test (không mạng; `/proc` giả qua tham số / fixture; worker gửi trường mới / không gửi), README / hướng dẫn.
- Out of scope: cảnh báo / thông báo; lưu lịch sử lâu dài; điều khiển (dừng / chạy / hủy) từ tab này; số liệu GPU khi worker không chạy; theo dõi máy Windows ngoài GPU.

## Authority / key decisions

- `docs/decisions/CP13.1-enhance-worker-contract.md` (sửa: heartbeat / lease / may-run nhận thêm `gpu_stats` tùy chọn), `docs/tasks/CP13.1a-enhance-worker-win.md`, `docs/tasks/CP13.1b-enhance-vm.md`, `docs/tasks/CP8.10-queue-lanes.md`, `docs/tasks/CP8.22-queue-pause-persist.md`, `docs/tasks/CP8.26-priority.md`, `docs/tasks/FIX-ollama-wait.md`, `docs/tasks/FIX-youtube-botcheck-wait.md`.
- K1: không thêm dependency (đọc `/proc`, `nvidia-smi --query-gpu ... --format=csv`).
- K2: route mới sau đăng nhập web như các route khác; số liệu worker chỉ nhận qua route worker có token (E8).

## Acceptance Criteria

1. API hàng đợi: với runner giả có job chạy ở 3 làn, job đợi HD / GPU / YouTube và 30 job chờ (có ưu tiên) → trả đúng job đang chạy (tập, bước, thời gian), lý do đợi, thứ tự chờ khớp thứ tự thực sẽ chạy, giới hạn 20 / làn.
2. CPU / RAM / đĩa từ `/proc` giả đúng số; top tiến trình gán đúng job khi suy được; lịch sử giới hạn ≈ 1 giờ.
3. Ollama `/api/ps` giả → model / VRAM hiển thị; Ollama mất kết nối → báo rõ, trang không lỗi.
4. Worker gửi `gpu_stats` (test với server giả hiện có của worker) → VM lưu và API trả; worker không gửi / `nvidia-smi` lỗi → vẫn chạy, hiển thị "chưa có số liệu GPU"; VM cũ không biết trường mới → worker vẫn chạy (test).
5. Trang `monitor` có link từ thanh điều hướng và từ thanh tóm tắt hàng đợi; chưa đăng nhập → bị chặn.
6. Không regression: lệnh chuẩn PASS; `-m slow` PASS (đổi `tools/enhance_worker/`).

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–6.
- `python -m pytest -q -n auto -m slow` (env `enhance-bench` theo Test policy §8, hoặc SKIP rõ lý do) — AC 6.
- `node scripts/framework-check.mjs`.
- Chạy thật trên server test 8081 (bản sao dữ liệu nhỏ, enhance tắt hoặc token giả, không đụng 8080): mở API monitor khi có job chạy; ghi JSON mẫu vào Result.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API web. Điểm danh trên 8080 sau khi cài lại worker trên 2 máy Windows:

- [ ] Tab "Theo dõi": thấy 3 job đang chạy (tên tập + bước), danh sách chờ, CPU VM.
- [ ] 3090 / 3050: % GPU, VRAM, tập đang enhance.

## Result

- Main changes: tab "Theo dõi" (`/monitor`, link trên 5 trang + thanh tóm tắt hàng đợi; làm mới 4 s, SVG tự vẽ). Mã mới `web/monitor.py` (đọc `/proc`, `Sampler` lịch sử 720 mẫu = 1 giờ trong RAM, `/api/ps` Ollama có đệm 3 s, nhãn tập + tiến độ render k/n từ log job và `clips.json`). `JobRunner.monitor_queue()` + `lane_tids()` (jobs.py; trường `step_t0` / `step_started_at`). Route cookie: `GET /api/monitor/queue?limit=`, `/system`, `/ollama`, `/gpu`. Gán tiến trình cho job qua `/proc/<pid>/task/<tid>/children` của thread làn + cây ppid (tiến trình web: "trong tiến trình web" + các job đang chạy). Worker (`tools/enhance_worker/worker.py`, `__version__ = "2"`) gửi `gpu_stats` (`nvidia-smi`, đệm 2 s, lỗi / `--device cpu` thì bỏ trường) ở lease (body), heartbeat (body), may-run (query JSON); VM (`enhance/service.py`, `app.py`) nhận tùy chọn, `clean_gpu_stats`, giữ số mới nhất trong RAM. Cập nhật `docs/decisions/CP13.1-enhance-worker-contract.md` (bảng API + đoạn `gpu_stats`), `docs/guides/enhance-worker-windows.md` (mục "Cập nhật worker đã cài": chép lại thư mục + chạy lại `setup-enhance-worker.ps1`; `auto-fix` không đủ vì không chép `worker.py`), README. `fake_server.py` ghi lại thân / query để test.
- Tests: `tests/test_monitor_cp828.py` (17 test: AC1 hàng đợi 3 làn + đợi HD / GPU / YouTube + 30 chờ có ưu tiên + giới hạn 20; AC2 `/proc` giả + lịch sử ≤ 720; AC3 Ollama; AC4 `gpu_stats` qua lease / may-run / heartbeat, worker không gửi, server giả = VM cũ; AC5 đăng nhập + link). Lệnh chuẩn `python -m pytest -q -n auto`: 1496 passed, 1 skipped (trước khi sửa nhỏ regex `expires_at` + 1 assert; file test mới chạy lại: 17 passed). `-m slow` (env `enhance-bench`): 16 passed (lần đầu `-n 8` khi VM tải ~45 do bench CP13.3: `test_self_test_reports_vm_states` quá hạn 120 s; chạy lại `-n 3` PASS). `node scripts/framework-check.mjs`: PASS.
- Chạy thật 8081 (bản sao `~/.cache/auto-short-cp828-test/`, enhance tắt, token giả, Ollama thật `/api/ps` chỉ đọc; đã dừng): 3 job render + lease giả có `gpu_stats`; ffmpeg của job render được gán đúng làn / job. JSON mẫu (rút gọn):

```json
{
 "queue (rút gọn, 8081, render đang chạy)": {
  "lanes": {
   "render": {
    "running": {
     "id": "1",
     "episode_id": "By0ZVJTPW3Y",
     "kind": "render",
     "stage": "render",
     "elapsed_seconds": 0.2,
     "episode": {
      "label": "Thái Thượng Cảm Ứng Thiên · Tập 5",
      "kind": "short"
     },
     "progress": {
      "done": 9,
      "total": 10
     }
    },
    "pending": [
     {
      "position": 1,
      "episode_id": "DoOTuWrXHAg",
      "episode": {
       "label": "Thái Thượng Cảm Ứng Thiên · Tập 8"
      }
     },
     {
      "position": 2,
      "episode_id": "BeptYl_4Cjw"
     }
    ],
    "pending_total": 2
   }
  },
  "waiting": [],
  "paused": false
 },
 "system (rút gọn)": {
  "cpu_pct": 90.2,
  "ncpu": 32,
  "load": [
   55.75,
   47.15,
   34.21
  ],
  "ram_pct": 9.9,
  "disk.path": "/home/ntnghia/.cache/auto-short-cp828-test/work",
  "top[lane=render]": {
   "pid": 206703,
   "comm": "ffmpeg",
   "cpu_pct": 315.6,
   "lane": "render",
   "job": {
    "id": "1",
    "episode_id": "By0ZVJTPW3Y",
    "kind": "render",
    "stage": "render"
   }
  }
 },
 "ollama": {
  "connected": true,
  "host": "http://127.0.0.1:11437",
  "models": [
   {
    "name": "qwen3:30b",
    "size_mb": 20712,
    "vram_mb": 20712,
    "expires_at": "2026-10-04T18:03:22.9236555+07:00"
   }
  ],
  "error": null,
  "gpu": {
   "state": "ok",
   "since": null,
   "error": null,
   "next_check": null
  },
  "job": null
 },
 "gpu": [
  {
   "name": "rtx3090",
   "label": "rtx3090-sim",
   "gpu": "RTX 3090",
   "connected": true,
   "last_seen": "2026-10-04T10:59:08Z",
   "seen_seconds": 4.986949682235718,
   "yield": false,
   "episode": null,
   "progress": null,
   "gpu_stats": {
    "name": "NVIDIA GeForce RTX 3090",
    "util_pct": 87.0,
    "mem_used_mb": 9000.0,
    "mem_total_mb": 24576.0,
    "temp_c": 71.0,
    "power_w": 310.5
   },
   "gpu_stats_age": 4.986949682235718,
   "gpu_stats_stale": false
  }
 ]
}
```

- Review:
- Important findings / decisions: (1) Trường `gpu_stats` ở `may-run` là query JSON (GET không có body). (2) Hạn thử lại YouTube / GPU lấy từ `next_check` có sẵn của runner. (3) Tiến độ render là best-effort (đếm dòng `render: clip <id>:` trong 200 dòng log gần nhất / số clip trong `clips.json`); enhance: số đoạn lấy từ `progress` của worker. (4) `expires_at` Ollama bỏ phần thập phân giây cho mọi trình duyệt parse được. (5) Test dừng runner phải `wait_idle` trước `stop()` (stop ngắt luồng làn bằng async exception có thể kẹt khóa nếu còn việc đang chạy).
- Known limitations: tiến trình nặng thuộc job chỉ suy được khi là con của luồng làn (ffmpeg / yt-dlp); Whisper / phân tích trong tiến trình web hiện là "trong tiến trình web" cùng danh sách job đang chạy, không tách theo làn. Không có cảnh báo / lịch sử dài / điều khiển (ngoài scope). Số GPU chỉ có sau khi cài lại worker trên 2 máy Windows (manual test checklist, chưa chạy).
- PR: (chưa; ORCHESTRATOR)
