# Task: PKG2 — Thumbnail cho tập (bản ngang HD + bản dọc), cả bộ kinh

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + test web / full suite + chạy thật trên bộ Địa Tạng
- Implementer: codex — mở rộng module PKG1 vừa viết, spec rõ (project-profile §7)
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` G7 (HUMAN LEAD 2026-10-24: ưu tiên trước VIS1)
- Parallel group: —
- Owned paths: `src/auto_short/packaging/episode.py` (mới), mở rộng `packaging/thumbnail.py` (bố cục tập 16:9 + 9:16, không đổi 3 template PKG1), `src/auto_short/web/episode_thumbs.py` (mới), `src/auto_short/web/static/thumbs.html` + `thumbs.js` (mới), sửa nhỏ: `web/app.py` (đăng ký), `web/static/playlist.html` / `app.js` (nút "Thumbnail cả bộ" trên trang bộ kinh, link tải ở trang tập), `tests/test_packaging_episode.py`, `tests/test_web_episode_thumbs.py`, contract này, module map `docs/ai/project-profile.md`
- Dependencies: PKG1 (cùng branch `feature/pkg1-thumbnail`, tuần tự, một writer)
- Base commit / branch: commit PKG1 READY trên `feature/pkg1-thumbnail`
- Human Lead approval: inherited from boundary (G7)
- Implementation authorized: YES

## Goal

Trên trang bộ kinh (ví dụ Kinh Địa Tạng, 102 tập), HUMAN LEAD bấm "Thumbnail cả bộ": hệ thống dựng thumbnail cho mọi tập có bản ngang HD và / hoặc bản dọc, hiện lưới để xem, cho đổi ảnh từng tập, rồi tải một file zip để upload tay.

## Scope

- In scope:
  - **Tập đủ điều kiện**: tập của playlist có bản ngang HD (`work/<id>/source_hd.mp4`, cùng điều kiện tải "bản ngang HD" hiện có) → thumbnail **16:9 1280×720**; tập có bản dọc hoàn chỉnh (`render.full.read_meta` / file hợp lệ) → thêm thumbnail **9:16 1080×1920**. Bản dọc dùng chung file 16:9 của tập (HUMAN LEAD chọn "cả 9:16 và 16:9").
  - **Chữ** (HUMAN LEAD chọn kiểu "Kinh Địa Tạng — Tập N", không AI, không gõ tay): tên bộ kinh + số tập + người giảng lấy deterministic từ header tập — `titles.json` `header.fields` nếu có, nếu không thì `titling.logic.resolve_header` (+ `titling.playlist.playlist_header`, "Tên bộ kinh" CP8.11) trên `metadata.json`. Không có số tập → tập bị bỏ qua, ghi lý do.
  - **Bố cục tập** (version hóa, `EPISODE_LAYOUT_VERSION`): dòng tên bộ kinh (vừa, ≤ 2 dòng), "TẬP N" (rất lớn), dòng người giảng (nhỏ); ảnh người giảng chiếm một bên (16:9) hoặc nửa dưới (9:16); nền màu ấm theo style. Dùng `render/text.py` + font ExtraBold + filtergraph ffmpeg như PKG1 (textfile, `expansion=none`). JPEG ≤ 2 MB.
  - **Ảnh khác nhau giữa các tập**: chọn deterministic từ asset `image` đã duyệt (sắp theo id) bằng `episode_number mod n`; HUMAN LEAD đổi ảnh một tập trên lưới (ghi override). Không có asset duyệt → nền gradient, vẫn dựng được.
  - **Lưu**: `output/<episode_id>/thumbs/` gồm `landscape-<key>.jpg`, `vertical-<key>.jpg`, `thumbs.json` (schema_version, header dùng, asset_id, override, key, sha256, updated_at). Key = hash(chữ, asset sha, layout version, font sha, khuôn). Dựng lại cùng key → không gọi ffmpeg. Header / ảnh đổi → key mới, file cũ bị thay.
  - **Web**: nút "Thumbnail cả bộ" trên trang bộ kinh → một job `episode_thumbs` (làn render, key theo playlist, khóa trùng); trang `/playlists/{pid}/thumbs` hiện lưới (tập, ảnh xem trước 16:9 / 9:16, nút đổi ảnh, trạng thái bỏ qua + lý do); `GET /files/playlists/{pid}/thumbs.zip` (tên trong zip `T<tập 3 số>_ngang.jpg`, `T<tập>_doc.jpg`, theo quy ước tên `T<tập>` CP8.21), tải từng file ở trang tập.
- Out of scope: chữ theo chủ đề / AI; nhiều template cho tập; thumbnail Short / khai thị 4–7 phút; upload YouTube; duyệt từng tập (lưới + zip là bước HUMAN LEAD xem, G7).

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` R3 (thư mục output khác — xem G7), R5, R7, R8, R9, G2, G4, G7.
- Header: `docs/decisions/CP6-titling-contract.md` (header deterministic), CP8.11 "Tên bộ kinh"; bản dọc: `render/full.py` (CP8.32).

## Implementation approach

- `packaging/episode.py`: liệt kê tập đủ điều kiện, tính header, chọn asset, dựng + cache, ghi `thumbs.json`; dùng runner tiêm được.
- `thumbnail.py`: thêm hàm dựng bố cục tập cho cả hai khuôn, tách phần dùng chung (copy font / textfile / vòng chất lượng JPEG) thay vì chép lại.
- Web theo mẫu `web/packaging.py` (lưu ý thứ tự `safe()` rồi mới gắn URL, như bản sửa PKG1).

## Phải giữ nguyên

- `source_hd.mp4`, `full/vertical.mp4|json`, `titles.json`, layout Short / bản dọc; 3 template PKG1 và route PKG1.
- Dọn / archive tập (CP8.6): xóa tập vẫn xóa `output/<id>/` như cũ (thumbnail đi theo).

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Tập có HD → 1 JPEG 1280×720; tập có bản dọc → thêm 1 JPEG 1080×1920; chữ tiếng Việt có dấu đúng (tên bộ dài như "Kinh Địa Tạng Bồ Tát Bổn Nguyện" vừa ≤ 2 dòng, "TẬP 102").
2. Tập không có header / số tập hoặc không có HD lẫn bản dọc → bỏ qua kèm lý do, job vẫn xong các tập khác.
3. Hai tập liên tiếp dùng ảnh khác nhau khi kho có ≥ 2 ảnh duyệt; đổi ảnh một tập chỉ dựng lại tập đó.
4. Chạy lại cả bộ không đổi gì → 0 lần gọi ffmpeg.
5. Zip chứa đúng các file hợp lệ với tên `T<NNN>_ngang.jpg` / `T<NNN>_doc.jpg`; file hỏng / sha lệch không vào zip.
6. Lỗi ffmpeg một tập không để file dở, không đụng file khác; route kiểm id / tên (không traversal), cần đăng nhập.

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py`
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs` (ORCHESTRATOR).
- Chạy thật trên bản sao danh sách Địa Tạng (output vào thư mục tạm): dựng vài tập 16:9 + 9:16, gửi HUMAN LEAD xem (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Chạm public API (route mới sau đăng nhập), không chạm security model / database.

- [ ] Trên 8080 ghim commit branch: "Thumbnail cả bộ" Địa Tạng, xem lưới, đổi ảnh 1 tập, tải zip.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
