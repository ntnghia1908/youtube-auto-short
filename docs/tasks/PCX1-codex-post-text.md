# Task: PCX1 — Codex viết lại bài đăng "Chữ AI từ phụ đề" (nhãn "Codex dịch")

## Status / Approval

- Status: READY
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
  7. Lỗi (Codex quá tải / kho 3090 không trả lời / output không có khối VI / rỗng): giữ nguyên bài cũ, ghi lỗi hiển thị trên thẻ; không fallback âm thầm.
  8. Hàng đợi tồn đọng tự động (HUMAN LEAD 2026-11-08 "chạy tự động … cho đến khi dịch hết"): khi `codex_auto` bật, web tự xử lý **mọi** bài `ai` / `raw` chưa đăng của mọi episode (không chỉ bài mới compose), từng bài một, đến khi hết; bài lỗi không-phải-quota ghi lỗi và bỏ qua (không lặp vô hạn; thử lại khi bấm tay hoặc khi text nguồn đổi). Trạng thái hàng đợi (còn bao nhiêu bài, đang làm bài nào, đang đợi gì) hiện trên web.
  9. Hết hạn mức Codex giữa chừng (output / log Codex báo usage limit / quota / rate limit — phân biệt với "at capacity" quá tải tạm): không tính là lỗi bài; bài giữ nguyên; job chuyển trạng thái "đợi hạn mức Codex" (hiển thị giờ VN dự kiến có lại nếu đọc được từ thông báo Codex hoặc `scripts/codex-usage.py`, không thì thử lại theo chu kỳ cấu hình, mặc định 30 phút), rồi **tự chạy tiếp** từ bài đang dở. Sống sót qua restart web (khởi động lại thì tiếp tục hàng đợi). Mẫu chờ có sẵn: `YoutubeWait` / `StoreWaitJob` trong `web/jobs.py`.
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
8. Hàng đợi tồn đọng: gom đúng mọi bài `ai`/`raw` chưa đăng; lỗi thường → bỏ qua bài đó, chạy bài sau; hết hạn mức → đợi, không đánh lỗi bài, tự chạy tiếp (runner giả + đồng hồ giả); restart → tiếp tục.
9. Chạy thật (ORCHESTRATOR, ngoài sandbox, 8080 ghim commit nhánh): VLT 25 k01 (bấm tay, bài đã đăng) + 3 bài ĐT ở Bằng chứng; HUMAN LEAD xem chữ trên web.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_post_*.py` (Codex trong sandbox, test không socket).
- Test web posts (TestClient) + full suite — ORCHESTRATOR ngoài sandbox.
- AC9 chạy thật.

## Manual test checklist (Tech Lead)

Chạm public API web nội bộ (route mới) và schema `posts.json` (thêm giá trị origin); không chạm database / security model. Manual test là gate trước merge.

- [ ] Thẻ VLT 25 k01: bấm "Codex dịch" → xác nhận → bài mới, badge "Codex dịch".
- [ ] 3 bài ĐT: chữ đúng, sao chép không hỏi.
- [ ] Lỗi Codex giả lập / kho tắt: thẻ báo lỗi, bài cũ giữ nguyên.

## Result

IMPLEMENTER handoff: READY để ORCHESTRATOR review; test TestClient / full suite / AC9 vẫn là gate ngoài sandbox, chưa tuyên bố PASS.

- Main changes: `post/codex_text.py` nghe lại Short bằng backend Whisper có cache, tái dùng `render.stage.probe_media`, tách audio mono 16 kHz và mọi khung cách 2 s thành contact sheet 3×2 (crop vùng video chỉ với Short dọc; khai thị / ngang giữ cả khung). Prompt v1 dùng JSON không tin cậy; đọc HAN / VI, lưu origin `codex`, không áp từ điển. Lưu source hash, prompt, Whisper, HAN, output, tokens, model/effort, thời gian và lỗi vào log.
- Posts / concurrency: giữ image / link / posted_at; kiểm tra lại nội dung bài, tick đăng, source hash và render manifest trước khi ghi. Lỗi thường giữ bài, ghi lỗi trên thẻ; các log compose/Codex dùng cùng `post_lock`.
- Web: job `post_codex`, khóa riêng `<episode>#post_codex`, làn `codex` một worker (kể cả serial mode), gộp yêu cầu và giữ xác nhận bài đã đăng theo từng clip; API `POST/GET /api/episodes/{id}/posts/codex`, `GET /api/posts/codex`; nút từng bài / cả tập, badge, copy không cảnh báo. `[post] codex_auto = true`, `codex_retry_minutes = 30`; CLI `post codex` hỗ trợ clips / include-posted / all-ai.
- Amendment Scope 8–9: đọc lại bản contract được bổ sung trong worktree khi đang triển khai. Backlog quét toàn bộ posts chưa đăng, chỉ nhận một clip khi làn rảnh; lỗi thường bỏ qua bền qua restart cho đến khi source text đổi hoặc bấm tay. Quota (usage/rate limit) tách khỏi overload, giữ job đang dở, không đánh lỗi bài, lưu thời điểm retry trong queue, tiếp tục đúng clip sau restart. Reset đọc epoch / ISO / khoảng chờ / ngày giờ tiếng Anh; không đọc được thì dùng cấu hình. Web hiển thị số bài, clip đang làm, trạng thái đợi và giờ VN.

### AC → test

| AC | Bằng chứng |
|---|---|
| 1 | `test_post_codex_text.py::test_media_prompt_all_images_schema_and_log`, `test_failure_keeps_old_text_and_logs_reason` (parametrize) |
| 2 | `test_post_codex_text.py::test_released_short_uses_borrow_short_and_store_failure_is_explicit` (mượn / offline) |
| 3 | `test_media_prompt_all_images_schema_and_log`, `test_eligibility_and_config_preserve_other_origins`; hồi quy `test_post_backend.py` / `test_post_kept.py` |
| 4 | `test_post_codex_jobs.py::test_compose_finished_schedules_only_eligible_result_clips`, `test_codex_lane_is_serial_but_does_not_block_other_work_and_merges_pending`; TestClient `test_compose_auto_and_bulk_only_unposted_ai` chưa chạy |
| 5 | Node VM `test_post_codex_ui.py::test_codex_button_requires_posted_confirmation`, `test_web_post_doc_gate.py::test_post_copy_warning_and_tick_only_after_success`; TestClient `test_api_manual_confirmation_and_protected_origins`, `test_api_running_error_and_restart_status_keeps_old_post` chưa chạy |
| 6 | ba hàm trong `test_post_codex_cli.py`: chọn clip / posted / all-ai, scope sai, lỗi giữ bài |
| 8 | ba hàm trong `test_post_codex_backlog.py`: quota retry/restart với runner + clock giả (exit 0/1), parse reset/fallback cấu hình, quét nhiều episode / bỏ qua lỗi / nguồn đổi; TestClient `test_api_backlog_reports_quota_and_resumes` chưa chạy |
| 9 | Chưa chạy — ORCHESTRATOR / HUMAN LEAD ngoài sandbox |

AC5 dùng bốn hàm vì cần kiểm chứng riêng handler UI xác nhận, clipboard, auth/validation API và lỗi/restart API; không chỉ assert chuỗi tĩnh.

### Verification trong môi trường này

CWD `/home/ntnghia/projects/yas-pcx1`, HEAD `6479ccd`, branch `feature/pcx1-codex-post`; không commit/push/PR, không gọi dịch vụ thật, không gọi agent.

Lượt cuối (dùng danh sách file để không vô tình thu thập fixture socket):

```bash
mapfile -t post_test_files < <(rg --files tests | rg '/test_post_.*\.py$' | rg -v '/test_post_fetch\.py$')
PYTHONPATH=/home/ntnghia/projects/yas-pcx1/src conda run -n auto-short python -m pytest -q "${post_test_files[@]}" tests/test_web_post_doc_gate.py -k 'not test_preflight' -x --tb=short
```

**306 passed, 3 deselected in 6.27s.** `test_web_post_doc_gate.py` dùng Node VM, không có TestClient/socket. Ba ca preflight cũ không chạy trong sandbox.

```bash
PYTHONPATH=/home/ntnghia/projects/yas-pcx1/src conda run -n auto-short python -m pytest -q tests/test_post_fetch.py -k 'test_check_url or test_image_urls or test_largest_srcset' -x --tb=short
```

**5 passed, 8 deselected in 0.11s.** Tám ca còn lại cần HTTP server loopback.

- `PYTHONPATH=/home/ntnghia/projects/yas-pcx1/src conda run -n auto-short python -m pytest -q --collect-only tests/test_web_post_codex.py`: **14 tests collected**; chỉ thu thập, chưa chạy TestClient.
- `git diff --check`: PASS. `node --check src/auto_short/web/static/app.js`: PASS.
- Một lượt mở rộng trước đó dùng `tests/test_post_*.py --ignore=tests/test_post_fetch.py -k 'not test_preflight'` vẫn thu thập đường dẫn được glob truyền trực tiếp: **209 passed, 3 deselected, 1 error**, fixture `test_post_fetch.py::server` bị sandbox từ chối tạo socket (`PermissionError: Operation not permitted`). Đã sửa danh sách đầu vào như lệnh cuối ở trên; không nới sandbox.
- Không chạy: TestClient posts, full suite, 3 test preflight, 8 test fetch cần loopback, và AC9 thật. ORCHESTRATOR chạy các gate này ngoài sandbox.

### Diff / helper / review

- Diff + / −: **app +715 / −34**, **test +648 / −1**; cộng `git diff --numstat` với dòng của file mới chưa tracked, app gồm `src/` + `config.example.toml`, loại docs. Không stage file.
- Tìm helper bằng `rg -n 'run_codex|CodexFailed' ...`, `rg -n 'extract_audio|def .*audio|pcm_s16le|16000' src/auto_short/transcript src/auto_short/analysis`, `rg -n '^def .*probe|^def .*audio|show_entries' src/auto_short/ingest src/auto_short/render src/auto_short/packaging`, `rg -n 'KIND_POST|post_compose|post_lock|post_' src/auto_short/web/jobs.py` và đọc `post/imggen.py`, `transcript/whisper.py`, `store/shorts.py`, `post/store.py` / `stage.py`.
- Tái dùng: `cover_suggest.run_codex` / `CodexFailed` / process lifecycle, `FasterWhisperBackend` cache, `borrow_short`, `probe_media`, `with_compose` / schema / atomic write, `_append_log`, job queue/persistence, `postHasAiText` / `postBadges` / copy helper, Node harness hiện có.
- Helper mới: `prepare_media` / `_media` (chưa có audio + contact-sheet pipeline; `_run` render không có timeout theo yêu cầu này); prompt / parse (khác IMG / Ollama); `eligible` (chỉ ai/raw, khác `auto_clips` chọn thiếu/stale); `rewrite_posts` / `Summary`; `quota_wait` / `CodexQuotaWait` / latest attempts (chưa có Codex quota wait, theo mẫu chờ YouTube); `PostCodexTarget` / `PostCodexBacklog` (job và backlog mới, dùng lại runner). Test fakes dùng chung đặt trong `test_post_codex_helpers.py`.
- Ownership decision cần ORCHESTRATOR review: `packaging/cover_suggest.py` không thuộc Owned paths. Không sửa file đó; `_run_codex_images` trong `post/` chuyển danh sách ảnh thành cờ `-i` qua process runner của `run_codex`, giữ sandbox / timeout / cancel / capacity handling và nguyên lệnh của caller bìa/IMG. Đây là adapter nhỏ thay cho mở rộng signature ngoài ownership. Làn `codex` độc lập cũng cần ORCHESTRATOR chốt ở review theo contract.
- Known limitations: chưa chạy media/Whisper/Codex thật; chất lượng chữ và crop trên 4 Short thật chờ AC9. Thông báo reset không parse được dùng chu kỳ cấu hình; không gọi script quota / mạng thật để suy đoán. Review độc lập / full verification / manual gate chưa thực hiện.
- PR: không tạo theo ràng buộc.

### ORCHESTRATOR verification (2026-11-08)

- Test web/post (TestClient) ngoài sandbox: **177 passed, 1 skipped**. Full suite: **4275 passed, 2 skipped** (28 phút 31 giây; test chập chờn đã biết `test_lower_thread_priority…` deselect, chạy riêng PASS ở nhánh FIX cùng đêm). Sau rebase lên `46ac329`: `test_post_codex_cli.py` + `test_titling_stage.py` 50 passed.
- Chạy thật CLI `post codex --include-posted` trên bản sao 4 workspace, config thật (Short local / kho), Whisper CPU + Codex `gpt-6.1-sol` medium: cả 4 `codex`, 0 lỗi.

  | Bài | Thời gian | Token Codex |
  |---|---|---|
  | VLT 25 k01 (đã đăng) | 123 s | 19.596 |
  | ĐT 83 k01 | 43 s | 11.054 |
  | ĐT 33 k02 | 83 s | 18.622 |
  | ĐT 22 k05 | 47 s | 10.426 |

  Chữ ORCHESTRATOR đọc: đúng ý, đúng thuật ngữ (Bát quan trai giới, Lục hòa kính, huống chi, Cứ nha địa ngục, hào khấp), bỏ câu Whisper bịa, sửa "tháng 5 → tháng 10" theo chữ trên hình.
- Review: lane `codex` riêng (1 job toàn cục) — chấp nhận; adapter nhiều ảnh trong `post/` thay vì sửa `cover_suggest.run_codex` — chấp nhận (caller cũ không đổi). Codex IMPLEMENTER 1 vòng, 202.919 token (tự đọc phần bổ sung Scope 8–9 trong lúc chạy).
- Known limitations: Whisper chạy CPU (~1–2 phút / Short) song song với các làn khác; log Codex đầy đủ lưu trong `post_log.json` (file lớn dần).
