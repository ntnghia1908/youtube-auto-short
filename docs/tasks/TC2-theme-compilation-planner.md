# Task: TC2 — AI Thematic Compilation Planner

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session (Opus), review độc lập
- Implementer: claude-code — subagent `implementer` (Sonnet), một writer. Ban đầu chọn `codex exec`; 2026-10-18 Codex BLOCKED trước khi sửa file (sandbox bwrap lỗi `RTM_NEWADDR` trên VM, chạy không sandbox bị chặn) → đổi binding, không có code Codex.
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/TC1-TC3-implementation-authorization.md` (ACCEPTED 2026-10-18) + Amendment A1 trong file đó (khoảng thời lượng 240–420 s)
- Parallel group: —
- Owned paths: xem §Owned paths
- Dependencies: TC1 + TC-WEB1 (merged PR #96, `a77f04a`); không dependency thư viện mới
- Base commit / branch: `c7fd2ae` (authorization, con của `main` `d56d200`) / `feature/tc2-theme-plan`, worktree `/home/ntnghia/youtube-auto-short-tc2`
- Human Lead approval: boundary inherited; G1, G2, G4 accepted 2026-10-18; G3 (HTTP API/UI) pending — phase A/B không chạm web
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`. Push / PR / merge / deploy cần HUMAN LEAD duyệt riêng.

## Goal

Trên một bộ kinh, HUMAN LEAD bấm một nút để (1) sinh / cập nhật index chủ đề TC1 bằng Ollama thật và (2) nhận các đề xuất chủ đề, mỗi đề xuất là danh sách khai thị yêu thích không trùng, có thứ tự nghe, tổng 30–40 phút. HUMAN LEAD chọn một đề xuất, bỏ / thêm / sắp lại clip rồi duyệt; kết quả là một `compilation_plan` có version, snapshot fingerprint và dấu duyệt, tự mất hiệu lực khi dữ liệu nguồn hoặc nội dung kế hoạch đổi. TC2 không render video (TC3).

## Scope

- In scope:
  - A1: khoảng thời lượng eligible của TC1 đổi 300–420 → 240–420 s (hằng số module, tests biên 239/240/420/421).
  - G2 (nếu duyệt phương án A): TC1 cho phép clip có file nguồn đã bị xoá khi chuỗi hash lưu trong artifact nhất quán; record mang `source_status` để TC3 biết phải khôi phục + kiểm.
  - Planner module độc lập: đọc index TC1 đã validate, gọi Ollama (client hiện có) đề xuất chủ đề + clip + thứ tự, validate strict, áp dụng ràng buộc không trùng / thời lượng / không lặp, báo thiếu thời lượng.
  - Lưu proposals và plan có revision; sửa plan xoá duyệt; duyệt gắn với revision + fingerprint snapshot; kiểm stale mỗi lần đọc.
  - Job nền làn `ai` (build index ghi cache + đề xuất), Ollama-wait theo cơ chế hiện có; không khôi phục sau restart.
  - HTTP routes + trang web theo G3; link từ trang Yêu thích.
- Out of scope: render / ghép / tải video (TC3), nhiều bộ kinh, tạo clip mới, lặp / độn thời lượng, AI viết câu nói hay trích dẫn mới, vector DB, dependency mới, publish, đổi hành vi CP8.33 hiện có, đổi framework, sửa TC-WEB1 ngoài việc tests biên thời lượng.

## Owned paths

- `src/auto_short/theme_index/__init__.py` — chỉ A1 và G2.
- `src/auto_short/theme_plan/` (mới) — planner, store, validation.
- `src/auto_short/web/theme_plan.py` (mới) — routes, job target.
- `src/auto_short/web/app.py` — chỉ wiring (register + link service).
- `src/auto_short/web/static/theme_plan.html`, `theme_plan.js` (mới); `favorites.html|js` — chỉ thêm link tới trang kế hoạch.
- `tests/test_theme_index.py`, `tests/test_web_theme_index.py` — chỉ biên thời lượng / G2.
- `tests/test_theme_plan*.py`, `tests/test_web_theme_plan.py` (mới).
- `docs/tasks/TC2-theme-compilation-planner.md`, `docs/decisions/TC1-TC3-implementation-authorization.md` (amendment).

## Authority / key decisions

- Boundary: `docs/decisions/TC1-TC3-implementation-authorization.md` §2, §4, §6. Media: CP8.9, CP5, CP7, CP8.3; CP8.33 (favorites, `output/_compilations/<pid>/`); TC1 / TC-WEB1 contracts.
- **G1 — ACCEPTED 2026-10-18:** khoảng 240–420 s (HUMAN LEAD “duyệt 240–420”). Lý do: audit read-only 3 bộ kinh — 31 khai thị yêu thích đều 242–297 s, 0 clip ≥ 300 s.
- **G2 — ACCEPTED 2026-10-18 (HUMAN LEAD: “Tải lại file nguồn nếu cần”): phương án A**; TC3 tải lại nguồn theo CP8.32 (`render/full.fetch_original`) khi render. Bối cảnh: Audit 240–420: vẫn 0 eligible vì `work/<ep>.kt/source.mp4` đã bị xoá (27/40 workspace khai thị không còn source lẫn HD). TC2 chỉ cần văn bản; TC3 mới cần video.
  - A (đề xuất): eligible cho index/plan nếu `manifest.source.sha256` = `transcript.media_sha256`, `render_manifest.source_sha256` khớp source gốc hoặc `enhance.json source_hd_sha256` đã ghi, mọi artifact văn bản còn và khớp; file còn thì vẫn hash như cũ. Record ghi `source_status: present | missing`; trang hiển thị; TC3 phải khôi phục (CP8.32) và kiểm hash / timing, không khớp thì fail closed.
  - B: giữ nguyên — clip mất nguồn không eligible (hiện 0 clip dùng được).
- **G3 — PENDING: HTTP API / UI.** HUMAN LEAD 2026-10-18: không muốn trang riêng cho TC2 → đề xuất đặt mục “Ghép theo chủ đề (AI)” trong trang Yêu thích hiện có; routes dưới đây chờ duyệt, implement ở phase C (authorization §4 tách riêng). Đề xuất, sau auth middleware hiện có, JSON, không media, không route ghi file ngoài `output/_compilations/<pid>/`:
  - `GET /playlists/{pid}/theme-plan` — trang.
  - `GET /api/playlists/{pid}/theme-plan` — trạng thái job, tóm tắt index (đếm theo status, `source_status`), proposals, plans kèm kết quả kiểm stale.
  - `POST /api/playlists/{pid}/theme-plan/generate` — xếp job làn `ai`: `build_index(write=True)` rồi đề xuất; 202, job đang có thì 200.
  - `POST /api/playlists/{pid}/theme-plans` `{proposal_id}` — tạo plan nháp từ đề xuất.
  - `PUT /api/playlists/{pid}/theme-plans/{plan_id}` `{revision, title, clips:[{episode_id, clip}]}` — revision mới, xoá duyệt; revision lệch 409.
  - `POST /api/playlists/{pid}/theme-plans/{plan_id}/approve` `{revision}` — duyệt; stale / invalid / lệch revision 409.
  - `DELETE /api/playlists/{pid}/theme-plans/{plan_id}`.
  - Lỗi 404 / 422 theo kiểu TC-WEB1; redaction đường dẫn tuyệt đối dùng lại `web/theme_index.py`.
- **G4 — ACCEPTED 2026-10-18: phương án A (cảnh báo, cho duyệt với `duration_override`).** A (đề xuất): đề xuất AI chỉ là "đủ" khi 30–40 phút (thiếu thì ghi rõ thiếu bao nhiêu phút); HUMAN LEAD vẫn được duyệt plan ngoài 30–40 phút sau khi tick xác nhận cảnh báo (`duration_override: true` ghi trong plan). B: chặn cứng — chỉ duyệt khi 30–40 phút.
- Quyết định cục bộ S1 (ORCHESTRATOR):
  - Artifact: `output/_compilations/<pid>/theme_proposals.json` (lần đề xuất mới nhất) và `theme_plans/<plan_id>.json`, ghi atomic; `schema_version: 1`. Không đụng `<cid>.json` / `favorites.json` của CP8.33.
  - Plan chứa: `plan_id`, `revision`, `title`, `theme` (label + rationale), `clips` theo thứ tự (identity, episode/clip label, duration, `input_fingerprint`, `render_sha256`, `source_reference` tương đối, `source_status`, evidence id/synopsis), `total_duration`, `proposal` gốc + provenance (model/prompt), `created_at` / `updated_at`, `approval: null | {revision, plan_fingerprint, approved_at, duration_override}`.
  - Stale: mỗi lần đọc, TC1 re-audit (cache, `RefusingClient`, không ghi); một clip không còn `indexed` hoặc `input_fingerprint` / `render_sha256` đổi → plan `stale`, approval bị coi là vô hiệu (giữ dữ liệu cũ để xem, không cho TC3 dùng). Sửa plan → revision + 1, approval = null.
  - AI chỉ chọn trong record `indexed`: output schema strict (nhãn chủ đề ≤ 120 ký tự, không ngoặc kép / xuống dòng như TC1; rationale ngắn mô tả, không trích dẫn; `clip_ids` phải là id thật, không trùng); vi phạm → loại đề xuất đó, ghi lý do. Thời lượng và cắt về ≤ 40 phút làm bằng code, không tin AI. Một clip có thể xuất hiện ở nhiều đề xuất khác nhau, không trùng trong cùng plan.
  - Job: key `theme:<pid>`, chạy làn `ai` qua `lane_steps()`; Ollama không trả lời thì dùng cơ chế chờ GPU hiện có; không `rebuild` sau restart (bị bỏ qua có log). Kind string định nghĩa trong module mới, không sửa `jobs.py`.

## Phases (outcome-driven, HUMAN LEAD 2026-10-18)

- **A (authorized, đang làm):** TC1 A1 + G2; module `src/auto_short/theme_plan/` (propose / plan store / edit / approve / stale) + tests. Không chạm web.
- **B (authorized):** TC3 renderer — contract riêng `docs/tasks/TC3-landscape-renderer.md` sau khi A READY.
- **C (chờ G3):** web — job làn `ai`, routes, mục UI trong trang Yêu thích.

Owned paths phase A: `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_plan/`, `tests/test_theme_index.py`, `tests/test_web_theme_index.py` (chỉ biên thời lượng), `tests/test_theme_plan*.py`, contract này.

## Implementation approach

1. A1 + G2 trong TC1 (đổi tối thiểu; giữ nguyên chính sách fail-closed khác).
2. `theme_plan`: prompt / schema / validate đề xuất; ghép thời lượng; store proposals / plans; stale check; approve. Inject `ChatClient` giả trong tests.
3. Web: job target, routes G3, trang (textContent, không innerHTML từ dữ liệu), link từ trang Yêu thích.
4. IMPLEMENTER chạy verification, trả READY report; ORCHESTRATOR review contract → diff (kể cả untracked) → AC → tự chạy lại verification; fix trả cùng writer.

## Acceptance Criteria

1. TC1 eligible với 240 ≤ duration ≤ 420 (tests 239/240/420/421 ở cả TC1 và TC-WEB1); các lý do ineligible khác không đổi. G2 theo phương án được duyệt, có tests present / missing / hash chain lệch.
2. Đề xuất chỉ chứa record `indexed` của đúng playlist; không trùng clip trong một đề xuất / plan; không lặp; tổng ≤ 40 phút; < 30 phút báo thiếu kèm số phút; output AI malformed / id bịa / trường lạ / trích dẫn bị loại, không làm hỏng các đề xuất khác. Tests dùng fake client, không gọi AI thật.
3. Plan lưu đủ trường ở §Authority; sửa → revision mới + mất duyệt; duyệt sai revision / plan stale / invalid → 409; duyệt ghi `plan_fingerprint`.
4. Stale: đổi render, cut, transcript, favorite (bỏ ♥), rejection hoặc index → plan báo stale và approval vô hiệu; có tests cho từng loại.
5. Job: generate xếp đúng làn `ai`, trùng job trả job cũ; Ollama down không fail job; lỗi AI per-record vẫn giữ trong index; GET không sinh AI / không ghi.
6. Routes theo G3: auth (page 303, API 401), pid sai 404, artifact hỏng 422, revision conflict 409, không lộ đường dẫn tuyệt đối; không route media / download.
7. CP8.33 (favorites, compilations, kept, xoá tập) và TC-WEB1 không đổi hành vi; full suite PASS.
8. Không dependency mới, không đổi framework / decision khác ngoài amendment A1 (và G2–G4 nếu duyệt).

## Required verification

- `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc2/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_index.py tests/test_web_theme_index.py tests/test_theme_plan*.py tests/test_web_theme_plan.py tests/test_web_compilation.py tests/test_web_auth.py -x --tb=short` — AC1–7.
- Cùng prefix `-m pytest -q -n auto` — full suite, AC7.
- `node scripts/framework-check.mjs`; `git diff --check`; inventory tracked + untracked ⊆ Owned paths — AC8.
- Read-only audit thật (ORCHESTRATOR, không AI, không ghi): đếm eligible 3 bộ kinh sau A1/G2.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task thêm public HTTP API (G3) → manual test là gate trước integration.

- [ ] Trên 8080 (ghim commit branch, HUMAN LEAD cho restart) hoặc preview riêng: bấm tạo index + đề xuất trên bộ kinh có nhiều khai thị yêu thích; Ollama thật.
- [ ] Đọc chủ đề / lý do / clip: đúng nghĩa không (semantic chỉ người kiểm được).
- [ ] Bỏ / thêm / sắp lại, duyệt; bỏ ♥ một clip → plan báo stale.
- [ ] Mobile: trang dùng được trên điện thoại.

## Result

- Phase A (2026-10-18, IMPLEMENTER subagent Sonnet): TC1 `MIN_DURATION, MAX_DURATION = 240, 420`; G2 — file nguồn / HD mất được chấp nhận khi chuỗi sha ghi trong manifest / transcript / render / enhance nhất quán, `source_status` present|missing (không vào `input_fingerprint`). Module mới `src/auto_short/theme_plan/__init__.py`: `propose`, `read_proposals`, `create_plan`, `update_plan`, `approve_plan`, `delete_plan`, `list_plans`, `check_plan`, `approved_plan`. Tests: `tests/test_theme_plan.py` (31), TC1 +G2 / biên 239–421; `tests/test_web_theme_index.py` biên + ca `mixlost` nay eligible theo G2.
- Tests (ORCHESTRATOR tự chạy lại): `-m pytest -q -n auto` → 2044 passed, 1 skipped, exit 0; framework-check PASS; `git diff --check` exit 0; inventory ⊆ Owned paths phase A.
- Review phase A: ACCEPTED, không blocking finding. Note: `check_plan` / `list_plans` / `update_plan` chạy lại TC1 audit (hash toàn file) mỗi lần — đúng nhưng tốn trên playlist lớn; `enhance._hd_usable` (private) được dùng từ TC1; nhãn "mất nguồn" của preview fixture TC-WEB1 nay không còn là ca ineligible.
- Audit thật read-only sau phase A (không AI, không ghi): `…BdXCp…` 5 eligible / 22,2 phút; `…A6C9…` 35 / 163,6 phút (4 `stale render: origin`); `…A3FS…` 2 / 10,9 phút; cả 42 `source_status: missing` → TC3 phải tải lại nguồn.
- PR: chưa (cần HUMAN LEAD cho phép).
