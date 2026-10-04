# Task: CP8.28 — Tab "Theo dõi": hàng đợi chi tiết, CPU VM, GPU

## Status / Approval

- Status: APPROVED
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

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
