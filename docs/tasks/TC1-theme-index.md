# Task: TC1 — Thematic Clip Indexer

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Human Lead: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: codex — main session, independent review
- Implementer: codex — one native worker, inherited model
- Authorization mode: boundary
- Authorization source: HUMAN LEAD Implementation Authorization Boundary TC1–TC3, 2026-10-18, explicit session instruction; TC1 boundary reproduced below. HUMAN LEAD subsequently confirmed “chốt chuyển sang codex + native Codex”.
- Parallel group: —
- Owned paths: `src/auto_short/theme_index/`; `tests/test_theme_index*.py`; `docs/tasks/TC1-theme-index.md`
- Dependencies: existing render/review/compilation/Ollama artifacts; no new dependency
- Base commit / branch: `bec36c02c7b38e92e2646a50f16349d6405d94b9` / `feature/tc1-theme-index`
- Human Lead approval: inherited from boundary
- Implementation authorized: YES

Lifecycle boundary: `DRAFT → IN_PROGRESS → READY`. Local commit permitted after checks. Push, PR and merge require a separate integration decision; stop at READY.

## Goal

Tạo index chủ đề có provenance và cache kiểm chứng được cho các khai thị yêu thích dài 300–420 giây của đúng một bộ kinh được chọn, chỉ dựa trên nội dung clip cuối cùng.

## Scope

- In scope: module Python độc lập, callable với playlist được chọn và config hiện có; đọc favorites/artifacts, báo eligibility từng favorite, AI metadata structured qua Ollama client hiện có, lưu artifact index riêng theo playlist và invalidation; deterministic fake-client tests.
- Out of scope: TC2/TC3, UI/HTTP API mới, pipeline stage mới, tạo/cắt/render video, xử lý thêm video nguồn, publish, vector DB, dependency, framework, accepted decisions, refactor ngoài module.
- Chỉ episode có `khaithi.json`, thuộc playlist được chọn và `favorites.json` của playlist đó; loại Short thường, rejected, chưa render, duration ngoài [300,420]. `watched.json` không phải approval. Không mở rộng sang nhiều bộ kinh trong một index.
- Favorite chỉ còn `kept` không tái dựng được nguồn/cắt ngang phải có record ineligible cùng reason; không âm thầm bỏ qua hoặc upscale 9:16.

## Authority / key decisions

- HUMAN LEAD boundary trên; `AGENTS.md`, project profile §2/§7 và workflow v4.4. Không sửa authority hiện có.
- Main GitHub đã xác minh bằng `git ls-remote origin refs/heads/main`, fetch cùng SHA base trên. Worktree `/tmp/youtube-auto-short-tc1`; các worktree khác giữ nguyên.
- Audit: `web/compilations.py` có thể trộn Short và khai thị, dùng kept snapshot thay live file; TC1 không tái dùng phép lọc rộng đó. `compilation/store.py` và `spec.py` giữ favorites/identity; snapshot kept không có transcript hay source ranges.
- `render/stage.py:render_targets()` là implementation owner tái dựng source_start/end và kept segments: AI dùng candidate trims; manual cut/added dùng `review/cuts.py:kept_segments_ms()` từ silences và max_pause. Đối chiếu reconstructed target với rendered manifest; stale render không được index như current. Không dùng toàn transcript tập hoặc một interval bao ngoài các khoảng đã bỏ.
- Source phải tồn tại và truy vết được; kiểm tra identity/content để không dùng stale source. Transcript có câu băng qua biên giữ/bỏ mà không có word timing không được đưa nguyên câu chứa phần đã bỏ: thể hiện thiếu/không chắc chắn, fail closed khi không đủ bằng chứng.
- Không tuyên bố semantic hallucination có thể được chứng minh chỉ bằng schema: dùng evidence transcript chính xác, không cho AI tạo quote/speech mới, explicit uncertainty và giới hạn review người.

## Implementation approach

1. Native worker bootstrap, xác minh HEAD/branch, đọc artifact validators/source và tests liên quan; chỉ ghi owned paths, không commit/push/PR hoặc delegate tiếp.
2. Tách eligibility/reconstruction và transcript evidence khỏi prompt/output validation/cache. Dùng artifact/path/hash helpers và Ollama ChatClient hiện có; không sửa module dùng chung.
3. Index riêng per playlist: mỗi favorite có identity/status/reason; indexed record gồm topic/subtopic, synopsis, key messages, provenance, source reference, final edited segment ranges, input fingerprint. Missing/uncertain và AI failure có trạng thái rõ.
4. Fingerprint bao gồm nội dung render/source, review/manual cut, final ranges/transcript, prompt/schema và model/options; cache chỉ reuse khi inputs hiện hành và output được validate. Removed/rejected/unhearted không giữ stale indexed record như usable.
5. Worker chạy checks và bàn giao; ORCHESTRATOR review diff + AC độc lập, chạy lại verification; fix trả cùng writer.

## Acceptance Criteria

1. Chỉ hearted khai thị có marker hợp lệ, thuộc đúng playlist, rendered không reject và duration [300,420] đủ nguồn mới eligible; invalid favorite và kept không tái dựng có reason, không bị bỏ qua.
2. Source reference/ranges khớp clip cuối cùng sau manual cut/silence removal; prompt không chứa phần transcript bị bỏ hoặc toàn tập; stale manifest/source bị chặn.
3. Mỗi indexed record chứa đủ identity/topic/subtopic/synopsis/key messages/provenance/source reference/final ranges/fingerprint, timestamp và model/prompt reference. Dữ liệu thiếu/không chắc chắn rõ ràng.
4. Validate strict structured output với fake Ollama; evidence phải thật trong transcript và đúng evidence ID; không chấp nhận quote bịa, trường lạ hoặc output malformed. Không gọi AI thật trong tests.
5. Cache invalidation có tests khi render, cut, source, transcript, prompt hoặc model đổi; favorites/rejection thay đổi không phục hồi stale approval. Cache hỏng không được tin vô điều kiện.
6. Module độc lập dùng client hiện có, không dependency/vector DB, không video processing/publish, không đổi framework/decision/public HTTP API; một writer.
7. Required verification PASS, review độc lập ACCEPTED và ghi evidence thực tế trước READY.

## Required verification

- `python -m pytest -q tests/test_theme_index*.py -x --tb=short` (shell glob expanded) và tests compilation/render/review liên quan trong vòng sửa — AC1–6.
- `python -m pytest -q -n auto` — full suite trước READY và sau vòng fix review.
- `node scripts/framework-check.mjs` — contract/framework compatibility.
- `git diff --check`; tracked + untracked inventory và owned path review — scope, whitespace.
- Dùng `/home/ntnghia/miniconda3/envs/auto-short/bin/python` để chạy đúng môi trường. Không claim PASS nếu chưa chạy thành công. ORCHESTRATOR tự chạy lại checks theo adapter native.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public HTTP API contract; manual review sau automated verification là điểm danh.

- [ ] Kiểm tra metadata và evidence một clip; AI semantic correctness vẫn cần HUMAN LEAD review.
- [x] Nếu có dữ liệu thật: audit read-only eligible/ineligible, không gọi AI thật hoặc ghi production artifacts.
- [x] TC2 chỉ được đề xuất sau TC1; không triển khai trong task này.

## Result

- Main changes: `src/auto_short/theme_index/__init__.py` provides callable `audit_playlist(config, playlist_id)` (read-only, no AI) and `build_index(config, playlist_id, client=...)`. Stored playlist/favorites define the single-playlist input; index artifact is `output/_compilations/<playlist_id>/theme_index.json`. Reconstruct final ranges through render helpers, verify source/render/transcript linkage, retain every invalid favorite as ineligible, validate extractive metadata and fingerprint/cache inputs. `tests/test_theme_index.py`: 31 deterministic fake-Ollama cases.
- Tests (IMPLEMENTER, 2026-10-18): with `PYTHONPATH=/tmp/youtube-auto-short-tc1/src` and conda Python, TC1 targeted: **31 passed**; related compilation/render CP9/review selection: **147 passed**; required full `python -m pytest -q -n auto`: **1963 passed, 1 skipped**, 1121 existing deprecation warnings, 93.13 s, exit 0. `node scripts/framework-check.mjs` and `git diff --check`: PASS. Initial targeted invocation without worktree PYTHONPATH failed collection because editable install points at the main checkout; corrected command passed. No real AI services called.
- Tests (ORCHESTRATOR independent, 2026-10-18): `env PYTHONPATH=/tmp/youtube-auto-short-tc1/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_index.py -x --tb=short` → **31 passed in 1.16 s**, exit 0. Cùng prefix với `-m pytest -q -n auto` → **1963 passed, 1 skipped**, 1124 deprecation warnings, 91.05 s, exit 0. `node scripts/framework-check.mjs` → PASS, exit 0. Main cũng gặp collection error ở lần targeted thiếu PYTHONPATH; đã sửa môi trường, không sửa tests để che lỗi.
- Review: **ACCEPTED; READY**. ORCHESTRATOR đọc contract → toàn bộ code/test untracked → AC → evidence; review yêu cầu bổ sung transcript digest/linkage, controlled uncertainty và edge tests, cùng writer đã xử lý trước final suite. Không còn blocking findings. Scope inventory chỉ ba owned files; main checkout sạch, base không đổi trong implementation. `git diff --check` PASS; staged diff whitespace được kiểm trước local commit. Required slow suite không áp dụng vì không sửa render/worker source.
- Native execution evidence: `collaboration.spawn_agent(task_name="tc1_implementer")` → `/root/tc1_implementer`, inherited model, không override; native worker viết implementation/tests, chạy verification, trả FINAL_ANSWER riêng; main review và retest độc lập. Runtime không expose exact model ID; không suy đoán model. Sau khi worker hoàn tất, main chỉ cập nhật lifecycle/evidence docs và thực hiện local integration housekeeping.
- Important findings / decisions: profile switched by HUMAN LEAD before implementation; earlier Claude audit stopped with clean worktree, no implementation edits.
- Known limitations: callable-only, no CLI/UI. Synopsis and key messages are exact extractive evidence references; topic/subtopic semantic accuracy needs HUMAN LEAD review. Transcript segments crossing final kept boundaries are conservatively omitted, including when word timings exist (TC1 consumes caption spans only), with explicit uncertainty. Missing original source fails closed even if a portrait/HD artifact survives. Source/render files are hashed in full on audit (no stat-only trust). Cache is a derived local artifact, not an approval authority.
- Read-only real audit (ORCHESTRATOR, no writes/AI): selected playlist `PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_`, **0 eligible / 2 ineligible**. `yZai50V4p44.kt/k02`: original source missing; base and khai thị episodes archived, no source fallback. `k03`: duration outside 300–420 s. No production index generated.
- Proposed TC2: consume validated TC1 records for thematic browsing/selection, retaining eligibility reasons, evidence and HUMAN LEAD semantic review; requires its own contract in the approved boundary, not implemented here.
- PR: https://github.com/ntnghia1908/youtube-auto-short/pull/96 — MERGED 2026-10-18, merge `a77f04a32998f254c6d13d2b7b4911b56b4cf41d`. HUMAN LEAD “cho phep het” authorize integration TC1 prerequisite cùng TC-WEB1; module/AC không đổi. DONE suy ra từ Git; rollout evidence ở contract TC-WEB1.
