# Task: PUB2S — PUB2 gắn thumbnail "TRÍCH ĐOẠN" cho Short trên YouTube

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-03 "viết contract cho short và làm thử trên 1-2 video" (kênh Tín Nguyện Trì Danh, Địa Tạng, "chỉ gắn khai thị và short từ T9 trở về trước")
- Parallel group: —
- Owned paths: `src/auto_short/publish/__main__.py`, `src/auto_short/publish/kt.py`, `src/auto_short/publish/shorts.py` (mới, nếu tách), `src/auto_short/publish/thumbs.py` (chỉ nhật ký / apply nếu cần), `src/auto_short/packaging/khaithi_thumbs.py` (chỉ thêm hàm vẽ ảnh Short từ tiêu đề cho trước, tái dùng `draw`), `tests/test_publish_kt.py`, `tests/test_publish_shorts.py` (mới), `tests/test_publish_thumbs.py`, `docs/decisions/PUB2-youtube-thumbnail-set.md`, file này
- Dependencies: PUB2K (đã merge, `kt-thumbs`); KTI2 (ảnh Short "TRÍCH ĐOẠN", đã merge)
- Base commit / branch: `385a112` / `feature/pub2s-short-thumbs` (worktree `~/projects/yas-pub2s`)
- Human Lead approval: accepted 2026-11-03 ("ok theo đề xuất": G2 = 1, G3 = 2)
- Implementation authorized: YES

## Bằng chứng đọc thật (2026-11-03, chỉ đọc, client `auto-short-tntd`)

- Kênh Tín Nguyện Trì Danh (`youtube-tokens/tin-nguyen-tri-danh.json`): 202 video = 76 KT (`T<N>_KT<NN>`) + 126 Short, **mọi Short có mã** ở tên file gốc / tiêu đề: `T9_S10_Không cần qua trời, có thể thành A-la-hán ngay.mp4` ↔ tiêu đề `T9 S10 Không cần qua trời, …`.
- Số Short theo tập: T1 6, T2 8, T3 10, T4 8, T5 6, T6 10, T7 9, T8 10, T9 10 (**T1–T9: 77**), T10 4, T11 18, T12 7, T14 9, T15 11.
- Web: Short Địa Tạng **T1–T9 không có trên web** (kho 3090 chỉ có `[KhaiThi]` cho T9; `work/<id>` không có Short) → không có tiêu đề / ảnh "TRÍCH ĐOẠN" phía web. Từ T10: có Short web (`[Short] … - Tập 10 - k01..k09`) và ảnh KTI2 `output/<id>/short_intro_thumbs/` (`clip_numbers` k01→1 …); 55 tập Địa Tạng có ảnh này.
- `episode.header(config, <id>)` chạy được cho T9 (PUB2K dùng) → có số tập / bộ kinh / giảng sư để vẽ.
- Chưa biết: YouTube có hiện thumbnail gắn qua API cho Short ở **feed Shorts** hay chỉ ở trang kênh / tìm kiếm / playlist / tab Đăng ký → đo bằng chạy thử (AC6).

## Goal

```text
python -m auto_short.publish short-thumbs --playlist <pid nguồn> [--yt-playlist <id> | (mặc định: video tải lên của kênh)] \
    --client … --token … [--episodes 1-9] [--only <youtube_id>,…] [--apply] [--force]
```

lập bảng Short YouTube → ảnh "TRÍCH ĐOẠN" dọc; `--apply` gắn. Chạy thử 1–2 Short T9 trước, HUMAN LEAD xem trên điện thoại rồi mới chạy phần còn lại T1–T9.

## Scope

- In scope:
  - Lệnh con `short-thumbs` (cùng `--config/--client/--token`, `apply` kiểm sha256 / 2 MB, nhật ký `work/_publish/thumbs.json`, `--force` như `kt-thumbs`). Thêm `--episodes A-B` và `--only id,…` (lọc sau khi lập bảng; dùng chung cho `kt-thumbs` nếu gọn).
  - Ghép: mã `T<N>[ _]S<NN>` ở đầu tên file gốc (ưu tiên) hoặc tiêu đề; tên file và tiêu đề lệch mã → bỏ qua. Tập N → đúng một tập trong playlist nguồn.
  - Nguồn ảnh (G2):
    - (a) Tập có Short web + ảnh KTI2 hợp lệ cho clip số NN → dùng ảnh đó.
    - (b) Tập không có Short web (T1–T9 Địa Tạng) → vẽ ảnh "TRÍCH ĐOẠN" dọc bằng layout KTI2 (`khaithi_thumbs.draw`, bìa `kt_vertical`, chân dung theo tập, nhãn `SHORT_LABEL`) với **tiêu đề lấy từ tên file / tiêu đề YouTube sau mã** (bỏ `T9_S10_`, đuôi `.mp4`, hashtag). Ghi vào thư mục riêng `output/<id>/short_yt_thumbs/` (cache theo khóa như KTI2), không đụng `short_intro_thumbs`.
  - Bảng in: video YouTube, mã, nguồn ảnh (web / YouTube-title), ảnh, trạng thái / lý do.
