# Task: CP8.32 — Bản dọc / bản ngang HD từ video gốc ≥ 720p + nút "Tạo bản dọc cả bộ"

## Status / Approval

- Status: APPROVED
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

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
