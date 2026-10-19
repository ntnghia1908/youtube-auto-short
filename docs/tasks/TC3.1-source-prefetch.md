# Task: TC3.1 — Kho nguồn gốc + tải dần nguồn cho video có mục yêu thích

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol, high), một writer; quota 5 giờ 9 %
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/TC1-TC3-implementation-authorization.md` §5 + G2 TC2; HUMAN LEAD 2026-10-19 “tải lại các bản gốc cho các tập có khai thị và Short yêu thích. Tìm cách tải từ từ để YouTube không chặn”
- Parallel group: —
- Owned paths: `src/auto_short/theme_render/sources.py` (mới), `src/auto_short/theme_render/__init__.py` (chỉ `_source`), `tests/test_theme_source_cache.py` (mới), contract này
- Dependencies: TC3 (`17fdf80`)
- Base commit / branch: HEAD `feature/tc2-theme-plan`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-10-19)
- Implementation authorized: YES

## Goal

Video gốc của mọi video có khai thị / Short yêu thích (♥, mọi bộ kinh) được tải lại dần và giữ trong kho riêng, để TC3 xuất video ngang không phụ thuộc YouTube lúc bấm. 2026-10-19: 13 video, 6,1 GB (lớn nhất 672 MB); VM đang bị YouTube chặn "Sign in to confirm you're not a bot".

## Scope

- In scope: kho `work/_theme_sources/<video_id>/source.<ext>` + `meta.json` (uri, downloaded_at, size, sha256, duration, height, khác sha ingest hay không); TC3 `_source` dùng kho trước khi tải (xác minh thời lượng như CP8.32: lệch ≤ max(2 s, 1 %) so với `metadata.json`), tải mới thì ghi vào kho (không còn xóa sau render); lệnh `python -m auto_short.theme_render.sources --config <toml> [--dry-run] [--min-gap 600] [--max-gap 1200] [--blocked-wait 3600] [--max-blocked-wait 21600]`: danh sách video = owner của mọi item trong `output/_compilations/*/favorites.json` (`.kt` → video gốc), bỏ qua video đã có nguồn khớp sha ingest trong workspace hoặc đã có trong kho; tải tuần tự một video, nghỉ ngẫu nhiên giữa hai lần tải, `YoutubeBlocked` → chờ rồi thử lại (backoff ×2 tới max), lỗi khác → ghi log, sang video kế; tải vào thư mục tạm trong kho rồi rename; log mỗi bước (stdout) và tổng kết; dừng bằng Ctrl-C an toàn (không để file dở).
- Out of scope: cookies YouTube, đổi ingest / archive / K2 sweep / storage tab, web UI, dọn kho (thủ công).

## Authority / key decisions

- Kho nằm ngoài thư mục tập (`work/<id>/`) nên archive / sweep K2 không xóa; `_theme_sources` không phải episode id hợp lệ nên storage / sweep bỏ qua. TC1 không đọc kho (eligibility vẫn theo chuỗi sha artifact, G2). Tương đương lời nói vẫn kiểm bằng audio từng clip (TC3).
- Dùng downloader ingest (`ingest.youtube.ytdlp_download`, `[ingest]` format) và node trên PATH (YouTube cần) — lệnh kiểm `shutil.which("node")`, thiếu thì dừng với hướng dẫn.

## Acceptance Criteria

1. Danh sách video đúng (khai thị + Short yêu thích, bỏ trùng, bỏ đã có).
2. Tải tuần tự, gap ngẫu nhiên trong [min,max]; bị chặn → chờ + backoff; không file dở khi lỗi / Ctrl-C; chạy lại tiếp tục được.
3. TC3 dùng kho khi workspace mất nguồn; nguồn kho lệch thời lượng → không dùng (tải lại / lỗi rõ); tải mới trong TC3 cũng vào kho.
4. Tests fake downloader / clock / sleep (không mạng); full suite PASS.

## Required verification

- `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc2/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_source_cache.py tests/test_theme_render.py -x --tb=short`; full suite + `--dry-run` thật (ORCHESTRATOR); framework-check; `git diff --check`.

## Result

- Main changes:
- Tests:
- Review:
- PR: chưa.
