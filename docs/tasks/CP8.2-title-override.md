# Task: CP8.2 — Manual Title + Single-Short Rerender

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `d343465` (`feature/cp8.1-dissolve` READY, stacked, cùng sửa `render/stage.py`) / `feature/cp8.2-title-override`; rebase lên `main` sau khi CP8/CP8.1 merge
- Human Lead approval: accepted (APPROVE TASK, 2026-09-27; T1–T6; P1 `review.json`; P2 luật hình thức + fit)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) tạo artifact người sửa `review.json` (CP1 §8, trước đây thuộc CP9) — CP9 sẽ mở rộng; (b) đổi rule nguồn title của render (CP7 R2/P1, CP6 G5) và cách dọn/ghi output (CP7 R8) để tái dùng Short không đổi; (c) thêm lệnh CLI. Re-plan HUMAN LEAD 2026-09-27: sửa title tay kéo từ CP9 lên (`AUTO_SHORT_CHECKPOINT_PLAN.md` CP8.2). Không thêm dependency.

## Goal

Người dùng đặt title tay (gõ mới hoặc chọn từ `alternatives` AI) cho một Short; chạy render lại thì **chỉ Short đó** được encode lại, các Short khác giữ nguyên file (byte-identical). Không gọi lại AI. Web (CP8.3) dùng đúng các hàm này.

## Scope

- In scope:
  - Artifact `work/<id>/review.json` (schema v1, T1) + module `src/auto_short/review/` (đọc/ghi/validate override, T2–T3).
  - Render: áp override (T4), cache từng Short (T5), dọn output không xóa Short tái dùng (T5).
  - CLI `auto-short title …` (T6).
  - Tests: validate title tay, override theo `(clip_id, candidate_id)`, mismatch sau selection chạy lại, clip `untitled` có title tay được render, cache (chỉ Short đổi được encode; `--force` encode hết; đổi config encode hết), tích hợp lavfi.
  - Chạy thật `rbjfCfFq3Dk`: sửa title một Short → render → đo; reset → về title AI.
  - Docs: decision record mới `docs/decisions/CP8.2-title-override-contract.md` (canonical owner `review.json` v1 + rule áp override); sửa CP7 record (R2, R8, schema: `title_origin`, `render_key`), pointer ở CP6 G5; project profile (module map `review/`), README (usage `title`), contract Result.
- Out of scope:
  - Approve/reject clip, sửa header, sửa điểm cắt, batch (CP9); web (CP8.3); upload (CP8.4).
  - Sinh lại title bằng AI cho một clip.

## Authority / key decisions

- `docs/decisions/CP1-product-contract.md` §6 (title ≤ 60 ký tự, 3 dòng / thu nhỏ), §8 (review stage, `review.json`); `docs/decisions/CP6-titling-contract.md` G5 (luật title), G6 (`untitled`), `alternatives`; `docs/decisions/CP7-render-contract.md` R2, R5 (fit), R8, R9, R11 (+ CP8.1).
- Quyết định (DECIDE cùng APPROVE TASK):
  - **T1 `review.json` v1** (ghi atomic, không timestamp):
    `{"schema_version": 1, "episode_id": "…", "titles": [{"clip_id": "k03", "candidate_id": "c00123", "title": "…", "origin": "manual" | "alternative"}]}` — chỉ chứa clip có override, sắp theo thứ tự `clips.json`. Không có file = không override.
  - **T2 Validate title tay** (lỗi → từ chối, không ghi): NFC, bỏ khoảng trắng thừa, 1…`[titling] max_chars` (60) ký tự, một dòng, không emoji / không viết hoa toàn bộ (tái dùng luật hình thức G5 phù hợp — **không** áp luật evidence vì người viết), mọi ký tự có glyph trong font, và fit được theo R5 (≤ 3 dòng, không dưới `min_font_scale`). Chọn `alternative N` → chép nguyên title AI đó.
  - **T3 Khóa override:** `(clip_id, candidate_id)`. Khi render: override có `clip_id` không còn hoặc `candidate_id` khác (selection đã chạy lại) → bỏ qua + cảnh báo, không lỗi. Titling chạy lại không xóa override (title tay vẫn thắng).
  - **T4 Nguồn title khi render:** title = override (nếu hợp lệ theo T3) > `titles.json` `title` (auto-approve AI, CP7 P1). Clip `untitled` có override → được render. `render_manifest.shorts[].title_origin`: `ai | manual | alternative`. `review.json` (nếu có) vào `inputs` của render → sửa title làm render không còn up to date. Giữ `title_source = "titles"` (CP9 mới thêm duyệt/loại).
  - **T5 Cache từng Short:** mỗi Short có `render_key` = sha256 canonical của mọi thứ quyết định file: sha256 nguồn, `segments`, kế hoạch dissolve, layout, header/title (dòng hiển thị + cỡ chữ, **nội dung** chữ chứ không phải path file tạm), encode config, sha256 font, và phiên bản kế hoạch render (hằng số trong code, tăng khi đổi cách dựng filter graph). Khi render chạy: Short có `render_key` trùng entry cũ + file tồn tại + sha256 khớp → **tái dùng** (không encode, log `reuse`); còn lại encode. `--force` bỏ cache. Dọn output (R8): chỉ xóa file cũ không còn được tái dùng; lỗi giữa chừng chỉ xóa file mới ghi của lần chạy đó. `render_key` ghi trong `render_manifest.shorts[]` (additive, schema v1).
  - **T6 CLI:** `auto-short title <episode_id> <clip_id> (--set "TEXT" | --alternative N | --reset) [--render] [--config PATH]` — ghi `review.json`, in title hiển thị (dòng + cỡ chữ) để xem trước; `--render` chạy luôn `render`. `auto-short title <episode_id> --list` in mọi clip: title AI, alternatives (đánh số), override. Exit code CP2 D8.
- Đề xuất cần HUMAN LEAD chốt:
  - **P1 Tên artifact:** `review.json` (đề xuất; CP9 mở rộng thêm approve/reject). Khác: `title_overrides.json` riêng.
  - **P2 Luật title tay:** chỉ luật hình thức + fit (T2, đề xuất). Khác: không kiểm gì ngoài độ dài / fit.

## Implementation approach

- `review/`: `load_overrides`, `set_title`, `reset_title`, `validate_manual_title` (dùng `render.text` để kiểm fit) — hàm thuần, CLI và web gọi chung.
- `render/stage.py`: tính `render_key` trước khi encode; tách bước dọn output theo T5; không đổi `run_stage`.

## Acceptance Criteria

1. `auto-short title rbjfCfFq3Dk k03 --set "<title mới>" --render`: chỉ `k03` encode, 12 Short còn lại log `reuse` và sha256 không đổi; `render_manifest` k03 có title mới, `title_origin: manual`; thời gian render ≈ thời gian một Short.
2. `--alternative 1` → title = alternatives[0], `origin: alternative`; `--reset` → về title AI, k03 encode lại, các Short khác reuse.
3. Title không hợp lệ (quá 60 ký tự, rỗng, emoji, ký tự không có glyph, không fit) → exit 1, `review.json` không đổi.
4. Test: override lệch `candidate_id` → bỏ qua + cảnh báo; clip `untitled` có override → render; `--force` encode hết; đổi `crf` → encode hết.
5. Chạy `render` hai lần không đổi gì → lần hai skip stage (up to date); xóa một mp4 → lần sau chỉ encode lại file đó.
6. Mọi test hiện có PASS; framework-check PASS; docs cập nhật.

## Required verification

- `pytest -q` — AC3–AC6.
- Chạy thật trên `rbjfCfFq3Dk` (AC1, AC2) với đo thời gian + so sha256 trước/sau.
- `node scripts/framework-check.mjs` — AC6.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model. Thêm lệnh CLI (additive). Manual test là điểm danh.

- [ ] Xem Short có title tay: hiển thị đúng, ngắt dòng hợp lý.

## Result

- Main changes: module mới `src/auto_short/review/` (`logic.py` thuần: schema `review.json` v1 T1, luật title tay T2, khóa `(clip_id, candidate_id)` + thứ tự ưu tiên T3/T4; `titles.py`: `load_overrides`, `list_titles`, `preview_title`, `set_title`, `set_alternative`, `reset_title` → `TitlePreview` / `ReviewError`, dùng chung CLI + web); `titling/logic.py` tách `form_reject_reason` (luật G5 1–8, hành vi CP6 không đổi); `render/plan.py` `RENDER_PLAN_VERSION = 1`; `render/stage.py` (`fit_clip_title` dùng chung, `review.json` vào `inputs`, `title_origin` + `render_key` mỗi Short, tái dùng khi key + file + sha256 khớp, encode ra `.part` rồi commit sau khi mọi clip xong, dọn chỉ file cũ không còn thuộc lần này, lỗi chỉ xóa file của lần chạy đó; `RenderResult.encoded/reused`; `run_stage` không đổi); `cli.py` lệnh `title` (T6). Docs: decision record mới `docs/decisions/CP8.2-title-override-contract.md` (PROPOSED; gồm chữ ký hàm cho web), sửa CP7 record (R2, R6, R8, R9, R10, R11 + ví dụ schema), pointer CP6 G5, project profile (authority + module map `review/` implemented partial), README (`title`).
- Tests: `pytest -q` 394 passed (41 mới: `tests/test_review.py` 34 — luật hình thức, schema, resolve/mismatch, thứ tự, set/alternative/reset/list/preview, title không hợp lệ giữ nguyên `review.json`, clip `untitled`, lỗi, CLI; `tests/test_render_reuse.py` 7 lavfi — chỉ Short đổi được encode + 1 reuse byte-identical, skip lần hai, xóa một mp4 chỉ encode nó, alternative/reset về byte-identical bản đầu, `--force`/đổi `crf`/tăng `RENDER_PLAN_VERSION` encode hết, file bị sửa không tái dùng, override lệch `candidate_id` bỏ qua + cảnh báo, `untitled` có override được render, reset `untitled` xóa mp4 cũ, lỗi ffmpeg giữ output cũ + lần sau vẫn tái dùng, `review.json` hỏng → `failed`, CLI `title --render`). Hai test cũ đổi theo T5 (`test_titling_not_done`, `test_ffmpeg_failure_cleans_everything` → `…_keeps_previous_render`: trước đây assert xóa hết output khi lỗi). `node scripts/framework-check.mjs` PASS.
  - Chạy thật `rbjfCfFq3Dk` (worktree, `config.toml` riêng): manifest CP8.1 chưa có `render_key` → `render --force` một lần: 13 encode 308.9 s, 13/13 mp4 byte-identical bản CP8.1.
  - AC1: `auto-short title rbjfCfFq3Dk k03 --set "Tâm thiện thì gương mặt cũng hiền hòa" --render` → 38.5 s wall (k03 encode 36.7 s; stage 38.1 s); 12 `reuse`, 12 sha256 không đổi, `k03` `d6e37d6a…` → `70c5a491…`; manifest `k03` `title_origin: manual`, `Tâm thiện thì / gương mặt / cũng hiền hòa` 88 px panel 353 px; `inputs` có `review.json`.
  - AC2: `--alternative 1` → "Tâm xấu khiến người khác sợ hãi", `alternative`, 1 encode + 12 reuse, 38.5 s. `--reset` → k03 encode lại (38.6 s), `review.json` `titles: []`, 13/13 mp4 byte-identical baseline, mọi `title_origin` `ai`.
  - AC3: 8 title không hợp lệ (61 ký tự, rỗng, khoảng trắng, emoji, `心`, HOA toàn bộ, từ dài không fit, xuống dòng) + `--alternative 9` + clip `k99` → exit 1, thông báo lý do, `review.json` byte không đổi, render sau đó skip.
  - AC5: `render` lần hai → `skip (up to date)`; xóa `k07.mp4` → `run (artifact missing)`, chỉ `k07` encode (28.9 s), byte-identical bản trước.
- Review: ACCEPTED (ORCHESTRATOR, diff-first). Không có blocking finding. Chấp nhận các quyết định khi implement (ghi ở decision record): lỗi/ngắt giữa chừng giữ nguyên bản render trước (file mới ở `.part`, chỉ commit khi mọi clip xong) — đúng T5; hai test CP7 đổi theo rule mới của contract, không phải che lỗi; `render_key` gồm cả render config hash. Non-blocking: `review.json` chưa có khóa ghi đồng thời CLI/web (ghi atomic, lần sau thắng) — web CP8.3 chạy job tuần tự; nâng ffmpeg cần `--force` hoặc tăng `RENDER_PLAN_VERSION`.
- Important findings / decisions: (1) Manifest trước CP8.2 không có `render_key` → lần render đầu sau nâng cấp encode hết (không tái dùng mù quáng); trên `rbjfCfFq3Dk` đã chạy `--force` một lần. (2) `render_key` gồm cả `render_config_hash` (bảo thủ: mọi key `[render]` trong hash đều encode lại). (3) Short encode giữ ở `.part` tới khi mọi clip xong → lỗi giữa chừng để nguyên output thành công trước (khớp manifest cũ), lần sau vẫn tái dùng; lỗi kiểm input trước khi chạy cũng không xóa output cũ nữa (CP7 R8 cũ xóa hết) — một luật "chỉ xóa file của lần chạy đó". (4) Luật hình thức T2 chỉ kiểm lúc ghi; render kiểm schema `review.json` + glyph/fit. (5) `review.json` không phải stage (stage `review` trong manifest vẫn `pending`).
- Known limitations: chưa có khóa ghi đồng thời CLI + web (ghi atomic, lần sau thắng); đổi phiên bản ffmpeg/x264 không vào `render_key` (dùng `--force` hoặc tăng `RENDER_PLAN_VERSION`); ngắt dòng cân R5 có thể cho 3 dòng ngắn với title tay như title AI.
- PR:
