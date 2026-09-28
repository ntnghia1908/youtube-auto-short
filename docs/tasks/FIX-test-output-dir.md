# Task: FIX — Test không ghi `output/` ra ngoài `tmp_path`

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `8fa8596` (`origin/main`) / `fix/test-output-dir` (worktree `../youtube-auto-short-fixture`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ sửa fixture test; không đổi source, config mặc định, contract, artifact hay dependency.

## Goal

Chạy `pytest` từ bất kỳ thư mục nào không tạo file nào ngoài thư mục tạm của pytest. Hiện tại `tests/test_web_jobs.py::test_pipeline_target_success_and_failure` ghi `output/abcdefghijk/render_manifest.json` + `shorts/k01.mp4`, `k02.mp4` vào cwd (chạy từ repo chính → lẫn vào `output/` thật, thư mục `output/abcdefghijk/` đang tồn tại ở repo chính).

## Nguyên nhân (đã tái hiện)

- Fixture `cfg` (`tests/conftest.py`) chỉ đặt `workspace.dir = tmp_path / "work"`; `render.output_dir` giữ mặc định `Path("output")` (tương đối, `src/auto_short/config.py`).
- `fake_pipeline` (`tests/web_helpers.py`) ghi `render_manifest.json` + Short giả vào `config.render.output_dir / <id>`.
- Tái hiện: chạy toàn bộ suite từ một cwd trống → 868 passed, cwd có `output/abcdefghijk/…`; bisect theo file → chỉ `tests/test_web_jobs.py`.

## Scope

- In scope:
  - `tests/conftest.py`: fixture `cfg` đặt `render.output_dir = tmp_path / "output"` (các trường render khác giữ mặc định); fixture `config_file` thêm `[render] output_dir` trỏ vào `tmp_path / "output"` cho nhất quán (cùng lớp lỗi, CLI test dùng file này).
  - Contract này (Result) và `docs/workflow/current-state.md` (bỏ mục "ngoài scope" về fixture).
- Out of scope:
  - Đổi mặc định `render.output_dir` hoặc bất kỳ source nào trong `src/`.
  - Xóa `output/abcdefghijk/` ở repo chính (dữ liệu runtime, không thuộc Git; HUMAN LEAD tự xóa hoặc duyệt xóa riêng — xem Manual test).
  - Thêm guard tự động (vd. fixture autouse `chdir`) — không cần khi nguồn lỗi đã bịt; ghi nhận nếu reviewer thấy cần.

## Authority / key decisions

- `docs/ai/workflow.md` (S1); `AGENTS.md` invariant "Không sửa test để che lỗi" — ở đây lỗi nằm ở fixture test, không che hành vi source.
- Quyết định cục bộ: sửa tại fixture dùng chung thay vì từng test, để mọi test dùng `cfg` đều hermetic.

## Implementation approach

- `cfg`: `Config(workspace=..., ingest=IngestConfig(), render=replace(RenderConfig(), output_dir=tmp_path / "output"))` — theo đúng mẫu đã có ở `tests/test_review.py`, `tests/test_render_stage.py`.
- `config_file`: thêm khối `[render]\noutput_dir = "<tmp_path/output>"`.
- Kiểm không test nào đang dựa vào `cfg.render.output_dir == Path("output")` (đã grep sơ bộ: không có).

## Acceptance Criteria

1. Chạy toàn bộ suite từ một thư mục trống (`cd <dir-trống> && PYTHONPATH=<worktree>/src python -m pytest -q -p no:cacheprovider <worktree>/tests`) → PASS và thư mục đó vẫn trống.
2. Toàn bộ suite PASS từ worktree như bình thường; số test không giảm (baseline 868 passed).
3. Diff chỉ gồm `tests/conftest.py` + docs trong scope.

## Required verification

- Lệnh ở AC1 + `find <dir> -mindepth 1` rỗng — chứng minh AC1.
- `PYTHONPATH=<worktree>/src python -m pytest -q` trong worktree — chứng minh AC2.
- `git diff --stat origin/main` — chứng minh AC3.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract → manual test là điểm danh.

- [ ] Sau merge: xóa `output/abcdefghijk/` ở repo chính (rác từ test cũ, không phải tập thật) — HUMAN LEAD tự làm hoặc duyệt cho agent xóa.
- [ ] Chạy `pytest` ở repo chính → `git status` + `ls output/` không xuất hiện thư mục mới.

## Result

- Main changes: `tests/conftest.py` — fixture `cfg` thêm `render=replace(RenderConfig(), output_dir=tmp_path / "output")` (import `replace`, `RenderConfig`); fixture `config_file` thêm khối `[render]\noutput_dir = "<tmp_path/output>"`. Không đổi `src/`. Đã grep: không test nào append thêm `[render]` vào `config_file` (tránh trùng bảng TOML) hoặc dựa vào `cfg.render.output_dir == Path("output")`.
- Tests (môi trường: conda `auto-short`, Python 3.12, node qua nvm; 2026-09-28):
  - AC1: `cd <scratchpad>/ac1` (thư mục mới, trống) `&& PYTHONPATH=<worktree>/src python -m pytest -q -p no:cacheprovider <worktree>/tests` → `868 passed, 1 warning in 172.72s`; `find <scratchpad>/ac1 -mindepth 1` → rỗng (trước fix: `output/abcdefghijk/…`). PASS.
  - AC2: trong worktree `PYTHONPATH=<worktree>/src python -m pytest -q` → `868 passed, 1 warning in 191.95s` (bằng baseline 868); sau đó worktree không có `output/` hay `work/`. PASS.
  - AC3: `git diff --stat origin/main` → `docs/tasks/FIX-test-output-dir.md` + `tests/conftest.py` (12 ++++--). PASS.
  - `node scripts/framework-check.mjs` → exit 0, 53 dòng PASS, không FAIL. PASS.
- Review: ORCHESTRATOR ACCEPTED — diff chỉ `tests/conftest.py` (+9/-3) theo đúng approach; chạy lại độc lập `tests/test_web_jobs.py` + `tests/test_cli.py` từ cwd trống → `12 passed`, `find` rỗng.
- Important findings / decisions: warning duy nhất trong suite có sẵn từ trước, không liên quan. `docs/workflow/current-state.md` cố ý chưa sửa ở commit này (ORCHESTRATOR cập nhật để tránh xung đột với nhánh state chưa merge). Quyết định: bỏ mục fixture khỏi `current-state.md` ở lần đồng bộ state sau merge (nhánh `docs/post-cp810-state`), không sửa trong PR này.
- Known limitations: không thêm guard tự động (autouse `chdir`) theo Out of scope; `output/abcdefghijk/` ở repo chính vẫn còn — xem Manual test.
- PR: chưa tạo (commit local, chưa push).
