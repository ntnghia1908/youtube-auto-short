# Task: CP8.18 — Từ điển sửa lỗi bài đăng học từ bản sửa tay

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; task có logic diff + route + UI, cần review diff riêng.
- Base commit / branch: `29506ae` (`origin/main`) / `feature/cp8.18-post-corrections` (worktree `../youtube-auto-short-cp818`)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-02: APPROVE CP8.18 — D1–D7 theo đề xuất; phạm vi chỉ bài đăng; mọi luật duyệt tay)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) sửa luật canonical của `docs/decisions/CP8.15-community-post-contract.md`: P2/P3 (bài không còn luôn đúng từng chữ transcript, mà đúng chữ transcript **sau từ điển đã duyệt**), P7 (`PUT` ghi thêm đề xuất), P9 (route mới), P11 (config mới); (b) thêm public API web; (c) thêm file dữ liệu người dùng dùng chung mọi tập. Không thêm dependency, không đổi schema `posts.json`, không đổi stage CP2–CP9 / `transcript.json` / title / render.

## Bối cảnh

HUMAN LEAD 2026-10-01: bài đăng còn nhiều lỗi chính tả, sai dấu câu; lời giảng có nhiều từ Hán Việt đặc thù kinh Phật. Thảo luận (ORCHESTRATOR ↔ HUMAN LEAD 2026-10-01) → chọn **hướng A**: user sửa bài, hệ thống rút ra luật sửa từ, user duyệt, luật áp cho mọi bài sau.

Chẩn đoán (dữ liệu `work/` 2026-10-01):

- Lỗi chính tả đến từ transcript: 26/36 tập caption tự động YouTube, 10/36 Whisper `large-v3-turbo`. AI bài đăng **không thể** sửa chữ: P3 chiếu kết quả về đúng chữ nguồn. Ví dụ `4oOZz2CBz3g` k01: "suốt thế gian pháp" (đúng: *xuất*), "hết thầy tất cả" (đúng: *hết thảy*).
- Lỗi dấu câu / viết hoa đến từ `qwen3:14b` — **ngoài scope task này** (giai đoạn sau: quy ước viết hoa, few-shot, thử model lớn hơn).
- Hiện có 141 bài, 1 bài `manual`: chưa có dữ liệu sửa tay để học sẵn.

## Goal

Khi user sửa chữ trong một bài và bấm "Lưu đoạn", hệ thống ghi lại các cặp sửa từ (có ngữ cảnh) thành **đề xuất**. User duyệt đề xuất trong "Từ điển sửa lỗi"; luật đã duyệt được áp tất định vào chữ nguồn của mọi bài soạn sau, và vào các bài chưa đăng đang có. Một con số cho biết user còn phải sửa bao nhiêu % từ mỗi bài, để thấy hệ thống có tốt lên không.

## Scope

- In scope:
  - Rút đề xuất từ `PUT …/posts/{clip}` có `paragraphs` (D2).
  - File từ điển + nhật ký sửa (D1, D6), config `[post] corrections_path`.
  - Áp luật đã duyệt khi soạn bài (D3) và khi duyệt luật (D4).
  - Route + hộp thoại "Từ điển sửa lỗi" trên tab Bài đăng (D5, D7).
  - Sửa đổi `docs/decisions/CP8.15-community-post-contract.md` (P14 mới + ghi chú sửa đổi ở P2, P3, P7, P9, P11), pointer trong `docs/decisions/CP8.3-web-contract.md` W7, `README.md` (config), `AUTO_SHORT_CHECKPOINT_PLAN.md`, `docs/ai/project-profile.md` (dòng module `post/`).
- Out of scope:
  - Sửa transcript, title, header, phụ đề, render (luật chỉ áp vào bài đăng).
  - Dấu câu / viết hoa / prompt / đổi model; luật cho chèn hoặc xóa từ (chỉ thay từ).
  - Tự duyệt luật; áp vào bài đã tick "Đã đăng bài" hoặc bài `manual`.
  - Rút đề xuất ngược từ bài `manual` có sẵn (1 bài).
  - Glossary cho Whisper; nới P3 cho AI sửa chữ.

## Quyết định (HUMAN LEAD 2026-10-02: APPROVE)

- **D1. Lưu ở đâu.** Một file JSON dùng chung mọi tập, ngoài repo, cạnh thư viện ảnh: `[post] corrections_path` mặc định `~/.local/share/auto-short/post-corrections.json`. Không vào `config_hash` (bài không phải artifact stage). Ghi atomic, dưới `post_lock` của server. File hỏng → API trả lỗi, không ghi đè; soạn bài vẫn chạy như không có từ điển (log cảnh báo).
  ```json
  {"schema_version": 1,
   "rules": [{"id": "r0001", "from": "hết thầy tất cả", "to": "hết thảy tất cả",
              "status": "proposed", "count": 2,
              "examples": [{"episode_id": "4oOZz2CBz3g", "clip_id": "k01", "at": "2026-10-01T08:00:00Z"}],
              "created_at": "…", "updated_at": "…"}]}
  ```
  `from` / `to` lưu dạng chuẩn hóa (`selection.logic.normalize_word` từng token: NFC, chữ thường, bỏ dấu câu hai đầu), cách nhau một dấu cách. `status` = `proposed` | `approved` | `rejected`. `examples` giữ tối đa 5 gần nhất.

- **D2. Rút đề xuất khi "Lưu đoạn".** So bản trước khi lưu (`paragraphs` cũ) với bản mới, theo token chuẩn hóa (`difflib.SequenceMatcher`, `autojunk=False`):
  - Chỉ xét khối `replace` có ≤ 3 token cũ và ≤ 3 token mới. `insert` / `delete` / khối lớn hơn (viết lại câu) bỏ qua. Chỉ đổi hoa/thường hoặc dấu câu → chuẩn hóa bằng nhau → không có đề xuất.
  - Thêm ngữ cảnh: 1 token liền trước và 1 token liền sau, nếu token đó nằm trong khối `equal`. `from` = ngữ cảnh trái + cũ + ngữ cảnh phải; `to` = ngữ cảnh trái + mới + ngữ cảnh phải. Lý do: "thầy" tự nó đúng, chỉ "hết thầy" sai.
  - Trùng cặp (`from`, `to`) có sẵn → `count + 1`, thêm example; trạng thái giữ nguyên (luật `rejected` không đề xuất lại, chỉ tăng đếm). Cặp mới → `proposed`.
  - Ghi đề xuất không được làm hỏng việc lưu bài: lỗi từ điển → bài vẫn lưu, log cảnh báo, response `proposed: null`.

- **D3. Áp luật khi soạn bài.** `compose_posts` áp mọi luật `approved` lên dãy token nguồn của Short **trước** khi gọi AI; AI và phép chiếu P3 làm việc trên chữ đã sửa; `raw` fallback cũng dùng chữ đã sửa.
  - So khớp theo token chuẩn hóa, cả cụm, trái sang phải, không chồng lấn; tại một vị trí ưu tiên luật `from` dài nhất.
  - Token thay vào nhận hoa/thường chữ đầu của token gốc ở cùng vị trí (thừa thì theo token gốc cuối).
  - Ranh giới dòng caption (chia khối P3) giữ theo vị trí token: token mới thuộc dòng của token gốc đầu tiên trong cụm.
  - `source_sha256` vẫn tính trên chữ nguồn **chưa** sửa → duyệt luật mới không làm bài thành `stale`.
  - `post_log.json` mỗi entry ghi thêm `corrections: [{rule_id, at_token}]`.

- **D4. Duyệt luật → áp vào bài có sẵn.** Khi một luật chuyển sang `approved` (duyệt, hoặc thêm tay), server áp nó tất định lên `paragraphs` của mọi bài có `origin` `ai` hoặc `raw`, **chưa** tick "Đã đăng bài", ở mọi tập trong workspace (không gọi AI). Dấu câu đầu của token đầu cụm và dấu câu cuối của token cuối cụm giữ nguyên; cụm vắt qua ngắt đoạn → không áp ở chỗ đó. Bài `manual` và bài đã đăng không đổi. `origin`, `posted_at`, `image`, `link` giữ nguyên; `updated_at` đổi khi có thay. Response trả số bài / số chỗ đã sửa.

- **D5. Route** (cookie CP8.3 W2; 422 lỗi dữ liệu; 404 id không có):
  - `GET /api/post-corrections` → `{rules: [...], stats: {saves, avg_changed_pct}, error}`.
  - `POST /api/post-corrections {from, to}` → thêm luật tay, `approved` ngay, áp D4 → 200 `{rule, applied: {posts, places}}`.
  - `PUT /api/post-corrections/{id} {status?, from?, to?}` → 200 `{rule, applied}` (`applied` chỉ khi vừa thành `approved`). Sửa `from` / `to` được ở mọi trạng thái.
  - `DELETE /api/post-corrections/{id}` → 200. Xóa / bỏ duyệt **không** hoàn tác các bài đã sửa.
  - Kiểm: `from`, `to` có 1–8 token sau chuẩn hóa; `from ≠ to`; hai luật `approved` không được trùng `from` (422).
  - `PUT /api/episodes/{id}/posts/{clip}` (có `paragraphs`) trả thêm `proposed: <số đề xuất mới hoặc tăng đếm>`.

- **D6. Số đo "% từ phải sửa".** Mỗi lần "Lưu đoạn" append một dòng vào `<corrections_path>` cùng thư mục, tên `post-edit-log.jsonl`: `{at, episode_id, clip_id, words, changed_words}` — `words` = số token bản cũ, `changed_words` = số token cũ không nằm trong khối `equal` (D2, chuẩn hóa: không tính dấu câu / hoa thường). `stats` trong `GET` = số lần lưu và trung bình `changed_words / words` của 20 lần lưu gần nhất.

- **D7. UI tab "Bài đăng".** Nút "Từ điển sửa lỗi (n đề xuất)" mở hộp thoại:
  - Phần "Đề xuất": mỗi dòng `from → to`, số lần, tập/Short ví dụ; nút "Duyệt", "Sửa" (sửa hai ô rồi duyệt), "Bỏ qua" (→ `rejected`).
  - Phần "Đã duyệt": "Bỏ duyệt" (→ `proposed`), "Xóa"; ô thêm luật tay.
  - Dòng số đo: "Trung bình bạn sửa x% từ mỗi bài (20 lần lưu gần nhất)".
  - Sau "Lưu đoạn": thông báo ngắn "Đã ghi n đề xuất sửa từ" khi `proposed > 0`. Sau khi duyệt: "Đã sửa k chỗ trong m bài chưa đăng" và tải lại danh sách bài.
  - Dùng được trên điện thoại.

## Implementation approach

- Module mới `src/auto_short/post/corrections.py`: đọc / ghi file từ điển, `extract(old_paragraphs, new_paragraphs)` (D2), `apply_tokens(tokens, rules)` (D3), `apply_paragraphs(paragraphs, rule)` (D4), nhật ký D6. Hàm thuần, test độc lập.
- `post/stage.py`: đọc luật `approved` một lần mỗi job, áp trước `compose_clip`; giữ `source_sha256` trên chữ chưa sửa.
- `web/app.py`: route D5; `PUT` bài gọi `extract` + ghi log dưới `post_lock`; D4 lặp các `posts.json` của workspace, mỗi file read-modify-write dưới `post_lock`.
- `web/static/`: hộp thoại D7.
- `config.py`: `PostConfig.corrections_path`.

## Acceptance Criteria

1. Lưu bài "… Pháp và suốt thế gian Pháp …" thành "… Pháp và xuất thế gian Pháp …" tạo đúng một đề xuất `from: "và suốt thế"`, `to: "và xuất thế"`, `status: proposed`, `count: 1`; cùng sửa đó ở bài khác → `count: 2`, không thêm luật.
2. Chỉ đổi dấu câu / hoa thường, xóa hoặc chèn từ, hoặc viết lại > 3 token → không tạo đề xuất; bài vẫn lưu `manual` như trước.
3. Luật `rejected` không bị đề xuất lại; lỗi đọc / ghi từ điển không làm `PUT` bài thất bại.
4. Soạn bài với luật `approved` → `paragraphs` chứa chữ đã sửa, hoa/thường chữ đầu theo chữ gốc; luật `proposed` / `rejected` không áp; `source_sha256` bằng giá trị khi không có luật (không `stale`).
5. Luật nhiều token khớp vắt qua hai dòng caption vẫn áp; chia khối P3 không đổi số khối.
6. Duyệt luật → mọi bài `ai` / `raw` chưa đăng ở mọi tập được sửa, giữ dấu câu hai đầu cụm; bài `manual` và bài đã tick "Đã đăng bài" không đổi; response đếm đúng.
7. Route D5: thêm / sửa / duyệt / bỏ qua / xóa đúng; 422 khi `from` rỗng, > 8 token, `from == to`, hoặc trùng `from` với luật `approved` khác; 404 id lạ; chưa đăng nhập → bị chặn như route khác.
8. `post-edit-log.jsonl` ghi một dòng mỗi lần lưu `paragraphs`; `stats.avg_changed_pct` đúng trên 20 dòng cuối.
9. Không có file từ điển → soạn bài, `PUT`, `GET` chạy bình thường (từ điển rỗng); file hỏng → `GET` trả `error`, không ghi đè.
10. Hành vi CP8.15–CP8.17 khác không đổi: toàn bộ suite PASS.

## Required verification

- `python -m pytest -q -n auto tests/test_post_corrections.py tests/test_web_post_corrections_cp818.py` — AC 1–9.
- `python -m pytest -q -n auto` — AC 10 (toàn bộ suite).
- `node scripts/framework-check.mjs` — tài liệu / pointer.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task chạm public API web (route mới) nhưng không chạm database, security model (dùng auth có sẵn) hay schema `posts.json`. Manual test là điểm danh sau automated verification, làm trên server test 8081 với bản sao dữ liệu (không phải `work/` chính).

- [ ] Sửa một chữ sai trong một bài, "Lưu đoạn" → thấy "Đã ghi 1 đề xuất sửa từ".
- [ ] Mở "Từ điển sửa lỗi" → thấy đề xuất, sửa ngữ cảnh, "Duyệt" → các bài chưa đăng khác có cùng lỗi được sửa.
- [ ] "Soạn lại" một bài có lỗi đó → chữ đã sửa; bài không bị `stale`.
- [ ] Bài đã tick "Đã đăng bài" không đổi.
- [ ] Số đo % hiện và thay đổi sau vài lần lưu.
- [ ] Hộp thoại dùng được trên điện thoại.

## Result

- Main changes: `post/corrections.py` mới (D1–D6: file từ điển, `extract`/`record`, `apply_tokens`/`apply_lines`/`apply_paragraphs`/`apply_rule_to_posts`, kiểm D5, nhật ký sửa + `stats`); `PostConfig.corrections_path`; `post/stage.py` áp luật `approved` trước AI, `source_sha256` trên chữ chưa sửa, `post_log.json` thêm `corrections`; `web/app.py` 4 route `/api/post-corrections` + `PUT` bài trả `proposed`; UI hộp thoại "Từ điển sửa lỗi" (tab Bài đăng). Tài liệu: CP8.15 P14 + ghi chú P2/P3/P7/P9/P11, CP8.3 W7, README, checkpoint plan, project profile.
- Tests: `tests/test_post_corrections.py`, `tests/test_web_post_corrections_cp818.py` (28 passed); toàn bộ `python -m pytest -q -n auto` 1255 passed, 1 skipped (ORCHESTRATOR chạy lại sau fix, `294ac08`); `node scripts/framework-check.mjs` PASS.
- Review: round 1 — B1 (blocking): áp luật làm mất dấu câu / hoa thường của token ngữ cảnh và chuyển token ngữ cảnh sang dòng caption khác → sửa `294ac08` (giữ nguyên tiền tố / hậu tố chung của `from`/`to`, chỉ thay phần giữa) + test. Round 1 fix ACCEPTED.
- Important findings / decisions: `tests/conftest.py` autouse chuyển `corrections_path` sang tmp (tránh test ghi vào home); `config.example.toml` không thêm key (test so với default), README ghi key; sửa `from`/`to` của luật đã duyệt không áp lại; luật `rejected` không hiện trên UI; nhật ký sửa ghi mỗi lần lưu `paragraphs`; luật chèn thuần (phần giữa rỗng) đặt từ mới cạnh token gốc gần nhất.
- Known limitations: chỉ thay từ (không chèn/xóa); bỏ duyệt / xóa luật không hoàn tác bài đã sửa; test chập chờn dưới `-n auto` (chạy riêng PASS): `tests/test_web_lanes_cp810.py::test_lanes_artifacts_identical_to_serial`, `tests/test_web_cp9.py::test_cut_save_reset_and_409`. Manual test checklist: chưa chạy.
- PR:
