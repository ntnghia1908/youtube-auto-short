# Task: VSAFE1 — Mẫu ảnh dọc an toàn 4:5 + 4 màu xoay theo tập (thumbnail + intro 3 s)

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-03: xem mẫu thử 4:5 → "Ok vậy được rồi"; "KT thì áp dụng hết", KT mới dùng dọc, "111 ảnh Người dân cực lạc bỏ mẫu ngang áp dụng mẫu mới luôn. Tín nguyện dùng mẫu mới luôn"; Short "gắn 2 ngày trước về sau này thôi"; màu: "lấy bộ 4 màu ở trên" (bộ 4 màu theo bộ kinh, không phải bảng 10 màu); "Dựng lại intro 3s luôn"
- Parallel group: —
- Owned paths: `src/auto_short/packaging/khaithi_thumbs.py`, `src/auto_short/packaging/cover.py` (chỉ phần dựng nền / box / chân dung cho `kt_vertical`), `src/auto_short/publish/youtube.py` (đọc ngày đăng), `src/auto_short/publish/shorts.py`, `src/auto_short/publish/kt.py`, `src/auto_short/publish/__main__.py`, `tests/test_khaithi_thumbs*.py`, `tests/test_publish_shorts.py`, `tests/test_publish_kt.py`, `tests/test_publish_thumbs.py`, `docs/decisions/PUB2-youtube-thumbnail-set.md` (pointer), file này
- Dependencies: PUB2S (#201, đã merge); KTI1 / KTI2 (intro 3 s, đã merge)
- Base commit / branch: `ddd324c` (main sau #201) / `feature/vsafe1-vertical-45-colors` (worktree `~/projects/yas-vsafe1`)
- Human Lead approval: accepted 2026-11-03 ("còn lại APPROVED"; phạm vi gắn: "gắn short+KT cho các tập đã lên lịch, và các tập đã công khai từ 1/11")
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

## Bằng chứng (2026-11-03)

- Tab Đăng ký trên app YouTube cắt giữa ảnh 9:16 thành khung ~4:5 (đo 923×1150) → trên ảnh 1080×1920 chỉ còn y 285–1635. Mẫu hiện tại: Địa Tạng box y = 220, VLT / CƯT y = 129, Thập Thiện y = 247 → mất nhãn "TRÍCH ĐOẠN (KHAI THỊ)" / hoa văn đỉnh khung.
- Mẫu thử (nháp, ngoài repo: scratchpad `mock45.py`, `mock45kt.py`), HUMAN LEAD duyệt:
  - dời nền + box xuống `shift = max(0, 330 − y)` (ĐT 110, VLT / CƯT 201, TT 83); dải trên lấp bằng phần nền phía trên khung (`min(shift, y − 60)` dòng) kéo giãn + lật dọc — còn lộ mẩu hoa văn nhỏ ở VLT / CƯT → bản thật dùng nền mờ (blur) cho dải lấp;
  - màu: `colorbalance` vùng tối / trung tính, giữ vàng sáng. 4 sắc nhuộm cố định: đỏ son `rs=.35:gs=-.05:bs=-.3:rm=.15:bm=-.1`, lục ngọc `rs=-.2:gs=.25:bs=-.05:gm=.1:rm=-.05`, nâu trầm `rs=.25:gs=.1:bs=-.35:rm=.1:bm=-.15`, lam `rs=-.3:gs=-.1:bs=.35:rm=-.1:bm=.15`.
  - Kết quả đã duyệt theo bộ: ĐT gốc / đỏ son / lục ngọc / nâu trầm; VLT gốc / đỏ son / lục / lam; CƯT gốc / đỏ son / nâu trầm / lam; TT gốc / đỏ son / lục / lam.
- Ảnh đã gắn trên YouTube: Người Dân Cực Lạc + VLT ~111 KT ngang (2026-11-02) + 1 dọc thử (T11 KT02); Tín Nguyện 63 KT dọc mẫu cũ (T1–T9, T11) + 2 Short (T9 S10, S09). Cron `run.sh` (ngang) đang tạm dừng.

## Goal

Ảnh dọc khai thị (KT) và Short "TRÍCH ĐOẠN" — cả thumbnail YouTube lẫn khung intro 3 s trong video — giữ đủ nhãn, tiêu đề, giảng sư, bộ kinh / tập và mặt chân dung khi bị cắt 4:5; màu nền xoay 4 màu theo số tập; gắn lại toàn bộ KT dọc trên các kênh và Short đăng từ 2026-11-01.

## Scope

- In scope:
  - Mẫu dọc (`kt_vertical`) cho `vertical_clip` (KT + Short web / intro KTI1 / KTI2) và `short_title` (Short từ tiêu đề YouTube): dời theo vùng an toàn, dải lấp mờ, chân dung neo đáy không đè box, 4 màu xoay theo tập.
  - Bump khóa cache (`LAYOUT_VERSION`) → ảnh cũ thành stale; intro dựng lại bằng `enqueue_intro_rebuild` có sẵn (KT + Short, mọi bộ đã bật intro).
  - `short-thumbs` và `kt-thumbs` cùng nhận `--since YYYY-MM-DD` (ngày đăng YouTube, giờ VN: video lên lịch dùng `status.publishAt`, còn lại `snippet.publishedAt`); `kt-thumbs` mặc định `--shape vertical` (ngang vẫn chọn được).
  - Vận hành (ORCHESTRATOR, ngoài code): `kt-thumbs` + `short-thumbs --since 2026-11-01` mẫu mới cho Người Dân Cực Lạc, VLT, CƯT, Tín Nguyện theo D3; cron chạy dần theo hạn mức.
- Out of scope: ảnh ngang (`kt_landscape`, bìa tập, HD), bìa tập dọc (`vertical` cover của PKG), ảnh video ghép (THUMB2), sửa video đã đăng trên YouTube (intro mới chỉ có ở file render lại / lần đăng sau), bảng 10 màu.

## Authority / key decisions

- `docs/decisions/PUB2-youtube-thumbnail-set.md` (gắn thumbnail qua API, nhật ký sha), PKG / KTI1 / KTI2 contracts (layout `khaithi_thumbs`).
- D1 vùng an toàn: mép trên box ≥ y 330 trên 1080×1920 (crop 4:5 bắt đầu y 285 + lề 45 cho hoa văn). Box đã ≥ 330 thì không dời.
- D2 màu: chỉ số màu = `(tập − 1) mod 4`; ô 0 = nền gốc không nhuộm; ô 1–3 = 4 sắc cố định theo thứ tự [đỏ son, lục ngọc, nâu trầm, lam] bỏ đi **một** sắc gần màu gốc nhất. Màu gốc = màu trung bình phần trong box của nền gốc, so theo hue với mốc đỏ son 5°, lục ngọc 150°, nâu trầm 30°, lam 225° (ĐT → bỏ lam, VLT → bỏ nâu, CƯT → bỏ lục, TT → bỏ nâu; khớp mẫu đã duyệt). Tính lại khi đổi ảnh bìa, nằm trong khóa cache.
- D3 (HUMAN LEAD 2026-11-03, thay quyết định "KT áp dụng hết" trước đó): **Short và KT** chỉ gắn video lên lịch (private có `publishAt`), private đã tải chưa lên lịch (sẽ công khai sau mốc), và public có ngày đăng từ 2026-11-01 (giờ VN). Public đăng trước mốc giữ ảnh hiện tại (kể cả ~111 KT ngang và KT dọc mẫu cũ đã công khai).
- G1 (HUMAN LEAD 2026-11-03): video đã đăng / lên lịch / đã tải lên YouTube giữ intro cũ. Intro chỉ dựng lại **từ tập kế tiếp sau tập cao nhất đã có trên YouTube** (đọc kênh 2026-11-03, tính cả public, lên lịch, private đã tải): Thập Thiện (Người Dân Cực Lạc) KT + Short tới T20 → dựng từ **21**; VLT KT tới T31, Short tới T30 → KT từ **32**, Short từ **31**; CƯT KT + Short tới T23 → từ **24**; Địa Tạng (Tín Nguyện) KT + Short tới T15 → từ **16**. Quy mô: KT 99 tập / 512 clip, Short 126 tập / 1.451 clip (~225 job render). Thứ tự: mỗi bộ xếp 10 tập đầu kể từ mốc trước (`enqueue_intro_rebuild(pid, mốc, mốc + 9)`), rồi phần còn lại; chạy **trước** feeder bản dọc CƯT (tạm dừng feeder tới khi hết hàng intro); enhance GPU chạy song song. Mốc chụp ngày 2026-11-03: ORCHESTRATOR đọc lại YouTube ngay trước khi xếp hàng, nếu đã đăng thêm thì dời mốc.

## Implementation approach

- `khaithi_thumbs` / `cover`: hàm dựng nền dọc (dời + dải lấp mờ + nhuộm) trước `draw_lines`, box dời theo D1, `portrait_box` dùng box đã dời; chọn sắc theo D2. Ảnh nền đã dựng cache theo (sha nền, shift, sắc) trong thư mục tạm của lần vẽ — không ghi file mới vào `cover/`.
- Khóa cache thêm `shift`, `tint`; bump `LAYOUT_VERSION`. `reuse_only` của `short_title` / kiểm sha trong `apply` giữ nguyên.
- `youtube.py`: `videos.list` thêm part `status` (cùng request) để có `publishAt`. `shorts.py` / `kt.py` lọc `--since` (helper chung) sau khi lập bảng, lý do bỏ qua "đăng trước <ngày>".
- Tái dùng: `draw`, `layout`, `cover.draw_lines`, `portrait_box`, `thumbnail.reusable`, `enqueue_intro_rebuild`, nhật ký `thumbs.json` của PUB2.

## Phải giữ nguyên

- Layout chữ (`layout`/`_fit`: 1–3 dòng, cỡ chữ, màu chữ vàng), nhãn "TRÍCH ĐOẠN" / "TRÍCH ĐOẠN KHAI THỊ", chọn chân dung theo tập, ảnh ngang, nhật ký PUB2 và quy tắc bỏ qua cùng sha, hạn mức / xử lý 429.
- Ảnh bìa gốc trong `cover/` không bị sửa.

## Code bị thay / xóa

- `portrait_box(shape="kt_vertical"/vertical)` dùng box gốc → dùng box đã dời (thay, không giữ nhánh cũ).
- Không xóa hàm nào khác.

## Acceptance Criteria

1. Ảnh KT và Short dọc của 4 bộ (ĐT, VLT, CƯT, TT): cắt `crop=1080:1350:0:285` còn đủ nhãn, tiêu đề, giảng sư, dòng bộ kinh · tập (ink box ⊂ y 285–1635) và mặt chân dung; mép trên box ≥ 330.
2. Màu: tập 1, 5, 9 = gốc; tập 2–4 theo D2; bảng sắc theo bộ khớp mục "Bằng chứng" cho 4 bộ hiện có (test với nền giả có hue tương ứng + kiểm thật 4 bộ).
3. Dải lấp phía trên không lộ hoa văn / khung (nền mờ); vàng sáng của khung không đổi màu.
4. Cache: ảnh mẫu cũ thành stale (khóa khác), vẽ lại 1 lần, chạy lại không vẽ lại; `short_title(reuse_only=True)` không vẽ.
5. `short-thumbs` / `kt-thumbs --since 2026-11-01`: public đăng trước ngày (giờ VN) bỏ qua có lý do "đăng trước <ngày>"; lên lịch (mọi ngày) và private chưa lên lịch được giữ; không có `--since` giữ hành vi cũ. `kt-thumbs` mặc định dọc.
6. Intro 3 s: clip render lại có khung intro dùng ảnh mẫu mới (kiểm 1 KT + 1 Short thật).
7. Chạy thật (ORCHESTRATOR, theo "Trial before bulk"): gắn 1 KT + 1 Short mỗi kênh trước, HUMAN LEAD xem trên điện thoại, rồi mới gắn hàng loạt.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_khaithi_thumbs*.py tests/test_publish_shorts.py tests/test_publish_kt.py tests/test_publish_thumbs.py -q` — AC1–5.
- Full suite `python -m pytest -q -n auto` (ORCHESTRATOR, ngoài sandbox).
- Vẽ thật 4 bộ × 4 màu + bản cắt 4:5 → gửi HUMAN LEAD (AC1–3).
- Render lại 1 KT + 1 Short thật, kiểm khung đầu video (AC6).
- `short-thumbs` / `kt-thumbs` chạy thử không `--apply` trên các kênh, rồi `--apply --only` mỗi kênh 1–2 video (AC5, AC7).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract. Manual test là điểm danh sau verification tự động.

- [ ] Điện thoại: trang kênh, tab Shorts, feed Shorts, tab Đăng ký (4:5), playlist — 1 KT + 1 Short mỗi kênh.
- [ ] Web: trang Short / KT hiện ảnh mới; clip render lại có intro mới.

## Result

- (chưa thực hiện)
