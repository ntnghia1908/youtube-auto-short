# Task: FIX-dl-abort-grace — Hàng đợi tải không tải lại khi token `aborted` chỉ thoáng qua (follow-up CP8.34)

## Status / Approval

- Status: IN_PROGRESS
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — fix nhỏ tự chứa trong máy trạng thái thuần có test Node sẵn, effort `medium`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng
- Authorization mode: task
- Authorization source: follow-up ở Result CP8.34 (log thật A1d, 2026-10-18) + `docs/workflow/current-state.md` Next action 4; HUMAN LEAD APPROVE 2026-10-19
- Parallel group: —
- Owned paths: `src/auto_short/web/static/dlqueue.js`, `src/auto_short/web/static/app.js` (chỉ `dqStatusText`), `tests/test_dlqueue_cp834.py`, file này
- Dependencies: CP8.34 (#88, đã merge)
- Base commit / branch: `79436e8` (origin/main) / `fix/dl-abort-grace`
- Human Lead approval: accepted 2026-10-19 (chat "APPROVE FIX-dl-abort-grace": D1–D4)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ logic client `dlqueue.js`; route / state của `GET /api/downloads/{token}` trong CP8.3 web contract giữ nguyên.

## Bối cảnh (2026-10-19, ORCHESTRATOR)

- Log thật từ điện thoại (CP8.34 Result, A1d): Chrome Android tải một bản dọc bằng 3 request Range song song cùng URL (cùng token), huỷ từng khúc khi chạm khúc sau và có lúc mở lại khúc. Trong tích tắc giữa hai request khúc, không còn request nào chạy và request cuối kết thúc bằng ngắt → server báo `aborted` đúng luật A1b (`_Entry.state()` trong `src/auto_short/web/downloads.py`).
- Client (`DownloadQueue.report` trong `static/dlqueue.js`) coi một lần thấy `aborted` là lỗi ngay → `fail()` → chờ 5 s → tải lại bằng token mới. Trình quản lý tải của điện thoại vẫn tải tiếp bản cũ → **cùng file tải hai lần** (tốn băng thông — đúng điều HUMAN LEAD muốn tránh ở CP8.34 — và thừa một file trong máy).
- Trang hỏi trạng thái mỗi 2 s (`DQ_POLL_MS`), mỗi lần hỏi có hạn 10 s (`DQ_POLL_TIMEOUT_MS`).

## Goal

Một `aborted` thoáng qua (request khúc mới tới trong vài giây) không làm hàng đợi tải lại file; ngắt thật (mất mạng, huỷ tải) vẫn tự thử lại như CP8.34 D4, chỉ chậm hơn tối đa một khoảng chờ.

## Quyết định cục bộ (S1, ORCHESTRATOR đề xuất — HUMAN LEAD xác nhận khi duyệt)

- **D1 Sửa ở client, không đổi server.** Ý nghĩa `aborted` của `/api/downloads/{token}` (CP8.3 web contract, sửa đổi CP8.34) giữ nguyên; trang tự chờ. Lý do: không chạm public API (giữ S1), máy trạng thái client đã thuần và có test Node. Phương án khác (server chỉ báo `aborted` sau N giây không còn request) đổi ngữ nghĩa API → S2, không chọn.
- **D2 Khoảng chờ `abortGraceMs` = 10 000 ms** (option của `createQueue`, có trong `DEFAULTS`). Lần đầu thấy `aborted` → ghi thời điểm, item vẫn `sending`. Câu trả lời sau là `sending` / `done` → xoá mốc (tiếp tục bình thường / xong). Vẫn `aborted` và `now − mốc ≥ abortGraceMs` → `fail(…, "bị ngắt giữa chừng")` như cũ. 10 s ≈ 5 lượt hỏi, đủ rộng so với khoảng hở "tích tắc" trong log; ngắt thật → bắt đầu thử lại sau ≤ 10 s + 2 s hỏi + 5 s chờ.
- **D3 Áp dụng mọi loại file** (zip / bản dọc / bản ngang HD) và cả `aborted` do route trả lỗi (`DownloadTable.fail`): một luật, lỗi thật chỉ chậm thêm ≤ 10 s.
- **D4 Trang hiện trạng thái chờ.** Trong khoảng chờ, cột trạng thái ghi "đang tải · mất kết nối, chờ nối lại…" (kèm MB như hiện nay) thay vì im lặng.

## Scope

- In scope: D1–D4 trong `dlqueue.js` (`report`, reset mốc ở `step` / `retry`), `dqStatusText` trong `app.js`, test Node.
- Out of scope: đổi `web/downloads.py` / route / API; điểm treo còn lại của review A1 (một khúc kết thúc bình thường còn lỗ, không còn request chạy → `sending` mãi); tải tiếp bằng Range; theo dõi tiếp token cũ sau khi đã thử lại; HTTPS cho 8080.

## Authority / key decisions

- `docs/decisions/CP8.3-web-contract.md` — sửa đổi CP8.34 (route `GET /api/downloads/{token}`, state `sending | done | aborted`): không đổi.
- `docs/tasks/CP8.34-sequential-download.md` — D3 / D4 (thử lại 2 lần, chờ 5 s, "Thử lại"), A1b (luật state server), A1c (hỏi độc lập, hạn 10 s), Result (log A1d + follow-up này).

## Implementation approach

- `createQueue`: thêm `abortGraceMs` vào `DEFAULTS`; item thêm trường mốc (vd `abortedAt`, `0` = không chờ), reset khi `step` bắt đầu lần thử mới và khi `retry`.
- `report`: nhánh `aborted` → đặt mốc nếu chưa có, chỉ `fail` khi đã quá `abortGraceMs`; nhánh `sending` / `done` xoá mốc. Câu trả lời `null` (404) giữ luật `noRequestMs` hiện có.
- `dqStatusText`: chữ D4 khi item `sending` có mốc chờ.

## Phải giữ nguyên

- Server: `web/downloads.py`, route tải, `GET /api/downloads/{token}` — không sửa; `tests/test_web_downloads_cp834.py` PASS không sửa.
- CP8.34 D4: tối đa 2 lần thử lại, chờ `retryWaitMs` 5 s, token mới mỗi lần, rồi `error` + "Thử lại"; file khác vẫn chạy.
- `noRequestMs` 60 s khi server chưa thấy request; bỏ qua câu trả lời của token cũ; hỏi độc lập từng item (A1c); `pause` / `resume`, `skipped`, giới hạn 1–3 cùng lúc, `keepAwakeMode`.
- Zip `done` → `loadPlaylist()` (tick "Đã đăng") như cũ.

## Code bị thay / xóa

- Nhánh `else if (info.state === "aborted") fail(i, now, "bị ngắt giữa chừng");` trong `report` của `dlqueue.js` — thay bằng luật D2, không giữ bản cũ.
- Test cũ trong `tests/test_dlqueue_cp834.py` báo `aborted` liên tục nên dự kiến PASS không sửa; nếu phải chỉnh thì chỉ chỉnh mốc thời gian, ghi lý do trong READY report.

## Acceptance Criteria

1. `aborted` rồi `sending` (hoặc `done`) trước khi hết 10 s → item không lỗi, `attempts` không tăng, không có token mới; `done` → item `done`.
2. `aborted` kéo dài ≥ 10 s (nhiều lượt hỏi) → lỗi như cũ: thử lại đúng 2 lần, mỗi lần cách ≥ 5 s, rồi `error`; file khác vẫn tiếp tục.
3. Mốc chờ theo từng lần thử: lần thử mới (token mới) bắt đầu không có mốc; `aborted` đã ngắt quãng (`aborted` → `sending` → `aborted`) tính lại từ lần `aborted` sau; câu trả lời của token cũ không ảnh hưởng.
4. Trong khoảng chờ, cột trạng thái hiện chữ D4.
5. Server và route tải không đổi; toàn bộ suite PASS.

## Required verification

- `python -m pytest -q -x --tb=short tests/test_dlqueue_cp834.py` — AC 1–3 (cần `node`; IMPLEMENTER chạy được trong sandbox).
- `node --check src/auto_short/web/static/app.js` + test tĩnh / Node cho chữ D4 nếu tách được, hoặc review diff + manual test — AC 4.
- `python -m pytest -q tests/test_web_downloads_cp834.py` — AC 5 (có uvicorn thật / loopback → ORCHESTRATOR chạy ngoài sandbox).
- `python -m pytest -q -n auto` — AC 5, ORCHESTRATOR chạy trước READY.
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API contract (chỉ logic trang). Manual test sau automated verification là điểm danh, nhưng lỗi chỉ thấy trên điện thoại nên đây là bằng chứng chính; 8080 ghim commit nhánh (restart: hỏi HUMAN LEAD).

- [ ] Trang bộ kinh, 4 bản dọc, cùng lúc 2 → đủ 4 file, **không file nào tải hai lần** (trình quản lý tải của máy; log server không có token mới cho cùng file khi không có lỗi thật).
- [ ] Tắt Wi-Fi giữa chừng một file → thấy "mất kết nối, chờ nối lại…", rồi tự thử lại (≈ 15 s), vẫn mất mạng → lỗi + "Thử lại"; bật lại → "Thử lại" được.
- [ ] Zip vẫn tick "Đã đăng" sau khi xong.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
