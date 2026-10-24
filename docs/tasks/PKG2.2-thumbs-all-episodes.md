# Task: PKG2.2 — Thumbnail cho mọi tập của bộ kinh (không cần video trên VM)

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + test web / full suite + dựng thật cả bộ Địa Tạng
- Implementer: claude-code `implementer` (Sonnet) — Codex cửa sổ 5 giờ 93 % (≥ 85 %, `scripts/codex-usage.py` 13:27 UTC)
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` G8 (HUMAN LEAD duyệt 2026-10-24: "Tôi duyệt a")
- Parallel group: —
- Owned paths: `src/auto_short/packaging/episode.py`, `src/auto_short/web/episode_thumbs.py`, `src/auto_short/web/static/thumbs.html`, `src/auto_short/web/static/thumbs.js`, `tests/test_packaging_episode.py`, `tests/test_web_episode_thumbs.py`, `docs/decisions/PKG-video-packaging-authorization.md` (dòng G8), contract này
- Dependencies: PKG2 (#132), PKG2.1 (#134) đã merge
- Base commit / branch: `fe82caf` (main) / `fix/pkg2-thumbs-deleted-episodes`
- Human Lead approval: inherited from boundary (G8)
- Implementation authorized: YES

## Goal

Kinh Địa Tạng (102 tập) đã backup bản HD ngang + bản dọc nguyên tập sang máy 3090 (`kdt-backup.ps1`); tập 1–9 đã xóa trên VM, nhiều tập không có bản dọc trên VM. Bấm "Thumbnail cả bộ" phải ra ảnh 16:9 **và** 9:16 cho mọi tập có header hợp lệ (tên bộ kinh + số tập), không phụ thuộc file video trên VM.

## Scope

- In scope: điều kiện dựng thumbnail tập (`episode.shapes` / `context`); trang thumbs không còn lý do bỏ qua "chưa có bản ngang HD hoặc bản dọc hoàn chỉnh"; test.
- Out of scope: đổi kiểu A/B/C, cache key, chữ, ảnh; upload YouTube; script backup trên 3090 (ops, ngoài repo); thumbnail video ghép chủ đề (PKG1).

## Authority / key decisions

- G8: thumbnail tập không phụ thuộc video; mọi tập header hợp lệ → cả hai khuôn.
- Header vẫn theo `episode.header` hiện có (`titles.json` ở `<id>/` hoặc `<id>.kt/`, rồi playlist). Header lỗi → vẫn bỏ qua với lý do hiện có.

## Implementation approach

- `context` luôn trả cả hai khuôn (`thumbnail.EPISODE_SIZES` theo thứ tự landscape, vertical); bỏ kiểm tra HD / bản dọc. Giữ kiểm tra symlink ở những đường dẫn vẫn còn đọc.
- Cache key không đổi → ảnh đã dựng được tái dùng, chỉ dựng thêm khuôn còn thiếu.
- Trang thumbs: chữ / chú thích nào nói thumbnail cần bản HD / bản dọc thì sửa cho đúng (nếu có).

## Phải giữ nguyên

- Cache key, tên file `landscape-<key>.jpg` / `vertical-<key>.jpg`, `thumbs.json`, zip `T###_ngang.jpg` / `T###_doc.jpg`, URL `/files/episodes/<id>/thumbs/landscape.jpg|vertical.jpg`.
- `valid_files` vẫn kiểm header, asset, key, sha256.
- Tập trùng lặp trong playlist, lỗi từng tập được cô lập như cũ.

## Code bị thay / xóa

- `episode.shapes()` (kiểm tra HD qua `enhance_state.effective_source` + `full.ready_file`) và thông báo "chưa có bản ngang HD hoặc bản dọc hoàn chỉnh"; import không còn dùng.
- Test điều kiện cũ: `test_hd_eligibility_uses_completed_enhance_or_high_resolution_original`, các assert `shapes` trong `test_header_kt_and_playlist_fallback_and_vertical_without_source` → thay bằng test G8.

## Acceptance Criteria

1. Tập có header hợp lệ nhưng không có `work/<id>/` source / `source_hd.mp4` / `output/<id>/full/vertical.mp4` (chỉ còn `work/<id>.kt/titles.json`) → `build_playlist` dựng cả `landscape` và `vertical`, `valid_files` trả cả hai.
2. Tập đã có ảnh landscape (cùng key) → không gọi lại ffmpeg cho landscape; chỉ dựng vertical.
3. Header thiếu tên bộ kinh / số tập → vẫn bỏ qua với lý do header như cũ.
4. Trang / API thumbs: tập ở AC1 có `files` đủ hai khuôn, zip có `T###_ngang.jpg` và `T###_doc.jpg`.
5. Chạy thật trên bộ Địa Tạng (`PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`): 102 / 102 tập có cả hai ảnh (trừ tập header lỗi, nếu có, ghi rõ).

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_packaging_episode.py tests/test_web_episode_thumbs.py -q` — AC1–AC4.
- Full suite (ORCHESTRATOR) — không hồi quy.
- AC5: ORCHESTRATOR chạy `episode.build_playlist` thật (hoặc nút trên 8080) và đếm.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract (route giữ nguyên) → manual test là điểm danh.

- [ ] Trang (sau khi 8080 chạy code này) `/playlists/PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4/thumbs`: tập 1–9 có ảnh ngang + dọc.

## Result

- Main changes: `episode.shapes()` (điều kiện HD / bản dọc) bị xóa; `context()` luôn trả cả `landscape` + `vertical`; cache key / tên file / zip / URL giữ nguyên. Test: thay test điều kiện cũ bằng test G8 (AC1–AC4, preview khi tập đầu không có video); cập nhật số lần ffmpeg / số file trong các test cũ vì tập fixture không có bản dọc giờ có cả hai khuôn. +107 / −60 dòng.
- Verification: `tests/test_packaging_episode.py` + `tests/test_web_episode_thumbs.py` 99 passed (IMPLEMENTER); full suite `python -m pytest -q -n auto` 2449 passed, 1 skipped (ORCHESTRATOR, 2026-10-24).
- AC5 chạy thật 2026-10-24 (`episode.build_playlist`, bộ `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`): 61 tập dựng mới, 41 tái dùng, 0 bỏ qua; 102 / 102 tập có cả ảnh ngang + dọc hợp lệ (tập 1–9 đã xóa video trên VM vẫn có, header từ `<id>.kt/titles.json`).
- IMPLEMENTER: Sonnet subagent ≈ 3 phút, 58k tokens, 0 vòng sửa.
