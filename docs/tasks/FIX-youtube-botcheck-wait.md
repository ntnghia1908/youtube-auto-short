# Task: FIX-youtube-botcheck-wait — Tạm dừng tải khi YouTube chặn bot

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `0e0581f` (`main`) / `fix/youtube-botcheck-wait` (worktree `../youtube-auto-short-ytwait`)
- Human Lead approval: APPROVED 2026-10-04 ("Làm task S1 tạm dừng tải khi YouTube chặn bot" — theo đề xuất ORCHESTRATOR cùng ngày; phạm vi ghi dưới đây)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: hành vi hàng đợi làn `prepare` khi tải lỗi tạm thời, theo đúng khuôn FIX-ollama-wait (làn `ai` đợi GPU); không đổi dependency, security model (không cookie), public API.

## Bối cảnh (2026-10-04, ORCHESTRATOR)

- 2026-10-03 23:58Z: yt-dlp báo `ERROR: [youtube] <id>: Sign in to confirm you’re not a bot …` → mỗi job làn `prepare` fail ngay ở ingest rồi làn chạy job kế tiếp → 13 video (26 job Short + khai thị) của Vô Lượng Thọ / Thập Thiện / Cảm Ứng Thiên fail trong ~1 phút.
- 2026-10-04 07:20Z: cùng video tải lại được (chặn tạm thời).
- Làn `prepare` đang có ~93 tập Địa Tạng ("Chuẩn bị + HD", CP13.2) → dễ gặp lại.
- Mẫu có sẵn: FIX-ollama-wait (`docs/tasks/FIX-ollama-wait.md`): `GpuUnavailable` → job quay lại làn `ai`, làn đợi, kiểm lại mỗi 60 s, banner trên web.

## Goal

Khi YouTube chặn bot, job đang tải **không fail**: quay lại đầu làn `prepare`, làn `prepare` ngừng tải (job không cần tải — tập đã có nguồn — vẫn chạy được), thử lại sau một khoảng chờ tăng dần; web hiện banner "YouTube tạm chặn tải từ … — thử lại lúc …". Hết chặn → tự chạy tiếp, không cần bấm.

## Scope

- In scope:
  - **Y1 Nhận dạng.** Lỗi yt-dlp chứa dấu hiệu chặn bot / giới hạn tốc độ (ít nhất: `Sign in to confirm you’re not a bot` / `confirm you're not a bot`, HTTP 429 / `Too Many Requests`) → ngoại lệ riêng (ví dụ `YoutubeBlocked`) tách khỏi `DownloadError` thường. Lỗi khác (video riêng tư, xóa, sai định dạng…) vẫn fail như cũ.
  - **Y2 Hàng đợi.** Job gặp `YoutubeBlocked` quay lại **đầu** làn `prepare` (không fail, không tính là lỗi tập); làn `prepare` vào trạng thái "YouTube chặn" tới hạn thử lại; trong lúc đó làn không bắt đầu job cần tải mới (job có nguồn sẵn — ví dụ "Chạy tiếp" / transcript — được phép chạy). Khoảng chờ: bắt đầu 15 phút, nhân đôi mỗi lần bị chặn liên tiếp, tối đa 2 giờ; tải thành công → reset. Khóa config `[web]` (hoặc `[ingest]`) cho khoảng đầu / tối đa, mặc định như trên.
  - **Y3 Bền + hiển thị.** Trạng thái chặn (từ lúc, hạn thử lại) sống qua khởi động lại (`.web_queue.json`, như CP8.22); API list / episode / bộ kinh trả `youtube` giống `gpu` (FIX-ollama-wait O7); banner web cạnh banner GPU.
  - **Y4 Tạm dừng / chạy tiếp toàn cục** (CP8.22) vẫn đúng; "Chạy tiếp" thủ công một tập khi đang bị chặn → job vào hàng, đợi như các job khác.
  - Test + cập nhật README / hướng dẫn nếu có mô tả lỗi tải.
- Out of scope: cookie YouTube / đăng nhập (đổi security model — đề xuất riêng nếu chặn kéo dài); proxy; đổi yt-dlp; thứ tự ưu tiên giữa các bộ kinh; tự chạy lại 26 job đã fail đêm 2026-10-03 (HUMAN LEAD bấm).

## Authority / key decisions

- `docs/tasks/FIX-ollama-wait.md` (mẫu đợi + banner), `docs/tasks/CP8.10-queue-lanes.md` (làn), `docs/tasks/CP8.22-queue-pause-persist.md` (bền + tạm dừng), `docs/tasks/CP13.2-hd-first.md` (job prepare-only).
- K1: không thêm cookie / thông tin đăng nhập.

## Acceptance Criteria

1. Downloader giả ném lỗi chặn bot ở job 1 trong 3 job: job 1 quay về đầu làn, không job nào fail, làn không chạy job 2, 3 cho tới hạn thử lại; hết hạn (đồng hồ giả) + tải được → cả 3 xong theo thứ tự.
2. Lỗi tải khác (ví dụ "Video unavailable") → job fail như cũ, làn chạy tiếp job kế.
3. Chặn liên tiếp: khoảng chờ 15 → 30 → 60 → 120 → 120 phút; tải thành công reset về 15.
4. Khởi động lại khi đang chặn: trạng thái + hạn thử lại khôi phục; job vẫn ở đầu làn.
5. API trả trạng thái `youtube` (blocked, since, next_check); banner hiện / ẩn đúng.
6. Job không cần tải (nguồn đã có, ingest "skip") vẫn chạy khi đang chặn.
7. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–7.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080 khi YouTube chặn lần sau: banner hiện, không có loạt job "lỗi Tải video", tự chạy tiếp sau khi hết chặn.

## Result

- Main changes: `ingest/youtube.py` `YoutubeBlocked` + `is_blocked_message` (ANSI / curly apostrophe / 429); `ingest/stage.py` `IngestBlocked`, `needs_download`; `web/jobs.py` `YoutubeWait` → `_requeue_blocked` (head of prepare queue, not failed), backoff `_set_yt_blocked_locked`, `_take_locked` (only no-download jobs start while blocked), state saved in `.web_queue.json` key `youtube`, `youtube_status()`, `Job.yt_wait`; `config.py` `[web] youtube_retry_minutes` (15) / `youtube_retry_max_minutes` (120) + `config.example.toml`; `web/app.py` `youtube` in list / episode / playlist views; `static/app.js` `showYoutube` banner + label.
- Tests: `tests/test_youtube_wait.py` (19, AC1-AC6 + Y4 pause); `python -m pytest -q -n auto` 1469 passed, 1 skipped; `node scripts/framework-check.mjs` PASS.
- Review: ORCHESTRATOR 2026-10-04 — round 1: F1 (blocking, AC3) backoff reset bởi ingest khai thị tái dùng nguồn (không lên YouTube) → sửa `1da83d2` (reset chỉ khi `needs_download()` trước khi chạy = True và ingest chạy) + test mới; xác nhận tập đang đợi hiện "đợi YouTube", không "lỗi Tải video". Round 2: ACCEPTED; chạy lại 42 test liên quan PASS.
- Important findings / decisions: review F1 fixed: `PipelineTarget._run` decides `needs_download()` before the run and the block resets only when that was True and ingest ran (a khai thị job reusing its base source no longer resets it; test added). While a job waits, the active job overrides the failed manifest ingest in the episode / bộ kinh views (`_kind_status`, `stateText`): shown as queued / "đợi YouTube", not "lỗi Tải video" (API test added). Serial mode: a block is still a plain failure.
- Known limitations: no manual "retry now" button; waiting jobs show "đang đợi" + banner (no per-row lane label while QUEUED).
- PR: #66
