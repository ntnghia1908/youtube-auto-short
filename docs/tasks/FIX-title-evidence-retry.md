# Task: FIX-title-evidence-retry — Short / khai thị không còn "không có tiêu đề" vì bằng chứng lệch chữ

## Status / Approval

- Status: APPROVED
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

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
