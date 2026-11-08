# Task: PCX1 — Codex viết lại bài đăng "Chữ AI từ phụ đề" (nhãn "Codex dịch")

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — mặc định IMPLEMENTER (`.claude/rules/execution.md`), quota tuần 21 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-08 "Bài đăng đưa lên web theo các đề xuất của bạn" (đề xuất: tự động cho bài AI chưa đăng + nút từng bài; bài đã đăng chỉ chạy khi bấm tay; nhãn "Codex dịch")
- Parallel group: P1 (song song FIX-title-evidence-retry)
- Owned paths: `src/auto_short/post/`, `src/auto_short/web/` (app.py, jobs.py, episodes.py nếu cần, static/app.js, static/*.css), `src/auto_short/config.py` (`PostConfig`), phần subcommand `post` trong `src/auto_short/cli.py`, `config.example.toml`, `tests/test_post_*.py`, `tests/test_web_post*.py`, `docs/decisions/CP8.15-community-post-contract.md` (amendment P7), file này
- Dependencies: none
- Base commit / branch: `46469da` / `feature/pcx1-codex-post`
- Human Lead approval: accepted (2026-11-08)
- Implementation authorized: YES

## Goal

Bài đăng có origin `ai` / `raw` ("Chữ AI từ phụ đề — đọc kỹ trước khi đăng") được Codex viết lại thành bài tiếng Việt chuẩn từ chính Short (nghe lại + nhìn chữ Hán trên hình), lưu với origin `codex`, web hiện nhãn "Codex dịch" và sao chép không cần cảnh báo.

## Bằng chứng (ORCHESTRATOR chạy thử ngoài web 2026-11-08, scratchpad)

- VLT 25 `X4Rg3nTYzzo` k01 (90 s): bài AI chỉ "Tham, Bảo, Trì giới, Rất nhỏ." vì transcript cả tập bỏ sót đoạn (Whisper cả tập coverage 0,58). Whisper nghe **riêng Short** (`large-v3-turbo`, `vad_filter=True`) ra đủ lời thuyết minh; Codex + ảnh phụ đề → bài 5 đoạn đúng thuật ngữ. 18 k token.
- ĐT 33 k02, ĐT 22 k05, ĐT 83 k01: Codex sửa "hướng chi → huống chi", "cử nha → Cứ Nha" (đối chiếu 鋸牙), "hào khắp → hào khấp", "tháng 5 → tháng 10" (theo chữ trên hình), bỏ câu Whisper bịa ("Hãy subscribe cho kênh …"). 10–15 k token, 17–36 s mỗi bài.
- Video là giọng thuyết minh tiếng Việt; chữ Hán in trên hình (phụ đề / kinh văn) vị trí thay đổi theo video.
- Prompt đã dùng (mẫu cho prompt v1 của task): khung 2 s / khung, crop vùng video `1080x1140+0+170` của Short dọc, scale 480 px, tile 3x2, số giây vẽ ở góc; prompt yêu cầu trả về `=== HAN ===` (chữ Hán đọc được hoặc "(không có)") và `=== VI ===` (bài, đoạn cách dòng trống); sửa chính tả / nghe nhầm / thuật ngữ Hán Việt, giữ âm Hán Việt khi đọc kinh văn, không thêm ý, không tóm tắt, bỏ câu bịa. Dữ liệu Whisper đặt trong khối dữ liệu không tin cậy (như `imggen.prompt`).

## Scope

- In scope:
  1. Module `post/codex_text.py`: cho một (episode, clip) — lấy file Short (local, hoặc mượn từ kho 3090 qua `store.shorts.borrow_short` khi đã giải phóng), tách audio, Whisper nghe lại (dùng cache model của `transcript/whisper.py`, ngôn ngữ / model theo `[transcript.whisper]`), dựng ảnh khung (Short dọc: crop vùng video; khai thị / video ngang: cả khung), gọi Codex qua `packaging.cover_suggest.run_codex` (mở rộng nhận nhiều ảnh, không đổi hành vi caller cũ), parse khối `=== VI ===` → `paragraphs`.
  2. `posts.json`: thêm origin `codex` (amendment CP8.15 P7). Lưu `source_sha256` như bài AI để logic stale giữ nguyên. Log mỗi lần vào `post_log.json` (prompt, bản Whisper, chữ Hán, output thô, tokens, thời gian, lỗi).
  3. Job web mới (kind riêng, không chạy song song với chính nó; lane không chặn render / prepare của Ollama 3090; ORCHESTRATOR chốt lane khi review): xử lý danh sách clip của một episode.
  4. Tự động: sau khi compose ra bài `ai` / `raw` **chưa đăng**, xếp job Codex cho các bài đó. Bật / tắt bằng `[post] codex_auto` (mặc định `true`).
  5. Web (tab "Bài đăng"): nút "Codex dịch" trên mỗi thẻ bài `ai` / `raw` (kể cả bài đã đăng — chỉ khi bấm, có xác nhận "bài đã đăng, chỉ thay chữ trên web"); nút "Codex dịch các bài AI" cho cả tập (chỉ bài chưa đăng); trạng thái đang chạy / lỗi; badge "Codex dịch", không còn cảnh báo "Chữ AI từ phụ đề" và "AI không chắc"; sao chép không hỏi lại.
  6. CLI backlog: `auto-short post codex <episode_id> [--clips k01,k02] [--include-posted]` và `--all-ai` (mọi episode, chỉ bài ai/raw chưa đăng) để ORCHESTRATOR chạy thử 1–3 bài rồi chạy hàng loạt.
  7. Lỗi (Codex quá tải / hết quota / kho 3090 không trả lời / output không có khối VI / rỗng): giữ nguyên bài cũ, ghi lỗi hiển thị trên thẻ; không fallback âm thầm.
- Out of scope: sửa transcript cả tập, đổi titling, ảnh bài đăng, bài `doc` / `manual`, tự động đăng YouTube, Whisper GPU.

## Authority / key decisions

- CP8.15 P7 amendment (HUMAN LEAD 2026-11-08): `ORIGINS` thêm `codex`; bài `codex` sửa tay trên web → `manual` như hiện nay.
- Bài đã "Đã đăng bài": không bao giờ tự động thay; chỉ thay khi HUMAN LEAD bấm.
- Bài `codex` không còn là "Chữ AI từ phụ đề" (không cảnh báo khi sao chép).
- Không áp từ điển sửa lỗi (CP8.18) lên chữ Codex.

## Implementation approach

- Tái dùng: `cover_suggest.run_codex` / `CodexFailed`, `imggen` (mẫu khối dữ liệu không tin cậy, đếm `tokens used`), `transcript/whisper.py` (cache model), `store.shorts.borrow_short`, `post/store.py` (`upsert`/schema), job runner + `KIND_POST` (mẫu job), `postBadges` / `copyPostButton` / `postHasAiText` trong `app.js`.
- Codex chạy trong thư mục tạm, `-s workspace-write` như `run_codex` hiện có; không mạng ngoài Codex.

## Phải giữ nguyên

- Compose Ollama (P3) như cũ; bài `doc` / `manual` không đổi; bài đã đăng không tự đổi.
- `run_codex` của bìa / IMG giữ nguyên lệnh khi không truyền ảnh mới.
- `posts.json` cũ vẫn đọc được (schema_version 1, chỉ thêm giá trị origin).

## Code bị thay / xóa

- `postHasAiText` / badge "Chữ AI từ phụ đề" giữ cho `ai` / `raw`; không xóa gì.

## Acceptance Criteria

1. `codex_text` (runner / whisper / store giả): dựng đúng prompt (khối dữ liệu không tin cậy), truyền đủ ảnh, parse `=== VI ===` thành đoạn; output thiếu khối / rỗng → lỗi, bài cũ giữ nguyên.
2. Short đã giải phóng lên kho được mượn qua `borrow_short`; kho không trả lời → lỗi rõ, bài cũ giữ nguyên.
3. `posts.json` nhận origin `codex`; `check_posts` PASS; bài cũ đọc được.
4. Tự động: compose ra bài `ai`/`raw` chưa đăng → xếp job Codex đúng các clip đó; bài đã đăng / `doc` / `manual` không xếp; `codex_auto = false` → không xếp.
5. API / web: nút từng bài (bài đã đăng cần xác nhận), nút cả tập (chỉ chưa đăng), badge "Codex dịch", sao chép không cảnh báo, lỗi hiện trên thẻ.
6. CLI `post codex` (`--clips`, `--include-posted`, `--all-ai`) đúng tập clip.
7. Chạy thật (ORCHESTRATOR, ngoài sandbox, 8080 ghim commit nhánh): VLT 25 k01 (bấm tay, bài đã đăng) + 3 bài ĐT ở Bằng chứng; HUMAN LEAD xem chữ trên web.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_post_*.py` (Codex trong sandbox, test không socket).
- Test web posts (TestClient) + full suite — ORCHESTRATOR ngoài sandbox.
- AC7 chạy thật.

## Manual test checklist (Tech Lead)

Chạm public API web nội bộ (route mới) và schema `posts.json` (thêm giá trị origin); không chạm database / security model. Manual test là gate trước merge.

- [ ] Thẻ VLT 25 k01: bấm "Codex dịch" → xác nhận → bài mới, badge "Codex dịch".
- [ ] 3 bài ĐT: chữ đúng, sao chép không hỏi.
- [ ] Lỗi Codex giả lập / kho tắt: thẻ báo lỗi, bài cũ giữ nguyên.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
