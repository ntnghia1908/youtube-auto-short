# Task: VSAFE1 — Mẫu ảnh dọc an toàn 4:5 + 4 màu xoay theo tập (thumbnail + intro 3 s)

## Status / Approval

- Status: READY
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
- D4 khung cao (sửa đổi 1, HUMAN LEAD 2026-11-03 sau mẫu thử: "làm khung cao 700 px cho Vô Lượng Thọ, Cảm Ứng Thiên, Thập Thiện"; dải lấp phẳng phía trên: "ổn không sao hết"): box `kt_vertical` có chiều cao h < 700 thì kéo khung tới 700 (`extra = 700 − h`; Địa Tạng h = 700 giữ nguyên). Trong cột của box [x, x+w): giãn một dải mỏng giữa box (box chỉ có nền phẳng) thành `dải + extra`; ngoài box (thanh khung + cảnh hai bên): giãn đều một vùng giữa khung tránh góc hoa văn (khoảng ±150 px quanh giữa box, không chạm góc) — không được để vệt sọc dọc. Mọi thứ dưới đó dời xuống `extra`; giữ 1920 px (bỏ `extra` dòng đáy). Chữ dùng box cao 700; chân dung neo đáy theo box đã kéo (đầu chạm khung như Địa Tạng). Nằm trong khóa cache; ảnh gốc `cover/` không sửa; ảnh ngang / THUMB2 không đổi.
- G1 (HUMAN LEAD 2026-11-03): video đã đăng / lên lịch / đã tải lên YouTube giữ intro cũ. Intro chỉ dựng lại **từ tập kế tiếp sau tập cao nhất đã có trên YouTube** (đọc kênh 2026-11-03, tính cả public, lên lịch, private đã tải): Thập Thiện (Người Dân Cực Lạc) KT + Short tới T20 → dựng từ **21**; VLT KT tới T31, Short tới T30 → KT từ **32**, Short từ **31**; CƯT KT + Short tới T23 → từ **24**; Địa Tạng (Tín Nguyện) KT + Short tới T15 → từ **16**. Quy mô: KT 99 tập / 512 clip, Short 126 tập / 1.451 clip (~225 job render). Thứ tự: mỗi bộ xếp 10 tập đầu kể từ mốc trước (`enqueue_intro_rebuild(pid, mốc, mốc + 9)`), rồi phần còn lại; chạy **trước** feeder bản dọc CƯT (tạm dừng feeder tới khi hết hàng intro); enhance GPU chạy song song. Mốc chụp ngày 2026-11-03: ORCHESTRATOR đọc lại YouTube ngay trước khi xếp hàng, nếu đã đăng thêm thì dời mốc. Dựng tới **tập cuối đã xử lý** của mỗi bộ (VLT KT T51 / Short T50, CƯT T50, TT T50, ĐT KT T64 / Short T102 + các tập ĐT còn thiếu tới T50 đang xếp hàng trên 8080 từ 2026-11-03, intro được ưu tiên trước chúng). Job dựng lại là **nhánh chỉ thay intro** sẵn có (`render/stage.py`: `intro.extract_content` cắt intro cũ bằng copy + `intro.prepend` chỉ encode 3 s): nội dung clip không encode lại (HUMAN LEAD 2026-11-03 "gắn thêm 3s đầu không cần phải render lại từ đầu").

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
1b. (D4) Box VLT / CƯT / TT cao 700 sau khi kéo, ĐT không đổi; chữ to hơn mẫu khung cũ; không vệt sọc ở cảnh hai bên khung (kiểm thật bằng mắt); AC1 vẫn đạt.
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

### IMPLEMENTER — READY để ORCHESTRATOR review (2026-11-03)

- Branch `feature/vsafe1-vertical-45-colors`, HEAD giữ `5d89ee6`; chưa commit / push / PR, không gọi agent khác hay mạng thật. Chỉ sửa owned paths.
- KT / Short web / intro và Short từ tiêu đề YouTube dùng nền dời + dải lấp mờ + tint D2 trước `cover.draw_lines`; truyền box đã dời cho chữ và `portrait_box`. `LAYOUT_VERSION = 7`, khóa thêm `shift` / `tint`; nền PNG dùng chung trong thư mục tạm theo SHA / shift / tint. Ảnh gốc không bị ghi; ảnh ngang và THUMB2 giữ byte / khóa layout 6 bằng entry không áp VSAFE1.
- `videos.list` thêm `status` trong request hiện có; cả hai planner dùng chung bộ lọc ngày VN trước đọc / dựng ảnh, giữ mọi private (gồm lên lịch mọi ngày), public cũ ghi đúng lý do. `kt-thumbs` mặc định dọc; thêm kiểm tra cú pháp / ngày hợp lệ của `--since`. PUB2 trỏ về D1–D3 tại contract này.
- Helper mới: `_vertical_palette` (RGB trung bình trong box + hue, cache theo ảnh/SHA/box), `vertical_entry` (chuẩn bị riêng KT/Short, giữ THUMB2), `_vertical_background` (PNG nền mờ / nhuộm trong temporary tree), `youtube.since_reason` (chung hai planner), CLI `_since` (validate ngày). Đã tìm bằng `rg -n 'colorbalance|rgb_to_hsv|publishedAt|publishAt|--since' src/auto_short/packaging src/auto_short/publish` và `rg -n 'hue|palette|blur|background|shift|since' src/auto_short/packaging src/auto_short/publish`: chưa có helper khớp; `thumbnail.white_background` chỉ đo bốn góc, không đo trong box. Tái dùng `draw`, `layout`, `cover.draw_lines`, `portrait_box`, `thumbnail.reusable`, `_encode` qua `draw_lines`, `_run`, nhật ký / apply PUB2; không cần sửa `cover.py`.

| AC | Bằng chứng tự động |
|---|---|
| 1 | `test_vsafe_vertical_flows_shift_ink_and_portrait`: bốn box hiện có + box không cần dời, cả KT/Short; đo ink và pixel chân dung sau crop 4:5 |
| 2 | `test_vsafe_palette_averages_inside_original_box`, `test_vsafe_background_blurs_ornament_preserves_highlights_and_caches`: hue giả, khoảng cách hue vòng tròn, bốn ảnh màu khác nhau; tập 1/5/9 tái dùng nền gốc |
| 3 | `test_vsafe_background_blurs_ornament_preserves_highlights_and_caches`: dải trên mất chi tiết sắc, highlight trắng không bị nhuộm; chưa thay thế kiểm ảnh thật bằng mắt |
| 4 | `test_vsafe_short_title_version_stale_reuse_only_and_single_rebuild`, `test_vsafe_vertical_flows_shift_ink_and_portrait`, `test_override_stale_rejected_and_two_shapes_cache`: stale / dựng một lần / reuse-only không vẽ |
| 5 | `test_since_both_commands_vietnam_midnight_and_private`, `test_since_cli_skips_public_before_apply_and_logs_private`, `test_cli_shape_selection`; thêm parametrize ngày CLI sai và test phân trang / batch hiện có (vượt ba hàm để giữ kiểm hồi quy API và validate đầu vào) |
| 6–7 | Chưa kiểm video thật / YouTube / điện thoại; ORCHESTRATOR thực hiện |

- Verification PASS: `PYTHONPATH=/home/ntnghia/projects/yas-vsafe1/src ~/miniconda3/envs/auto-short/bin/python -m pytest tests/test_khaithi_thumbs.py tests/test_publish_shorts.py tests/test_publish_kt.py tests/test_publish_thumbs.py tests/test_compilation_thumbs.py -q` → **335 passed, 238.94 s**. Sau bổ sung assertion chu kỳ màu, chạy riêng `tests/test_khaithi_thumbs.py -k 'vsafe_background or vsafe_palette' -q -x --tb=short` → **6 passed, 95 deselected, 8.07 s**. `git diff --check` PASS.
- Kiểm chỉ đọc trên bốn ảnh gốc đã xác thực SHA tại `/home/ntnghia/projects/youtube-auto-short/output/_compilations/*/cover/`: ĐT gốc/đỏ/lục/nâu (shift 110), VLT gốc/đỏ/lục/lam (201), CƯT gốc/đỏ/nâu/lam (201), TT gốc/đỏ/lục/lam (83), khớp D2. Chưa vẽ bộ 4 × 4 ảnh thật + crop để HUMAN LEAD duyệt.
- `git diff --numstat`: code **+133 / −14**, test **+205 / −10**. Không thêm dependency; không sửa test ngoài owned paths, gồm test THUMB2 khóa byte / key cũ vẫn PASS.
- Giới hạn / bàn giao: READY chỉ cho phần IMPLEMENTER; task chưa đạt READY tổng thể khi verification của ORCHESTRATOR còn thiếu. Theo phân công không chạy web `PYTHONPATH=/home/ntnghia/projects/yas-vsafe1/src ~/miniconda3/envs/auto-short/bin/python -m pytest tests/test_web_episode_thumbs.py tests/test_web_khaithi_cp89.py -q` hoặc full suite `PYTHONPATH=/home/ntnghia/projects/yas-vsafe1/src ~/miniconda3/envs/auto-short/bin/python -m pytest -q -n auto` trong sandbox không socket; không claim PASS hai lệnh này. ORCHESTRATOR còn vẽ ảnh thật / kiểm crop, render 1 KT + 1 Short thật (AC6), trial YouTube + điện thoại (AC7), đọc lại kênh và xếp intro theo G1; IMPLEMENTER chưa xếp job hay thay dữ liệu vận hành.

### IMPLEMENTER — vòng 2, READY để review (2026-11-03)

- D4: `vertical_entry` giữ box gốc để đo màu, trả box cao ít nhất 700 và `stretch`; VLT/CƯT +103, TT +119, ĐT 0. Khóa thumbnail và nền tạm chứa `stretch`. Kéo khung trên ảnh gốc trước dời / lấp / nhuộm, trong một lệnh ffmpeg xuất PNG lossless. Giữ nguyên sửa `_last_line(proc.stderr)` của ORCHESTRATOR; không sửa `cover.py` hay ghi vào ảnh gốc.
- Helper mới `_stretch_frame`: dựng graph ghép ba cột, giữa box giãn 8 dòng, hai bên giãn vùng ±150 px (thu nhỏ khi gần góc), cắt về 1080×1920. Đã tìm `rg -n 'stretch|vstack|hstack|scale=.*flags' src/auto_short/packaging`; helper cũ chỉ có ghép / scale thông thường, chưa có kéo vùng giữa khác nhau theo cột. Tái dùng `_vertical_background`, `layout`, `cover.draw_lines`, `portrait_box`.
- AC1b → `test_vsafe_stretch_preserves_regions_and_smooth_side_scenery` (pixel vùng trên nguyên trạng, vùng dưới dời đúng, gradient hai bên không thành sọc; ĐT không kéo; cache nền đổi theo stretch), `test_vsafe_taller_box_grows_text_and_samples_original_cover` (màu đo box gốc, chữ 80 → 95 px), `test_vsafe_vertical_flows_shift_ink_and_portrait` (KT/Short: box 700, đầu chân dung chạm đáy box, ink + mặt còn trong crop 4:5). Khóa thumbnail đổi theo stretch cũng được kiểm trong test palette. Cỡ chữ vẫn chịu giới hạn chiều rộng của layout cũ.
- Verification đúng lệnh targeted ở vòng 1 / delegation: **339 passed, 259.91 s**. Thêm `PYTHONPATH=/home/ntnghia/projects/yas-vsafe1/src ~/miniconda3/envs/auto-short/bin/python -m pytest tests/test_khaithi_intro.py::test_existing_content_gets_intro_after_source_cleanup -q -x --tb=short` → **2 passed, 12.96 s**. `git diff --check` PASS.
- Dựng nền bốn ảnh thật vào `/tmp/vsafe1-round2-backgrounds/`, kiểm SHA ảnh nguồn trước/sau không đổi; đã xem nền VLT/CƯT/TT, không thấy vệt sọc hai bên. Đây chưa thay thế HUMAN LEAD duyệt bộ ảnh đầy đủ / video / điện thoại; web, full suite và vận hành vẫn giao ORCHESTRATOR như trên.
- Riêng vòng 2 so với lúc nhận việc (đã gồm sửa stderr của ORCHESTRATOR): code **+31 / −4**, test **+60 / −2**. Chỉ sửa source / test nêu trên và Result này; giữ các thay đổi có sẵn, HEAD `5d89ee6`; không commit / push / PR / agent khác / mạng thật.

### ORCHESTRATOR (2026-11-03)

- Codex vòng 1: 151.361 tokens, 335 test targeted PASS (theo report). Chưa review / full suite / chạy thật — chuyển session mới.
- Review vòng 1: inventory ⊆ Owned paths, `cover.py` không đổi. ORCHESTRATOR sửa nhỏ: lỗi nền dọc kèm dòng stderr ffmpeg (`test_khaithi_intro` cần thông báo gốc).
- Sửa đổi 1 (D4 khung cao 700, HUMAN LEAD 2026-11-03 sau mẫu thử): Codex vòng 2 (resume cùng session, effort medium; tổng session 337.896 tokens) +31/−4 code, +60/−2 test; mẫu thật hết vệt sọc, HUMAN LEAD "Ổn rồi".
- Verification: full suite `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` → **3875 passed, 1 skipped** (2026-11-03, sau vòng 2). Vẽ thật 4 bộ × 4 màu + cắt 4:5: đủ nhãn / tiêu đề / giảng sư / dòng tập / mặt (AC1, AC1b, AC2, AC3), HUMAN LEAD duyệt.
- AC6: dựng lại intro trên bản sao VLT Short T31 k01 + KT T32 k01 (`extract_content` + `prepend`): khung đầu dùng mẫu mới, màu đúng D2; gói video nội dung trùng byte (streamhash); audio thêm 4 gói pre-roll ts âm (hành vi sẵn có của nhánh chỉ thay intro, không lệch tiếng).
- AC5 / AC7: chạy thử `kt-thumbs` / `short-thumbs --since 2026-11-01` 4 kênh; gắn thử `--apply --only` mỗi kênh 1 KT + 1 Short private, rồi 1 KT + 1 Short **public** (TT T11_KT03 / T2_S02, VLT T13_KT02 / T12_S02, CƯT T12_KT02 / T10_S06, ĐT T9_KT03 / T10_S04); HUMAN LEAD xem điện thoại: "ổn rồi". Gắn hàng loạt: xoay vòng 3 kênh chung hạn mức, KT + Short đều nhau (HUMAN LEAD 2026-11-03).
- Kèm commit riêng: ngưỡng quota Codex trong `.claude/rules/execution.md` (5 giờ ≥ 95 %, tuần ≥ 97 %; HUMAN LEAD 2026-11-03).