- Out of scope: Short không mã; sửa / tạo Short; upload; đổi mẫu ảnh theo vùng an toàn 4:5 (task riêng sau khi HUMAN LEAD xem ảnh dọc); kênh khác (lệnh dùng được cho mọi kênh, nhưng chỉ chạy Tín Nguyện trong task này); route web.

## Authority / key decisions

- Sửa decision `docs/decisions/PUB2-youtube-thumbnail-set.md` (HUMAN LEAD duyệt cùng contract):
  - G1: thêm lệnh `short-thumbs` (cùng API `thumbnails.set`, cùng scope).
  - **G2 = 1 (HUMAN LEAD 2026-11-03)**: Short không có trên web lấy tiêu đề từ YouTube để vẽ ảnh "TRÍCH ĐOẠN" (nguồn (b)).
  - **G3 = 2 (HUMAN LEAD 2026-11-03)**: chạy thử (AC6) bằng mẫu "TRÍCH ĐOẠN" KTI2 hiện tại; gắn hàng loạt chờ task vùng an toàn 4:5 sửa mẫu.
  - Hạn mức: project `auto-short-tntd` riêng cho kênh Tín Nguyện; 100 thumbnail / kênh / ngày (đã gắn 58 KT hôm nay → Short hàng loạt chạy ngày sau, chia ≤ 100 / ngày).

## Implementation approach

- Tách phần chung của `kt.plan` (ghép mã → tập, đọc video) để `shorts.plan` dùng lại; regex mã Short riêng.
- Vẽ ảnh (b): hàm mới trong `khaithi_thumbs` nhận `title` + `fields` + `pid`, gọi `draw(..., label=SHORT_LABEL)`; khóa cache = `cache_key(...)` như `vertical_clip`.
- `--episodes` / `--only` lọc hàng trước `apply`; mặc định không lọc (giữ hành vi `kt-thumbs`).

## Phải giữ nguyên

- `thumbs` / `kt-thumbs` hiện có: bảng, ghép, nhật ký, `--force`.
- Ảnh KTI2 `short_intro_thumbs` và video Short trên web không bị sửa.

## Code bị thay / xóa

- Không có (chỉ thêm; tách hàm chung trong `kt.py` nếu cần, không giữ bản trùng).

## Acceptance Criteria

1. `short-thumbs` chạy thử (không `--apply`) trên kênh Tín Nguyện, pid Địa Tạng, `--episodes 1-9`: 77 dòng, mỗi dòng có ảnh nguồn (b) hoặc lý do bỏ qua; không gọi `thumbnails.set`.
2. Ghép mã: `T9_S10_…` → tập 9; tên file / tiêu đề lệch mã → bỏ qua có lý do; không mã → bỏ qua.
3. Ảnh (b): JPEG dọc 1080×1920 ≤ 2 MB, nhãn "TRÍCH ĐOẠN", tiêu đề đúng (không còn `T9_S10_`), chạy lại không vẽ lại (cache).
4. Tập có Short web (T10+) dùng đúng ảnh KTI2 của clip số NN (test bằng fixture).
5. `--only` / `--episodes` lọc đúng; `--apply` ghi nhật ký có `clip_id`/mã; chạy lại bỏ qua video đã gắn cùng sha (trừ `--force`).
6. Chạy thật: `--apply --only` 2 Short T9 (đề xuất `T9 S10`, `T9 S09`) → HUMAN LEAD xem trên điện thoại: trang kênh, tab Shorts của kênh, feed Shorts, tab Đăng ký, playlist; ghi kết quả vào Result. Phần còn lại T1–T9 chỉ chạy sau khi HUMAN LEAD đồng ý.

## Required verification

- `pytest -q tests/test_publish_shorts.py tests/test_publish_kt.py tests/test_publish_thumbs.py` — AC1–5 (YouTube giả lập).
- Full suite (ORCHESTRATOR, ngoài sandbox).
- Chạy thử thật (chỉ đọc) AC1; xem 2–3 ảnh (b) mẫu (gửi HUMAN LEAD) trước AC6.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API của app (chỉ gọi YouTube Data API như PUB2). Manual test = AC6 trên điện thoại.

- [ ] 2 Short T9 hiện ảnh "TRÍCH ĐOẠN" ở trang kênh / tìm kiếm
- [ ] Feed Shorts / tab Shorts của kênh: ghi nhận hiện hay không
- [ ] Tab Đăng ký (khung ~4:5): chữ có bị cắt không

## Result

- Main changes:
