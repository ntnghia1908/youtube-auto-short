# Task: CLEAN-P5 — Tách `web/app.py` thành router theo nhóm route

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — di chuyển code lớn nhưng cơ học, spec theo từng nhóm route, effort `high`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng
- Authorization mode: task
- Authorization source: `docs/audit/code-growth-report.md` §5.2 mục P5; HUMAN LEAD chọn hướng "Tách router" 2026-10-19 (chat)
- Parallel group: —
- Owned paths: `src/auto_short/web/app.py`, `src/auto_short/web/context.py` (mới), `src/auto_short/web/routes/` (mới), `src/auto_short/web/episodes.py` (chỉ đổi tên hàm private bị gọi chéo và biến local che tên public), `src/auto_short/web/monitor.py`, `src/auto_short/web/playlists.py`, `src/auto_short/web/storage.py`, `src/auto_short/web/compilations.py` (A1: chỉ sửa caller cơ học), test có `monkeypatch.setattr(app_mod, …)` (chỉ đích patch), `docs/decisions/CP8.3-web-contract.md` (W1 + dòng Accepted by), `docs/ai/project-profile.md` (dòng module `web/`), file này
- Dependencies: CLEAN-P4 (#118, đã merge)
- Base commit / branch: `95c213f` (origin/main) / mỗi phase một branch `refactor/p5-<n>-…`
- Human Lead approval: accepted 2026-10-19 (chat "APPROVE CLEAN-P5": D1–D4)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge (cả ba phase).

S2 vì: sửa rule W1 của `docs/decisions/CP8.3-web-contract.md`.

## Goal

`web/app.py` chỉ còn app factory: dựng state, lifespan, middleware auth, gắn router. Route chia theo nhóm vào `web/routes/*.py`. Không route nào đổi method, path, tham số, response, status code hay thứ tự khớp. Không còn gọi hàm private chéo module trong `web/`.

## Bằng chứng trước task (ORCHESTRATOR đo 2026-10-19, base `95c213f`)

- `web/app.py` dài 3 054 dòng. `create_app` (dòng 384–3054) có 188 hàm lồng dùng state qua closure và 103 route.
- Dòng route theo nhóm (gồm closure helper nằm giữa các route): `/api/episodes` 1 076, `/api/playlists` 491, `/files` 141, `/api/post-images` 136, `/api/enhance` (+ `enhance-pause`) 118, `/api/post-corrections` 77, `/api/reading` 59, `/api/monitor` 49, trang + auth (`/`, `/login`, `/logout`, `/episodes`, `/playlists`, `/storage`, `/monitor`, `/sutras`) ≈ 100, nhỏ khác (`queue`, `deleted`, `storage`, `downloads`, `ui`) ≈ 55.
- State dùng chung (dòng 411–715): `runner`, `tokens`, `storage`, `playlists`, `submit_lock`, `publish_lock`, `post_lock`, `auto_vertical`, `signer`, `svc`, `sampler`, `ollama_view`, `compilations`, `theme_plans`, `download_table` + các callable inject (`preflight`, `pipeline`, `render`, `clock`, `titler`, `post_*`, `vertical*`, …). Helper closure dùng chung ≈ 250 dòng (450–700).
- Auth bằng `@app.middleware("http")` (dòng 727). `Depends` chỉ dùng cho worker enhance (`_worker`).
- Gọi private chéo: `ep._render_manifest` ×4, `ep._zip_series`, `ep._publish`, `ep._label`, `ep._copy_prefixes`.
- Rule W1 (`CP8.3` dòng 21) "Chỉ `web/app.py` và `web/server.py` import FastAPI/uvicorn" đã lệch thực tế: `web/downloads.py`, `web/theme_index.py`, `web/theme_plan.py`, `sutra/web.py` cũng import.
- Test: 25 file import `web.app`; 13 patch `monkeypatch.setattr(app_mod, …)` (`LOGIN_DELAY` ×8, `reject_clip` ×2, `mark_downloaded`, `delete_episode`, `classify_url`); dựng app qua `tests/web_helpers.make_app` → `create_app`. Test thu thập: **2198**.

## Scope

- In scope:
  - `web/context.py`: `WebContext` (dataclass) giữ state + callable inject + helper dùng chung ≥ 2 nhóm route. Không import FastAPI.
  - `web/routes/<nhóm>.py`: mỗi file có `def build(ctx: WebContext) -> APIRouter`, route giữ nguyên thân, đọc state qua `ctx`. Helper closure chỉ một nhóm dùng thì chuyển theo nhóm đó.
  - `create_app`: giữ nguyên chữ ký và docstring, dựng `WebContext`, lifespan, middleware, `StaticFiles`, `include_router` mỗi router nguyên khối đúng một lần; giữ thứ tự khớp của các cặp route chồng pattern (review P5.1 F1).
  - Đổi 6 hàm `ep._*` bị gọi chéo thành tên public (bỏ `_`), sửa mọi nơi gọi (A1 bổ sung `_series`).
  - Test: đổi đích `monkeypatch.setattr` sang module đang dùng tên đó. Không đổi assert.
  - Sửa đổi CP8.3 W1 (D1) và dòng module `web/` trong project-profile.
- Out of scope:
  - Đổi hành vi, URL, payload, thông điệp lỗi, model Pydantic (chỉ di chuyển sang file router dùng nó).
  - Tách `web/jobs.py` (2 055 dòng) hay module logic khác.
  - Gom / viết lại helper ngoài việc di chuyển (trùng phát hiện thêm thì ghi vào Result).
  - Thêm dependency, đổi `pyproject.toml`.

## Authority / key decisions

- `docs/decisions/CP8.3-web-contract.md` (W1, W2 auth, W7 API); `docs/audit/code-growth-report.md` §5.2 P5; `docs/ai/workflow.md` §4, §8 (F4 ngân sách diff).
- **D0 (đã chọn, HUMAN LEAD 2026-10-19):** tách router, sửa rule W1. Phương án loại: giữ rule và chỉ tách logic (app.py còn ≈ 1 200–1 500 dòng); chỉ sửa private (không giảm god-file).
- Cần HUMAN LEAD duyệt:
  - **D1** W1 mới: "FastAPI / Starlette / uvicorn chỉ được import trong package `web/` và `sutra/web.py`. CLI pipeline và các package xử lý (`pipeline`, `render`, `review`, `post`, …) không phụ thuộc web; `auto-short web` khi chưa cài `[web]` vẫn exit 1 như cũ."
  - **D2** State qua `WebContext` truyền vào factory `build(ctx)`, không dùng `app.state` hay biến module toàn cục. Lý do: giữ cơ chế inject callable của `create_app` mà test đang dựa vào, và không đổi chữ ký `create_app`.
  - **D3** Ba phase, mỗi phase một PR:
    - **P5.1** hạ tầng (`context.py`, `routes/`), trang + auth, `files`, `monitor`, `queue`, `storage`, `deleted`, `downloads`, `ui`, `reading`, `sutras`; đổi tên `ep._*`; sửa CP8.3 W1 + project-profile. ≈ 500 dòng di chuyển.
    - **P5.2** `playlists`, `enhance` (+ `enhance-pause`), `post-images`, `post-corrections`. ≈ 820 dòng.
    - **P5.3** `/api/episodes` thành hai file (`routes/episodes.py`: xem / tải / publish / xóa; `routes/episode_edit.py`: title, cuts, add, post). ≈ 1 076 dòng. Vượt ~800 của F4 nhưng là di chuyển thuần nên ghi lý do ở đây, không tách thêm PR.
  - **D4** Thứ tự khớp route giữ nguyên. Route bắt-tất-cả `GET /files/{episode_id}/{name}` (hiện dòng 3003, đăng ký cuối) chồng pattern với `/files/post-images/{name}`, `/files/{episode_id}/posts.docx` và các route `/files/…` khác. Nó phải nằm trong router riêng `routes/files_catchall.py`, được `include_router` **sau cùng** ở mọi phase. Giữ thứ tự tương đối của các cặp route chồng pattern; route không chồng có thể đăng ký theo nhóm router (ORCHESTRATOR review P5.1 F1, 2026-10-19).

## Amendment A1 — ORCHESTRATOR review P5.1, 2026-10-19

- Bổ sung 4 file caller `monitor.py`, `playlists.py`, `storage.py`, `compilations.py` vào Owned paths và `_series → series` vào phạm vi AC3; ORCHESTRATOR đã áp dụng bản vá đổi tên, IMPLEMENTER không áp lại.
- F1 làm rõ D4: chỉ giữ thứ tự của các cặp route chồng pattern; include mỗi router P5.1 nguyên khối đúng một lần, thành một khối liền nhau. Catch-all sau cùng.
- F2: mọi verification Python / pytest phải đặt `PYTHONPATH` trỏ `src` của worktree. Không sử dụng số PASS vòng trước; chạy lại targeted.

## Amendment A2 — ORCHESTRATOR review P5.3, 2026-10-19

- Helper test tra endpoint theo tên (`tests/test_restore_source_cp837.py` `endpoint()`) được duyệt cả router lồng (`_IncludedRouter.original_router`). Đây là đích tra cứu như đích `monkeypatch.setattr`; assert, tên test, parametrize không đổi. ORCHESTRATOR áp dụng bản vá.

## Implementation approach

- Mỗi phase: chụp bảng route trước (`[(r.path, sorted(r.methods or []), type(r).__name__) for r in app.routes]` theo thứ tự) bằng script tạm ngoài repo (F6). Di chuyển nhóm. Chụp lại, so khớp. Chạy test targeted rồi full suite.
- Chuyển closure thành tham chiếu `ctx.<field>`, chỉ đổi cơ học. Helper chuyển vào `context.py` giữ nguyên thân.
- Import FastAPI trong router chỉ những gì dùng. Model Pydantic chuyển theo router dùng nó; model dùng ở ≥ 2 router thì để ở `routes/models.py`.

## Phải giữ nguyên

- Chữ ký, tham số mặc định và docstring của `create_app`; `server.py` vẫn `from .app import create_app`.
- Bảng route (path, method, loại route) và thứ tự khớp các cặp chồng pattern giống hệt trước (review P5.1 F1).
- Middleware auth (W2), vẫn ở `create_app`: cookie, `LOGIN_DELAY`, redirect `/login?next=…` (303), 401 JSON `chưa đăng nhập` cho `/api/*`, `/files/*` và non-GET, ngoại lệ route worker enhance (`ENHANCE_PREFIX` trừ `ENHANCE_UI_PATHS`); header `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control` như cũ.
- Lifespan: thứ tự `JobRunner.restore()` → làn chạy → vòng tự dọn nguồn; sampler / enhance service khởi động và dừng như cũ.
- Số test thu thập = 2198; tên test, parametrize và assert không đổi.
- OpenAPI / docs vẫn tắt (`docs_url=None`, `redoc_url=None`, `openapi_url=None`).

## Code bị thay / xóa

- Thân route và closure helper trong `create_app` → `web/routes/*.py` / `web/context.py` (xóa khỏi `app.py` trong cùng phase).
- `ep._render_manifest`, `ep._zip_series`, `ep._publish`, `ep._label`, `ep._copy_prefixes`, `ep._series` (A1) → tên public. Không giữ alias `_`.
- Import trong `app.py` không còn dùng sau mỗi phase.

## Acceptance Criteria

1. Sau P5.3, `web/app.py` ≤ 700 dòng và không chứa decorator route (`grep -cE '@(app|router)\.(get|post|put|patch|delete|websocket)\(' src/auto_short/web/app.py` = 0).
2. Bảng route trước / sau mỗi phase giống hệt (script so khớp ghi trong Result: số route, diff rỗng).
3. `grep -rnE '\bep\._[a-z]' src/auto_short/web` rỗng; không module nào trong `web/` import tên `_…` của module khác trong `web/`.
4. `grep -rlE '^\s*(from|import) (fastapi|starlette|uvicorn)' src` chỉ ra file trong `src/auto_short/web/` và `src/auto_short/sutra/web.py` (đúng D1).
5. Full suite PASS, collect = 2198, assert test không đổi (diff test chỉ ở đích `monkeypatch.setattr` / import).
6. CP8.3 W1 ghi rule D1; dòng "Accepted by" thêm "Sửa đổi HUMAN LEAD 2026-10-19 (CLEAN-P5, D1–D4): W1"; project-profile dòng `web/` có `routes/`, `context.py`.

## Required verification

- `python -m pytest -q -m '' tests` (full suite, ngoài sandbox) — AC 5.
- `python -m pytest --collect-only -q -m '' tests | tail -1` = 2198 — AC 5.
- Script so bảng route trước / sau (tạm, ngoài repo) — AC 2.
- Các lệnh `grep` / `wc -l` ở AC 1, 3, 4.
- `jscpd` + `vulture` tạm trên file đổi (F5): không tăng trùng / code chết.
- Pin 8080 vào commit của phase, smoke thủ công (mục dưới).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task không đổi database, security model hay public API contract (route giữ nguyên). Middleware auth được di chuyển, không đổi, nên smoke đăng nhập là gate trước merge của P5.1. Các mục còn lại chỉ là điểm danh.

- [ ] P5.1: đăng nhập / đăng xuất, sai mật khẩu bị chậm; tab Bộ nhớ, Theo dõi, Đọc Kinh mở được; tải một Short `.mp4` và `shorts.zip`.
- [ ] P5.2: trang bộ kinh (danh sách, "Chạy tiếp cả bộ"), thư viện ảnh bài đăng, Từ điển sửa lỗi; worker enhance lấy lease được.
- [ ] P5.3: trang tập: sửa title + render lại, Thêm Short, Sửa đầu/cuối, đánh dấu Đã đăng, xóa / khôi phục Short.

## Result

### P5.1 — sửa review vòng 1, 2026-10-19

- **F1 đã sửa:** 5 router mới include nguyên khối đúng một lần, trong một khối sau các route còn lại và router sutra; catch-all sau router theme, cuối cùng. Bỏ mọi slice / import `APIRouter` trong app.py và các biến `*_router` tạm. Không thay thân route / helper / middleware / lifespan.
- **F2 đã sửa:** lượt verification mới đều dùng `PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/chg-current-state-trim/src`; đã assert `auto_short.web.app.__file__` đúng worktree. Không dùng kết quả PASS của vòng trước.
- A1: giữ nguyên bản vá public hóa 6 hàm do ORCHESTRATOR áp dụng; `rg -n '\bep\._[a-z]' src/auto_short/web` rỗng. Không sửa test, không helper mới, không commit/push, không mạng, không P5.2/P5.3 trong vòng này.

Trích cuối `create_app` (app.py:2407; StaticFiles vẫn mount ở dòng 684; sutra router dòng 2311):

```python
app.include_router(auth.build(ctx))
app.include_router(pages.build(ctx))
app.include_router(status.build(ctx))
app.include_router(reading_api.build(ctx))
app.include_router(files.build(ctx))

theme_index_web.register(app, config, playlists, STATIC_DIR)
theme_plan_web.register(app, theme_plans)

app.include_router(files_catchall.build(ctx))  # cuối cùng
```

| AC / finding | Verification vòng này |
|---|---|
| F1 / AC2 / D4 | Script ORCHESTRATOR → **127 route, 3 cặp chồng**; diff `/tmp/p51-review1-after.txt` với `…/p5/base.txt` **rỗng**. AST xác nhận 5 router đúng một lần, liền nhau; catch-all cuối; không `APIRouter` / slice. |
| F2 / AC5 | Targeted chọn không socket: **58 passed, 1 warning in 2.20s**. Collect: **2198 tests collected in 3.47s**. Assert / tên test / parametrize giữ nguyên. |
| Auth / signature / lifespan | `/tmp/p51_ast_review.py`: **103 route + 25 helper** tương đương cơ học; chữ ký/docstring create_app và AST middleware/lifespan giữ nguyên. `/tmp/p51-direct-smoke.py`: PASS auth/pages, reading so docx, file MP4/ZIP, queue, monitor, storage, downloads, deleted, ui (không TestClient/socket; không thay integration test). |
| AC3 / AC4 | Không còn `ep._…`; FastAPI/Starlette/uvicorn chỉ import trong `web/` và `sutra/web.py`. |
| AC1 / AC6 | app.py **3054 → 2418 dòng**; mốc ≤700 chỉ sau P5.3. Docs W1 và project-profile đã sửa. |

Lệnh mới (tất cả đặt `PYTHONPATH` tuyệt đối nêu trên):

- `python /home/ntnghia/.claude/jobs/1c1feb65/tmp/p5/routes.py "$PWD" /tmp/p51-review1-after.txt` rồi `diff /home/ntnghia/.claude/jobs/1c1feb65/tmp/p5/base.txt /tmp/p51-review1-after.txt`: PASS, rỗng.
- `timeout 120 xargs -a /tmp/p51-unit-nodes.txt /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short tests/test_dlqueue_cp834.py`: **58 PASS** (storage, monitor, reading, downloads, naming/file, playlist, HD lease order, dlqueue).
- `timeout 120 python -m pytest --collect-only -q -m '' tests`: **2198**, exit 0.
- `timeout 120 python -m pytest -q -x --tb=short -o faulthandler_timeout=20 tests/test_web_app.py`: **TIMEOUT 120s, exit 124** ở `TestClient.__enter__` / `anyio.from_thread`; log `/tmp/p51-review1-web-app.log`. Không claim PASS integration.
- AST review, direct endpoint smoke, `git diff --check`: PASS. Full suite / smoke 8080 dành cho ORCHESTRATOR. `jscpd`/`vulture` chưa có cục bộ, không cài/mạng. Framework checker vòng trước có lỗi metadata contract `Change class: S2 (…)`, chưa sửa.

Diff: vòng sửa này riêng app.py **+6 / −67**, test **+0 / −0**, contract/Result **+47 / −36**; toàn P5.1 ứng dụng **+933 / −746** (gồm file mới và A1), riêng app.py **+74 / −710**, test **+18 / −10**, authority docs **+4 / −4** (chưa tính contract/Result). Không coi full suite / smoke / TestClient là PASS; ORCHESTRATOR chạy verification còn lại trước gate READY/merge.

### P5.1 — ORCHESTRATOR verification, 2026-10-19

- Full suite (ngoài sandbox, `PYTHONPATH=<worktree>/src`): **2185 passed, 13 skipped** (631 s). Collect 2198.
- Bảng route (script tạm ngoài repo): 127 route, 3 cặp chồng, diff với base `95c213f` rỗng.
- F5: `jscpd` `src/auto_short/web` 1 clone có sẵn trong `storage.py` (không do P5.1); `vulture` file đổi chỉ báo route handler / callback (dương tính giả), không helper chuyển sang mà không dùng.
- Diff + / −: src +933 / −746 (app.py 3054 → 2418; mới `context.py` 248, `routes/` ≈ 575), tests +18 / −10 (chỉ đích patch / import).
- Helper mới: không (helper closure chuyển nguyên thân vào `WebContext` / router).
- IMPLEMENTER: Codex (`gpt-6.1-sol`, high), 2 vòng (≈ 166k + 218k tokens). Review vòng 1: F1 cắt router theo chỉ số → include nguyên khối; F2 PYTHONPATH (test vòng đầu chạy nhầm code checkout chính).
- Manual smoke 8080 (gate P5.1): chờ HUMAN LEAD.

### P5.2 — 2026-10-19 (branch `refactor/p5-2-routers`, base `9df942e`)

- Router mới: `routes/playlists.py` (20 route `/api/playlists*`, gồm vertical / favorites / compilations / enhance-redo), `routes/enhance.py` (7 route `/api/enhance/*` + `enhance-pause`, `Depends(_worker)`), `routes/post_images.py` (9 `/api/post-images*` + `/files/post-images/{name}` + `/files/post-image-candidates/…`), `routes/post_corrections.py` (4), `routes/models.py` (`PublishedIn`, dùng bởi playlists + app.py). Include nối vào khối liền nhau của P5.1; catch-all vẫn cuối. Route `/api/episodes/{id}/enhance*`, `/posts*` ở lại cho P5.3.
- `WebContext`: thêm 11 field inject (`submit_lock`, `auto_vertical`, `pipeline`, `preflight`, `vertical*`, `post_*`, `keyword_search`, `doc_prepare`) và 7 helper dùng ≥ 2 nhóm chuyển nguyên thân (`vertical_target`, `restore_job`, `auto_vertical_waiting`, `job_view`, `queue_video`, `post_now`, `enh_error` nhận `error_response` để context không import FastAPI); hằng `KINDS`, `KIND_RESTORE_SOURCE` chuyển sang `context.py`, app.py vẫn import lại (test `test_restore_source_cp837` import từ `web.app`). Helper mới: không.
- AC1: app.py **2418 → 1464** dòng. AC2: 127 route, 3 cặp chồng, cùng quan hệ BEFORE; diff thô chỉ khác thứ tự liệt kê dòng cặp `/files/post-images/{name} BEFORE catch-all` (script in cặp theo vị trí route trước), `diff <(sort base) <(sort after)` **rỗng**. AC3 rỗng; AC4 chỉ `web/` + `sutra/web.py`; `git diff --check` sạch.
- AC5: full suite ngoài sandbox (`pytest -o pythonpath=src`, đã xác nhận import `routes/enhance.py` của worktree): **2185 passed, 13 skipped** (641 s); collect 2198. Test **+0 / −0**.
- F5: `vulture` (≥ 60 %) `web/` trước / sau 128 = 128, không khác. `jscpd` thêm 1 clone 5 dòng trong `routes/post_images.py` (409 "đang tìm ảnh" của `search` và `find`) — trùng có sẵn trong app.py gốc, vượt ngưỡng token do tiền tố `ctx.`; không gom (ngoài scope).
- Diff: app.py **+135 / −1089**, `context.py` **+112 / −5**, `routes/` mới **+1022**; test 0. Codex trong sandbox: 64 test targeted PASS, `test_enhance_api.py` treo ở `TestClient.__enter__` (đã chạy trong full suite ngoài sandbox).
- IMPLEMENTER: Codex (`gpt-6.1-sol`, high), 1 vòng, ≈ 9 phút, 165k tokens; không vòng sửa.
- Manual smoke 8080 (điểm danh P5.2): chờ HUMAN LEAD.

### P5.3 — 2026-10-19 (branch `refactor/p5-3-episodes`, base `8560eb4`)

- Chuyển 30 route còn lại sang `routes/episodes.py` (19) và `routes/episode_edit.py` (11), mỗi router `build(ctx)` include nguyên khối sau `post_corrections_routes`, trước theme; catch-all vẫn cuối. Model/helper riêng đi theo router; `PublishedIn` dùng lại từ `routes/models.py`.
- `WebContext`: di chuyển nguyên thân 3 helper dùng chung `check_clip`, `episode_or_404`, `busy` (nhận `error_response`, không import FastAPI); thêm `render`, `titler` và 4 callable trỏ tới callback factory `enhance_complete`, `hd_ready`, `release_hd`, `restore_target`. Helper mới: không. Callback/lifespan/middleware và `RestoreSourceTarget` giữ ở app.py; giữ re-export `KINDS` / `KIND_RESTORE_SOURCE`.
- AC1: app.py **1464 → 581 dòng**, decorator route **0**. AC2: **127 route, 3 cặp chồng**, diff thô và sort với `…/tmp/p5/base53.txt` đều **rỗng** (`/tmp/p53/after53.txt`). AC3: không `ep._…` / import private chéo trong `web/`; AC4 chỉ `web/` + `sutra/web.py`; `git diff --check` sạch.
- AST `/tmp/p53/review.py`: **61 hàm/helper** tương đương cơ học, gồm 30 route; model/constant, signature/docstring factory không đổi; callback/middleware/lifespan AST nguyên vẹn. Smoke `/tmp/p53/smoke.py`: PASS gọi trực tiếp đủ 30 handler bằng fixture cục bộ, chặn network; có title/render, delete/restore Short, cut/reset, add, posts compose/edit/posted và kiểm đích patch mới.
- AC5: collect **2198** (`-m '' -o pythonpath=src`); targeted **14 PASS** prepare/Whisper và **121 PASS, 3 deselected** review/post backend (`-k 'not preflight'`). Lượt backend đầu: 116 PASS rồi lỗi socket `test_post_stage.py::test_preflight_ok`; không coi lượt đó PASS. `test_web_titles.py`: **TIMEOUT 120s, exit 124**, ở `TestClient.__enter__`. Full suite / manual smoke 8080 dành cho ORCHESTRATOR; không claim PASS.
- Đích patch: `test_web_compilation.py:373` `app_mod.delete_episode → routes.episodes.delete_episode`; `:389`, `:514` `app_mod.reject_clip → routes.episode_edit.reject_clip`; `test_youtube_id_dash.py:118` `app_mod.classify_url → routes.episodes.classify_url`. `replace` (test prepare), `JobRunner`, `episode_sizes` vẫn tra ở app.py; `mark_downloaded` vẫn tra ở context.py, không đổi patch.
- Blocker Codex: `test_restore_source_cp837.py:94` helper `endpoint()` chỉ duyệt lớp ngoài `app.routes` nên `test_route_statuses_duplicate_sibling_and_busy_guards` gặp `StopIteration` sau khi route vào router. ORCHESTRATOR áp bản vá duyệt router lồng theo A2 (test +8 / −1, assert không đổi).
- F5: `jscpd` toàn `web/` trước/sau **9 clone, 69 dòng trùng**; `vulture` **128 → 127 finding**, không finding mới. Pyflakes chỉ còn `KINDS` re-export có sẵn; không thêm import không dùng. Logs/scripts tạm ở `/tmp/p53/`, không thêm dependency/mạng/commit/push.

### P5.3 — ORCHESTRATOR verification, 2026-10-19

- Full suite ngoài sandbox (`pytest -q -m '' -o pythonpath=src`, sau bản vá A2): **2185 passed, 13 skipped** (654 s); collect 2198.
- Bảng route chạy lại: 127 route, 3 cặp chồng, diff thô với base `8560eb4` **rỗng**. AC1 app.py **581** dòng, 0 decorator; AC3 / AC4 grep đạt; `git diff --check` sạch.
- Diff: app.py **+13 / −896**, `context.py` **+24 / −0**, `routes/` mới **+913**, tests **+14 / −6** (đích patch + A2). Helper mới: không.
- IMPLEMENTER: Codex (`gpt-6.1-sol`, high), 1 vòng, 147k tokens; ORCHESTRATOR áp bản vá test A2, không vòng sửa.
- Manual smoke 8080 (điểm danh P5.3): chờ HUMAN LEAD.
