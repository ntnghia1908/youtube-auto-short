# Task: PKG3 — Thumbnail video ghép chủ đề theo kiểu A / B / C (tuyển tập khai thị)

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, test web / full suite, dựng thật 3 video ghép, xem trang trên 8080
- Implementer: claude-code `implementer` (Sonnet) — việc có UI + test web (Codex sandbox không chạy test web); Codex đang làm PUB2 song song
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` (PKG1 thumbnail, G5) + HUMAN LEAD 2026-10-24 xem mẫu: "Mẫu ổn nhưng ghi tuyển tập khai thị và thêm tên bộ kinh", "Lấy cả 3" (kiểu A / B / C), muốn đổi được nền và màu
- Parallel group: PKG-2026-10-24b (song song PUB2; owned paths rời nhau, worktree riêng)
- Owned paths: `src/auto_short/packaging/thumbnail.py`, `src/auto_short/packaging/record.py`, `src/auto_short/web/packaging.py`, `src/auto_short/web/static/package.html`, `src/auto_short/web/static/package.js`, `tests/test_packaging_thumbnail.py`, `tests/test_web_packaging.py`, contract này. **Không** sửa `packaging/episode.py`, `tests/test_packaging_episode.py`, `tests/test_web_episode_thumbs.py` (PR #138 đang sửa).
- Dependencies: —
- Base commit / branch: `fe82caf` (main) / `feature/pkg3-khaithi-thumbs`
- Human Lead approval: HUMAN LEAD 2026-10-24 (chọn mẫu)
- Implementation authorized: YES

## Goal

Trang Đóng gói của một video ghép (TC3) dựng thumbnail theo **kiểu A / B / C** của thumbnail tập (PKG2) thay cho 3 mẫu PKG1 classic / minimal / scenic. Mỗi kiểu có bản **16:9 1280×720** và **9:16 1080×1920**. Chữ: 3 dòng tiêu đề (mặc định dòng 1 "Tuyển tập khai thị"), tên bộ kinh, tên người giảng, khung **thời lượng** ("21 PHÚT"; kiểu C "21 phút") thay cho "TẬP N". Kiểu A chọn được **bảng màu** và **nền** (màu trơn / ảnh mờ toàn khung). HUMAN LEAD chọn một kiểu, duyệt, tải về như PKG1.

## Scope

- In scope: vẽ (tái dùng code kiểu A / B / C), bản ghi package, API + trang Đóng gói (chọn kiểu, sửa 3 dòng, bảng màu / nền kiểu A, ảnh, vị trí ảnh), duyệt / tải.
- Out of scope: thumbnail tập (PKG2) — **ảnh tập phải giữ nguyên từng byte**; bảng màu / nền cho thumbnail tập; AI sinh chữ; màu tự do (chỉ bảng màu có sẵn); upload YouTube.

## Authority / key decisions

- Kiểu, chữ, khung: như mẫu HUMAN LEAD xem 2026-10-24 (`styleABC_mock.py` / `styleA_palettes.py` của ORCHESTRATOR — xem "Implementation approach").
- Bảng màu kiểu A (id → nền gốc rgb, quầng sáng rgb, gradient chữ vàng c0 / c1, nền khung): `nau-vang` (mặc định, = kiểu A hiện tại) `(22,16,11)` `(70,45,18)` `0xfff3b0` `0xb8862b` `0xb3261e`; `xanh-ngoc` `(6,22,24)` `(18,70,66)` `0xfff3b0` `0xb8862b` `0x8a1c14`; `do-son` `(34,6,6)` `(110,28,18)` `0xfff6c8` `0xd09a3a` `0x5a0d0a`; `xanh-dem` `(8,12,30)` `(28,46,104)` `0xfff3b0` `0xb8862b` `0xb3261e`. Nền `blur`: ảnh đã chọn scale + crop toàn khung, `boxblur=30:3`, `eq=brightness=-0.32:saturation=0.6`, trộn dưới nền màu với độ mờ 0.75 (như mẫu số 5).
- Mặc định bản ghi mới: kiểu `A`, bảng màu `nau-vang`, nền `plain`, dòng 1 "Tuyển tập khai thị", dòng 2 = nhãn chủ đề (`plan.theme.label`), dòng 3 rỗng (bố cục 2 dòng tiêu đề như PKG2), tên bộ kinh = `series` của playlist (in hoa ở A / B), người giảng = `theme_plan.speaker_for_clips` (mặc định "Hòa Thượng Tịnh Không" nếu rỗng), thời lượng = `round(duration_TC3 / 60)` phút (tối thiểu 1).
- Bản ghi package hiện chưa có trên máy (`output/_compilations/*/theme/pkg/` trống) → được đổi schema (`schema_version` 2); bản ghi v1 (nếu có) coi như chưa dựng (đọc không lỗi trang, dựng lại tạo v2).

## Implementation approach

- `thumbnail.py`: tách phần vẽ A / B / C dùng chung cho tập và video ghép, tham số hóa (chữ khung, dòng ghi công thứ hai, bảng màu, nền). Mặc định = hành vi hiện tại → `build_episode` / `episode_text` / `cache_key` của tập cho **đúng cùng filtergraph** (test so sánh filtergraph script hoặc bytes với bản trước refactor cho cả 3 kiểu × 2 khuôn). Bỏ `TEMPLATES` classic / minimal / scenic và `_graph` PKG1 nếu không còn dùng.
- Dàn dòng: 2 dòng ghi công + khung không chồng nhau ở cả 3 kiểu × 2 khuôn (mẫu kiểu B ngang bị chồng — phải sửa); kiểm bằng hộp chữ đo được (giống test baseline / ink bounds của PKG2).
- `record.py` v2: các trường settings ở trên + mỗi kiểu một entry có file / key / sha256 cho từng khuôn; `selected` ∈ {A, B, C}; cache key gồm tc3_sha256, kiểu, khuôn, settings, asset sha, layout version, font sha.
- `web/packaging.py` + `package.html` / `package.js`: thay khu chọn 3 mẫu bằng chọn A / B / C (ảnh xem trước cả 2 khuôn), ô 3 dòng tiêu đề, chọn bảng màu + nền (chỉ hiện khi kiểu A), giữ chọn ảnh / duyệt / tải; tải về cho cả 2 khuôn của kiểu đã duyệt.
- Mẫu tham khảo của ORCHESTRATOR (đã chạy được): `/home/ntnghia/.claude/jobs/1c1feb65/tmp/styleA_palettes.py`, `/home/ntnghia/.claude/jobs/1c1feb65/tmp/styleABC_mock.py`.

## Phải giữ nguyên

- Thumbnail tập PKG2: cache key, file, filtergraph, test PKG2 / PKG2.1 pass không sửa.
- Luồng TC3 → package: kiểm plan / fingerprint / sha, state draft / approved / stale, variant VIS1 / AUD1, route hiện có (đổi payload thumbnail là chấp nhận được, route không bỏ).
- Chữ không vào filtergraph (textfile, expansion none).

## Code bị thay / xóa

- `thumbnail.TEMPLATES` (classic / minimal / scenic), `thumbnail.fit`, `thumbnail._graph`, `thumbnail.build` / `ready` / `key` bản PKG1 và test tương ứng trong `tests/test_packaging_thumbnail.py`, `tests/test_web_packaging.py` → thay bằng bản A / B / C.

## Acceptance Criteria

1. Video ghép dựng được 3 kiểu × 2 khuôn với chữ: 3 dòng (dòng 3 tùy chọn), tên bộ kinh, người giảng, "N PHÚT" / "N phút"; không dòng nào chồng nhau hay tràn khung (đo ink bounds) ở cả 6 tổ hợp.
2. Kiểu A: 4 bảng màu + nền plain / blur ra ảnh khác nhau, đổi bảng màu chỉ dựng lại kiểu A; dựng lại cùng settings không gọi ffmpeg.
3. Thumbnail tập PKG2: filtergraph / cache key của cả 3 kiểu × 2 khuôn giống bản trước refactor; test PKG2 / PKG2.1 hiện có pass không sửa.
4. API / trang: sửa 3 dòng, chọn kiểu / bảng màu / nền / ảnh, dựng, xem trước, duyệt, tải 2 khuôn của kiểu đã duyệt; settings không hợp lệ (bảng màu lạ, dòng quá dài, không vừa) bị từ chối trước ffmpeg.
5. Chạy thật 3 video ghép của `PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa` (bddcede7d89d-r2, d6a874b50e91-r1, 1ec7a733a281 nếu có TC3): đủ 3 kiểu × 2 khuôn, ORCHESTRATOR gửi ảnh cho HUMAN LEAD.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_packaging_thumbnail.py tests/test_web_packaging.py tests/test_packaging_episode.py tests/test_web_episode_thumbs.py -q` — AC1–AC4.
- Full suite (ORCHESTRATOR).
- AC5 chạy thật + xem trang trên 8080 (ORCHESTRATOR).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model; đổi payload API nội bộ của trang Đóng gói (không phải public API ngoài) → manual test là điểm danh.

- [ ] Trang Đóng gói một video ghép: đổi kiểu / bảng màu / nền / chữ, dựng, duyệt, tải.

## Result

- Main changes:
