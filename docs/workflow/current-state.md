# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Auto Short: CP8–CP8.16 + CP9 đã merge (trừ CP8.4; CP8.16 PR #37, `d0c1517`; CP8.15 PR #35, `2622de8`; CP9 PR #30, `e60ab7a`; CP8.12 PR #25, `33ca2f8`; CP8.13 PR #26, `25f5b59`; CP8.14 PR #28, `d623cd3`). CP8.14 layout V16 (title nổi trên đáy video, mép dưới y 1600): 24 tập chưa đăng Short nào được render lại nền 2026-09-29 (tmux `youtube:rerender`, log `~/.local/state/auto-short/rerender-cp814.log`); Short layout cũ backup hard-link ở `~/.cache/auto-short-backup/cp814-prelayout/` (xóa khi HUMAN LEAD hài lòng). `rbjfCfFq3Dk` (đã đăng 11/13) và `X8ao0_7ufto.kt` (1/5) giữ layout cũ — chạy lại sẽ render lại cả tập, tick "Đã đăng" thành stale. Manual test CP8.14 (điện thoại, tài khoản khác) làm trên 8080. CP8.4 upload YouTube: BỎ QUA (HUMAN LEAD 2026-09-27, `AUTO_SHORT_CHECKPOINT_PLAN.md`); Short vẫn tải về và đăng tay. CP8.9 video khai thị (+ A1–A3) đã merge (PR #19, `7e347a3`); dữ liệu web test (tập khai thị `.kt` + Short mới) đã chuyển vào `work/` / `output/` chính, không ghi đè tập có sẵn. CP8.11 nhận dạng tên bộ kinh / số tập + ô "Tên bộ kinh" đã merge (PR #20, `716e858`), manual test HUMAN LEAD đạt 2026-09-28. CP8.10 hàng đợi theo làn prepare / ai / render đã merge (PR #22, `8fa8596`; HUMAN LEAD merge 2026-09-28 khi chưa chạy manual test checklist của contract — kiểm trên web 8080 khi dùng). Dữ liệu chạy thật CP8.10 (`4oOZz2CBz3g`, `4oOZz2CBz3g.kt`, `Irmcm5Ep478`, `E4QhRRXFbIM`) đã chuyển vào `work/` / `output/` chính (không ghi đè, mọi stage `done`). Tập `.kt` làm trước `c76d55e` (`7axON1RpRjo.kt`, `7w4nSj3PguI.kt`, `W2d-xS4ttTw.kt`) có analysis stale: chạy lại sẽ làm lại analysis + selection.

Chinese Learning (CL1, bản đồ: `docs/tasks/CL1-roadmap.md`): CL1.1 MERGED (PR #12); CL1.2 MERGED (PR #15, `38d828f`). G6A (Pinyin authority) và G6B (model dịch): PENDING HUMAN LEAD DECISION — chưa chọn model. CL1.3: PENDING G6A/G6B + C10. CL1.4: PENDING CL1.3.

Web chạy cho HUMAN LEAD trong tmux `youtube:web` từ worktree `../youtube-auto-short-web` (detached, ghim `d0c1517` = CP8.16 đã merge; pane chưa khởi động lại sau khi ghim — không cần: `0eaf1a8` → `d0c1517` chỉ khác docs, `[web] queue_mode` mặc định `lanes`, `PYTHONPATH=<worktree>/src`, `--config` của repo chính → `work/`, `output/`, `models/` repo chính); mật khẩu chỉ qua env của pane, không lưu.

Framework: FW-implementer-speed đã merge (PR #31, `6516638`): `pytest-xdist` (`pytest -q -n auto`), Test policy `docs/ai/project-profile.md` §8, IMPLEMENTER `model: sonnet`. Task S1/S2 kế tiếp kiểm checklist trong `docs/tasks/FW-implementer-speed.md` (transcript IMPLEMENTER = Sonnet; số lần chạy toàn bộ suite ≈ 2–3; review không tăng blocking finding bất thường).

## Next proposed action

1. G6A — thí nghiệm + khuyến nghị chiến lược Pinyin authority (task contract riêng, từ `origin/main` sạch); không đổi production Pinyin trước khi HUMAN LEAD duyệt.
2. Sau G6A: G6B → CL1.3 (+ C10) → CL1.4 theo roadmap.
3. Auto Short tiếp theo:
   - FIX-test-output-dir: đã merge (PR #23; `main` = `d2cfce3`). `output/abcdefghijk/` rác đã xóa ở repo chính.
   - CP8.12 (S1, `docs/tasks/CP8.12-episode-ui.md`): đã merge (PR #25, `33ca2f8`).
   - CP8.13 (S2, `docs/tasks/CP8.13-playlist-groups-loop.md`): đã merge (PR #26, `25f5b59`): nhóm lọc bộ kinh mới (Đang xử lý / Lỗi / dở dang / Đang làm = chỉ tập đã render chưa đăng hết), bỏ link "Khai thị" ở dòng tập, nút "Lặp lại" trên thẻ video.
   - CP8.14 (S2, `docs/tasks/CP8.14-title-layout.md`): đã merge (PR #28, `d623cd3`): layout V16 tránh giao diện YouTube Shorts.
   - CP9 (S2, `docs/tasks/CP9-clip-review.md`): đã merge (PR #30, `e60ab7a`): thêm Short từ đề xuất AI / đoạn chọn trên transcript + sửa điểm đầu/cuối. 8080 đã ghim lên `e60ab7a`; server test 8081 + dữ liệu test đã dọn.
   - CP8.15 (S2, `docs/tasks/CP8.15-community-post.md`): đã merge (PR #35, `2622de8`): bài đăng cộng đồng từ Short. 8080 đã ghim `2622de8`; `config.toml` repo chính có `[post] image_dir = ~/.local/share/auto-short/post-images` (25 ảnh + `sources.tsv`). Manual test checklist của contract: **chưa chạy** — HUMAN LEAD làm trên 8080, ghi kết quả vào Result.
   - CP8.16 (S2, `docs/tasks/CP8.16-post-tab-auto.md`): đã merge (PR #37, `d0c1517`): tab Bài đăng gộp Short + khai thị; tự soạn sau job render + khi mở tab; job soạn bài khóa riêng `<id>#post`; dòng nguồn "HT. Tịnh Không". Manual test HUMAN LEAD trên 8080 2026-09-30: "đã ổn". Worktree `../youtube-auto-short-cp816`, branch và dữ liệu test `~/.cache/auto-short-cp816-test` đã dọn.
   - CP8.17 (S2, `docs/tasks/CP8.17-download-rules.md`, branch `feature/cp8.17-download-rules`, worktree `../youtube-auto-short-cp817`, base `d0c1517`): **DRAFT — chờ HUMAN LEAD duyệt** D1–D5 + câu hỏi mở Q1 (bài không có ảnh: chỉ sao chép có tự tick không; đề xuất có). Nội dung: tự tick "Đã đăng bài" sau "Sao chép bài" + "Tải ảnh" (theo dõi ở trình duyệt); zip cả tập không tick "Đã đăng" (đổi luật CP8.7); tên zip `<bộ kinh>_Tập<N>_Shorts|KhaiThị.zip`; nút "Tải cả hai" (`all.zip`, thư mục `Shorts/`, `KhaiThị/`). Dual-agent, IMPLEMENTER Sonnet.
   - FIX đề xuất: `tests/test_web_lanes_cp810.py::test_lanes_artifacts_identical_to_serial` chập chờn dưới `-n auto` (chạy riêng PASS).
   - FW-starter-kit (S2): session song song, worktree `../youtube-auto-short-fw-kit`; CP8.15 đã merge → không còn ràng buộc file.
   - Re-plan 2026-09-29: "xử lý tất cả" bộ kinh không làm. CP10: đóng (HUMAN LEAD 2026-09-29).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- CP8.17: duyệt contract DRAFT (D1–D5) + Q1 — bài đăng không có ảnh: chỉ "Sao chép bài" có tự tick "Đã đăng bài" không (đề xuất: có).

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
