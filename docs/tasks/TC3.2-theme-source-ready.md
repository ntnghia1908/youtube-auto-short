# Task: TC3.2 — Nguồn ghép chủ đề: chờ khi bị chặn, trạng thái nguồn, yt-dlp

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 (chọn "Nguồn: ghép không lỗi"); `docs/decisions/TC1-TC3-implementation-authorization.md` §5; `docs/decisions/SRC1-source-backup-3090.md` G5
- Parallel group: —
- Owned paths: `src/auto_short/web/theme_plan.py`; `src/auto_short/web/static/theme_plan.js`; `tests/test_web_theme_plan.py`; file này. G3 ở PR #153, không sửa `pyproject.toml` trong worktree này.
- Dependencies: SRC1 (G5 thứ tự lấy nguồn có kho 3090); SRC2 (đường tải dùng chung trong `sources.py`, 403 = chặn) — làm sau SRC2
- Base commit / branch: `bf75ab4` (`feature/src2-source-redownload`, PR #155 READY; xếp chồng SRC1 #154) / `feature/tc3.2-theme-source`. G3 đã tách thành PR #153 (`chore/ytdlp-2026.10.21`, `2979a46`); branch này không sửa `pyproject.toml`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt tất cả theo đề xuất"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì G3 đổi phiên bản dependency `yt-dlp`; phần còn lại là S1.

## Bối cảnh — bằng chứng (2026-10-25)

Job ghép 111 (VLT "Chuyển hóa tâm niệm", 7 clip) tải được `qKTzy8sYyKQ` rồi lỗi ở `xPBuSsKEY-U`: `yt-dlp download failed: ERROR: unable to download video data: HTTP Error 403: Forbidden`. `is_blocked_message` chỉ coi bot-check / 429 là "bị chặn" → 403 thành lỗi cứng, job hỏng ngay. Tải lại toàn bộ bản đã xóa lên 3090: SRC2.

## Goal

Thẻ chủ đề cho biết còn thiếu mấy video gốc; khi lúc ghép vẫn phải tải YouTube mà bị từ chối, job ghép chờ rồi tự thử lại thay vì hỏng; yt-dlp đủ mới để giảm 403.

## Scope

- In scope: G2, G3 và dòng trạng thái nguồn dưới đây.
- Out of scope: tải nền / tải lại toàn bộ (SRC2); chọn / thay clip khi thiếu nguồn; chất lượng AI.

## Authority / key decisions

- **G2 (đề xuất)**: job `theme_render` thêm bước tải nguồn ở làn `prepare` trước bước `render` (thứ tự SRC1 G5); YouTube chặn (bot-check / 429 / 403) → `YoutubeWait` (cơ chế FIX-youtube-botcheck-wait: về đầu hàng prepare, lùi dần, không giữ slot render); bản đã tải giữ trong cache.
- **G3 (đề xuất, dependency)**: nâng `yt-dlp` lên bản ổn định mới nhất đã phát hành ≥ 2 tuần; chạy test ingest / youtube; thử tải 1 video; tệ hơn → về `2026.8.19`. HUMAN LEAD 2026-10-25: làm trước SRC2 (bước riêng) để SRC2 tải bằng bản mới.
- Thẻ chủ đề: dòng "Video gốc: 6 / 7 sẵn sàng (3090: 2) · 1 cần tải YouTube" kiểm bằng `stat` + `meta.json` / index kho (không hash file lớn mỗi lần xem); hash đầy đủ vẫn ở lúc render.

## Phải giữ nguyên

- `fetch_to_cache` tạm → rename, kiểm sha / thời lượng; CLI `sources` vẫn chạy; TC3 fail closed; plan / cache key không đổi.

## Code bị thay / xóa

- Thông báo "YouTube đang chặn tải, thử lại sau" (`RenderTarget`) thay bằng trạng thái chờ của G2.

## Acceptance Criteria

1. Job ghép thiếu nguồn: bước prepare lấy nguồn trước (kho 3090 rồi YouTube); 403 / bot-check → chờ, không `failed`; đủ nguồn mới sang render.
2. Thẻ chủ đề hiện số video gốc sẵn / ở 3090 / cần tải; không hash file khi xem.
3. G3: test ingest / youtube PASS với bản mới, hoặc ghi lý do quay về.
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py tests/test_theme_render.py -x --tb=short` — AC 1–2.
- `… -m pytest -q tests/test_ingest_youtube.py tests/test_youtube_wait.py tests/test_youtube_id_dash.py` — AC 3.
- `… -m pytest -q -n auto`; `node --check src/auto_short/web/static/theme_plan.js`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- Chạy thật trên 8080 (ghim branch, hỏi trước khi restart): thẻ VLT hiện đúng số thiếu; Ghép lại "Chuyển hóa tâm niệm" → MP4.

## Manual test checklist (Tech Lead)

Không chạm database / security / public API. Manual sau automated là điểm danh.

- [ ] Thẻ chủ đề VLT hiện đúng số video gốc thiếu; sau SRC2 hiện đủ.
- [ ] Ghép "Chuyển hóa tâm niệm" ra video ≈ 35 phút, nghe 2–3 điểm nối.

## Result

- IMPLEMENTED tại `feature/tc3.2-theme-source`, base thực tế `4f74ed6`. Review fix nguồn chỉ có trên kho đã xong, sẵn sàng ORCHESTRATOR review lại; giữ `IN_PROGRESS` tới quyết định READY của ORCHESTRATOR. Không commit / push / PR, không mạng thật, không gọi agent khác.
- Files sửa: `src/auto_short/web/theme_plan.py`, `src/auto_short/web/static/theme_plan.js`, `tests/test_web_theme_plan.py`, contract này. G3 đã tách, không sửa dependency.
- G2: `theme_render` có `Step(PREPARE, prepare)` (`theme_sources`) → `Step(RENDER, self)`. Duyệt lại approval / fingerprint trước cả hai bước; mỗi video gốc chỉ chuẩn bị một lần, theo workspace → cache kiểm SHA → HEAD kho → YouTube. Lỗi kho sang YouTube; bot-check / 429 / HTTP 403 thành `YoutubeWait`, lỗi khác thành `JobFailed`; tải thành công báo `job.youtube_ok()`, giữ cache.
- `needs_download()` dùng kiểm nhẹ và `self.service.store_sources.snapshot()` để scheduler áp dụng backoff: video đã có local hoặc snapshot kho không cần YouTube, nên job chỉ dùng nguồn kho vẫn chạy khi YouTube chặn. Service giả thiếu `store_sources` dùng snapshot rỗng. `self.youtube_wait` vẫn ưu tiên True sau prepare bị chặn, tránh stat lạc quan (file cùng size nhưng sai SHA) hoặc snapshot cũ gây retry liên tục; HEAD chỉ chạy trong prepare.
- Race sau prepare: render gặp chặn vẫn `JobFailed("Nguồn chưa sẵn sàng, bấm Ghép lại")`, **không** `YoutubeWait` ở render lane.
- AC2: GET bổ sung `sources: {total, ready, store, youtube}` theo video gốc phân biệt; `ready` gồm local + kho, `store` chỉ đếm nguồn cần mượn từ kho sau ưu tiên local. Thẻ gợi ý gắn với plan và thẻ plan hiện số nguồn, ẩn phần 0; job chờ hiện “đang chờ YouTube”. Snapshot index kho lazy trong daemon thread, TTL 300 giây sau mỗi lần hoàn tất; lỗi về 0, request không gọi / đợi mạng kho.
- Helpers mới: `source_videos`, `youtube_blocked`, `local_source_ready`, `StoreSources.snapshot/_refresh`; `RenderTarget.current_plan/prepare/needs_download`, `ThemePlans.source_counts`; JS `sourceStatus`. Đã đọc `theme_render/sources.py`: cả `workspace_source` / `cached_source` đều hash, nên chỉ dùng chúng ở prepare; helper nhẹ kiểm provenance / duration / meta size + stat để hiển thị. Audit TC1 hiện có (cache hash theo stat-key) giữ nguyên; không tuyên bố GET lạnh bỏ toàn bộ hash của audit TC1. Đã tìm bằng `rg -n 'update_source_backup|source_backup|class StoreClient|def index|def head|HTTP|403' src/auto_short/web/storage.py src/auto_short/store/client.py src/auto_short/store/redownload.py`: snapshot `StorageCache.update_source_backup` chỉ có tổng, không có video ID để đếm từng plan; dùng index cache riêng. Regex 403 giữ đúng SRC2, không sửa `redownload.py`.

AC → tests (trong `tests/test_web_theme_plan.py`):

| AC | Bằng chứng |
|---|---|
| AC1 | `test_sources_prepare_order_and_dedup_without_http` (workspace/cache/kho/YouTube/kho tắt), `test_sources_prepare_errors_without_http` (bot/429/403/lỗi khác), `test_sources_prepare_rejects_changed_plan_before_io_without_http`, `test_sources_queue_backoff_retains_cache_and_frees_render_without_http` (đồng hồ giả: 60 → 120 giây, cache không tải lại, job render khác chạy trong lúc chờ, cả stat lạc quan), `test_sources_other_error_fails_queue_without_http`, `test_sources_render_race_requests_retry_without_http` |
| AC2 | `test_sources_light_cache_validation_without_hash` (12 trường hợp), `test_sources_view_counts_distinct_owners_without_io`, `test_sources_real_view_without_http` (audit / plan thật, warm view không hash), `test_sources_store_snapshot_async_ttl_and_failure_without_http`; JS smoke `sources`, `sources-ready` |
| AC3 | G3 thuộc PR #153; regression ingest / YouTube không dùng TestClient chạy thành công, chưa chạy tải thật |
| AC4 | JS syntax / framework / whitespace thành công; ORCHESTRATOR báo trước review fix: targeted 195 passed, full suite 2895 passed / 1 skipped ngoài sandbox; IMPLEMENTER không chạy lại full suite sau fix theo chỉ định |

Lệnh đã chạy (cwd = worktree; `PYTHONPATH=src` tương đương đường tuyệt đối trong Required verification; Python = `/home/ntnghia/miniconda3/envs/auto-short/bin/python`):

| Lệnh | Kết quả thật |
|---|---|
| `timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/tc3.2-theme-source/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py tests/test_theme_render.py -x --tb=short` | EXIT 124, treo TestClient tại login fixture đầu tiên; không PASS |
| `timeout 20 env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py::test_auth_and_missing_pid -o faulthandler_timeout=5 --tb=short` | EXIT 124; stack: `setup → c.post('/login') → starlette.testclient → anyio.from_thread`; chưa vào kiểm tra TC3.2 |
| `timeout 60 env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py -k 'sources or without_http or js' -x --tb=short` | **66 passed, 27 deselected**, 2.60 s; 1 Starlette deprecation warning |
| `timeout 240 env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_render.py -x --tb=short` | **35 passed**, 28.13 s |
| `timeout 240 env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_render.py tests/test_ingest_youtube.py tests/test_youtube_wait.py tests/test_youtube_id_dash.py -x --tb=short` | EXIT 124, dừng tại ca TestClient; không PASS nguyên lệnh |
| `timeout 120 env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_ingest_youtube.py tests/test_youtube_wait.py tests/test_youtube_id_dash.py -k 'not api_youtube_status_and_banner and not episode_pages_for_dash_ids and not submit_short_and_khaithi_for_a_dash_id and not invalid_id_is_422_not_500' -x --tb=short` | **63 passed, 4 deselected**, 1.75 s |
| `timeout 60 node --check src/auto_short/web/static/theme_plan.js` | EXIT 0 |
| `timeout 60 node scripts/framework-check.mjs` | EXIT 0 |
| `git diff --check` | EXIT 0 |

Chưa chạy bởi IMPLEMENTER: full suite `python -m pytest -q -n auto` (contract giao ORCHESTRATOR ngoài sandbox), lệnh AC3 nguyên bộ riêng (4 ca TestClient cần môi trường ngoài sandbox), thử tải YouTube thật / kho thật, restart 8080 / manual checklist. Kết quả ngoài sandbox do ORCHESTRATOR cung cấp ở trên là trước review fix; không tuyên bố đã chạy lại full suite sau fix.

Review fix (ORCHESTRATOR): bỏ việc giữ job chỉ dùng nguồn 3090 trong backoff YouTube. Sửa `theme_plan.py`, thêm đúng một test `test_needs_download_store_snapshot_bypasses_youtube_backoff_without_http` trong `tests/test_web_theme_plan.py`, cập nhật contract này; không thêm helper. Test chứng minh YouTube đang chặn + toàn bộ nguồn chỉ ở snapshot → `needs_download=False` / scheduler cho chạy; thiếu một nguồn trong snapshot → True; `youtube_wait=True` luôn giữ True; service giả thiếu snapshot → True; không gọi HEAD / YouTube.

Lệnh duy nhất chạy sau review fix: `timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/tc3.2-theme-source/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py -k 'sources or without_http or needs_download'` → **41 passed, 53 deselected**, 1.24 s, exit 0; 1 Starlette deprecation warning. Không TestClient, không chạy lại JS / framework / full suite theo yêu cầu ORCHESTRATOR.

`git diff --stat` tại bàn giao:

```text
 docs/tasks/TC3.2-theme-source-ready.md   |  49 ++++-
 src/auto_short/web/static/theme_plan.js |   8 +-
 src/auto_short/web/theme_plan.py        | 161 +++++++++++++++-
 tests/test_web_theme_plan.py            | 330 +++++++++++++++++++++++++++++++-
 4 files changed, 532 insertions(+), 16 deletions(-)
```

ORCHESTRATOR (2026-10-25, ngoài sandbox, sau review fix): targeted Required verification (`test_web_theme_plan.py test_theme_render.py test_ingest_youtube.py test_youtube_wait.py test_youtube_id_dash.py`) 195 passed trước fix; full suite `-n auto` **2896 passed, 1 skipped**; `node --check`, `framework-check`, `git diff --check` PASS. Codex: 2 vòng, 130k + 258k tokens (tổng tích lũy session). Theo dõi sau: gộp `StoreSources` với `store/index_cache.py` (SRC4) khi cả hai đã merge. Còn: chạy thật 8080 (chờ HUMAN LEAD cho restart).

Chạy thật 8080 (2026-10-25, commit gộp `8309ab8` = TC3.2 `ff61518` + SRC3 + SRC4): GET `theme-plan` VLT "Chuyển hóa tâm niệm" → `sources {total 7, ready 7, store 0, youtube 0}`; Thái Thượng "Đạo hiếu" → 6 / 6 → **AC2 PASS** (thẻ hiện đủ, GET không hash). "Ghép lại" chưa chạy: MP4 35,5 phút của plan VLT đã có từ 09:46 (trước TC3.2) và cả 7 nguồn đã ở máy, nên ghép lại không thử được nhánh tải / chờ YouTube (AC1 chỉ có test tự động).
