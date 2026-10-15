# Task: FIX-youtube-id-dash — Video YouTube có id bắt đầu bằng `-` / `_`

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `c568f1b` (`main`) / `fix/youtube-id-dash` (worktree `../youtube-auto-short-yid`)
- Human Lead approval: APPROVED 2026-10-15 (chọn "Nới D3 cho id YouTube" — theo đề xuất ORCHESTRATOR cùng ngày; phạm vi ghi dưới đây)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: sửa luật id tập CP2 D3 (HUMAN LEAD đã quyết ở decision gate) cho đúng với id YouTube thật; không đổi dependency, security model, public API (cùng route, chỉ nhận thêm id hợp lệ).

## Bối cảnh (2026-10-15, ORCHESTRATOR)

- Bấm xử lý tập 13 / 102 Địa Tạng (`-RjgLgw_iVk`), Thập Thiện tập 21 (`-9AytPxmjLc`) → HTTP 500. Log 8080: `POST /api/submit` → `web/app.py` `_queue_video` → `khaithi.episode_id_for` → `KhaithiError: invalid episode id '-RjgLgw_iVk' … (must start with a letter or digit …)`; `KhaithiError` không được bắt → 500.
- Nguyên nhân: CP2 D3 nói id tập YouTube = video id 11 ký tự, nhưng regex `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` cấm ký tự đầu `-` / `_` — id YouTube thật dùng bảng `[A-Za-z0-9_-]` ở mọi vị trí. Nhánh Short (`eid = video_id`) cũng sẽ fail ở stage đầu.
- Ảnh hưởng hiện tại (`work/_playlists/*.json`): 22 tập ở 4 bộ kinh (Vô Lượng Thọ 11, Cảm Ứng Thiên 4, Địa Tạng 6, Thập Thiện 1); ~3 % video nói chung.
- Thư mục hệ thống ở gốc workspace: `_playlists` (10 ký tự), `_sutras` (7), `_deleted` (8), `_learning` (9), `_post-backups` (13), file `.web_*` / `.enhance_state.json` — không cái nào dài đúng 11 ký tự.

## Goal

Mọi video YouTube (id 11 ký tự `[A-Za-z0-9_-]`) xử lý được như video thường — Short, khai thị (`<id>.kt`), enhance, bài đăng, tải về, CLI — với episode id = video id như CP2 D3. Lỗi id không hợp lệ (nếu còn) ở web trả 4xx có thông báo, không 500.

## Scope

- In scope:
  - **I1 Luật id (sửa CP2 D3).** Id tập hợp lệ khi khớp **một trong hai**: (a) luật cũ `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`; (b) id YouTube `^[A-Za-z0-9_-]{11}$`, có thể kèm hậu tố khai thị `.kt` (CP8.9 K1). Không nhận `.` đầu, `..`, `/`. Ghi sửa đổi vào `docs/decisions/CP2-workspace-contract.md` D3 (canonical; dòng "Sửa đổi FIX-youtube-id-dash (HUMAN LEAD 2026-10-15)"), kèm ràng buộc: tên thư mục hệ thống mới ở gốc workspace bắt đầu bằng `_` / `.` **không được** dài đúng 11 ký tự (hoặc 14 với `.kt`). Pointer ngắn ở CP8.9 K1 nếu cần.
  - **I2 Mọi nơi kiểm id dùng chung luật.** `workspace.validate_episode_id` + `iter_manifests`; rà các regex / kiểm tra riêng còn giả định ký tự đầu là chữ / số hoặc bỏ qua thư mục bắt đầu `_` / `-`, tối thiểu: `web/app.py` `_LEASE_ID_RE` (lease enhance, nếu chứa episode id), `post/images.py:196` (bỏ qua thư mục `_…` → phải phân biệt thư mục hệ thống với tập `_xIElIoe2Ls`), `web/episodes.py`, `web/playlists.py`, enhance service / state, worker enhance (`tools/enhance_worker`, nếu kiểm id). Không đổi `_CLIP_ID_RE`, `SLUG_RE` (không phải episode id).
  - **I3 Không có id bắt đầu `-` thành tham số dòng lệnh.** Rà mọi `subprocess` / yt-dlp / ffmpeg: id / đường dẫn có id phải là đường dẫn tuyệt đối hoặc URL (không phải argv trần bắt đầu `-`). CLI `auto-short`: `--episode-id=-xxx` hoặc `--` dùng được; ghi vào README nếu cần.
  - **I4 Web không 500 vì id.** `KhaithiError` / `WorkspaceError` từ id ở `api_submit` (và route tương tự) → 422 với thông báo tiếng Việt.
  - Test cho các điểm trên.
- Out of scope: đổi cách đặt id (tiền tố…); di chuyển / đổi tên workspace có sẵn; tự xếp hàng lại 22 tập (HUMAN LEAD bấm); mọi thay đổi khác của bộ kinh / hàng đợi.

## Authority / key decisions

- `docs/decisions/CP2-workspace-contract.md` D3 (sửa theo I1), `docs/decisions/CP8.9-khai-thi-contract.md` K1, `docs/decisions/CP8.3-web-contract.md` W7 (API).
- K1: episode id YouTube = video id, không đổi.

## Acceptance Criteria

1. `validate_episode_id` nhận `-RjgLgw_iVk`, `_xIElIoe2Ls`, `-RjgLgw_iVk.kt`, mọi id cũ hợp lệ; vẫn từ chối `.x`, `..`, `a/b`, `-abc` (không đủ 11 ký tự), `_playlists`, `_sutras`, `_deleted`, `_learning`, `_post-backups`, chuỗi rỗng, > 128 ký tự.
2. `POST /api/submit` với video `-RjgLgw_iVk` (Short + khai thị, downloader giả) → 200, job xếp hàng; chạy pipeline giả đủ stage tới render, workspace `work/-RjgLgw_iVk/` và `work/-RjgLgw_iVk.kt/`.
3. Trang bộ kinh / tập / tải về / bài đăng / ảnh bài đăng hiện đúng tập có id `-…` và `_…`; `iter_manifests` liệt kê chúng, vẫn bỏ qua `_playlists` v.v.
4. Enhance: lease / nộp kết quả cho tập `-…` chạy được (route worker).
5. Id không hợp lệ ở API → 422, không 500.
6. Không có lệnh con nào nhận id bắt đầu `-` làm argv trần (test hoặc rà soát ghi trong Result).
7. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–7.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Trên 8080 (ghim commit nhánh): bấm xử lý Thập Thiện tập 21 và Địa Tạng tập 13 → không còn 500, job chạy hết; trang tập, tải về, bài đăng bình thường.

## Result

- Main changes: `workspace.is_episode_id` (một chủ duy nhất của luật; `validate_episode_id` + `iter_manifests` dùng) = luật cũ HOẶC `^[A-Za-z0-9_-]{11}(\.kt)?$` (`.kt` là literal vì `khaithi` import `workspace`); `post/images.usage_counts` và `post/redistribute` dùng luật chung thay vì bỏ thư mục `_…` / regex riêng; worker enhance `tools/enhance_worker/worker.py` nhận `episode_id` YouTube (bản sao regex có chú thích, tool độc lập); `web/app.py` `_queue_video`: id sai → mục lỗi 422 tiếng Việt (không 500; bulk playlist cũng nhận); CP2 D3 sửa đổi + pointer CP8.9 K1 + README (CLI `--episode-id=-x` / `--`).
- Tests: `tests/test_youtube_id_dash.py` (AC1, 2, 3, 5, 6) + `test_lease_and_put_for_a_dash_episode_id` trong `tests/test_enhance_api.py` (AC4). `pytest -q -n auto`: 1801 passed, 1 skipped; `node scripts/framework-check.mjs`: PASS.
- Review: ORCHESTRATOR 2026-10-15 — ACCEPTED vòng 1; chạy lại `python -m pytest -q -n auto` 1801 passed, 1 skipped. Lưu ý triển khai: worker enhance trên máy GPU cần cập nhật `tools/enhance_worker/worker.py` mới; worker cũ nhận lease tập `-…` / `_…` sẽ trả lease ("lease khong hop le") thay vì xử lý.
- Important findings / decisions: `_LEASE_ID_RE` (web/app.py) chỉ kiểm lease id (hex ngẫu nhiên `secrets.token_hex`), không chứa episode id → giữ nguyên. enhance service `_dir` đã dùng `validate_episode_id`; `web/episodes.py`, `web/playlists.py` dùng `validate_episode_id` / `_VIDEO_ID_RE` đã cho phép `-`/`_`. Rà subprocess / yt-dlp / ffmpeg (ingest/probe, render, analysis/detect, post/dhash, enhance service/state, sutra importer, worker): argv luôn là `str(<workspace>/<id>/…)` hoặc URL `https://youtu.be/<id>` (yt-dlp qua API Python, `canonical_url`), không có id trần ở argv; chỉ argparse CLI cần `--episode-id=-x` / `--`.
- Known limitations: Chưa chạy trên 8080 (manual test do Tech Lead). Nếu `--workspace.dir` bắt đầu bằng `-` thì đường dẫn tương đối sẽ thành argv bắt đầu `-` (không đổi, ngoài phạm vi).
- PR:
