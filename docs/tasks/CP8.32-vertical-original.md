# Task: CP8.32 — Bản dọc / bản ngang HD từ video gốc ≥ 720p + nút "Tạo bản dọc cả bộ"

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `c568f1b` (`main`) / `feature/cp8.32-vertical-original` (worktree `../youtube-auto-short-cp832`)
- Human Lead approval: APPROVED 2026-10-15 ("Kinh Vô Lượng Thọ và Thập Thiện tôi cũng cần làm bản dọc giống kinh Địa Tạng"; decision gate cùng ngày: V1 = video gốc khi ≥ 720p, V2 = tự tải lại khi tạo bản dọc, V3 = thêm nút cả bộ)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa luật CP8.27 H1 / H4 (nguồn HD không chỉ là `source_hd.mp4`), sửa luật CP8.6 W9 (tập archived được tải lại video gốc cho bản dọc), thêm route web mới (bộ kinh). Không đổi dependency, security model, API worker enhance.

## Bối cảnh (2026-10-15, ORCHESTRATOR)

- CP8.27 H4: bản dọc cả tập chỉ tạo từ `work/<id>/source_hd.mp4` (enhance xong); H1 bản ngang HD cũng vậy. Out of scope CP8.27: "bản dọc cho video chưa enhance".
- Enhance chỉ chạy khi nguồn < 720p (`enhance.json` `reason`). Vô Lượng Thọ (1080p), Thập Thiện (1080p), Cảm Ứng Thiên (720p) → `wanted = false` → không có `source_hd.mp4` → không có nút "Tạo bản dọc" / "Tải bản ngang (HD)". Địa Tạng 480p → có (sau enhance).
- Video gốc đã bị dọn (CP8.6 W9, `archive.json`, tự dọn S5) ở nhiều tập đã xong: Vô Lượng Thọ 14/20, Thập Thiện 4/34, Cảm Ứng Thiên 3/20 (2026-10-15). Ingest hiện từ chối tập archived.
- Mỗi bản dọc ≈ 30 phút làn `render` / tập 1 giờ (CP8.27 Result).

## Goal

Mọi tập có video chất lượng ≥ 720p — hoặc từ enhance (`source_hd.mp4`) hoặc từ video gốc — đều tạo / tải được bản dọc cả tập và bản ngang HD như Địa Tạng; trang bộ kinh có nút tạo bản dọc cho cả bộ.

## Scope

- In scope:
  - **V1 Nguồn HD hiệu lực.** Một hàm dùng chung chọn nguồn cho bản dọc (H4) và bản ngang (H1) của tập (khai thị `.kt` dùng của video gốc như CP8.27): (a) `source_hd.mp4` hợp lệ (luật CP8.27 hiện có) → dùng; (b) không thì, nếu video gốc của tập có chiều cao ≥ ngưỡng enhance (`[enhance]` ngưỡng 720 hiện có — dùng đúng khóa config / hàm quyết định `wanted`, không lặp hằng số) → dùng video gốc `work/<id>/source.<ext>`; (c) còn lại (< 720p chưa enhance xong) → như cũ (ẩn nút, API 404). Khóa dùng lại bản dọc (`vertical.json`) tính theo sha / kích thước của nguồn thật dùng; ghi nguồn (`hd` / `original`) vào `vertical.json`. Bản ngang từ video gốc: tải file gốc (đuôi thật, tên `…_HD.<ext>`), không encode lại.
  - **V2 Tập đã dọn video gốc (sửa CP8.6 W9 cho riêng bản dọc).** Tập archived có nguồn (b) (chiều cao lưu trong manifest / probe trước khi dọn ≥ 720p): nút "Tạo bản dọc" vẫn hiện; job bản dọc tải lại video gốc (yt-dlp như ingest, cùng xử lý YouTube chặn bot của làn `prepare` — FIX-youtube-botcheck-wait), xác minh (probe; nếu manifest có sha / kích thước cũ thì so khớp, lệch → vẫn dùng nhưng ghi cảnh báo), tạo bản dọc, rồi **dọn lại** video gốc và giữ `archive.json` như trước (không đổi trạng thái tập, không chạy lại pipeline Short). Phần tải chạy theo luật làn `prepare` (hoặc trong job render nếu IMPLEMENTER chứng minh không chiếm làn render khi đang tải — ghi lựa chọn vào Result). Bản ngang HD của tập archived: **không** tải lại (nút ẩn), trừ khi bản dọc đang / vừa tải lại — giữ đơn giản.
  - **V3 Nút "Tạo bản dọc cả bộ"** trên trang bộ kinh: xếp job bản dọc cho mọi tập **đã xong Short** và có nguồn hợp lệ theo V1 / V2, chưa có bản dọc hiện hành và chưa có job bản dọc đang chờ; hỏi xác nhận với số tập + ước lượng giờ làn render (≈ 0,5 h / tập); thứ tự theo số tập; job bản dọc **xếp sau** mọi job Short / khai thị trong làn `render` (Short không phải đợi hàng trăm bản dọc). Kết quả trả số tập đã xếp / bỏ qua (lý do). Hủy được như job khác. Route mới cùng auth / cookie các route bộ kinh (CP8.7).
  - Hiển thị: trang tập + dòng tập ở trang bộ kinh hiện nút / icon "Tải bản dọc" như CP8.31 cho cả nguồn (b). Trang Theo dõi / hàng đợi hiện job bản dọc như hiện có.
  - Docs: sửa đổi canonical ở `docs/decisions/CP8.3-web-contract.md` (W7 route mới, W9 ngoại lệ tải lại cho bản dọc) + pointer CP8.27 nếu cần; README đoạn bản dọc.
  - Test cho V1–V3.
- Out of scope: enhance video ≥ 720p; bản dọc cho video < 720p chưa enhance; tự tạo bản dọc khi xong tập (HUMAN LEAD chọn nút cả bộ); đổi bố cục bản dọc (Amendment 2 CP8.27); encode trên GPU; tải lại video gốc cho bản ngang của tập archived; dọn `.vertical.mp4.part` cũ (`output/9NQFsvecC04/full/`) ngoài phạm vi cleanup tự nhiên của job.

## Authority / key decisions

- `docs/tasks/CP8.27-hd-download.md` (H1, H4, Amendment 2), `docs/decisions/CP8.3-web-contract.md` (W5 làn, W7 route, W9 archived), `docs/decisions/CP13.1-enhance-worker-contract.md` (`wanted`, ngưỡng), `docs/tasks/CP8.10-queue-lanes.md`, `docs/tasks/FIX-youtube-botcheck-wait.md`, `docs/tasks/CP8.31-downloads-mobile.md` (icon tải trang bộ kinh).
- K1: nguồn < 720p chỉ qua enhance; K2: tập archived sau khi làm bản dọc vẫn archived (video gốc dọn lại).

## Acceptance Criteria

1. Tập 1080p không enhance, còn video gốc: nút "Tạo bản dọc" + "Tải bản ngang (HD)" hiện; job tạo 1080×1920 đúng thời lượng (± 1 khung) từ video gốc; bấm lần hai không encode lại; `vertical.json` ghi nguồn `original`.
2. Tập 480p chưa enhance: nút ẩn, API 404 như cũ; tập 480p đã enhance: dùng `source_hd.mp4` như cũ (không regression CP8.27).
3. Tập 1080p archived (downloader giả): job bản dọc tải lại, tạo bản dọc, xóa lại video gốc, `archive.json` còn, manifest / trạng thái tập không đổi; YouTube chặn bot khi tải lại → job đợi như làn prepare, không fail.
4. Nút cả bộ: bộ 5 tập (2 xong + nguồn hợp lệ, 1 đã có bản dọc, 1 < 720p chưa enhance, 1 chưa xong Short) → xếp đúng 2 job, trả lý do bỏ qua 3 tập; bấm lần hai không xếp trùng.
5. Thứ tự làn render: có job Short xếp sau loạt bản dọc vẫn chạy trước các bản dọc chưa bắt đầu.
6. Khai thị `.kt` dùng nguồn của video gốc (cả nhánh (b)).
7. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–7.
- `node scripts/framework-check.mjs`.
- Tạo thật bản dọc một tập 1080p (ví dụ Thập Thiện còn video gốc) trên bản sao dữ liệu / output riêng (không ghi `output/` chính): thời gian, kích thước, ảnh khung — AC 1.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / API worker. Trên 8080 (ghim commit nhánh): Thập Thiện — tạo + tải bản dọc một tập còn video gốc và một tập đã dọn; tải bản ngang HD; bấm "Tạo bản dọc cả bộ", xem hàng đợi (Short vẫn đi trước); xem bản dọc trên điện thoại.

## Result

- Main changes: (V1) one decision `enhance.state.effective_source(config, id)` -> `EffectiveSource(kind hd|original|archived, path, sha256)`: valid `source_hd.mp4`; else the original `source.<ext>` when `metadata.json` `height` >= `[enhance] min_height` (the key `decide` uses; no new constant), `.kt` -> base video; else None. Used by `web/episodes.hd_file` / `hd_source` (landscape route: the original served as is, `…_HD.<ext>`, Range), the vertical routes, `hd_video` (new `source` field), playlist `hd_url` / `hd_name`, and `render/full.py` (`run_vertical`, `current`); `vertical.json` records `source`, key = sha256 of the source used (HD sha256 as before, so existing CP8.27 files stay current; original / archived: the ingest manifest sha256, stable across a re-download; `source_kind` joins the key only for non-HD). (V2) `render/full.fetch_original` (yt-dlp downloader of ingest, `[ingest]` format, into `work/<id>/.vertical-fetch-tmp` then `source.<ext>`; manifest / `archive.json` / stages untouched; verified: probe, height >= threshold, duration within max(2 s, 1 %); size / sha256 differing from the manifest = warning kept in `vertical.json` `source_warning`, still used; `SourceBlocked` on YouTube bot check / 429) and `remove_refetched_source` (K2: archived => no `source.*`, run on success and on error). `VerticalTarget(episode_id=…)`: an archived episode gets two steps, prepare-lane fetch then render-lane encode; fetch raises `YoutubeWait` so FIX-youtube-botcheck-wait waits instead of failing, W9 disk check first. Already-current archived vertical is not downloaded again. Archived + valid `source_hd.mp4` encodes straight from the HD (no 409 any more). (V3) `POST /api/playlists/{pid}/vertical` (episode order, same cookie as other playlist routes) -> `{episodes, queued, queued_ids, skipped:[{episode_id, reason}], errors}`; playlist entry field `vertical {status, reason, fetch, ready, url, name}`; page button "Tạo bản dọc cả bộ (n)" with confirm (count, ≈ 0,5 h / tập, number to re-download) + a phone-icon download per row; `JobRunner._rank`: vertical jobs after every other job of the lane (also after a priority mark); at most `VERTICAL_PREFETCH` = 2 re-downloaded originals in flight / waiting / encoding (disk); auto clean-up (S5) skips a video with an active vertical job; queue restore rebuilds vertical jobs of archived episodes. Docs: `docs/decisions/CP8.3-web-contract.md` (header, W5 order + prefetch, W7 routes + fields, W9 exception), pointer in CP8.27 out-of-scope, README paragraph.
- Tests: `tests/test_web_vertical_cp832.py` (18: effective-source rules + threshold key, AC1 original buttons / routes / Range / reuse, extension in the name, real ffmpeg vertical from an original (1080x1920, 50 frames, reuse, `.kt`), AC2 480p unchanged + enhanced HD, AC6 `.kt`, AC3 archived re-download + cleanup (archive.json / manifest / metadata / titles byte-identical, no source left, reuse without a second download), AC3 YouTube block waits and then finishes, wrong video refused + cleaned, differing bytes warn, archived < 720p not offered, auto-archive waits for a vertical job, AC4 five-episode bulk (2 queued, 3 skipped with reasons, second press queues nothing, 404 / auth), playlist icons, AC5 queue order + running lane takes the Short first, prefetch bound). `python -m pytest -q -n auto`: 1781 passed, 1 skipped (1m52; one earlier run had a timing flake in unrelated `test_web_post_cp815.py::test_put_edit_allowed_while_job_running[serial]`, passes alone and on rerun); `node scripts/framework-check.mjs` PASS.
- Real run (AC1), copy `~/.cache/auto-short-cp832-test/` (hard link of `source.mp4` + copies of manifest / metadata / titles of Thập Thiện tập 1 `eXKpw0KqkAk`, 1080p 3523 s, 644 MB; own work / output; production untouched; script `run.py`, log `run.log`): `nice -n 10`, ffmpeg `-threads 8` (`[render] preset` medium, crf 22), VM load average ≈ 42 on 32 cores: wall 1902.8 s (31 min 43 s, ≈ 0.54x realtime), child CPU 11909 s (≈ 6.3 cores), output 807.5 MB (1080x1920 h264 yuv420p 30000/1001, 105583 frames, video 3522.953 s, audio 3522.981 s = source). `vertical.json`: `source: original`, `hd_sha256` = manifest sha256. Second call: reuse in 0.13 s (no encode). Frames: `~/.cache/auto-short-cp832-test/frames/vertical_5.png`, `vertical_900.png`, `vertical_2400.png`; file `~/.cache/auto-short-cp832-test/output/eXKpw0KqkAk/full/vertical.mp4`.
- Round 1 fixes (ORCHESTRATOR F1 / F2): identity of an original / archived source is always the ingest-manifest sha256 (re-downloaded bytes only give `source_warning`), so the vertical stays current after the clean-up and the bulk button skips it; `JobRunner.on_vertical_failed` removes the re-downloaded original when a vertical job ends failed / interrupted (not on a stop, where it resumes), and `full.sweep_refetched_sources` runs after the queue restore at start-up (archived workspaces holding `source.*` / `.vertical-fetch-tmp` with no active vertical job). Tests +3 (21 in `test_web_vertical_cp832.py`). W9 text in CP8.3 unchanged (behaviour already stated).
- Review:
- Important findings / decisions: **V2 lane = prepare lane** (two-step job: download in `prepare`, encode in `render`). Reason: a download in the render step would hold the single render lane (30 min encodes) for the whole download, and could not wait for YouTube's bot check without blocking Shorts; the prepare lane already has the 4 slots, `needs_download` hook, W9 disk check and the Y2 wait / retry. Cost: a downloaded original (≈ 0,6–0,9 GB) waits on disk until the render lane reaches the (last-ranked) vertical job, so `VERTICAL_PREFETCH` = 2 bounds that. Fallback: if the render step finds an archived episode without a file (e.g. cut by "pause now" / restart after the fetch), `run_vertical` downloads inline. Limitation of the archived reuse shortcut: an archived episode whose vertical file is current is not rebuilt for a layout / header-only change (the source dimensions are needed for the key, so the original would have to be fetched); delete `output/<id>/full/` or use force to rebuild. Vertical jobs of a video with a priority mark still run after all non-vertical jobs. A vertical job queued behind Shorts keeps the (non-archived) original on disk: the auto clean-up skips the video meanwhile.
- Known limitations: no progress percentage (as CP8.27); `[enhance] min_height` is the only threshold (no separate key); the landscape download of an archived episode stays hidden (contract); bulk button counts only entries whose state is Short-rendered (`rendered` / `complete`), khai thị-only progress does not count; the playlist page does not poll vertical job progress (reload / monitor tab).
- PR:
