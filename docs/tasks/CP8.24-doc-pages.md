# Task: CP8.24 — Văn bản gốc: một trang cho nhiều video (Địa Tạng: 2 video / trang)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `0e8a2a2` (`main`, sau CP13.2 + CP8.23) / `feature/cp8.24-doc-pages` (worktree `../youtube-auto-short-docpg`)
- Human Lead approval: APPROVED 2026-10-04 (HUMAN LEAD gửi link biên tập Địa Tạng: "Mỗi tập tương ứng 2 video bài giảng và theo thứ tự"; ORCHESTRATOR đề xuất cách nối cùng ngày, phạm vi ghi dưới đây)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: mở rộng tính năng văn bản gốc CP8.19 trong khuôn đã duyệt (link tập N suy từ `doc_url` của bộ kinh, D1); thêm một trường tùy chọn của bộ kinh, mặc định giữ hành vi cũ; không đổi dependency, security model, public API.

## Bối cảnh (đo 2026-10-04, ORCHESTRATOR)

- Biên tập Địa Tạng: `https://ph.tinhtong.vn/Home/DiaTangBoTatBonNguyenKinhGiangKy?d=DiaTangBoTatBonNguyenKinhGiangKy_01.html`. Trang `_NN` ứng với **2 video liên tiếp** (video 2N−1, 2N).
- `post/doc.py` D1 hiện 1 video = 1 trang (`url_for_episode`: số tập → `_NN`, giữ độ rộng số 0).
- Đo `match_ratio` (D3, ngưỡng `MIN_MATCH = 0,6`): trang `_01` với video tập 1 `9NQFsvecC04` = **0,59**, tập 2 `rBvztHKbNe4` = **0,61**; trang `_02` với cả hai = 0,03. → Nối đúng, nhưng tập 1 sát dưới ngưỡng (Whisper trên âm thanh cũ 480p).

## Goal

Bộ kinh có thể khai báo "số video mỗi trang văn bản" (mặc định 1). Với Địa Tạng = 2: video tập N dùng trang `ceil(N / 2)`; bài đăng (CP8.19) của tập 1 và 2 đều lấy từ `_01`, tập 3 và 4 từ `_02`, …

## Scope

- In scope:
  - **P1** Trường mới trong `_playlists/<id>.json` (ví dụ `doc_videos_per_page`, số nguyên 1–10, mặc định 1 / vắng = 1); setter + validate như `set_doc_url`; ô nhập cạnh "Link văn bản gốc" trên trang bộ kinh.
  - **P2** `lookup()` / `url_for_episode()` dùng trường này: trang = `ceil(N / k)`; giữ độ rộng số 0. Cache `doc.json` đổi khi link đổi (đã có: so `url`).
  - **P3** Ngưỡng match khi một trang ứng nhiều video: đo `match_ratio` trên các tập Địa Tạng đã có transcript (ít nhất tập 1, 2 và vài tập khác nếu có) và các bộ 1:1 hiện có; nếu cần, đề xuất (không tự đổi) cách xử lý tập sát ngưỡng như tập 1 (0,59) — ghi vào Result để HUMAN LEAD quyết; không đổi `MIN_MATCH` trong task này.
  - Test + cập nhật hướng dẫn nếu có mô tả ô "Link văn bản gốc".
- Out of scope: đổi D3 / D4 / D5 (ngưỡng, căn, mở rộng câu); title / điểm cắt từ văn bản (CP8.20 đã quyết không đổi); tự dò số video / trang.

## Authority / key decisions

- `docs/tasks/CP8.19-post-doc-source.md` (D1–D5), `docs/decisions/CP8.15-community-post-contract.md` P15.
- Mặc định 1 → mọi bộ hiện có không đổi (link, cache, bài đăng giống hệt).

## Acceptance Criteria

1. Bộ kinh không có trường mới: link mọi tập giống hệt trước (test hiện có PASS, thêm test không đổi).
2. `k = 2`: tập 1, 2 → `_01`; 3, 4 → `_02`; 101, 102 → `_51`; giữ độ rộng số 0 (`_1` → `_51`, `_001` → `_051`).
3. Giá trị không hợp lệ (0, âm, chữ, > 10) bị từ chối với thông báo rõ; UI lưu / hiện đúng.
4. Đổi `k` làm link tập đổi → `doc.json` cũ không được dùng (theo `url`).
5. Bảng `match_ratio` P3 trong Result.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–4.
- Script đo P3 (đọc `work/` chính chỉ đọc; tải trang qua `fetch_paragraphs`) — AC 5.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080:

- [ ] Bộ Địa Tạng: dán link `_01`, đặt "2 video / trang"; tab Bài đăng của tập 1, 2 lấy chữ từ trang `_01`.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
