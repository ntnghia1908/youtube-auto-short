# Task: FIX-post-doc-gate — Gióng Short vào văn bản gốc khi phụ đề lỗi nặng + cảnh báo khi sao chép bài chữ AI

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — IMPLEMENTER mặc định (`gpt-6.1-sol`, effort high); quota 2026-10-24: 5 giờ 5 %, tuần 17 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-24 ("Đồng ý" đề xuất sửa code; thêm "những bài chữ AI nên có cảnh báo khi copy")
- Parallel group: —
- Owned paths: `src/auto_short/post/doc.py`, `src/auto_short/web/context.py` (chỉ field bài đăng), `src/auto_short/web/static/app.js` (tab Bài đăng), `src/auto_short/web/static/style.css` (nếu cần), `tests/test_post_doc.py`, `tests/test_web_post_*.py` (test mới có thể đặt `tests/test_web_post_doc_gate.py`); docs: file này, `docs/decisions/CP8.15-community-post-contract.md` (D4, P9 — ORCHESTRATOR sửa)
- Dependencies: none
- Base commit / branch: `fe82caf` (`main`) / `fix/post-doc-gate` (worktree `.claude/worktrees/fix-post-doc-gate`)
- Human Lead approval: APPROVED 2026-10-24
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi decision D4 đã accepted (`docs/decisions/CP8.15-community-post-contract.md` P15) và thêm hành vi UI (P9).

## Bối cảnh (đo 2026-10-24)

- HUMAN LEAD báo Thái Thượng Cảm Ứng Thiên T11 Short 3 có bài đăng "không giống nội dung". Nguyên nhân: phụ đề tự động quá lỗi → D4 `ratio` 0,52 < 0,6 → nhánh AI P3 chỉ chấm câu chữ ASR sai ("trứng thật là chính mình", "Em vú to là sự mở rộng…"), dù văn bản gốc có đúng đoạn.
- Quét `work/` (2166 bài): 1866 `doc`, 274 `ai` ở tập có văn bản gốc; 0 bài stale. 364 bài `doc` đã đăng đều đúng vị trí (lệch vị trí tương đối ≤ 5 %, bộ một video / trang). 6 bài `ai` đã đăng sai nặng (VLT tập 9 S9; CƯT T5 S8, T6 S9, T7 S1, T9 S7, T11 S3).
- Thử gate nới trên 264 bài `ai` chưa tick: ratio ≥ 0,40 + chuỗi khớp tốt nhất ≥ 20 token + ≥ 2× chuỗi thứ hai → 151 bài gióng được, đúng đoạn khi xem mẫu; trong số có cả hai Short neo `doc` hai bên, chỉ 2/78 nằm sai thứ tự (chủ yếu bản `.kt`). Ratio thấp chủ yếu do ASR sai và đoạn đọc tín chỉ cuối tập ("Vọng Tây cư sĩ, địa chỉ email…").
- Đã sửa dữ liệu một lần (ORCHESTRATOR, 2026-10-24 14:05 UTC, backup `~/.local/share/auto-short/backup-posts-2026-10-24T140515Z/`): 149 bài chưa tick → `doc`; T11 k03 chỉnh tay (`manual`). Task này sửa code để Short mới không lặp lại lỗi.

## Goal

1. Short có phụ đề lỗi nặng nhưng gióng rõ ràng vào văn bản gốc lấy bài từ văn bản gốc (`origin: doc`), không rơi sang chữ ASR.
2. Bài chữ AI (`ai` / `raw`) có nhãn cảnh báo và phải xác nhận trước khi "Sao chép bài".

## Scope

- In scope:
  - **D4 mới** (`post/doc.py` `align`): giữ nguyên luật cũ — `ratio ≥ 0.6` → dùng (không đổi kết quả của bài đang `doc`). Thêm: `0.40 ≤ ratio < 0.6` cũng dùng **khi** cụm khối dày nhất có tổng ≥ 20 token khớp **và** ≥ 2 × tổng của cụm thứ hai (không có cụm thứ hai = 0). Hằng số đặt tên (`MIN_RATIO`, `MIN_RATIO_LOW = 0.40`, `MIN_CHAIN = 20`, `CHAIN_DOMINANCE = 2`). Cách gom cụm (khối ≥ 4, `MAX_GAP`) và cách mở rộng vùng / câu (D5) giữ nguyên.
  - **Chú thích văn bản gốc** (`expand` / `compose`): bỏ đoạn (paragraph) bắt đầu bằng `[số]` (định nghĩa chú thích) và dấu tham chiếu `[số]` trong câu (xóa cả khoảng trắng thừa trước nó). Ngoặc vuông chứa chữ (vd `[bốn giai đoạn]`, lời người dịch) giữ nguyên.
  - **UI tab Bài đăng** (`app.js`): bài `origin` ∈ {`ai`, `raw`} có nhãn "Chữ AI từ phụ đề — đọc kỹ trước khi đăng" (nhãn `raw` hiện có giữ nguyên, không trùng hai nhãn cùng nghĩa). Nút "Sao chép bài" của bài đó: lần bấm đầu **không** copy, hiện cảnh báo tại chỗ "Bài này do AI chấm câu từ phụ đề tự động, có thể sai chữ. Đọc kỹ / sửa trước khi đăng." + nút "Vẫn sao chép" (lần bấm thứ hai là thao tác người dùng mới → copy + `markPostStep("copy")` như cũ) + nút "Hủy". Không dùng `confirm()` / `alert()` (copy fallback cần user gesture trên HTTP). Bài `doc` / `manual` copy như cũ, một lần bấm.
  - API `GET …/posts` thêm boolean `ai_text` (= origin ∈ {ai, raw}) nếu cần cho UI; schema `posts.json` không đổi.
- Out of scope: D3 (`MIN_MATCH`); soạn lại hàng loạt bài cũ (đã làm bằng script dữ liệu, xem Bối cảnh); xuất Word (P16); kiểm thứ tự theo Short lân cận; bài khai thị (`khaithi`) nếu dùng đường copy khác.

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P3, P9, P15 D4–D6; `docs/tasks/CP8.19-post-doc-source.md`; `docs/tasks/FIX-doc-match-050.md` (tiền lệ đổi ngưỡng).
- Bỏ phép kiểm thứ tự: chỉ loại thêm 2/264 ở dữ liệu thật; điều kiện "chuỗi trội ≥ 2×" đã chặn trường hợp đoạn lặp hai chỗ.

## Code bị thay / xóa

- `align`: điều kiện `if ratio < MIN_RATIO: return None` thay bằng gate hai mức ở trên. Không thêm module mới; tái dùng `SequenceMatcher` / cụm khối có sẵn.
- `copyTitleButton` dùng chung với tiêu đề — không đổi hành vi cho tiêu đề; cảnh báo chỉ ở nút "Sao chép bài".

## Acceptance Criteria

1. `align`: (a) ratio ≥ 0,6 → dùng như cũ; (b) ratio 0,40–0,6 + cụm ≥ 20 + trội ≥ 2× → dùng; (c) ratio 0,40–0,6 nhưng cụm < 20 hoặc cụm thứ hai > ½ cụm nhất → không dùng; (d) ratio < 0,40 → không dùng. Test biên cho từng điều kiện.
2. Chữ ASR lỗi nặng kiểu T11 k03 (fixture nhỏ dựng từ đoạn thật) → `compose` trả bài `doc` đúng đoạn; test hiện có của D4 / D5 / compose_posts PASS không sửa kỳ vọng.
3. Chú thích: đoạn `[1] …` bị bỏ, `…chân’[1]. Cội…` → `…chân’. Cội…`, `[bốn giai đoạn]` giữ nguyên.
4. UI: bài `ai` / `raw` có nhãn; bấm "Sao chép bài" lần một không gọi copy và hiện cảnh báo + "Vẫn sao chép"; bấm "Vẫn sao chép" → copy + đánh dấu bước copy; bài `doc` / `manual` copy ngay (test web / JS theo cách test hiện có của tab Bài đăng, hoặc test HTML/JS tĩnh nếu repo đang làm vậy).
5. Replay trên dữ liệu thật (ORCHESTRATOR, ngoài sandbox): gióng lại chữ nguồn của mọi bài trong `work/` có `doc.json` → không bài `doc` hiện có nào bị loại; ≥ 149 bài `ai` (theo `post_log` trước đợt sửa) gióng được.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest -q tests/test_post_doc.py` + test web bài đăng (ORCHESTRATOR chạy test web / full suite `-n auto` ngoài sandbox).
- `node --check src/auto_short/web/static/app.js`.
- `node scripts/framework-check.mjs`.
- Replay AC5 (script ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Trên 8080 (pin commit branch): mở tab Bài đăng một tập Địa Tạng có bài `ai` → thấy nhãn, bấm "Sao chép bài" → cảnh báo → "Vẫn sao chép" → dán được; bài "Văn bản gốc" copy một lần bấm.

## Result

- Main changes: `post/doc.py` `align` gate hai mức (`MIN_RATIO` 0,6 giữ nguyên; `MIN_RATIO_LOW` 0,40 + `MIN_CHAIN` 20 + `CHAIN_DOMINANCE` 2); `expand` bỏ paragraph chú thích `[số]` và dấu `[số]` trong câu ở đầu ra (chỉ số gióng không đổi), `compose` trả None nếu chỉ còn chú thích; `app.js` thêm `postHasAiText`, `copyPostButton` (nhãn + cảnh báo hai bước "Vẫn sao chép" / "Hủy"), `copyTitleButton` thêm tham số tùy chọn `beforeCopy` (tiêu đề không đổi hành vi). Không thêm field API. Decision CP8.15 D4 + P9 cập nhật.
- Tests: `tests/test_post_doc.py` (AC1 `test_align_two_level_gate_boundaries` 10 case, AC2 `test_noisy_t11_k03_style_source_composes_doc_without_ai`, AC3 `test_doc_footnotes_removed_only_from_output`); `tests/test_web_post_doc_gate.py` (AC4, chạy handler JS thật trong Node VM, 8 case: copy không xảy ra ở lần bấm đầu, không confirm/alert, copy trong user gesture). Full suite ngoài sandbox: 2470 passed, 1 skipped. `node --check app.js`, framework-check PASS.
- AC5 replay (ORCHESTRATOR, dữ liệu thật `work/`, chỉ đọc): 1866/1866 bài `doc` trước đợt sửa vẫn gióng được; 168/274 bài `ai` gióng được (4 tập có D3 `match` < 0,5 vẫn không dùng văn bản trong app).
- Review: ORCHESTRATOR 2026-10-24 — ACCEPTED, không có blocking finding. Codex 1 vòng, 103k tokens, không vòng sửa.
- Important findings / decisions: bỏ kiểm thứ tự theo Short lân cận (chỉ loại thêm 2/264 trên dữ liệu thật); dữ liệu đã sửa một lần trước code (xem Bối cảnh).
- Known limitations: ~106 bài `ai` vẫn không gióng được (chuỗi khớp ngắn / mơ hồ) — UI cảnh báo khi copy. Vùng gióng có thể lệch một hai câu ở đầu / cuối khi phụ đề rất lỗi (T11 k03 chỉnh tay).
- PR:
