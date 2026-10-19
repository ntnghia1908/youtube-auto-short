# Task: CLEAN-P4 — Fixture / helper test chung + sửa test chập chờn CP8.10

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — refactor test cơ học, spec rõ từng file, effort `medium`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng
- Authorization mode: task
- Authorization source: `docs/audit/code-growth-report.md` §5.2 mục P4; `docs/workflow/current-state.md` Next action 3 (FIX CP8.10)
- Parallel group: —
- Owned paths: `tests/conftest.py`, `tests/web_helpers.py`, `tests/wait_helpers.py` (mới), 13 file có `wait_for` (`test_hd_first_cp132`, `test_enhance_api`, `test_enhance_pipeline`, `test_enhance_worker`, `test_monitor_cp828`, `test_web_queue_cp822`, `test_web_render_slots_cp836`, `test_prepare_parallel_cp829`, `test_ollama_wait_runner`, `test_priority_cp826`, `test_youtube_wait`, `test_web_stop_fix`, `test_web_lanes_cp810`), 15 file có `tcfg` cơ sở (`test_ollama_wait_runner`, `test_playlist_cp87`, `test_priority_cp826`, `test_web_cp817`, `test_web_cp821`, `test_web_cp85`, `test_web_episode_ui_cp812`, `test_web_khaithi_cp89`, `test_web_lanes_cp810`, `test_web_playlist_groups_cp813`, `test_web_queue_cp822`, `test_web_sutra_sr11`, `test_web_sutra_sr12`, `test_web_titles`, `test_youtube_wait`), 26 file có `client` / `make_client` / `login` / `_login` (danh sách ở Scope), `test_web_series_cp811.py` (`tcfg`), file này. Tất cả dưới `tests/`, không chạm `src/`.
- Dependencies: CLEAN-P2P3 (#117, đã merge)
- Base commit / branch: `46fad94` (origin/main) / `chore/p4-test-fixtures`
- Human Lead approval: pending
- Implementation authorized: NO

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Mỗi helper test dùng chung (`wait_for`, `tcfg` cơ sở, dựng TestClient web, `login`) chỉ còn một bản; `test_web_lanes_cp810.py::test_lanes_overlap_fifo_and_render_job` không còn chập chờn dưới tải. Số test thu thập và hành vi kiểm tra không đổi.

## Bằng chứng trước task (ORCHESTRATOR đo 2026-10-19, base `46fad94`)

- Định nghĩa trùng (AST, `tests/*.py`): `wait_for` 13 file / 3 biến thể; `tcfg` 31 file / 13 biến thể (15 file cùng bản cơ sở `workspace=tmp/work`, `render.output_dir=tmp/output`); `client` 18 / 13 biến thể; `make_client` 9 / 9; `login` 13 + `_login` 9, cùng thân `assert c.post("/login", data={"password": PW}).status_code == 303` (trừ `test_web_app`, `test_youtube_id_dash` gửi thêm `next`); `ws` 11 / 10 biến thể.
- `PW`: 32 file `"pw"`, 4 file khác (`"mật-khẩu"` ×2, `"đúng-mật-khẩu"`, `"pw-test"`).
- Test thu thập: `pytest --collect-only -q -m '' tests` = **2198**.
- Test chập chờn: 64 tiến trình bận CPU trên VM 32 nhân, chạy riêng test 30 lần → **2 / 30 lỗi**, cả hai ở dòng 115 `assert runner.running() == {RENDER: ja}` với `running() == {}`.
  - Nguyên nhân: điều kiện chờ `jc.waiting and jc.lane == RENDER` đạt khi `ja` đã vào hàng chờ làn render (`waiting=True`) nhưng thread làn render chưa kịp lấy `ja` ra (`_current[render]` còn rỗng, `web/jobs.py` `_loop`). Lỗi ở test, không ở runner: A vẫn chạy trước B, C (FIFO đúng).

## Scope

- In scope:
  - **W `wait_for`.** File mới `tests/wait_helpers.py`: `wait_for(pred, timeout=10.0, what="condition")`, poll 0,005 s theo `time.monotonic`, hết giờ → `AssertionError(f"{what} not reached")`. 13 file import thay cho bản riêng. File đang dựa vào mặc định 20 s (`test_hd_first_cp132`, `test_enhance_api`, `test_enhance_pipeline`) truyền `timeout=20.0` ở lời gọi không ghi timeout. `test_enhance_worker` đã gọi `wait_for(cond, timeout, what)` theo vị trí nên khớp chữ ký; mặc định 60 s của nó → truyền rõ ở lời gọi không ghi timeout.
  - **F FIX CP8.10.** `test_lanes_overlap_fifo_and_render_job`: điều kiện chờ thêm `runner.running().get(RENDER) is ja` (giữ nguyên mọi assert sau đó). Docstring module vẫn đúng (chỉ còn "settle" trước assert phủ định ở test khác).
  - **T `tcfg`.** Thêm fixture `tcfg` cơ sở vào `tests/conftest.py`; xóa bản riêng ở 15 file trên. `test_web_series_cp811` (`output_dir=tmp/out`) chuyển sang bản chung nếu không test nào phụ thuộc tên `out`. 15 file biến thể còn lại giữ fixture riêng (pytest ưu tiên fixture trong module).
  - **C client / login.** Trong `tests/web_helpers.py`:
    - `PW = "pw"`, `DISK_OK = lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9)`.
    - `make_app(cfg, password=PW, **kw)`: `create_app` với mặc định `preflight=lambda c: None`, `pipeline=fake_pipeline([])`, `disk_usage=DISK_OK`; `kw` ghi đè.
    - `web_client(cfg, *, login=False, password=PW, **kw)` → `TestClient(make_app(...), follow_redirects=False)`, `login=True` thì đăng nhập luôn.
    - `login(c, password=PW, **data)` assert 303.
    - 26 file: bỏ `login` / `_login` riêng; `client` / `make_client` riêng thành lời gọi `web_client` / `make_app` (giữ hàm bọc mỏng khi file có fake riêng như `FakeRender`, `FakeComposeAI`, hoặc trả `(c, app)`). File có `PW` khác truyền `password=`.
    - File: `test_web_episode_ui_cp812`, `test_playlist_cp87`, `test_web_downloads_cp834`, `test_web_cp9`, `test_web_queue_cp822`, `test_web_post_doc_cp819`, `test_web_hd_cp827`, `test_youtube_id_dash`, `test_web_app`, `test_storage_cp86`, `test_web_series_cp811`, `test_web_vertical_cp832`, `test_web_imgsearch_cp830`, `test_web_auto_vertical_cp835`, `test_web_cp85`, `test_web_compilation`, `test_web_lanes_cp810`, `test_web_post_cp815`, `test_web_playlist_groups_cp813`, `test_web_post_corrections_cp818`, `test_web_cp831`, `test_web_khaithi_cp89`, `test_web_post_cp816`, `test_web_cp821`, `test_web_cp817`, `test_web_titles`.
- Out of scope:
  - `ws` (10 biến thể khác dữ liệu, đều đã gọi `make_*_episode`; gộp thêm không giảm dòng đáng kể).
  - `test_web_theme_index.client` (đăng nhập JSON + cookie qua `fx.build_app`, khác luồng).
  - `create_app` gọi trực tiếp trong thân test (không qua helper `client` / `make_client`).
  - Các biến thể `tcfg` có thêm section (`post`, `web`, `enhance`, `preset`, params `lanes` / `serial`).
  - Sửa `src/` (kể cả `web/jobs.py`): runner đúng, lỗi ở test.
  - Test chập chờn khác (nếu thấy khi chạy suite: ghi vào Result, không sửa).

## Authority / key decisions

- `docs/audit/code-growth-report.md` §5.2 P4; `docs/ai/workflow.md` §4 (code bị thay phải xóa).
- Quyết định cục bộ cần HUMAN LEAD duyệt:
  - **D1** `make_app` mặc định `disk_usage=DISK_OK` cả cho các file hiện **không** truyền `disk_usage` (`test_web_cp85`, `test_web_titles`, `test_web_app`, `test_youtube_id_dash`, `test_web_post_*`, `test_web_cp9`, `test_web_imgsearch_cp830`): các test này hiện đọc dung lượng đĩa thật của VM, một nguồn phụ thuộc môi trường. Không test nào trong số đó kiểm cảnh báo đĩa (IMPLEMENTER xác nhận bằng grep `disk`/`storage`/`BLOCK_MESSAGE`; nếu có thì file đó truyền `disk_usage=None` → giữ hành vi cũ).
  - **D2** `wait_for` chung poll 0,005 s cho cả `test_enhance_worker` (cũ 0,1 s, `time.time`): chỉ poll nhanh hơn, thông điệp lỗi giữ `what`.
- Không đổi dependency, không đổi `pyproject.toml` / cấu hình pytest.

## Implementation approach

- Làm theo thứ tự W → F → T → C, chạy test targeted của từng file sau mỗi nhóm.
- Import helper theo kiểu hiện có (`from web_helpers import ...`, `tests/` đã nằm trên `sys.path` qua rootdir); không dùng `from conftest import`.

## Phải giữ nguyên

- Số test thu thập (`--collect-only -m ''`) = 2198; tên test, parametrize và assert không đổi (ngoài điều kiện chờ ở F).
- Timeout thực tế của từng lời gọi `wait_for` (10 / 20 / 60 s như cũ).
- `PW` từng file (4 file khác `"pw"` vẫn đăng nhập bằng mật khẩu riêng).
- `login` của `test_web_app` trả response (không assert) và gửi `next`; `test_youtube_id_dash` gửi `next`.
- `test_web_auto_vertical_cp835.make_client` vẫn `__enter__()` client (lifespan).

## Code bị thay / xóa

- 13 bản `def wait_for` trong file test → `tests/wait_helpers.wait_for`.
- 15 (+1 `test_web_series_cp811` nếu được) fixture `tcfg` cơ sở → `tests/conftest.tcfg`.
- 22 bản `login` / `_login` → `web_helpers.login` (`test_web_app` giữ hàm bọc trả response nếu caller cần response).
- Thân `create_app(... preflight / pipeline / disk_usage ...)` + `TestClient(...)` lặp trong các helper `client` / `make_client` → `web_helpers.make_app` / `web_client`; hàm bọc mỏng còn lại chỉ truyền fake riêng của file.
- Hằng `PW = "pw"` cục bộ ở file không còn dùng trực tiếp → xóa (import `PW` từ `web_helpers` nếu test còn tham chiếu).
- Import thừa (`time`, `TestClient`, `app_mod`, `WorkspaceConfig`, `RenderConfig`, …) sau khi xóa.

## Acceptance Criteria

1. `grep -rnE '^def wait_for\(' tests` chỉ còn `tests/wait_helpers.py`.
2. `grep -rnE '^def _?login\(' tests` chỉ còn `tests/web_helpers.py` (và `test_web_app.py` nếu giữ hàm bọc trả response).
3. Không file nào trong 15 (+1) file liệt kê ở T còn fixture `tcfg` riêng; `tests/conftest.py` có `tcfg` cơ sở.
4. Không helper `client` / `make_client` nào trong các file ở C còn gọi `app_mod.create_app(` trực tiếp.
5. `test_lanes_overlap_fifo_and_render_job` dưới tải (64 tiến trình bận CPU, 30 lần): 0 lỗi (trước: 2 / 30).
6. Số test thu thập = 2198; full suite PASS.
7. Diff `tests/` giảm ròng ≥ 150 dòng.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest -q -p no:cacheprovider <13 file W> <26 file C> <file T>` — AC1–4 không phá test (IMPLEMENTER chạy được phần không cần socket; ORCHESTRATOR chạy lại toàn bộ ngoài sandbox).
- grep AC1–4 — AC1–4.
- Script tải CPU + 30 lần test CP8.10 (ORCHESTRATOR, ngoài sandbox) — AC5.
- `PYTHONPATH=<worktree>/src python -m pytest --collect-only -q -m '' tests` = 2198 và `PYTHONPATH=<worktree>/src python -m pytest -q -n auto -p no:cacheprovider tests` PASS (ORCHESTRATOR) — AC6.
- `git diff --numstat origin/main -- tests` — AC7.
- `node scripts/framework-check.mjs` PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract; chỉ sửa `tests/`. Manual test là điểm danh, không phải gate.

- [ ] Đọc lướt `tests/wait_helpers.py`, `tests/web_helpers.py`, `tests/conftest.py` mới.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
