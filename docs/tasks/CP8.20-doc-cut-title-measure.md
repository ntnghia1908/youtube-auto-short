# Task: CP8.20 — Đo: văn bản gốc cho title và điểm cắt theo câu

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; viết script đo và chạy thí nghiệm, ORCHESTRATOR review số liệu, đọc mẫu và viết khuyến nghị.
- Base commit / branch: `59e5b6a` (`fix/post-doc-no-gpu`), rebase lên `main` `c2007c6` sau khi #48 + #50 merge / `feature/cp8.20-doc-measure` (worktree `../youtube-auto-short-cp820`)
- Human Lead approval: APPROVED (HUMAN LEAD 2026-10-02, nguyên bản)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ thêm script đo trong `scripts/` và một báo cáo; không đổi source trong `src/`, config, contract, dependency hay hành vi production (như CP11). Mỗi thay đổi được chọn sau báo cáo là task S2 riêng (đổi CP4 / CP5 / CP6 và hash stage).

## Bối cảnh

CP8.19 (PR #48) gióng transcript với văn bản gốc trên `ph.tinhtong.vn` (`post/doc.py`). Khi soạn 148 bài từ văn bản (17 tập, 3 bộ kinh), **102 Short (69%) bắt đầu giữa câu** (trung vị thiếu 8 token đầu câu) và 42 Short kết thúc giữa câu. Văn bản là bản đã biên tập nên số này có thể cao hơn thực tế.

Hai hướng HUMAN LEAD muốn đo trước khi quyết (2026-10-02):

1. **Title**: title AI hiện viết từ caption sai chính tả; title in thẳng lên video.
2. **Điểm cắt theo câu**: Short bắt đầu / kết thúc đúng ranh giới câu.

Hiện trạng: điểm cắt chỉ nằm ở ranh giới `units` (CP4: khối lời tách bởi khoảng lặng / shot); candidate = dãy unit liên tiếp; AI selection (CP5) chọn candidate và tự đánh giá `start_complete` / `end_complete`; title AI (CP6) đọc `clip_text` từ caption.

## Goal

Một báo cáo có số liệu và mẫu để HUMAN LEAD chọn: (1) có nên cho title AI đọc văn bản gốc không; (2) có nên ưu tiên / bắt buộc điểm cắt ở ranh giới câu của văn bản không, và theo cách nào.

## Scope

- In scope:
  - Script `scripts/measure_doc_cut_title.py` (dùng `post/doc.py`, `titling`, `selection` có sẵn; chỉ đọc artifact, ghi kết quả ra thư mục output riêng).
  - Dữ liệu: bản sao `~/.cache/auto-short-cp820-test/` (không ghi vào `work/` / `output/` chính) của 3 tập: `Bi7kVGbnPfE` (Vô Lượng Thọ 1), `4oOZz2CBz3g` (Cảm Ứng Thiên 1), `yzR1eCK_iV0` (Thập Thiện 6), cùng tập `.kt` của chúng cho M1.
  - Báo cáo `docs/decisions/CP8.20-doc-cut-title-report.md` + bảng mẫu.
- Out of scope: sửa `src/`; render lại tập thật; đổi model / prompt production; bộ kinh không có văn bản.

## Thí nghiệm

- **M1. Hiện trạng ranh giới.** Gióng toàn bộ transcript với văn bản (token → vị trí văn bản). Với mỗi Short đang có (`clips.json` + Short thêm tay) và mỗi Short khai thị: điểm đầu / cuối có rơi đúng ranh giới câu của văn bản không; nếu không, thiếu / thừa bao nhiêu token và bao nhiêu giây. So với `start_complete` / `end_complete` AI đã tự chấm.
- **M2. Ranh giới unit vs câu.** Tỉ lệ ranh giới unit (CP4) trùng ranh giới câu; nếu chỉ giữ candidate có cả hai đầu ở ranh giới câu thì còn bao nhiêu candidate trong khoảng thời lượng mục tiêu (đủ để chọn hay không). Ranh giới câu trong văn bản rơi vào giữa unit bao nhiêu lần (cần tách unit theo timestamp chữ).
- **M3. Selection biết câu.** Chạy lại selection (Ollama, model / prompt production, chỉ trên bản sao) với 2 biến thể: (a) chỉ đưa candidate có hai đầu ở ranh giới câu; (b) giữ mọi candidate nhưng ghi nhãn "đầu/cuối trọn câu" trong text đưa AI. Đo: % Short trọn câu hai đầu, điểm `score` AI, số Short chọn được, thời gian. So với baseline.
- **M4. Title từ văn bản.** Với mọi Short của 3 tập: chạy lại title AI (model / prompt production) với text = đoạn văn bản gốc (D5 CP8.19) thay cho `clip_text`. Bảng so sánh title cũ / mới. ORCHESTRATOR đánh dấu lỗi chính tả / thuật ngữ trong cả hai cột.
- **M5. Mẫu nghe / xem.** Từ M3 biến thể tốt hơn: dựng (render) 4–6 Short mẫu vào thư mục bản sao, cùng bản baseline tương ứng, để HUMAN LEAD xem / nghe so sánh (gửi file như CP11).

Thí nghiệm Ollama chỉ chạy khi hàng đợi 8080 rỗng (như CP11).

## Acceptance Criteria

1. Script chạy được trên bản sao, không ghi vào `work/` / `output/` chính (kiểm `git status` + mtime).
2. Báo cáo có số liệu M1–M4 cho 3 tập, kèm cách tính.
3. Bảng title cũ / mới đủ mọi Short của 3 tập, có đánh dấu lỗi.
4. Có 4–6 cặp Short mẫu (baseline / mới) để HUMAN LEAD xem.
5. Báo cáo kết thúc bằng khuyến nghị (PROPOSED) cho title và điểm cắt, mỗi mục kèm cái giá: contract cần đổi (CP4 / CP5 / CP6), hash stage, tập cũ.
6. `python -m pytest -q -n auto` vẫn PASS (không đổi `src/`).

## Required verification

- Chạy script trên bản sao — AC 1–4 (ORCHESTRATOR kiểm số liệu, đọc mẫu).
- `python -m pytest -q -n auto` — AC 6.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API. HUMAN LEAD xem các cặp Short mẫu và bảng title, rồi chọn khuyến nghị.

- [ ] Xem / nghe cặp Short mẫu.
- [ ] Đọc bảng title.
- [ ] Chọn: title từ văn bản (có / không); điểm cắt theo câu (không / ưu tiên / bắt buộc).

## Result

- Main changes: `scripts/measure_doc_cut_title.py` (M1–M5, không đổi `src/`); báo cáo `docs/decisions/CP8.20-doc-cut-title-report.md` (số liệu M1–M4, bảng title 50 Short, mẫu M5, khuyến nghị nháp PROPOSED). Dữ liệu bản sao + kết quả thô + mẫu: `~/.cache/auto-short-cp820-test/` (`results/`, `samples/`).
- Tests: `python -m pytest -q -n auto` — 1324 passed, 1 skipped (84 s, sau rebase lên `c2007c6`); `node scripts/framework-check.mjs` — PASS (sau khi ORCHESTRATOR sửa Status báo cáo thành `PROPOSED`; bản IMPLEMENTER FAIL ở check này). Script chạy trên bản sao (m1m2, m3, m4, m5, tables).
- Review: ORCHESTRATOR round 1 ACCEPTED (2026-10-03): kiểm số liệu M1–M3 khớp kiểm chéo `doc.compose`; chốt cột lỗi title (cũ 1 lỗi chính tả từ caption; mới 0 chính tả, 5 viết hoa/thường, 3 evidence ngoài Short); viết lại §8 khuyến nghị PROPOSED.
- Important findings / decisions: AI chấm 100% Short trọn đầu/cuối nhưng 74% đầu và 61% cuối giữa câu (31 Short); caption YouTube: unit gần như không trùng ranh giới câu (7–13%), lọc bắt buộc → Thập Thiện 6 còn 0 candidate mục tiêu; Whisper (Cảm Ứng Thiên) ổn; nhãn câu (M3 b) tăng Short trọn câu (Bi7k 1/11 → 6/6, 4oOZ 6/9 → 10/12) nhưng không tạo ranh giới mới; title từ văn bản hợp lệ 50/50.
- Known limitations: mẫu nhỏ (3 tập, 1 tập Whisper); chạy lại selection có nhiễu (4oOZ base 9 ≠ 7 đã lưu); M3/M5 không chạy cho tập `.kt`; Ollama có `qwen3:14b` nạp sẵn lúc M5; file ở repo chính đổi trong lúc chạy là do web 8080 (không do script).
- PR: chưa (không push).
