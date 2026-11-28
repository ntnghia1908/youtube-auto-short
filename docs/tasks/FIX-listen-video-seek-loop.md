# Task: FIX-listen-video-seek-loop — Nghe chung: chuyển bài thì một máy đen hình nhưng vẫn có tiếng

## Status / Approval

- Status: IN_PROGRESS (chờ manual test 8080)
- Type: BUG
- Change class: S1 — chỉ JS phía trình duyệt của player (tab Nghe / Xem chung); không đổi API / dữ liệu / dependency
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota 5 giờ 4 %, tuần 35 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-28: "Đồng ý" sau đề xuất "khi video đang tua / chưa có hình thì chờ, không tua thêm"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/player.js` (chỉ `syncVideo` và listener của `this.video`), `tests/test_web_listen.py` (thêm test), file này
- Dependencies: none
- Base commit / branch: `cb101df` (origin/main) / `fix/listen-video-seek-loop` (worktree `~/projects/yas-vseek`)
- Human Lead approval: accepted 2026-11-28
- Implementation authorized: YES

## Bằng chứng (2026-11-28)

- HUMAN LEAD: nghe chung, cả 2 máy mở màn hình; chuyển bài thì máy A đen hình nhưng vẫn nghe tiếng; tải lại trang A thì có hình.
- Log 8080 (`player {...}` trong tmux `youtube:web`): client `20e13a…` ghi `video_resync` liên tục (giới hạn 1 dòng / 5 s), `drift` ≈ 0,51–0,56 suốt > 30 s sau mỗi lần đổi bài (vd t = 5,7 → 30,7). Video đang phát bình thường thì drift ≈ 0 và không có resync liên tục.
- `syncVideo` chạy trên mỗi `timeupdate` của audio (~250 ms). Khi `|drift| > 0.5` nó gán `video.currentTime`. Lúc vừa đổi nguồn, audio `.m4a` phát ngay còn video `.mp4` cần > 0,5 s để tua. Trong lúc `video.seeking`, audio chạy thêm > 0,5 s → lại gán `currentTime` → seek mới hủy seek cũ → video không bao giờ có khung hình (đen), tiếng vẫn chạy.

## Goal

Sau khi đổi bài (tay, phòng, tự chuyển), video hiện hình và chạy theo tiếng trên mọi máy trong phòng, kể cả máy chậm / mạng yếu; không cần tải lại trang.

## Scope

- In scope: trong `syncVideo`, không tua lại video (bỏ qua chỉnh drift) khi `video.seeking` hoặc video chưa có dữ liệu để phát (`video.readyState < HAVE_FUTURE_DATA`), trừ khi `force` và video không đang seeking; video tua xong (`seeked`) / có dữ liệu (`canplay`) thì gọi lại `syncVideo` để đo drift mới.
- Out of scope: đổi ngưỡng 0,5 s, đổi audio / phòng / nghe nền / PiP, đổi server.

## Phải giữ nguyên

- Audio là đồng hồ chính; video luôn muted; video tạm dừng khi ẩn trang / audio dừng.
- Drift > 0,5 s khi video sẵn sàng vẫn được tua lại và ghi `video_resync` (giới hạn 5 s như cũ).
- `syncVideo(true)` sau `loadedmetadata` / `visibilitychange` vẫn tua về đúng vị trí audio khi video không đang seeking.
- Toàn bộ hành vi nghe nền, early start, hidden advance, PiP, phòng (WATCH1 / LISTEN1 / LISTEN2) giữ nguyên.

## Code bị thay / xóa

- Không có (thêm điều kiện chờ trong `syncVideo` + listener `seeked` / `canplay` của video).

## Acceptance Criteria

1. Video đang `seeking`: các `timeupdate` của audio với drift > 0,5 không gán thêm `video.currentTime` (không seek chồng).
2. Video `readyState < 3` (chưa seeking): không gán `currentTime` theo drift; khi video phát `canplay` / `seeked` thì drift được đo lại và tua nếu > 0,5.
3. Video sẵn sàng, drift > 0,5 → tua 1 lần như cũ; play video khi audio chạy vẫn được gọi.
4. Test cũ của `tests/test_web_listen.py` + `tests/test_web_watch_party.py` PASS; full suite PASS.

## Required verification

- `PYTHONPATH=<worktree>/src pytest -q tests/test_web_listen.py` (IMPLEMENTER, AC1–3 bằng harness node có sẵn).
- `node --check src/auto_short/web/static/player.js`.
- `pytest -q -n auto` (ORCHESTRATOR, ngoài sandbox) — AC4.

## Manual test checklist (Tech Lead)

- [ ] 2 điện thoại, 8080 = commit của task, Nghe chung: chuyển bài ≥ 5 lần (nút Sau, chọn trong danh sách, tự chuyển) → cả 2 máy có hình, không cần tải lại.

## Result

- IMPLEMENTER 2026-11-28: implementation hoàn tất, sẵn sàng ORCHESTRATOR review; chưa xác nhận READY toàn task vì verification toàn file bị treo ở HTTP TestClient trong sandbox, AC4 / full suite còn chờ ORCHESTRATOR.
- `syncVideo` chỉ chỉnh drift khi không seeking và (`force` hoặc `readyState >= 3`); giữ nguyên rate, play, mute, pause, ngưỡng 0,5 s và log resync. Listener `seeked` / `canplay` gọi lại `syncVideo`, đặt sau handler action hiện có để handler cũ xử lý mark trước khi resync arm lượt seek mới.
- Không thêm helper / harness. Đã tìm bằng `rg -n 'harness|video_resync|Fake|fake|def .*player|node|syncVideo' tests/test_web_listen.py`; tái dùng `run_player_js`, fake `Element`, `boot`, `metadata`, `settled`, `visibility`, `useRoomTransport`. Bổ sung bước fake video readyState=4 + canplay sau loadedmetadata trong helper `metadata` để các test playback cũ mô phỏng video đã sẵn sàng; không sửa assertion cũ.

| AC | Test / bằng chứng |
|---|---|
| AC1 | `test_player_js_video_drift_waits_for_seek_and_data[seeking-*]`: setter đếm seek, 8 timeupdate và force khi seeking không gán thêm; seeked đo lại drift, không phát action thừa. |
| AC2 | Cùng test, `[canplay-*]` / `[seeked-*]`: readyState=2 không tua, readyState=4 + event tua một lần. |
| AC3 | Cùng test, `[ready-*]`: tua một lần, play được gọi, rate / muted và log throttle giữ nguyên. Các mode đều chạy solo và room. |
| Giữ force | `test_player_js_video_force_seeks_before_canplay`: loadedmetadata / visibilitychange tua khi readyState=2 và không seeking; không tua khi seeking. |
| AC4 | Phần không HTTP của `tests/test_web_listen.py`: 167 PASS; 2 HTTP test chưa xác minh; `tests/test_web_watch_party.py` và full suite do ORCHESTRATOR chạy. |

- Diff (`git diff --numstat`): ứng dụng **+2 / −1**; test **+71 / −1**.
- Verification:
  - `node --check src/auto_short/web/static/player.js`: PASS (exit 0).
  - `PYTHONPATH=/home/ntnghia/projects/yas-vseek/src python -m pytest -q tests/test_web_listen.py`: Python mặc định thiếu pytest (`No module named pytest`).
  - Chạy lại với `PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH`: treo ở `test_http_listen_auth_404_and_queue`, đã ngắt; lượt `-v` xác định đúng test này. Lượt loại riêng test đó cũng treo khi tới HTTP test còn lại; không claim PASS cho hai HTTP test.
  - `PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH PYTHONPATH=/home/ntnghia/projects/yas-vseek/src python -m pytest -q tests/test_web_listen.py -k 'not test_http'`: **167 passed, 2 deselected in 14.93s**.
  - `git diff --check`: PASS.
- Không commit / push / PR, không gọi agent khác hoặc mạng thật. Manual test hai điện thoại còn chờ Tech Lead.
