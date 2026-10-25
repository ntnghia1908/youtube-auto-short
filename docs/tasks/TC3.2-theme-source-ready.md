# Task: TC3.2 — Nguồn ghép chủ đề: chờ khi bị chặn, trạng thái nguồn, yt-dlp

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 (chọn "Nguồn: ghép không lỗi"); `docs/decisions/TC1-TC3-implementation-authorization.md` §5; `docs/decisions/SRC1-source-backup-3090.md` G5
- Parallel group: —
- Owned paths: `src/auto_short/web/theme_plan.py`; `src/auto_short/web/static/theme_plan.js`; `pyproject.toml` (chỉ dòng `yt-dlp`, G3); `tests/test_web_theme_plan.py`; file này
- Dependencies: SRC1 (G5 thứ tự lấy nguồn có kho 3090); SRC2 (đường tải dùng chung trong `sources.py`, 403 = chặn) — làm sau SRC2
- Base commit / branch: sau SRC2 / `feature/tc3.2-theme-source`
- Human Lead approval: pending (G2, G3 ORCHESTRATOR đề xuất khi HUMAN LEAD "không ưu tiên"; tải nền nằm ở SRC2)
- Implementation authorized: NO

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
- **G3 (đề xuất, dependency)**: nâng `yt-dlp` lên bản ổn định mới nhất đã phát hành ≥ 2 tuần; chạy test ingest / youtube; thử tải 1 video; tệ hơn → về `2026.8.19`. Có thể làm trước SRC2 để SRC2 tải bằng bản mới (HUMAN LEAD chọn).
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

- Main changes:
