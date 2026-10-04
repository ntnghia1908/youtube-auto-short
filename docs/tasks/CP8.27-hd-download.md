# Task: CP8.27 — Nút tải video đầy đủ đã enhance (HD)

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `0cb2f0c` (`main`, gồm CP8.26 + CP8.28) / `feature/cp8.27-hd-download` (worktree `../youtube-auto-short-hddl`)
- Human Lead approval: APPROVED 2026-10-04 ("Thêm nút tải full video đã enhance")
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: thêm một route tải file sau đăng nhập web (cùng cookie / luật như các nút tải Short / zip CP8.7, CP8.17); không đổi dependency, security model, API worker.

## Bối cảnh

CP13.1b ghép bản HD cả tập vào `work/<id>/source_hd.mp4` (1440×1080, H.264 + Opus, ~1,3–2 GB / tập 1 giờ) và chỉ dùng để render. HUMAN LEAD muốn tải bản HD đầy đủ này về.

## Amendment 1 (HUMAN LEAD 2026-10-04)

"Bản HD nên cho tạo 2 loại: bản ngang và bản dọc (xem trên điện thoại cả tập, có banner cho tựa); bản ngang không cần banner." → thêm **H4 bản dọc**; bản ngang = H1 (file `source_hd.mp4`, không banner).

## Amendment 2 (HUMAN LEAD 2026-10-04, sau khi xem khung bản dọc)

"Khoảng 1/4 dưới của khung là màu đen. Title chia làm 2: ở trên để tên Kinh, ở dưới để HT. Tịnh Không phóng to lên; nếu vẫn còn đen thì phóng to video thêm chút." → bản dọc (H4) dùng hai panel: **panel trên** = tên bộ kinh + "(tập N)"; **panel dưới** (vùng đen cũ) = dòng người giảng "HT. Tịnh Không" (chèn dấu cách sau dấu chấm như CP8.16 R5) cỡ chữ lớn hơn panel trên rõ rệt; cùng kiểu panel vàng bo góc của Short. Sau khi đặt hai panel, nếu vẫn còn dải đen đáng kể (> ~5 % chiều cao) thì phóng video (giữ tỷ lệ, cắt giữa) để lấp, giữ lề đều; ghi bố cục cuối (tọa độ) + ảnh khung vào Result. Khóa dùng lại (layout) đổi → bản dọc cũ (nếu có) tạo lại khi bấm.

## Goal

Trang tập (và dòng tập ở trang bộ kinh) có nút "Tải video HD" khi `source_hd.mp4` đã xong (`enhance.json` `state = done`, sha / kích thước khớp); tải được file lớn ổn định (hỗ trợ `Range`, tải tiếp được), tên file dễ đọc.

## Scope

- In scope:
  - **H1 Route** `GET /api/episodes/{id}/source-hd` (tên tùy IMPLEMENTER): chỉ khi đã đăng nhập; chỉ file `source_hd.mp4` của tập (khai thị `.kt` dùng HD của video gốc); `FileResponse` (Range), `Content-Disposition: attachment` với tên `<bộ kinh>_Tập<N>_HD.mp4` (theo quy ước tên của CP8.17; tập lẻ / không có số tập → `<video id>_HD.mp4`; tên non-ASCII theo cách CP8.17 đang làm); 404 rõ khi chưa có HD.
  - **H2 UI**: nút "Tải video HD (x,x GB)" ở trang tập + biểu tượng tải ở dòng tập của trang bộ kinh khi có HD; ẩn khi chưa có.
  - **H4 Bản dọc cả tập (Amendment 1).** Nút "Tạo bản dọc" ở trang tập (khi có HD) → job làn `render` tạo video 1080×1920 cả tập từ `source_hd.mp4`: banner tựa ở trên (cùng kiểu panel header của Short — dòng "HT. Tịnh Không" + tên bộ kinh + "(tập N)" theo CP8.11 / CP8.14, không có panel tiêu đề Short ở dưới), video cắt giữa như Short, âm thanh giữ nguyên, không dissolve / cắt lặng; lưu `output/<id>/full/vertical.mp4` (dùng lại khi HD / layout / header không đổi — hash như render); nút "Tải bản dọc" + tên `<bộ kinh>_Tập<N>_Doc.mp4`. Bản ngang = H1, đổi nhãn nút thành "Tải bản ngang (HD)". Tốn CPU (cả giờ video): job theo luật làn `render` hiện có (không chạy song song quá `[render] jobs`), hủy được như job khác; IMPLEMENTER đo thời gian thật một tập và ghi vào Result.
  - **H3** Tải không tự tick "Đã đăng" / "Đã xem"; không chặn job đang chạy (đọc file, không khóa).
  - Test (file nhỏ giả) + README nếu có danh sách nút tải.
- Out of scope: bản dọc cho video chưa enhance (chỉ từ `source_hd.mp4`); encode bản dọc trên GPU worker; tải bản HD từng đoạn / nén lại; tải video gốc; zip nhiều tập HD; xóa `source_hd.mp4`.

## Authority / key decisions

- `docs/tasks/CP13.1b-enhance-vm.md` (source_hd), `docs/tasks/CP8.17-download-rules.md` (tên file, luật tải), `docs/tasks/CP8.7-playlist.md`.

## Acceptance Criteria

1. Tập có HD xong: route trả file đúng, `Content-Disposition` tên đúng, `Range` trả 206.
2. Tập chưa có HD / đang enhance / HD hỏng (sha / size không khớp `enhance.json`): 404 + thông báo; nút ẩn.
3. `.kt` trả HD của video gốc; id sai / ngoài workspace → 404 / 422, không đọc file ngoài `work/`.
4. Chưa đăng nhập → bị chặn như các route khác.
5. Bản dọc (H4): job tạo file 1080×1920 đúng thời lượng nguồn (± 1 khung), banner đúng chữ bộ kinh / tập, dùng lại khi bấm lần hai (không encode lại); tập chưa có HD → nút ẩn, API 409 / 404 rõ.
6. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–6.
- Tạo thật bản dọc một tập Địa Tạng trên bản sao dữ liệu (server test 8081 hoặc gọi hàm render, không ghi `output/` chính): thời gian, kích thước, ảnh chụp khung có banner — AC 5.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080: tải bản ngang tập 1 Địa Tạng (mở được, tên đúng); tạo + tải bản dọc, xem trên điện thoại (banner đúng, hình / tiếng khớp).

## Result

- Main changes: `render/full.py` (`run_vertical`: 1080x1920, Short header panel V16 on top + HD video centre-cropped, no title panel / dissolve / cuts, all audio; `output/<id>/full/vertical.mp4` + `vertical.json` with a key = HD sha256 + render config hash + font + fps + layout + header text; reuse without encode when unchanged; .part + atomic replace); routes `GET /api/episodes/{id}/source-hd`, `GET` / `POST /api/episodes/{id}/vertical` (404 without a valid HD, `.kt` uses the base video's HD; Range via `FileResponse`; names `[<bộ kinh>_]Tập<N>_HD.mp4` / `_Doc.mp4`, `<video id>_HD.mp4` without episode number via `review/names.video_name`); job kind `vertical` (runner key `<id>#vertical`, lane render, `VerticalTarget`, restored from the queue file, label "bản dọc cả tập" in the monitor / queue views); episode view field `hd_video`, playlist entry `hd_url` / `hd_name` (download icon); episode page buttons "Tải bản ngang (HD, x,x GB)", "Tạo bản dọc" / "Tải bản dọc"; README paragraph. Downloads tick nothing (H3).
- Tests: `tests/test_web_hd_cp827.py` (13: auth, name + Range 206 + no tick, 404 for none / assembling / bad sha / bad size, `.kt`, bad ids, no-episode name, job + reuse, failure, real small ffmpeg vertical encode + reuse + header change); `python -m pytest -q -n auto`: 1509 passed, 1 skipped (2m13 on the shared VM); `-m slow` not run (Short render core untouched); `node scripts/framework-check.mjs` PASS.
- Real run (AC 5), copy `~/.cache/auto-short-cp827-test/` (hard-linked `source_hd.mp4` of Địa Tạng tập 1 `9NQFsvecC04`, own config / output; production untouched): ffmpeg `-threads 8` (`[render] preset` medium, crf 22), VM under load (other jobs ~15 cores busy): wall 1993.7 s (33 min 14 s) for 3461 s of video (~0.58x realtime), child CPU 10525 s (~5.3 cores avg), output 811.3 MB (1080x1920 h264 yuv420p 30000/1001, 103730 frames, video 3461.124 s = source 3461.124 s; aac 48 kHz stereo 3461.161 s = source). Second call: `ran=False` in 0.22 s (no encode). Frames with banner: `~/.cache/auto-short-cp827-test/frames/vertical_5.png`, `vertical_900.png`, `vertical_2400.png`; file `~/.cache/auto-short-cp827-test/output/9NQFsvecC04/full/vertical.mp4`.
- Review: ORCHESTRATOR 2026-10-04 — Amendment 2 ACCEPTED (khung `amend2_40.png`: panel trên tên kinh + tập, video phóng lấp, panel dưới "HT. Tịnh Không" chữ lớn; đen còn ≈ 1 %). Lần đầu: ACCEPTED, không có blocking finding. Đã xem khung `vertical_900.png` (banner đúng, video giữa, đáy đen ≈ 25 %); route HD kiểm sha / size theo `enhance.json`, sau đăng nhập; job `vertical` khóa riêng `<id>#vertical`, dùng lại theo khóa; chạy lại 40 test liên quan PASS. Lưu ý vận hành: một bản dọc chiếm làn render ≈ 30 phút / tập (Short các tập khác đợi). Non-blocking: không có nút tạo lại khi đã có file; không tính dung lượng `output/<id>/full/`.
- Important findings / decisions: layout = Short V16 minus the title panel, so the lower ~25% of the frame (where the Short title panel sits) is black; the video is centre-cropped (1440x1080 -> the middle ~862:1000 part), as the contract asked ("như Short"). Vertical reuse key does not look at config changes other than via the key (job always recomputes the key; the UI "Tải bản dọc" appears only when the stored file matches the current HD sha256, so after a layout / header change use "Tạo bản dọc" again only if the HD changed; a layout-only change is picked up when the job runs, `POST` is always accepted).
- Amendment 2 (final vertical layout, 1080x1920; spacing s = 22 px = `min_frame_margin` for the top margin, the gaps and the bottom margin): top panel x 81 y 22 w 918 h 184 r 59 (bộ kinh + "(tập N)", header font 49 px, wraps to 2 lines when needed); video y 228 w 1080 h 1464 (crop 798x1080 at x 321 of the 1440x1080 source, scaled up x1.356, aspect kept); bottom panel x 81 y 1714 w 918 h 184 r 59 (speaker, "HT.Tịnh Không" -> "HT. Tịnh Không", font 78 px = 1.6 x header; `SPEAKER_SCALE`). Black left: only the 22 px margins (~1.1 %). `FULL_PLAN_VERSION` 2 + layout + speaker text in the reuse key, so an old vertical file is rebuilt on "Tạo bản dọc" (the UI only checks the HD sha for the button; POST recomputes the key). Verified on a 75 s excerpt of Địa Tạng tập 1 (no full re-render): encode 72 s (`-threads 8`, loaded VM), 19 MB; frames `~/.cache/auto-short-cp827-test/frames/amend2_5.png`, `amend2_40.png`. Tests 1518 passed / 1 skipped (`-n auto`), framework-check PASS.
- Known limitations: the button hides "Tạo bản dọc" while a current file exists (no "tạo lại" for layout-only changes; `POST` still works); no progress percentage while encoding (shown as "đang tạo…"); the render lane is busy for the whole encode (~0.5 h under load); `source_hd.mp4` cleanup / disk accounting of `output/<id>/full/` not added.
- PR: #71
