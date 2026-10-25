# Task: HD2a — Kho 3090 + nguồn HD / dọc từ kho cho tập đã giải phóng

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, full suite, chạy thật (kho giả trên VM + 3090 thật sau khi HUMAN LEAD cài)
- Implementer: phần A (kho Windows, `tools/store/`) — Codex CLI (tự chứa, stdlib, test không cần socket); phần B (client + tích hợp VM) — claude-code `implementer` (Sonnet) (job / route web, test web). Hai phần owned paths rời nhau, làm nối tiếp trên cùng branch.
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: `docs/decisions/HD2-external-store-3090.md` ACCEPTED (HUMAN LEAD 2026-10-25 "ok cả hai"), G1–G4 + G8
- Parallel group: —
- Owned paths: A — `tools/store/` (mới: `store.py`, `setup-store.ps1`, `config.example.json`, `test_store.py` hoặc `tests/test_store_server.py`), `docs/guides/store-3090.md` (mới). B — `src/auto_short/store/` (mới: client), `src/auto_short/config.py` (`[store]`), `src/auto_short/enhance/state.py`, `src/auto_short/render/stage.py`, `src/auto_short/render/full.py`, `src/auto_short/review/backup.py`, `src/auto_short/web/jobs.py`, `src/auto_short/web/app.py`, `src/auto_short/web/routes/episodes.py`, `src/auto_short/web/routes/playlists.py`, `src/auto_short/web/static/app.js`, `config.example.toml` (nếu có), `tests/test_store_client.py` (mới), contract này.
- Dependencies: HD1a + FIX-hd-owner-kt (PR #144)
- Base commit / branch: `be8cb7f` / `feature/hd2a-store`
- Human Lead approval: HD2 ACCEPTED 2026-10-25
- Implementation authorized: YES

## Goal

3090 chạy dịch vụ kho (ổ E) qua kênh SSH sẵn có; VM dùng bản HD / dọc trên kho cho tập đã giải phóng: tạo bản dọc còn thiếu, render Short / khai thị, ghép chủ đề — file tải từ kho được kiểm **đúng sha256 đã giải phóng**, dùng xong xóa; kho tắt → "đợi 3090".

## Scope

- In scope: HD2 G1 (kho), G2 (kênh + token + cài đặt), G3 (tên / index), G4 (nguồn cho job), G8.
- Out of scope: HD2 G5 (tải qua web), G6 (đẩy file mới lên kho), G7 (Bộ nhớ) → HD2b; nguồn YouTube.

## Authority / key decisions

- HD2 G1–G4, G8 (canonical). Kho chỉ nghe `127.0.0.1:18090` trên 3090; SSH `RemoteForward 127.0.0.1:18090 127.0.0.1:18090` thêm vào block `gpu-worker-v4` (setup script sửa block do `setup-enhance-worker.ps1` tạo, có backup `~/.ssh/config`). Token: header `Authorization: Bearer`, env VM `AUTO_SHORT_STORE_TOKEN`, so sánh hằng thời gian.
- Thư mục gốc mặc định `E:\AutoShortStore`; mỗi bộ kinh khai báo thư mục trong `config.json` của kho (`{"series": {"<playlist_id>": "E:\\KinhDiaTang_HD"}}`), Kinh Địa Tạng dùng thư mục sao lưu hiện có. Ánh xạ `video_id`/`kind` → file qua `index.csv` + `SHA256SUMS.txt` do `backup.ps1` ghi (cột `video_id`, `loai` HD/Doc, `file`).
- VM: `released` + kho có file với sha = `backup.json released.<kind>.sha256` → tải về đúng chỗ cũ (`work/<owner>/source_hd.mp4` / file dọc tạm), job xong xóa (`released` giữ nguyên); render key không đổi. Kho tắt / thiếu / sha khác → job không lỗi đỏ mà ở trạng thái "đợi 3090" (như "đợi HD", E6), thử lại theo chu kỳ khi kho trả lời; nút "Render bằng bản gốc" giữ nguyên.

## Implementation approach

- A: `store.py` (http.server + ThreadingHTTPServer, stdlib): `GET /index`, `HEAD|GET /files/<video_id>/<kind>` (Range, 206, Content-Length, header `X-Sha256`), `PUT` (`.part` → kiểm sha header → rename → cập nhật sums + index; cho HD2b, có sẵn từ đầu), chặn path traversal / symlink, log không chứa token. `setup-store.ps1`: tìm env Python của worker enhance, chép `store.py`, tạo token (in ra một lần để dán lên VM), thêm RemoteForward, đăng ký Task Scheduler tự chạy khi đăng nhập (mẫu như worker), `-Uninstall`. `docs/guides/store-3090.md`: cài đặt + kiểm tra.
- B: `auto_short/store/client.py` (urllib): `index()`, `head(video_id, kind)`, `fetch(video_id, kind, dest, sha256)` (tải `.part`, kiểm sha, rename), `available()`. `[store] url = "http://127.0.0.1:18090"`, `enabled = false` mặc định. Tích hợp vào chỗ HD1a đang từ chối "HD đã chuyển ra máy ngoài" (render stage, vertical job, effective_source) → lấy từ kho; trạng thái chờ + thử lại trong `web/app.py` / `jobs.py` theo mẫu "đợi HD".

## Phải giữ nguyên

- Tập chưa giải phóng: không đổi gì. Short cũ của tập đã giải phóng vẫn hiện hành. `[store] enabled = false` → hành vi HD1a.

## Code bị thay / xóa

- Thông báo từ chối "HD đã chuyển ra máy ngoài" của HD1a trở thành nhánh "kho tắt / không bật" (không xóa test, sửa theo hành vi mới).

## Acceptance Criteria

1. Kho: index / HEAD / GET Range / PUT đúng; sai token 401; path lạ 400 / 404; PUT sai sha không ghi.
2. VM, kho bật, tập released: tạo bản dọc / render Short dùng file từ kho, sha kiểm khớp, file tạm bị xóa sau job, render key Short cũ không đổi; `.kt`-owner (FIX-hd-owner-kt) chạy được.
3. Kho tắt / file thiếu / sha khác: job ở trạng thái chờ, không lỗi đỏ, không rơi về bản gốc im lặng; kho bật lại → job tiếp tục.
4. `[store] enabled = false`: hành vi HD1a, test HD1a pass.

## Required verification

- A: test kho (không socket nếu chạy trong sandbox Codex; ORCHESTRATOR chạy thêm test có socket).
- B: `tests/test_store_client.py` + test HD1a / FIX + test module sửa; full suite (ORCHESTRATOR).
- Chạy thật: kho chạy trên VM với thư mục giả (ORCHESTRATOR); sau khi HUMAN LEAD cài trên 3090: tạo bản dọc 1 tập Kinh Địa Tạng đã giải phóng từ kho.

## Manual test checklist (Tech Lead)

Thêm kênh mạng + token (security model) → manual test là gate.

- [ ] 3090: chạy `setup-store.ps1`, dán token lên VM; web thấy kho.
- [ ] Giải phóng 1 tập rồi bấm tạo bản dọc: dựng từ kho, xong không còn file tạm trên VM.

## Result

- Main changes: A (Codex, 62,6k tokens, 1 lượt) — `tools/store/store.py` (index từ `danh-sach.csv` / `index.csv` + `SHA256SUMS.txt`, HEAD / GET Range / PUT kiểm sha, Bearer token hằng thời gian, chỉ `127.0.0.1`, chặn traversal / symlink / junction), `setup-store.ps1` (tìm Python worker, token, RemoteForward vào `gpu-worker-v4` có backup, Task Scheduler, `-Uninstall`), `docs/guides/store-3090.md`. B (Sonnet) — `auto_short/store/client.py` (fetch `.part` + Range + sha), `store/borrow.py` (`borrow_hd`: mượn HD vào chỗ cũ, sha = `backup.json released.hd`, đếm lượt dùng, xóa sau job), `[store]` config (mặc định tắt), `run_render` / `_run_vertical` mượn HD khi released + kho bật, `StoreWait` → job "đợi 3090" (interrupted, không đỏ) + `store_retry_pass` mỗi `retry_seconds`, `render_full.current` so sha đã giải phóng, route / view `store`, `app.js` "HD trên 3090".
- Tests: `tests/test_store_server.py` 87, `tests/test_store_client.py` 14 (server thật trên 127.0.0.1); targeted 124 + 201 passed; full suite 2612 passed, 1 failed (test chập chờn `test_lower_thread_priority…`).
- Chạy thật trên VM: kho thật `store.py` cổng 18191, thư mục giả đúng định dạng `danh-sach.csv` PowerShell (BOM, ngoặc kép), media hard link; bản sao tập 11 `54iAdqkUMrY`: xác nhận + giải phóng (2,78 GB) → `run_render` mượn HD qua HTTP, kiểm sha, chạy xong xóa file mượn, `released` giữ nguyên; kho tắt → `StoreWait` "đợi 3090: không kết nối được kho", manifest không đổi. Đối chứng không giải phóng: render cũng encode lại 18 lần (tập vốn cũ so cấu hình / đường dẫn bản sao) → HD2a không gây render lại. Short thật không bị đụng (render ghi file mới rồi đổi tên, link trong bản sao bị thay).
- Diff + / − (app, test): A +657 (server / setup / config / docs), test +372; B app ≈ +360 / −11, test ≈ +330.
- Helper mới (đã tìm, lý do không tái dùng): `StoreClient`, `borrow_hd`, `released_hd_sha`, `StoreWait` / `StoreWaitJob` (cơ chế "đợi HD" gắn với pipeline giữa các làn, không tái dùng được — làm bản tối thiểu), phía kho: `no_links`, `inside`, `parse_range`, `Store`.
- Review: ORCHESTRATOR — an ninh kho đạt; `borrow_hd` chỉ xóa file chính nó tải; ghi nhận hạn chế bên dưới.
- Known limitations: ghép chủ đề (theme_render) chưa mượn từ kho → HD2b; job "đợi 3090" chỉ tự thử lại khi web còn chạy (restart thì bấm lại); web tắt giữa lúc mượn → file mượn nằm lại (HD2b dọn); `.part` dở trên kho chặn PUT cùng tên tới khi xóa tay; `run_vertical` tải cả HD kể cả khi bản dọc đã có; setup Windows chưa chạy được trên VM (gate: cài trên 3090).
- PR:
