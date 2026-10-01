# Task: CP11-R1 — Render song song nhiều Short trong một job

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `ebff15c` (`origin/main` 2026-10-01) / `feature/render-parallel` (worktree `../youtube-auto-short-render-parallel`)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-01: APPROVE J1–J6 theo đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì thêm khóa config `[render]` execution-only, phải loại khỏi `config_hash` → sửa `docs/decisions/CP7-render-contract.md` (R6 dòng Encode, R10 dòng `config_hash`). Không đổi schema artifact, không đổi `render_key`, không thêm dependency (`concurrent.futures` của stdlib).

## Bối cảnh

HUMAN LEAD 2026-10-01 chọn R1 trong `docs/decisions/CP11-performance-report.md`. Số liệu (`docs/decisions/CP11-performance-data.md` §1.1, §1.3, §1.5): một ffmpeg render chỉ dùng ≈ 9 lõi trên VM 48 vCPU; `render.threads` không giúp. Cả tập, mỗi tiến trình một Short: Short p=1 191 s → p=2 119.5 s, p=4 99.4 s, p=7 84.2 s; khai thị p=1 699 s → p=3 347.7 s, p=6 257.2 s. Whisper + một render chồng nhau đã ×1.27–1.34 (§5). R2 (`cpu_threads = 24`) đã áp dụng 2026-10-01.

Hiện trạng (`render/stage.py::_render`): lần lượt từng Short — tính kế hoạch, `render_key`, quyết định tái dùng (T5), viết filter script, chạy `ffmpeg` → `.part`, `verify_output`, sha256. Chỉ sau khi mọi Short xong mới validate + đổi tên `.part` nguyên tử + ghi `render_manifest.json`; lỗi → xóa mọi `.part`.

## Quyết định (HUMAN LEAD 2026-10-01: APPROVE J1–J6)

- **J1. Khóa `[render] jobs`** (int 1–16, mặc định **1** = hành vi hiện nay): số Short encode cùng lúc trong một lần chạy stage `render`. Execution-only: thêm vào `EXEC_KEYS`, **không** vào `config_hash` (sửa CP7 R10: "trừ `output_dir`, `threads`, `jobs`") → đổi `jobs` không làm render `stale`, không render lại tập nào.
- **J2. Giá trị trên máy này:** sau merge, `config.toml` repo chính đặt `[render] jobs = 4` (S0, như R2) rồi khởi động lại 8080. Mặc định code giữ 1 vì số lõi tùy máy. p = 4: render ≈ 24 lõi + Whisper 24 luồng vừa 48 lõi (report R1).
- **J3. Cái gì chạy song song:** chỉ phần "encode": `ffmpeg` + `verify_output` + sha256 của Short không tái dùng. Phần kế hoạch (đo chữ, layout, `render_key`, quyết định tái dùng, filter script, record manifest) vẫn tuần tự theo thứ tự clip như hiện nay → `render_manifest.json` giống hệt khi `jobs = 1` (cùng thứ tự, cùng giá trị, cùng sha256 file — encode deterministic, `+bitexact`).
- **J4. Lỗi:** một Short lỗi (ffmpeg / `verify_output`) → không khởi động encode mới; đợi các ffmpeg đang chạy kết thúc (không kill; tối đa `jobs − 1` tiến trình, mỗi cái ≤ vài phút), rồi báo lỗi của **clip lỗi đầu tiên theo thứ tự clip** (message như hiện nay). Dọn `.part` như hiện nay; không file mới nào được commit (giữ tính nguyên tử T5). Dừng server (SIGINT tới tiến trình con, W5) áp cho mọi ffmpeg đang chạy như với một ffmpeg hiện nay.
- **J5. Log:** dòng mỗi clip (`clip kNN: … rendered in X s`) giữ nguyên format, có thể xen kẽ thứ tự; dòng tổng giữ nguyên. Thêm `jobs` vào dòng stderr đầu (font + fps + kích thước nguồn) khi `jobs > 1`.
- **J6. Không đổi:** CLI (không thêm cờ), web / API / tiến độ, hàng đợi làn CP8.10 (làn `render` vẫn một job), `threads`, preset / crf, `render_key`, schema, mọi stage khác. Render một Short (sửa title, thêm Short CP9) dùng chung đường này → cũng song song khi có ≥ 2 Short phải encode.

## Goal

Với `jobs = 4`, render cả tập Short ≈ 191 → ≈ 100 s và khai thị ≈ 699 → ≈ 300 s trên máy này; file ra và `render_manifest.json` giống hệt `jobs = 1`.

## Scope

- In scope: J1 (config + `EXEC_KEYS` + validate), J3–J5 trong `render/stage.py`; sửa CP7 R6 / R10 (J1); `README.md` / `config.example.toml` (nếu có) ghi khóa mới; tests.
- Out of scope: J2 (S0 sau merge); R3, R4; tự điều chỉnh `jobs` theo tải CPU / làn `prepare`; kill tiến trình khi lỗi.

## Authority / key decisions

- `docs/decisions/CP7-render-contract.md` R6, R9, R10, CP8.2 T5 (tái dùng + commit nguyên tử).
- `docs/decisions/CP11-performance-report.md` R1; J1–J6 ở trên.

## Implementation approach

- Tách vòng `for cp in plans` thành: (1) vòng tuần tự như hiện nay, Short cần encode được thu vào danh sách tác vụ (clip, cmd, part, record); (2) chạy tác vụ bằng `ThreadPoolExecutor(max_workers=jobs)` (ffmpeg là tiến trình con, thread chỉ đợi), `jobs = 1` chạy tuần tự như cũ.
- `Runner` injectable giữ nguyên → test dùng runner giả (đếm số lệnh đồng thời, giả lỗi một clip).

## Acceptance Criteria

1. `[render] jobs` hợp lệ 1–16, sai kiểu / ngoài khoảng → `ConfigError`; đổi `jobs` không đổi `config_hash`, tập `done` vẫn `done` (không stale).
2. Với runner giả: `jobs = 4` có tối đa 4 encode đồng thời và > 1 khi có ≥ 2 Short; `jobs = 1` không bao giờ đồng thời.
3. `render_manifest.json` và sha256 mọi Short giống hệt giữa `jobs = 1` và `jobs = 4` (fixture ffmpeg thật có sẵn trong tests, ≥ 3 Short).
4. Một clip lỗi khi `jobs = 4`: stage `failed` với lỗi của clip lỗi đầu tiên theo thứ tự, không còn `.part`, file / manifest cũ nguyên vẹn, không encode mới khởi động sau lỗi.
5. Tái dùng T5 vẫn đúng khi `jobs > 1` (Short có `render_key` không đổi không encode lại).
6. Toàn bộ suite PASS.
7. Render thật một tập Short và một tập khai thị (bản sao dữ liệu, không ghi `work/` / `output/` chính) với `jobs = 4`: exit 0, thời gian ≈ số đo CP11, sha256 từng Short bằng lần chạy `jobs = 1` trên cùng bản sao.

## Required verification

- `python -m pytest -q -x tests/test_render_stage.py tests/test_render_config.py tests/test_render_reuse.py` (+ file test mới) — AC1–AC5.
- `python -m pytest -q -n auto` — AC6.
- Bản sao một tập Short + một tập `.kt` vào `~/.cache/auto-short-render-parallel-test/` (hard-link `source.mp4`), `auto-short render <id> --force` với `jobs = 1` rồi `jobs = 4`; so sha256 + thời gian — AC7.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract → manual test là điểm danh sau automated verification.

- [ ] Sau merge + J2 + ghim 8080: render một tập trên web, thời gian render trên trang tập giảm rõ; Short xem bình thường.

## Result

- Main changes: `[render] jobs` (int 1–16, mặc định 1) trong `config.py`, `EXEC_KEYS` (không vào `config_hash`); `render/stage.py`: vòng kế hoạch giữ nguyên, Short cần encode thu vào danh sách `_Encode`, `_encode_all` chạy bằng `ThreadPoolExecutor(jobs)` (jobs 1 → tuần tự); lỗi đầu tiên → `stop` event, không encode mới, đợi tiến trình đang chạy, báo lỗi clip lỗi đầu tiên theo thứ tự; `, jobs N` vào dòng log đầu khi jobs > 1; sửa CP7 R6 / R10 + dòng Accepted by / Task contract; `config.example.toml`, `README.md`.
- Tests: `tests/test_render_parallel.py` mới (7 test: AC2–AC5, config_hash / không stale) + `tests/test_render_config.py` (AC1). Targeted 62 passed; toàn bộ `pytest -q -n auto`: 1226 passed, 1 skipped. AC7 (bản sao `~/.cache/auto-short-render-parallel-test/`, không có tiến trình ffmpeg khác lúc đo): tập Short `4oOZz2CBz3g` (7 Short) jobs 1 → 191.2 s, jobs 4 → 101.4 s; tập khai thị `4oOZz2CBz3g.kt` (6 Short) 700.1 s → 323.1 s; sha256 mọi Short + `render_manifest.json` giống hệt giữa jobs 1 và jobs 4.
- Review: ORCHESTRATOR round 1 ACCEPTED (2026-10-01): diff đúng J1–J6; kế hoạch tuần tự, encode trong `TemporaryDirectory`, lỗi → clip lỗi đầu theo thứ tự; chạy lại `tests/test_render_parallel.py` + `tests/test_render_config.py` 36 passed. Ghi nhận: lỗi kế hoạch (ví dụ title không vừa ở clip sau) giờ báo trước khi encode — cả `jobs = 1`; trạng thái cuối như cũ (lần chạy lỗi không commit gì).
- Important findings / decisions:
- Known limitations:
- PR:
