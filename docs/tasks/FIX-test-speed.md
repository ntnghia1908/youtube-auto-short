# Task: FIX-test-speed — Suite nhanh lại và không chập chờn

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `27f9238` (`main`) / `fix/test-speed` (worktree `../youtube-auto-short-tspeed`)
- Human Lead approval: APPROVED 2026-10-03 ("đồng ý fix test speed" — đề xuất ORCHESTRATOR cùng ngày, phạm vi ghi dưới đây)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi test, cấu hình pytest và lệnh chuẩn trong Test policy (`docs/ai/project-profile.md` §8, canonical owner); không đổi `src/`, dependency hay hành vi production.

## Bối cảnh (đo 2026-10-03, ORCHESTRATOR)

- `python -m pytest -q -n auto` trên `main` `27f9238`: **305 s** (trước CP13.1a: 83–103 s). Load VM ≈ 18–20 (8080 đang render / Whisper, 24 CPU).
- Chậm nhất: `tests/test_enhance_worker.py::test_self_test_reports_vm_states` **163 s** (đường găng của xdist), các test worker khác 20–31 s (torch CPU); test render thật 20–38 s.
- Chập chờn: `tests/test_web_cp9.py::test_cut_save_reset_and_409[lanes|serial]` fail dưới `-n auto` (job `post` tự soạn sau render gọi Ollama thật `127.0.0.1:11437`, `wait_idle` quá hạn) — fail cả trên `main`.
- Transcript IMPLEMENTER: phần lớn thời gian task là chờ suite / chạy lại vì chập chờn.

## Goal

Suite chuẩn ≈ ≤ 90 s trên VM khi 8080 bận vừa phải, không test nào gọi dịch vụ thật (Ollama, mạng), không chập chờn; test chậm vẫn chạy được khi cần.

## Scope

- In scope:
  - **T1 Marker `slow`.** Khai báo marker trong `pyproject.toml`; test tích hợp worker cần torch (và test nào khác > 20 s mà không thiết yếu cho mỗi lần chạy — IMPLEMENTER đề xuất danh sách, giữ test render thật cốt lõi) đánh dấu `slow`; lệnh chuẩn bỏ qua `slow` (`addopts`/`-m "not slow"`); `-m slow` chạy riêng. Self-test worker: dùng enhance giả / khung rất nhỏ để test nhanh còn trong suite chuẩn nếu được.
  - **T2 Không gọi dịch vụ thật.** `test_web_cp9.py` (và mọi test web chạy job render → bài đăng tự soạn) tiêm `post_compose` / preflight giả; thêm chốt chặn chung (fixture autouse hoặc conftest) làm test fail rõ nếu mở kết nối tới `127.0.0.1:11437` / Ollama thật.
  - **T3 Số worker xdist.** Đo `-n auto` / `-n 12` / `-n 8` (≥ 2 lần mỗi mức, ghi load lúc đo) khi 8080 chạy; chọn lệnh chuẩn nhanh nhất; cập nhật Test policy (`docs/ai/project-profile.md` §8): lệnh chuẩn, khi nào chạy `-m slow` (sửa `tools/enhance_worker` hoặc phần render / worker liên quan), README nếu nhắc lệnh test.
  - Báo cáo số đo trước / sau trong Result (thời gian suite, top 10 `--durations`).
- Out of scope: tối ưu code production; bỏ test render thật cốt lõi; CI.

## Acceptance Criteria

1. Lệnh chuẩn mới PASS, không chạy test `slow`, thời gian ≤ 90 s khi load ≤ 20 (ghi số đo thật; nếu không đạt thì ghi lý do + số tốt nhất).
2. `-m slow` PASS (test worker torch chạy được bằng env `enhance-bench` như CP13.1a mô tả, hoặc SKIP rõ lý do).
3. `test_web_cp9.py` PASS 5 lần liên tiếp dưới lệnh chuẩn; chốt chặn Ollama thật có test riêng.
4. Không nới test để che lỗi: mọi test bị đổi giữ nguyên ý kiểm (ghi rõ từng test đổi gì).
5. Test policy §8 + README khớp lệnh mới; `node scripts/framework-check.mjs` PASS.

## Required verification

- Lệnh chuẩn mới (≥ 2 lần, ghi thời gian + load) — AC 1, 3.
- `-m slow` — AC 2.
- `pytest tests/test_web_cp9.py` × 5 dưới xdist — AC 3.
- `node scripts/framework-check.mjs` — AC 5.

Mọi lệnh pytest chạy với `PYTHONPATH=<worktree>/src` (env `auto-short` cài editable trỏ repo chính). Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security / public API. Không cần manual test ngoài đọc số đo trong Result.

## Result

- Main changes: marker `slow` + `addopts = "-m 'not slow'"` (`pyproject.toml`); 10 worker torch tests + 5 render tests marked `slow`; autouse guard in `tests/conftest.py` (blocks Ollama ports 11434 / 11437 and non-loopback connects) + `tests/test_no_real_services_guard.py`; `test_web_cp9.py` injects `FakeComposeAI` + no-op `post_preflight`; Test policy §8 + README updated.
- Tests changed (intent kept):
  - `tests/test_web_cp9.py::make_client`: adds `post_compose=FakeComposeAI()` (from test_web_post_cp815), `post_preflight=lambda c: None`; assertions untouched.
  - `tests/test_web_lanes_cp810.py::_tree` (used by `test_lanes_artifacts_identical_to_serial`): `*_log.json` hashed without per-call `seconds` fields (wall-clock, rounded to ms; this test failed under load on `selection_log.json` / `titling_log.json`). All other artifacts still compared byte for byte.
  - `slow` marker only (bodies unchanged): all 10 `@needs_torch` tests in `test_enhance_worker.py` (self-test 163-187 s alone; others 20-39 s); `test_render_reuse.py::{test_force_config_and_plan_version_encode_all, test_cli_title_render}`, `test_render_parallel.py::test_jobs_one_is_sequential`, `test_render_stage.py::{test_ffmpeg_failure_keeps_previous_render, test_force_rerender_is_byte_identical}` (each 17-32 s real render; lighter siblings keep the same behaviours covered).
  - Not changed: self-test stays real (slow), no fake enhance.
- Measurements (VM shared with 8080 + another IMPLEMENTER; load 16-31 during runs, so AC1 "load <= 20" not met):
  | Command | Time | Notes |
  |---|---|---|
  | before (contract, main 27f9238) `-n auto` | 305 s | load 18-20, 2 flaky fails |
  | after `-n auto` x5 | 121 (1 fail, lanes log), 118, 120, 114, 118 s (after lanes fix 114-120) | load 17-33 |
  | after `-n 12` x2 | 211, 158, 135 s | slower |
  | after `-n 8` x2 | 148, 166 s | slower |
  | `-m slow -n auto` | 195 s, 15 passed | |
  Top after: render_reuse override 35 s, lanes_identical 25 s, render_cp9 cut 23 s, render_stage resume 23 s, web_titles 21 s, render_parallel 20 s, dissolve 20 s...
  Suite CPU is ~560 s in ~40 real-render tests; wall is bound by CPU shared with 8080, so <= 90 s not reached (best 114 s at load ~25). Dropping more real-render tests would cut core coverage (out of scope).
- Verification: standard command x5 PASS (1367 passed, 1 skipped) after lanes fix; `pytest -n auto tests/test_web_cp9.py` x5 PASS (14 passed, ~4 s); `-m slow` 15 passed; `node scripts/framework-check.mjs` PASS.
- Review:
- Important findings / decisions: `-n auto` best. Cause of cp9 flake was real Ollama in the auto-compose post job.
- Known limitations: AC1 time target missed under load (see above).
- PR:
