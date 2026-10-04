# Task: CP8.24 — Văn bản gốc: một trang cho nhiều video (Địa Tạng: 2 video / trang)

## Status / Approval

- Status: READY
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

- Main changes: trường `doc_videos_per_page` (1–10, vắng = 1, k = 1 không lưu) trong `_playlists/<id>.json` (`USER_FIELDS`); `doc.normalize_videos_per_page` / `stored_videos_per_page`; `url_for_episode(url, ep, k)` và `lookup()` dùng trang `ceil(N/k)` giữ độ rộng số 0; `PUT /api/playlists/{id}/doc` nhận thêm `videos_per_page` (vắng = giữ giá trị cũ; xóa link = xóa luôn trường), phản hồi PUT và GET bộ kinh có `doc_videos_per_page`; ô "Số video mỗi trang" trong khối "Văn bản gốc" (`playlist.html`, `app.js`). Cache `doc.json` theo `url` nên đổi k làm cache cũ không dùng. Phản hồi PUT thêm khóa `doc_videos_per_page` nên test chính xác-dict cũ (`test_put_saves_get_returns_null...`) được cập nhật 1 khóa.
- Tests: `python -m pytest -q -n auto` (PYTHONPATH=worktree/src): 1446 passed, 1 skipped (92 s). Test mới: `tests/test_post_doc.py` (AC1, AC2 gồm `_01`/`_1`/`_001`, 101/102 → 51, AC3 validate, AC4 cache theo url), `tests/test_web_post_doc_cp819.py` (AC3 API + lưu / giữ qua refresh / series, UI hooks). `node scripts/framework-check.mjs`: PASS.
- Review: ORCHESTRATOR 2026-10-04 — ACCEPTED, không có blocking finding. Đã kiểm: `ceil(N/k)` giữ độ rộng số 0; vắng / 1 → link như cũ; đổi `k` cùng link → `_recompose_for_doc` soạn lại, cache theo `url`; chạy lại 93 test post doc / playlist PASS. Ghi chú: phương án (a) trong P3 (transcript lại từ HD) không giúp — HD chỉ đổi hình, âm thanh giữ nguyên; quyết định ngưỡng D3 tách thành việc riêng của HUMAN LEAD.
- Important findings / decisions: P3 `match_ratio` (tải trang bằng `fetch_paragraphs`, transcript `work/` chính; `MIN_MATCH` = 0,6, không đổi):

  | Bộ | Tập (video) | k | Trang | match |
  |---|---|---|---|---|
  | Địa Tạng | 1 (`9NQFsvecC04`) | 1 hoặc 2 | _01 | 0,587 |
  | Địa Tạng | 2 (`rBvztHKbNe4`) | 1 | _02 | 0,029 |
  | Địa Tạng | 2 (`rBvztHKbNe4`) | 2 | _01 | 0,608 |
  | Vô Lượng Thọ 10 | 1–5 | 1 | 001–005 | 0,882 / 0,863 / 0,860 / 0,882 / 0,880 |
  | Cảm Ứng Thiên | 1–5 | 1 | 001–005 | 0,810 / 0,856 / 0,666 / 0,837 / 0,670 |
  | Thập Thiện Nghiệp | 1–5 | 1 | 01–05 | 0,908 / 0,891 / 0,890 / 0,909 / 0,901 |

  Chỉ có 2 tập Địa Tạng có transcript trong `work/` (không có tập khác để đo). Bộ 1:1 khớp 0,67–0,91, thấp nhất Cảm Ứng Thiên t3 / t5 (0,67). Địa Tạng t1 = 0,587 dưới ngưỡng 0,6 chỉ 0,013; t2 = 0,608 sát ngưỡng. Nguyên nhân khả dĩ: 1 trang ứng 2 video nên mẫu số (transcript 1 video) chỉ phủ ~một nửa trang cũng không sao, nhưng Whisper trên âm thanh 480p cũ nhiều lỗi. Đề xuất (không tự đổi, HUMAN LEAD quyết): (a) giữ `MIN_MATCH` 0,6 và chạy lại transcript tập 1 bằng nguồn tốt hơn (CP13.2 HD-first) rồi đo lại; hoặc (b) hạ ngưỡng xuống 0,55 riêng cho bộ có `doc_videos_per_page` > 1 (an toàn vì trang sai chỉ 0,03); hoặc (c) hạ ngưỡng chung 0,55 (các bộ 1:1 thấp nhất 0,67 và trang sai ≈ 0,03 nên khoảng cách rất rộng). Hiện tập 1 Địa Tạng dùng cách cũ (AI) cho tới khi chọn.
- Known limitations: nối trang theo thứ tự tập cố định (k hằng số cho cả bộ); không dò tự động; ngưỡng chưa đổi nên tập 1 Địa Tạng chưa dùng văn bản gốc.
- PR: #64
