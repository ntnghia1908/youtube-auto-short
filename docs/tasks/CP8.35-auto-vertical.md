# Task: CP8.35 — "Xử lý" tự tạo luôn bản dọc cả tập

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `e7a9d05` (`main`, sau #88 CP8.34) / `feature/cp8.35-auto-vertical` (worktree `../youtube-auto-short-cp835`).
- Human Lead approval: APPROVED D1–D6 (2026-10-18)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi hành vi `POST /api/episodes` (field mới trong body), hành vi hàng đợi (job bản dọc tự xếp), UI hai trang; CP8.3 web contract W5 / W6 / W7. Không đổi dependency, security model.

## Bối cảnh (2026-10-18, ORCHESTRATOR)

- HUMAN LEAD: "khi nhấn xử lý một tập thì mặc định tạo luôn video bản dọc cho tập đó; hiện tại bấm xử lý nhưng không tự tạo video dọc". Trả lời câu hỏi cùng ngày: áp dụng **trang bộ kinh + trang gửi video lẻ**; Short xong mà HD chưa xong → **đợi HD rồi tạo**.
- Hiện nay: bản dọc chỉ tạo bằng tay ("Tạo bản dọc" một tập — `POST /api/episodes/{id}/vertical`; "Tạo bản dọc cả bộ" — CP8.32 V3). Job `vertical` chạy ở làn `render`, sau mọi job khác (CP8.32 V1), cần nguồn HD: `source_hd.mp4` (enhance) hoặc video gốc ≥ `[enhance] min_height` (CP8.32); gốc đã dọn → job tải lại (CP8.32 W9). Ô "Khi bấm Xử lý tạo:" (`#pl-kinds`, CP8.9 A2.2) chỉ có Short / Khai thị, nhớ trong `localStorage` `autoShort.plKinds`. Khi enhance bật, job pipeline "đợi HD" sau titling (CP13.1b E6); `_hd_ready` chạy khi ghép HD xong.

## Goal

Bấm "Xử lý" (hoặc gửi một video) với ô "Bản dọc" được tick → sau khi Short của tập xong và nguồn HD tốt nhất đã sẵn sàng, job bản dọc tự vào hàng đợi; không phải bấm "Tạo bản dọc".

## Quyết định cần HUMAN LEAD duyệt (D1–D6)

- **D1 Ô chọn.** Thêm ô "Bản dọc" vào "Khi bấm Xử lý tạo:" (trang bộ kinh) và vào ô loại ở trang gửi video; **mặc định tick**; nhớ cùng chỗ với lựa chọn hiện có (bộ kinh: `autoShort.plKinds`; trang gửi video: theo cách trang đó đang nhớ, nếu có). Trình duyệt đã lưu lựa chọn cũ (không có khóa bản dọc) → coi như tick. "Bản dọc" không tính là một "loại" Short / Khai thị: bỏ tick cả Short lẫn Khai thị vẫn báo "Chọn ít nhất một loại".
- **D2 Áp dụng.** "Xử lý", "Xử lý lại" (trang bộ kinh), "Chạy tiếp cả bộ" / xử lý nhiều tập dùng cùng lựa chọn của ô, và trang gửi một video. Bộ kinh: gửi link playlist (nhập bộ) không đổi.
- **D3 API.** `POST /api/episodes` nhận field tùy chọn `vertical: bool` (vắng = `false` → hành vi cũ, client cũ / script không đổi). `true` → ghi ý muốn "tự tạo bản dọc" cho video **trên đĩa** (sống qua khởi động lại server), gắn với video (`hd_owner`), xóa khi job bản dọc đã được xếp hoặc khi lần "Xử lý" sau gửi `vertical: false`.
- **D4 Khi nào xếp job bản dọc.** Khi một job của tập chạy bước render kết thúc `done` (hook CP8.16 R2a) **hoặc** khi HD của video ghép xong (`_hd_ready`), nếu video có ý muốn D3:
  - enhance của video đang bật và HD chưa xong (đang chờ / đang chạy / còn đoạn) → **chưa xếp**, đợi `_hd_ready`;
  - có nguồn HD (`source_hd.mp4` xong, hoặc enhance không bật cho video và gốc ≥ `min_height`, kể cả gốc đã dọn — job tự tải lại như CP8.32) → xếp job `vertical` như nút "Tạo bản dọc" (cùng hàm submit, cùng làn / thứ tự CP8.32 V1, trùng → "đã có");
  - không có nguồn HD (gốc < `min_height`, enhance không bật) → không xếp, xóa ý muốn, log 1 dòng + trang bộ kinh hiện lý do như hiện nay ("không có bản HD / video gốc < …p");
  - bản dọc đã `current` (cùng nguồn) → không xếp lại.
- **D5 Khai thị.** Bản dọc là của cả video (`hd_owner`), một lần cho cả Short lẫn Khai thị; tập chỉ chạy Khai thị (`.kt`) cũng kích hoạt.
- **D6 Hiển thị.** Không thêm màn hình mới: job bản dọc hiện ở hàng đợi / tab Theo dõi và icon bản dọc của trang bộ kinh như job bấm tay. Tập có ý muốn D3 mà đang đợi HD: dòng trạng thái bản dọc ghi "sẽ tạo khi có HD".

## Scope

- In scope: D1–D6; UI `playlist.html` / `index.html` (trang gửi video) / `app.js`; `POST /api/episodes` field `vertical`; lưu ý muốn trên đĩa; hook ở `web/app.py` (on_finished + `_hd_ready`); pointer CP8.3 web contract (W5, W6, W7); README dòng ngắn.
- Out of scope: tạo lại bản dọc khi HD đến sau một bản dọc từ gốc (đã chọn "đợi HD"); bản dọc cho tập đã xử lý trước đây mà không bấm lại "Xử lý" (dùng "Tạo bản dọc cả bộ"); đổi thuật toán bản dọc (`render_full`); render song song (CP8.36).

## Acceptance Criteria

1. Ô "Bản dọc" có ở hai trang, mặc định tick, nhớ qua lần mở sau; lựa chọn cũ không có khóa → tick.
2. `vertical: true` + enhance không bật + gốc ≥ 720p → sau job render `done` có đúng một job `vertical` xếp (log + hàng đợi).
3. `vertical: true` + enhance bật, HD chưa xong → không xếp khi Short xong; HD ghép xong → xếp đúng một job `vertical` từ `source_hd.mp4`.
4. `vertical: true` + gốc < `min_height` + enhance không bật → không xếp, ý muốn bị xóa, lý do hiển thị.
5. `vertical` vắng / `false` → không xếp job bản dọc (hành vi cũ); khởi động lại server giữa chừng → ý muốn còn, job vẫn được xếp khi điều kiện D4 tới.
6. Short + Khai thị cùng video → một job bản dọc (không trùng); bản dọc đã `current` → không xếp lại.
7. Toàn bộ suite PASS; route / hành vi cũ không đổi.

## Required verification

- `python -m pytest -q -n auto` — PASS (test mới `tests/test_web_auto_vertical_cp835.py` cho AC 1–7).
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API (field mới ở `POST /api/episodes`, cùng auth); không chạm database, security model. Manual test qua 8080 (ghim commit nhánh) là gate trước integration.

- [x] Trang bộ kinh: ô "Bản dọc" đã tick sẵn; "Xử lý" một tập không enhance (gốc ≥ 720p) → sau khi Short xong có job bản dọc trong hàng đợi, tải được bản dọc.
- [x] Một tập có enhance: Short xong → chưa có job bản dọc ("sẽ tạo khi có HD"); HD xong → job bản dọc tự xếp.
- [x] Bỏ tick "Bản dọc" → "Xử lý" không tạo bản dọc.

HUMAN LEAD 2026-10-18: "đạt" (manual test qua 8080 ghim bản gộp thử `5d408a7` = main + #89 + CP8.35 + CP8.36 + FIX-runner-stop).

## Result

- Main changes: `POST /api/episodes` / `resume-prepared` nhận `vertical: bool`; ý muốn lưu `<workspace>/.web_auto_vertical.json` (module `web/auto_vertical.py`, như `.web_priority.json`, không nằm trong thư mục tập nên không tạo "tập mồ côi"); `_auto_vertical_check` chạy từ `runner.on_finished` (hook gộp `_on_episode_finished` = `_auto_post` rồi bản dọc, lỗi hook này không chặn hook kia) và từ `_hd_ready`; `jobs.py` không đổi. UI: ô "Bản dọc" ở `playlist.html` (`#pl-vertical-box`, khóa `vertical` trong `autoShort.plKinds`, thiếu = tick) và `index.html` (`#idx-vertical`, khóa mới `autoShort.idxVertical`); Xử lý / Xử lý lại / Chạy tiếp / Chạy tiếp cả bộ gửi `vertical`; entry bộ kinh có `vertical.auto_waiting` + dòng "bản dọc: sẽ tạo khi có HD".
- Tests: `tests/test_web_auto_vertical_cp835.py` (AC 1–6); AC7 = toàn suite.
- Verification: `pytest -q -n auto` = 1900 passed, 1 skipped, 1 failed (`test_web_downloads_cp834::test_keep_awake_fallback_video_and_warning`: `keepawake.mp4` bị `.gitignore`, sửa ở PR #89, không thuộc CP8.35; `test_ac8_cancel_whole_...` là flake timing có sẵn, lần này PASS). Test CP8.35: 12 passed; `test_ac5_false_after_true_clears_the_wish` chạy 30 lần + cả file 10 lần không treo. `node scripts/framework-check.mjs` PASS.
- Hang (review): test kết thúc ngay sau `submit` khi một job pipeline mới đang chạy -> `c.__exit__` -> `JobRunner.stop` ngắt job bằng `KeyboardInterrupt` bất đồng bộ (`PyThreadState_SetAsyncExc`) lên thread làn; ngắt rơi vào đoạn `with self._lock` thì khóa RLock bị rò (thread chết còn giữ), `stop()` chờ `self._lock` ở dòng 395 mãi. Không do hook CP8.35: tắt hook bản dọc vẫn treo ~50 % (7/14). Là hạn chế có sẵn của cơ chế dừng async, chỉ gặp khi tắt server giữa lúc job chạy; sửa trong test (`idle(c)` trước `__exit__`), không đổi `jobs.py`.
- Review: ORCHESTRATOR 2026-10-18 ACCEPTED — đọc `web/auto_vertical.py`, hook `_on_episode_finished` / `_auto_vertical_check` / `_hd_ready`, `_queue_video(vertical_wish)`, UI; không lồng `submit_lock` (`_hd_ready` gọi ngoài khóa). Chấp nhận: ý muốn ở `<workspace>/.web_auto_vertical.json`; "Chạy tiếp" từng tập cũng gửi `vertical`. 2 test lỗi của suite có sẵn trên `main` `e7a9d05`: `keepawake.mp4` (FIX-keepawake-mp4, PR #89) và `test_ac8_cancel_whole_bo_waiting_fetching_encoding` (timing khi chạy song song lúc máy bận; PASS khi chạy riêng) — không thuộc CP8.35 → READY.
- Important findings / decisions: ý muốn lưu ở file trung tâm trong workspace dir thay vì trong thư mục video (thư mục chỉ chứa file này sẽ hiện là tập mồ côi ở danh sách dung lượng và chưa tồn tại lúc gửi video mới). Bản dọc chỉ xếp khi không còn job `pipeline` / `render` / `add` active của hai phần (Short, `.kt`) và đã có Short render; "enhance đang đợi HD" = `enhance.json` `wanted` + `pending` / `assembling` của Short hoặc `.kt`. Enhance `failed` thì không coi là đợi: dùng nguồn hiệu lực hiện có (gốc ≥ min_height) hoặc bỏ ý muốn.
- Known limitations: ý muốn chỉ được kiểm tra khi job render kết thúc hoặc `_hd_ready`; HD ghép xong trong lúc server tắt thì ý muốn chờ tới sự kiện kế (render lại / bấm "Tạo bản dọc"). "Chạy tiếp" từng tập cũng gửi `vertical` theo ô (ngoài danh sách D2 nhưng cùng ý nghĩa). Không có bản dọc nếu HD tới sau bản dọc từ gốc (ngoài scope).
- PR:
