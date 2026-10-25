# Task: TC3.2 — Nguồn ghép chủ đề luôn sẵn sàng

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 (chọn "Nguồn: ghép không lỗi", "Web tự tải chậm"; "xem lại tất cả video nào có yêu thích mà bị xóa thì plan tải lại"); `docs/decisions/TC1-TC3-implementation-authorization.md` §5; `docs/decisions/SRC1-source-backup-3090.md` G4a / G5
- Parallel group: —
- Owned paths: `src/auto_short/theme_render/sources.py`; `src/auto_short/web/theme_plan.py`; `src/auto_short/web/app.py` (chỉ wiring vòng tải nền); `src/auto_short/web/static/theme_plan.js`; `pyproject.toml` (chỉ dòng `yt-dlp`, G3); `tests/test_theme_source_cache.py`, `tests/test_web_theme_plan.py`; file này
- Dependencies: SRC1 (G5 thứ tự lấy nguồn có kho 3090) — làm sau SRC1
- Base commit / branch: sau khi SRC1 merge / `feature/tc3.2-theme-source`
- Human Lead approval: pending (G1 đã chọn; G2, G3 ORCHESTRATOR đề xuất khi HUMAN LEAD "không ưu tiên")
- Implementation authorized: NO

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì G3 đổi phiên bản dependency `yt-dlp`; phần còn lại là S1.

## Bối cảnh — bằng chứng (2026-10-25)

Job ghép 111 (VLT "Chuyển hóa tâm niệm", 7 clip) tải được `qKTzy8sYyKQ` rồi lỗi ở `xPBuSsKEY-U`: `yt-dlp download failed: ERROR: unable to download video data: HTTP Error 403: Forbidden`. `is_blocked_message` chỉ coi bot-check / 429 là "bị chặn" → 403 thành lỗi cứng, job hỏng ngay. 4 video ♥ mất hẳn nguồn (decision SRC1 §2 G4a). Tải lại chỉ chạy bằng lệnh tay `python -m auto_short.theme_render.sources`.

## Goal

Bấm "Ghép video" thì nguồn thường đã sẵn: web tự tải chậm (10–20 phút / video) các video ♥ không còn nguồn ở workspace, kho nguồn ghép và kho 3090; thẻ chủ đề cho biết còn thiếu mấy video gốc; khi YouTube từ chối, job ghép chờ rồi tự thử lại thay vì hỏng.

## Scope

- In scope: G1–G3 dưới đây.
- Out of scope: chọn / thay clip khi thiếu nguồn; chất lượng AI; video không ♥.

## Authority / key decisions

- **G1 (HUMAN LEAD chọn)**: vòng nền trong web dùng lại `sources.run` từng bước (một video mỗi lượt, khoảng nghỉ ngẫu nhiên `min_gap`–`max_gap` 600–1200 s, backoff khi bị chặn), chỉ khi làn prepare rảnh và YouTube không đang backoff (`youtube_status`). Bỏ qua video đã có ở kho 3090 (SRC1). Tải xong → SRC1 đẩy lên 3090.
- **G2 (đề xuất)**: job `theme_render` thêm bước tải nguồn ở làn `prepare` trước bước `render`; YouTube chặn (bot-check / 429 / **403**) → `YoutubeWait` (cơ chế FIX-youtube-botcheck-wait: về đầu hàng prepare, lùi dần, không giữ slot render); bản đã tải giữ trong cache. Coi 403 là "chặn" chỉ trong đường tải nguồn ghép (`sources.fetch_to_cache`), không đổi `is_blocked_message` toàn hệ.
- **G3 (đề xuất, dependency)**: nâng `yt-dlp` lên bản ổn định mới nhất đã phát hành ≥ 2 tuần; chạy test ingest / youtube; thử tải 1 video mất nguồn; tệ hơn → về `2026.8.19`.
- Thẻ chủ đề: dòng "Video gốc: 6 / 7 sẵn sàng · 1 đang chờ tải" kiểm bằng `stat` + `meta.json` (không hash file lớn mỗi lần xem); hash đầy đủ vẫn ở lúc render.

## Phải giữ nguyên

- `fetch_to_cache` tạm → rename, kiểm sha / thời lượng; CLI `sources` vẫn chạy; TC3 fail closed; plan / cache key không đổi.

## Code bị thay / xóa

- Thông báo "YouTube đang chặn tải, thử lại sau" (`RenderTarget`) thay bằng trạng thái chờ của G2.

## Acceptance Criteria

1. Vòng nền chỉ tải video ♥ thiếu ở mọi nơi, một video mỗi lượt, đúng khoảng nghỉ, dừng khi prepare bận / YouTube backoff; có test với đồng hồ giả.
2. Job ghép thiếu nguồn: bước prepare tải trước; 403 / bot-check → chờ, không `failed`; tải xong mới sang render.
3. Thẻ chủ đề hiện số video gốc sẵn / thiếu / đang tải; không hash file khi xem.
4. G3: test ingest / youtube PASS với bản mới, hoặc ghi lý do quay về.
5. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_source_cache.py tests/test_web_theme_plan.py tests/test_theme_render.py -x --tb=short` — AC 1–3.
- `… -m pytest -q tests/test_ingest*.py tests/test_youtube*.py` — AC 4.
- `… -m pytest -q -n auto`; `node --check src/auto_short/web/static/theme_plan.js`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- Chạy thật trên 8080 (ghim branch, hỏi trước khi restart): 4 video VLT tập 16, 17, 19, 20 về cache; bấm Ghép lại "Chuyển hóa tâm niệm" → MP4.

## Manual test checklist (Tech Lead)

Không chạm database / security / public API. Manual sau automated là điểm danh.

- [ ] Thẻ chủ đề VLT hiện đúng số video gốc thiếu; sau khi tải xong hiện đủ.
- [ ] Ghép "Chuyển hóa tâm niệm" ra video 35 phút, nghe 2–3 điểm nối.

## Result

- Main changes:
