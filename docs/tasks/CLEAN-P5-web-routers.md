# Task: CLEAN-P5 — Tách `web/app.py` thành router theo nhóm route

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S2 (sửa rule W1 của `docs/decisions/CP8.3-web-contract.md`)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — di chuyển code lớn nhưng cơ học, spec theo từng nhóm route, effort `high`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng
- Authorization mode: task
- Authorization source: `docs/audit/code-growth-report.md` §5.2 mục P5; HUMAN LEAD chọn hướng "Tách router" 2026-10-19 (chat)
- Parallel group: —
- Owned paths: `src/auto_short/web/app.py`, `src/auto_short/web/context.py` (mới), `src/auto_short/web/routes/` (mới), `src/auto_short/web/episodes.py` (chỉ đổi tên hàm private bị gọi chéo), test có `monkeypatch.setattr(app_mod, …)` (chỉ đích patch), `docs/decisions/CP8.3-web-contract.md` (W1 + dòng Accepted by), `docs/ai/project-profile.md` (dòng module `web/`), file này
- Dependencies: CLEAN-P4 (#118, đã merge)
- Base commit / branch: `95c213f` (origin/main) / mỗi phase một branch `refactor/p5-<n>-…`
- Human Lead approval: pending
- Implementation authorized: NO

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge (cả ba phase).

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
  - `create_app`: giữ nguyên chữ ký và docstring, dựng `WebContext`, lifespan, middleware, `StaticFiles`, `include_router` theo đúng thứ tự đăng ký cũ.
  - Đổi 5 hàm `ep._*` bị gọi chéo thành tên public (bỏ `_`), sửa mọi nơi gọi.
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
  - **D4** Thứ tự khớp route giữ nguyên. Route bắt-tất-cả `GET /files/{episode_id}/{name}` (hiện dòng 3003, đăng ký cuối) chồng pattern với `/files/post-images/{name}`, `/files/{episode_id}/posts.docx` và các route `/files/…` khác. Nó phải nằm trong router riêng `routes/files_catchall.py`, được `include_router` **sau cùng** ở mọi phase. Mọi route khác giữ thứ tự tương đối cũ.

## Implementation approach

- Mỗi phase: chụp bảng route trước (`[(r.path, sorted(r.methods or []), type(r).__name__) for r in app.routes]` theo thứ tự) bằng script tạm ngoài repo (F6). Di chuyển nhóm. Chụp lại, so khớp. Chạy test targeted rồi full suite.
- Chuyển closure thành tham chiếu `ctx.<field>`, chỉ đổi cơ học. Helper chuyển vào `context.py` giữ nguyên thân.
- Import FastAPI trong router chỉ những gì dùng. Model Pydantic chuyển theo router dùng nó; model dùng ở ≥ 2 router thì để ở `routes/models.py`.

## Phải giữ nguyên

- Chữ ký, tham số mặc định và docstring của `create_app`; `server.py` vẫn `from .app import create_app`.
- Bảng route (path, method, loại route, thứ tự) giống hệt trước.
- Middleware auth (W2), vẫn ở `create_app`: cookie, `LOGIN_DELAY`, redirect `/login?next=…` (303), 401 JSON `chưa đăng nhập` cho `/api/*`, `/files/*` và non-GET, ngoại lệ route worker enhance (`ENHANCE_PREFIX` trừ `ENHANCE_UI_PATHS`); header `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control` như cũ.
- Lifespan: thứ tự `JobRunner.restore()` → làn chạy → vòng tự dọn nguồn; sampler / enhance service khởi động và dừng như cũ.
- Số test thu thập = 2198; tên test, parametrize và assert không đổi.
- OpenAPI / docs vẫn tắt (`docs_url=None`, `redoc_url=None`, `openapi_url=None`).

## Code bị thay / xóa

- Thân route và closure helper trong `create_app` → `web/routes/*.py` / `web/context.py` (xóa khỏi `app.py` trong cùng phase).
- `ep._render_manifest`, `ep._zip_series`, `ep._publish`, `ep._label`, `ep._copy_prefixes` → tên public. Không giữ alias `_`.
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

- Main changes:
- Tests: <bảng AC → test, docs/ai/workflow.md §7>
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
