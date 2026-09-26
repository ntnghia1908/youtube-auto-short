# Task: CP2 — Media Input + Artifact Workspace

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `dcf388e` / `feature/cp2-media-workspace`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26; D1–D8 as proposed, D4 = reference local file, no copy)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP2 tạo shared abstraction (manifest / stage status / hash convention) mà mọi stage CP3+ dùng lại, và tạo CLI surface đầu tiên. Architecture tổng thể đã chốt ở `docs/decisions/CP1-product-contract.md` §8, §10; các quyết định chi tiết dưới đây (D1–D8) cần HUMAN LEAD duyệt cùng APPROVE TASK.

## Goal

Một video (YouTube URL hoặc file local) đi vào workspace `work/<episode_id>/` và sinh `metadata.json` + `manifest.json` ổn định, resume được, không dùng AI (roadmap CP2 Success).

## Scope

- In scope:
  - Python package skeleton `src/auto_short/`, `pyproject.toml`, `.venv` workflow, `config.example.toml`.
  - Typed config (TOML/`tomllib`) cho workspace path.
  - Ingest stage: YouTube URL (tải bằng `yt-dlp` vào workspace) và file local (tham chiếu, không copy).
  - `metadata.json` (probe bằng `ffprobe` + metadata YouTube nếu có).
  - `manifest.json`: stage status, input hashes, config hash, artifact paths; skip/stale logic.
  - CLI: `ingest`, `status`.
  - Tests `pytest` (không cần mạng).
  - Docs: decision record CP2, project profile (module map path, setup), README setup, current-state.
- Out of scope:
  - Transcript (kể cả tải caption YouTube — CP3), shot/candidate analysis, AI, render.
  - Playlist/batch (CP9). Upload YouTube.
  - Dependency ngoài `docs/decisions/CP1-product-contract.md` §10.

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §3, §4 CP2; `docs/decisions/CP1-product-contract.md` §1, §8, §10, §11.
- Quyết định đề xuất (DECIDE cùng APPROVE TASK):
  - **D1 Package / layout:** package `auto_short` theo src-layout `src/auto_short/<stage>/`; module map trong project profile đổi `src/<stage>/` → `src/auto_short/<stage>/`.
  - **D2 Runtime:** `.venv` tạo từ system Python 3.12 (`/usr/bin/python3`), không dùng conda base; `pip install -e ".[dev]"`. `pyproject.toml` khai báo `requires-python >=3.11`, runtime deps CP2 chỉ `yt-dlp`; dev `pytest`. `faster-whisper` thêm ở CP3 khi dùng.
  - **D3 Episode ID:** YouTube → video id (vd `rbjfCfFq3Dk`); file local → `<slug tên file>-<12 ký tự đầu sha256>`; ghi đè bằng `--episode-id`.
  - **D4 Source handling:** YouTube tải vào `work/<id>/source.<ext>` (≤1080p, mp4). File local **không copy** (video 700 MB): manifest ghi absolute path + sha256 + size + mtime.
  - **D5 Manifest schema** (`work/<id>/manifest.json`, `schema_version: 1`): `episode_id`, `source` {kind, uri, path, sha256, size}, `stages` {`<name>`: {status `pending|running|done|failed`, `artifacts` [paths], `inputs` [{path, sha256}], `config_hash`, `started_at`, `finished_at`, `error`}}. Ghi file atomically (write tmp + rename).
  - **D6 Resume / stale rule:** stage `done` được skip khi mọi input sha256 và `config_hash` khớp và artifacts tồn tại; ngược lại chạy lại và đánh dấu stale mọi stage downstream. `--force` chạy lại. Sha256 file lớn được cache theo (path, size, mtime) trong manifest để không hash lại 700 MB mỗi lần.
  - **D7 Config hash:** sha256 của JSON canonical (sort keys) chỉ gồm các key config mà stage đó dùng.
  - **D8 CLI:** `python -m auto_short` và entry point `auto-short`; lệnh `auto-short ingest <url|path> [--episode-id ID] [--force] [--config PATH]`, `auto-short status <episode_id>`. Exit code ≠ 0 khi lỗi, message rõ ràng.
  - `config.toml` gitignored; `config.example.toml` commit.

## Implementation approach

- Stage framework nhỏ (dataclass + JSON), stdlib; `ffprobe` qua `subprocess`; `yt-dlp` dùng như Python library.
- Tests dùng video tổng hợp bằng `ffmpeg -f lavfi testsrc` (vài giây) trong tmp dir; YouTube path test bằng fake downloader (không mạng).
- Decision record `docs/decisions/CP2-workspace-contract.md` (ACCEPTED) ghi D1–D8 làm canonical owner cho manifest/stage convention.

## Acceptance Criteria

1. `auto-short ingest <file local>` tạo `work/<id>/manifest.json` + `metadata.json` (duration, width, height, fps, video/audio codec, sha256, size, source kind/uri; title/channel khi là YouTube).
2. Chạy lại cùng lệnh: stage `ingest` được skip (log rõ), artifact không đổi (sha256 `metadata.json` giống lần trước), không hash lại file lớn khi (size, mtime) không đổi.
3. Đổi nội dung file nguồn hoặc config liên quan → ingest chạy lại; `--force` luôn chạy lại.
4. `auto-short ingest <YouTube URL>` tải vào workspace và sinh metadata (kiểm bằng test với fake downloader + một lần chạy thật thủ công với video test).
5. Lỗi (file không tồn tại, không phải video, `ffprobe` lỗi) → exit ≠ 0, message rõ, manifest ghi stage `failed` + `error`, không để artifact dở dang.
6. `auto-short status <id>` in trạng thái các stage.
7. Không dependency ngoài CP1 §10; không code transcript/analysis/AI/render.
8. `node scripts/framework-check.mjs` PASS; decision record CP2 ACCEPTED.

## Required verification

- `.venv/bin/pytest -q` → PASS (AC1–AC3, AC5, AC6; AC4 với fake downloader).
- Chạy thật: `auto-short ingest input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` hai lần → lần 2 skip, `sha256sum work/<id>/metadata.json` giống nhau, thời gian lần 2 ngắn (AC1, AC2).
- Chạy thật: `auto-short ingest https://youtu.be/rbjfCfFq3Dk` → tải vào workspace + metadata (AC4).
- `auto-short status <id>` (AC6).
- `git diff --stat main...HEAD` + đọc `pyproject.toml` (AC7).
- `node scripts/framework-check.mjs` (AC8).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database hay security model. CLI là giao diện người dùng đầu tiên (không phải public API contract mạng); manual test là điểm danh sau automated verification.

- [ ] `auto-short ingest input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` → xem `work/<id>/metadata.json`.
- [ ] Chạy lại → thấy skip.
- [ ] `auto-short status <id>`.

## Result

- Main changes: package `auto_short` (src-layout, hatchling, `yt-dlp` + dev `pytest`); typed TOML config; manifest v1 + stage skip/stale framework (`workspace.py`, `hashing.py`); ingest local/YouTube (`ingest/`); CLI `ingest`/`status`; 36 tests; decision record `docs/decisions/CP2-workspace-contract.md` ACCEPTED; project profile, README, current-state. IMPLEMENTER commits `f696fa8`, `7389c2f`, `4ac2300`.
- Tests (ORCHESTRATOR chạy lại độc lập, workspace sạch trong scratchpad):
  - `.venv/bin/pytest -q` → `36 passed` (venv: system Python 3.12.3, `yt-dlp` 2026.8.19, `pytest` 9.1.1).
  - `auto-short ingest input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` lần 1: run, 2.70 s; lần 2: `skip (up to date)`, 0.089 s; `metadata.json` sha256 `aa2c8687…7a35` giống nhau; `--force` chạy lại.
  - `status` → ingest `done`, các stage sau `pending`.
  - Lỗi: file không tồn tại → exit 1; `README.md` với `--episode-id` → exit 1, manifest ghi `failed` + `error`, không để `metadata.json`; URL không phải YouTube → exit 1.
  - YouTube (IMPLEMENTER chạy thật): `ingest https://youtu.be/rbjfCfFq3Dk` → exit 0, 11m03s, `work/rbjfCfFq3Dk/source.mp4` sha256 trùng file local; ORCHESTRATOR chạy lại → `skip (up to date)` 0.089 s, không gọi mạng.
  - `node scripts/framework-check.mjs` → PASS; `work/`, `.venv/`, `config.toml` không bị track.
- Review: ACCEPTED (dual-agent, ORCHESTRATOR review diff-first); không có blocking finding. Chi tiết IMPLEMENTER tự chọn trong phạm vi D1–D8 (ghi ở decision record): status `stale` (D6 yêu cầu đánh stale), `source.mtime_ns` làm key cache hash, config key `ingest.js_runtimes` (mặc định `["node"]`, không vào config hash).
- Important findings / decisions:
  - Non-blocking: `--force` YouTube mà tải lại thất bại sẽ xóa cả `source.mp4` cũ (nhất quán với quy tắc stage `failed` không giữ artifact, nhưng phải tải lại ~700 MB); comment trong `_ingest_youtube` nói "chỉ thay sau khi probe OK" chưa phản ánh nhánh lỗi.
  - Non-blocking: `yt-dlp` không pin version; YouTube thay đổi có thể cần nâng cấp hoặc `yt-dlp[default]` (thêm `yt-dlp-ejs`) — là dependency decision nếu xảy ra.
  - Môi trường: máy thiếu `python3.12-venv` (ensurepip) → venv tạo bằng `--without-pip` + pip wheel local (README ghi cách); cách sạch là `sudo apt install python3.12-venv`. Node chỉ có trên PATH sau khi nạp nvm.
- Known limitations: chưa có transcript/analysis/AI/render (CP3+). YouTube ingest cần mạng và JS runtime trên PATH.
- PR: chưa; chờ HUMAN LEAD approve integration.
