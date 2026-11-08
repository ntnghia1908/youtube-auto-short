# Task: FIX-title-evidence-retry — Short / khai thị không còn "không có tiêu đề" vì bằng chứng lệch chữ

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — mặc định IMPLEMENTER (`.claude/rules/execution.md`), quota tuần 21 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-08 "Lỗi không tiêu đề sửa luôn"
- Parallel group: P1 (song song PCX1, path tách rời)
- Owned paths: `src/auto_short/titling/`, phần subcommand `titling` trong `src/auto_short/cli.py`, `tests/test_titling_*.py`, `tests/titling_helpers.py`, file này
- Dependencies: none
- Base commit / branch: `46469da` / `fix/title-evidence-retry`
- Human Lead approval: accepted (2026-11-08)
- Implementation authorized: YES

## Goal

Short không còn bị bỏ qua khi render (web hiện "(không có tiêu đề)") chỉ vì AI trích câu bằng chứng lệch nhẹ so với lời giảng; 4 Short hiện bị lỗi được đặt tiêu đề lại mà không đụng tiêu đề các Short khác.

## Bằng chứng (ORCHESTRATOR đo 2026-11-08)

4 Short `untitled` trên 880 workspace: `7axON1RpRjo` k01, `AiF-lVD29jM.kt` k01, `S0AbpjI3tXw.kt` k01, `jKGZC-ENyMo.kt` k06. Mọi option đều `evidence not in clip text`; 3 lần thử ra **y hệt nhau** (`temperature 0`, `seed 42` cố định, cùng messages). Ví dụ lệch:

- evidence "niệm phật không gián đoạn 24 giờ" / "niệm phật 24 giờ không gián đoạn" — lời gốc "24 giờ niệm phật không gián đoạn" (đảo thứ tự);
- evidence "… như Thị Nhất thiết **bộ** bắt do Tâm Tạo …" — lời gốc "… thiết **bị** bắt do …" (lệch 1 chữ);
- evidence "Vì sao bị nói xấu mà không cần cãi lại" — diễn ý, không có trong lời (phải vẫn bị loại).

## Scope

- In scope:
  1. Thử lại có khác biệt: lần thử ≥ 2 dùng `seed = cfg.seed + attempt − 1` và thêm vào messages câu trả lời trước + một lượt user ngắn liệt kê lý do loại từng option, nhắc "evidence phải chép nguyên văn liên tục từ lời giảng". Lần thử 1 giữ nguyên request hiện tại (byte-for-byte).
  2. Khớp bằng chứng gần đúng (trong `reject_reason` / `evidence_in_text`, dùng chung cho `validate_titles`): ngoài khớp nguyên văn như cũ, chấp nhận khi có một cửa sổ từ liên tiếp trong lời giảng dài `len(ev) ± 2` từ chứa **cùng tập từ** (đảo thứ tự) hoặc lệch tối đa 1 từ / 8 từ evidence (thay thế), với evidence ≥ `MIN_EVIDENCE_WORDS`. Câu diễn ý như ví dụ thứ ba vẫn bị loại.
  3. Đặt lại tiêu đề chỉ cho Short `untitled`: `auto-short titling <id> --untitled-only` — gọi AI cho đúng các entry `status = untitled`, ghi đè entry đó trong `titles.json` (giữ `clips_sha256`, `candidates_sha256`, header, model, params, thứ tự entry; cập nhật `stats`), thêm log vào `titling_log.json`; không đụng entry đã `titled`.
- Out of scope: đổi prompt v2, đổi model, UI web, Short thêm tay (`added.py` hưởng mục 1–2 tự nhiên qua `_title_clip`), tiêu đề tay.

## Phải giữ nguyên

- Lần thử đầu: request y hệt hiện tại; tiêu đề đã có không đổi, `titles.json` hiện có vẫn hợp lệ (luật mới là tập cha của luật cũ).
- `HASH_KEYS` / `PARAM_KEYS` / prompt sha không đổi → không episode nào bị coi là stale và đặt lại tiêu đề hàng loạt.
- `--force` giữ hành vi cũ.

## Code bị thay / xóa

- Không có (chỉ mở rộng `_title_clip`, `evidence_in_text`; thêm nhánh `--untitled-only`).

## Acceptance Criteria

1. Thử lại: lần 2, 3 có `seed` khác và có lượt phản hồi lý do loại; lần 1 không đổi (test so request).
2. Khớp gần đúng: chấp nhận đảo thứ tự và lệch 1 chữ như 2 ví dụ đầu; loại câu diễn ý ví dụ 3, evidence < 3 từ, và evidence chỉ trùng từ rải rác ngoài cửa sổ.
3. `--untitled-only`: chỉ entry untitled được gọi AI; entry titled giữ nguyên byte; `stats` đúng; `validate_titles` PASS; không có entry untitled → không gọi AI, báo rõ.
4. Chạy thật trên bản sao 4 workspace ở Bằng chứng (ORCHESTRATOR, ngoài sandbox, Ollama 3090): mỗi Short có tiêu đề hoặc ghi rõ lý do còn thiếu.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_titling_logic.py tests/test_titling_stage.py tests/test_titling_added_cp9.py tests/test_web_titles.py` — AC1–3.
- Full suite (ORCHESTRATOR, ngoài sandbox).
- AC4 chạy thật (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API. Sau merge: chạy `--untitled-only` trên 4 workspace thật, render lại, HUMAN LEAD xem 4 Short trên web.

- [ ] 4 Short có tiêu đề và hiện trên web.

## Result

- Main changes: retry giữ nguyên request đầu, từ lần 2 tăng seed và đưa response/lý do loại vào hội thoại; evidence dùng cửa sổ trượt 5 độ dài, bộ đếm cập nhật O(n + m); CLI `--untitled-only` tái dùng luồng titling, giữ entry titled/header/provenance/thứ tự, cộng dồn log và stats, đánh stale render sau cập nhật.
- Tests (IMPLEMENTER, sandbox, client giả; mọi lệnh từ `/home/ntnghia/projects/yas-title-fix`):
  - `PYTHONPATH=/home/ntnghia/projects/yas-title-fix/src conda run -n auto-short python -m pytest -q tests/test_titling_logic.py tests/test_titling_stage.py tests/test_titling_added_cp9.py -x --tb=short` → **131 passed in 1.91s** (vòng đầu).
  - `PYTHONPATH=/home/ntnghia/projects/yas-title-fix/src conda run -n auto-short python -m pytest -q tests/test_titling_logic.py tests/test_titling_stage.py tests/test_titling_added_cp9.py tests/test_series_cp811.py -x --tb=short` → **160 passed in 2.08s** (sau bổ sung kiểm tra byte entry và Short thêm tay).
  - `PYTHONPATH=/home/ntnghia/projects/yas-title-fix/src conda run -n auto-short python -m pytest -q tests/test_ollama_wait_client.py::test_titling_unavailable_stops_stage_without_untitled_clip tests/test_ollama_wait_client.py::test_added_short_title_unavailable_one_call_untitled -x --tb=short` → **2 passed in 0.21s** (không dùng fixture socket).
  - `git diff --check` → PASS; kiểm AST `HASH_KEYS` / `PARAM_KEYS` và so byte `prompt.py` với HEAD bằng Python → không đổi.

  | AC | Test / bằng chứng |
  |---|---|
  | 1 | `test_no_valid_option_retries_then_untitled`, `test_error_then_success`, `test_added_title_inherits_retry_feedback_and_fuzzy_evidence` |
  | 2 | `test_evidence_local_window_shared_by_option_and_artifact_validation` (parametrize), `test_evidence_windows_on_long_lecture` (6.000 từ + evidence 1.000 từ), test Short thêm tay ở AC1 |
  | 3 | `test_untitled_only_preserves_titles_metadata_and_appends_log`, `test_cli_untitled_only_and_no_untitled_noop`, `test_untitled_only_failure_keeps_existing_artifacts` (parametrize; gồm AI/ghi file/input/config lỗi) |
  | 4 | ORCHESTRATOR 2026-11-08, bản sao 4 workspace, Ollama 3090 qwen3:14b: cả 4 `titled` — 7axON1RpRjo k01 "Tâm tạo nghiệp thiện ác từ thân ngữ ý", AiF-lVD29jM.kt k01 "Người nghe danh hiệu Phật có công đức lớn không?", S0AbpjI3tXw.kt k01 "Kinh Hoa Nghiêm có phải là gốc của Phật pháp không?", jKGZC-ENyMo.kt k06 "Niệm Phật 24 giờ không gián đoạn có thật không?"; entry titled khác giữ nguyên; render dùng lại các Short không đổi (`render_key`) |

- Diff + / − (app, test): app **+118 / −10**; test **+178 / −2** (không tính tài liệu).
- Helper mới: `_retitle_untitled` điều phối kiểm freshness, chuẩn bị kết quả trước khi ghi và phục hồi artifact/manifest nếu ghi lỗi. Đã tìm bằng `rg -n 'Counter\(|sliding|evidence_in_text|SequenceMatcher|levenshtein|untitled.only|ai_calls.*extend' src tests/titling_helpers.py` và đọc stage/workspace: không có helper repair một phần; `run_stage` đơn lẻ xóa artifact khi lỗi nên không dùng trực tiếp cho toàn bộ quá trình repair. Tái dùng `title_clips`, `_title_clip`, `validate_titles`, `check_up_to_date`, `run_stage`, `atomic_write_json`; không thêm helper fuzzy riêng, không dùng `SequenceMatcher` vốn không có cùng luật và có nguy cơ O(n²).
- Review: IMPLEMENTER tự rà contract → diff → AC → verification; chờ ORCHESTRATOR review độc lập. Chỉ sửa Owned paths, không commit/push/PR/agent/mạng thật.
- Important findings / decisions: HEAD thực thi `41a6474` theo delegation. Repair yêu cầu input/config còn current; từ chối kết hợp `--untitled-only` với `--force` hoặc header override để giữ provenance. `--force` riêng giữ hành vi cũ. Không có entry untitled → không gọi AI/ghi artifact, thông báo rõ. HASH_KEYS/PARAM_KEYS/prompt SHA không đổi.
- Known limitations: không chạy `tests/test_web_titles.py` (TestClient/socket), full suite `python -m pytest -q -n auto`, hoặc AC4/Ollama thật theo ràng buộc sandbox/delegation; chưa xác nhận 4 Short thật hết untitled. Khớp gần đúng kiểm từ trong cửa sổ theo contract, không chứng minh ý nghĩa title.
- ORCHESTRATOR verification: `tests/test_web_titles.py` nằm trong full suite; full suite ngoài sandbox **4244 passed, 2 skipped** (26 phút 56 giây), test chập chờn đã biết `test_lower_thread_priority_is_per_thread_and_inherited_by_children` chạy riêng **1 passed**. Codex IMPLEMENTER 1 vòng, 91.191 token.
- PR: xem nhánh `fix/title-evidence-retry`.
