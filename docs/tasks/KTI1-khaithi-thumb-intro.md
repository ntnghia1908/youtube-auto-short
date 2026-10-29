# Task: KTI1-khaithi-thumb-intro — Clip khai thị có 3 giây thumbnail khai thị ở đầu video

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29: "Tôi muốn khai thị cũng có thumnail 3s đầu. Việc này áp dụng với tất cả khai thị của cảm ứng thiên, thập thiện nghiệp đạo từ tập 21 trở về sau. Với Vô Lượng Tho từ tập 31 về sau"; "lưu ý với video khai thị ghép không ghép phần 3s này vào. Ghép như hiện tại"; G1–G3 bên dưới
- Parallel group: —
- Owned paths: đường render clip khai thị (`src/auto_short/render/stage.py` và module render clip liên quan), `src/auto_short/packaging/khaithi_thumbs.py` (dựng ảnh cho 1 clip theo yêu cầu render), mọi đường đọc file clip khai thị để ghép: `src/auto_short/compilation/`, `src/auto_short/web/compilations.py`, `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_render/__init__.py`, `src/auto_short/store/shorts.py` (mượn clip từ kho), `src/auto_short/web/static/` (chỉ thông báo "chưa có bìa" + link trang Thumbnail), test tương ứng + `tests/test_khaithi_intro.py` (mới), contract này
- Dependencies: THUMB1 (#182: bìa KT, `khaithi_thumbs`, `khaithi_from.json`), VERT2 (intro 3 s bản dọc: filter + key), SHO1 (clip trên kho 3090, bản `(rN)`), HDI1 (#183: mẫu độ lệch intro + sha nội dung). Bắt đầu sau khi THUMB2 merge (cùng sửa `khaithi_thumbs.py`).
- Base commit / branch: `0a1277f` (`feature/thumb2-compilation-thumbs`, PR #184 — xếp chồng vì cùng sửa `khaithi_thumbs.py`; đổi base sang main sau khi #184 merge) / `feature/kti1-khaithi-thumb-intro`
- Human Lead approval: APPROVED 2026-10-29
- Implementation authorized: YES

S2 vì: đổi sản phẩm video khai thị đã đăng / trên kho (bản `(rN)`), mọi đường ghép clip phải bù độ lệch, và có đợt dựng lại hàng loạt khoảng 500 clip.

## Quyết định

- D-KTI1-1: clip khai thị dựng mới = **3 s ảnh thumbnail khai thị dọc** của clip (THUMB1, `kt_vertical`, cùng chữ / chân dung như ảnh tải về) **trước** nội dung, tiếng im lặng (như VERT2 G2). Phạm vi theo `khaithi_from.json` (VLT ≥ 31, Cảm Ứng Thiên ≥ 21, Thập Thiện ≥ 21); tập trước mốc: không intro, không đổi.
- D-KTI1-2 (G1 = "Dựng lại tất cả"; G2 = "Dựng lại luôn"): sau merge, ORCHESTRATOR xếp dựng lại mọi clip khai thị đã render trong phạm vi, **kể cả tập đã đăng**; tiêu đề / đoạn cắt giữ nguyên; bản mới lên kho 3090 thành `(rN)` (SHO1b). Thứ tự theo D-KTI1-5.
- D-KTI1-5 (HUMAN LEAD 2026-10-29, thứ tự ưu tiên khi thiếu CPU / GPU): (1) video khai thị ghép có thumbnail (THUMB2); (2) clip khai thị có intro — **mỗi bộ chạy trước 10 tập** (VLT 31–40, Cảm Ứng Thiên 21–30, Thập Thiện 21–30), đánh dấu "Ưu tiên" (CP8.26 `priority.mark`) để vượt các job bản dọc Địa Tạng còn chờ; phần còn lại xếp sau, không ưu tiên; (3) Kinh Địa Tạng: thumbnail bản dọc (VERT2, đang render) và bản ngang (HDI1).
- D-KTI1-3 (G3, HUMAN LEAD: "báo chưa có bìa và chuyển qua trang thiết kế bìa"): bộ trong phạm vi chưa có bìa KT → **không render clip thiếu intro**; job khai thị dừng với lý do "Bộ kinh chưa có ảnh bìa khai thị", web hiện thông báo + link sang trang Thumbnail của bộ (THUMB1). Cài bìa xong → chạy lại job.
- D-KTI1-4 (HUMAN LEAD 2026-10-29: "video khai thị ghép không ghép phần 3s này vào. Ghép như hiện tại"): video ghép yêu thích (CP8.33) và tuyển tập chủ đề (TC3) **bỏ 3 s intro** của từng clip: nội dung ghép giống hiện tại. Sidecar clip ghi độ lệch intro + sha nội dung (mẫu HDI1); fingerprint index / plan đã duyệt dựa trên nội dung → plan **không** stale chỉ vì thêm intro.
- D-KTI1-6 (HUMAN LEAD 2026-10-29 sau xem 5 mẫu GIF: "Mẫu 1 và hiệu ứng 1s thay vì 0.7"): **hòa tan** (`xfade=transition=fade`) **1 s** cuối của 3 s intro, từ thumbnail sang **khung hình đầu tiên của nội dung** (ảnh tĩnh); nội dung clip vẫn giữ nguyên byte (concat copy), độ lệch intro không đổi; video ghép vẫn cắt sạch theo độ lệch.
- Thumbnail đổi (sửa tiêu đề, đổi bìa / chân dung) → key render đổi → clip cũ không còn hiện hành, dựng lại như sửa tiêu đề hiện nay.

## Goal

Clip khai thị trong phạm vi (VLT ≥ 31, Cảm Ứng Thiên / Thập Thiện ≥ 21) mở đầu bằng 3 giây thumbnail khai thị; video ghép vẫn y như hiện tại.

## Scope

- In scope: dựng ảnh KT dọc cho clip lúc render (tái dùng `khaithi_thumbs` + cache), filter intro 3 s + `anullsrc` (tái dùng VERT2 `full.py`: lệnh / filter intro, tách helper chung nếu cần), key render gồm sha ảnh + độ dài intro, sidecar clip `intro` (sha ảnh, giây) + sha nội dung; mọi đường ghép bỏ intro theo sidecar; bộ thiếu bìa KT → lỗi có lý do + link web; lệnh / API xếp dựng lại clip KT theo playlist + mốc tập (cho đợt D-KTI1-2).
- Out of scope: Short; bản dọc / HD (VERT2 / HDI1); clip trước mốc `khaithi_from.json`; tự đăng YouTube / thay video đã đăng; đổi giao diện thumbnail KT.

## Phải giữ nguyên

- Video ghép yêu thích + tuyển tập chủ đề: nội dung ghép như hiện tại (không intro); plan đã duyệt không stale vì intro; Short không đổi byte; clip khai thị trước mốc không đổi; thumbnail KT tải về (THUMB1) không đổi.

## Code bị thay / xóa

- Không xóa; filter render clip khai thị thêm nhánh intro.

## Acceptance Criteria

1. Clip khai thị trong phạm vi: 3 s đầu là ảnh KT dọc của đúng clip (so khung), tiếng im lặng, độ dài = nội dung + 3 s; sidecar có `intro` + sha nội dung; render lại không đổi gì → cache.
2. Clip trước mốc / Short: không intro, byte / key không đổi.
3. Bộ trong phạm vi chưa có bìa KT → job dừng với lý do "Bộ kinh chưa có ảnh bìa khai thị", không ghi clip; API / web trả link trang Thumbnail.
4. Video ghép yêu thích + tuyển tập chủ đề từ clip có intro: không chứa 3 s intro (so framemd5 nội dung với bản ghép từ clip không intro), plan đã duyệt không stale; mượn clip `(rN)` từ kho bù đúng độ lệch.
5. Sửa tiêu đề clip → thumbnail + intro đổi, clip dựng lại.
6. Lệnh xếp dựng lại theo playlist + mốc tập: xếp đúng các clip trong phạm vi, bỏ qua clip đã có intro hiện hành.
7. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix như THUMB1.

- `<prefix> tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py` + test render / compilation / theme hiện có — AC 1–6 (không socket).
- TestClient (ORCHESTRATOR) cho AC3 web; `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh): 1 tập VLT ≥ 31 dựng lại clip khai thị → gửi HUMAN LEAD 10 s đầu 1 clip; ghép 1 video yêu thích có clip đó → so với bản cũ (không intro); 1 tập Cảm Ứng Thiên chưa có bìa → thấy thông báo + link.

## Manual test checklist (Tech Lead)

- [ ] 3 s đầu clip khai thị là đúng thumbnail của clip, dấu đúng.
- [ ] Video ghép không có đoạn 3 s ảnh giữa các clip.

## Result

IMPLEMENTER hoàn tất 2026-10-29, sẵn sàng ORCHESTRATOR review. Status task vẫn `IN_PROGRESS`: AC7 (full suite / TestClient) và chạy thật do ORCHESTRATOR xác nhận; không tuyên bố PASS các phần chưa chạy. Không commit / push / PR, không gọi agent, không mạng thật.

- File đổi: `render/stage.py`, **mới** `render/intro.py`, `render/full.py` (chỉ tách helper VERT2); `packaging/khaithi_thumbs.py`; `compilation/assemble.py`, `compilation/store.py`; `web/compilations.py`, `web/static/app.js`; `theme_index/__init__.py`, `theme_render/__init__.py`; `store/shorts.py`; **mới** `tests/test_khaithi_intro.py`, thêm ca vào `tests/test_khaithi_thumbs.py`, `tests/test_theme_render.py`; contract này.
- Nội dung clip giữ nguyên packet encode. Intro dùng chung input/filter VERT2, encode riêng ảnh rồi concat copy; có `-force_key_frames 3`, content bắt đầu bằng IDR. Giữ timestamp với `-copyts` / `-avoid_negative_ts disabled`, tránh lệch AAC 21 ms. `intro.seconds=3`; `content_offset` là mốc frame thực tế (NTSC 90 / 29.97 ≈ 3.003 s), dùng thống nhất khi cắt.
- Sidecar render có `intro`, `content_offset`, `content_sha256`, `content_render_key`; fingerprint TC1/TC3 chiếu về manifest nội dung cũ. `content_workspace_manifest_sha256` giữ fingerprint trước lần thêm intro khi nội dung không đổi. Clip mượn từ kho và kept có `.intro.json` kèm SHA được kiểm; un-heart xóa cả sidecar.
- `_intro_from_existing` kiểm config, artifact, review / ranges / title và sha trước khi thêm intro vào clip cũ. Dùng được khi nguồn đã dọn / HD đã giải phóng; lấy lại clip qua SHO1 nếu cần, không lấy nguồn HD. Khi đổi nội dung / intro cũ, dùng đường render hiện hành.
- Hàm cho ORCHESTRATOR trên **runner web đang chạy**: `auto_short.packaging.khaithi_thumbs.enqueue_intro_rebuild(config, runner, pid, first, last, prioritize_first_ten=True)`. Chọn tập theo `khaithi_from.json`, bỏ clip current (kể cả nguồn archived), dùng `render_target`, `runner.submit`, `runner.priority.mark`; 10 tập tính từ mốc cấu hình, không tính từ đầu khoảng yêu cầu. Không xếp / upload dữ liệu thật trong session.

### AC → test

| AC | Bằng chứng |
|---|---|
| 1 | `test_intro_pixels_silence_content_sha_cache_and_title` (mới + nâng cấp), `test_kti1_single_vertical_is_thumb1_download_with_same_portrait_and_cache`, `test_existing_content_gets_intro_after_source_cleanup` (local / kho + retry) |
| 2 | `test_outside_scope_keeps_bytes_and_key` (Short / trước mốc / chưa cấu hình), regression `test_khaithi_ac1.py` |
| 3 | `test_missing_cover_fails_with_link_and_no_new_clip`: stage + JobFailed + gọi route trực tiếp, không socket; kiểm reason, URL, không ghi clip |
| 4 | `test_compilation_copy_and_reencode_skip_intro` (25 fps B-frame + NTSC, framemd5); `test_borrow_revision_kept_duration_and_cleanup` (handler kho thật qua I/O giả, upload `(r2)` + mượn + kept); `test_kti1_intro_preserves_approval_and_content_reference` (local / kho); `test_kti1_real_theme_rebuild_strips_reference_intro` (audio gate + framemd5) |
| 5 | `test_intro_pixels_silence_content_sha_cache_and_title`: đổi title → ảnh / key / clip đổi |
| 6 | `test_rebuild_range_priority_and_skip_current`: khoảng tập, trước mốc, 31–40 được ưu tiên / 41 không, bỏ current; ca archived ở AC1 kiểm skip sau dựng |
| 7 | Framework / diff / JS syntax PASS; full suite + TestClient + chạy thật chưa chạy |

AC4 dùng 4 hàm thay vì ≤3 vì có bốn boundary độc lập: concat copy/fallback, kho/kept, approval/fingerprint, dựng TC3 thực. Không sửa/xóa assertion của test cũ.

### Helper mới / tái dùng

Đã tìm bằng `rg -n 'intro|def .*command|def .*filter' src/auto_short/render/{full,plan}.py`, `rg -n 'sha256|duration|borrow|render_manifest|shorts'` trên các consumer, đọc `khaithi_thumbs` và `git show df562e6:src/auto_short/enhance/state.py`.

- `intro.inputs`, `intro.filters`: tách từ VERT2, full giữ nguyên graph / command mặc định. `intro.prepend`: cần giữ packet nội dung; encode toàn clip qua filter sẽ đổi SHA và tốn CPU. Dùng lại concat command / escaping của compilation.
- `intro.offset`, `clip_record`, `content_record`, `content_manifest`: consumer cần phân biệt stored SHA và content SHA, hỗ trợ local / kept / kho; HDI1 chỉ là mẫu chưa merge nên không import từ đó. Digest tiếp tục dùng memo `_json_digest` hiện có.
- `_intro_from_existing`: `reusable` chỉ nhận cùng render key của cả file; thêm intro làm key đổi nhưng nội dung cũ vẫn dùng được, kể cả nguồn đã dọn.
- `khaithi_thumbs.intro_context`, `vertical_clip`: `build_episode` dựng mọi clip / cả hai chiều, không phù hợp render một clip. Tái dùng `before_start`, `cache_key`, `choose_portrait`, `draw`, `thumbnail.reusable`, không đổi key/byte THUMB1.
- `enqueue_intro_rebuild`: chưa có selector playlist + khoảng tập + intro hiện hành; tái dùng runner/priority/render target, không thêm queue hay UI.

Diff ứng dụng **+496 / −32**, test **+376 / −0** (gồm file mới, tính theo `git diff --numstat` cộng số dòng file untracked). Không tính contract.

### Verification đã chạy

Mọi lệnh pytest dưới đây dùng `timeout 290s env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/kti1/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2`:

| Test arguments | Kết quả |
|---|---|
| `tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py` | **96 PASS**, 115.07 s, sau thay đổi cuối |
| `tests/test_compilation_thumbs.py tests/test_compilation.py` | **65 PASS**, 83.37 s |
| `tests/test_theme_index.py tests/test_theme_plan.py tests/test_theme_render.py` | **250 PASS**, 111.85 s |
| `tests/test_render_stage.py tests/test_render_reuse.py tests/test_render_plan.py tests/test_render_cp9.py` | **76 PASS**, 283.68 s |
| `tests/test_render_stage.py tests/test_render_reuse.py` | **28 PASS**, 89.65 s, chạy lại sau thêm đường dùng clip cũ |
| `tests/test_vertical_silence_intro.py tests/test_store_shorts_edit.py tests/test_khaithi_ac1.py tests/test_render_parallel.py` | **56 PASS**, 138.40 s |
| `-m slow tests/test_render_stage.py tests/test_render_reuse.py tests/test_render_parallel.py` | **5 PASS**, 51.32 s |

- `node scripts/framework-check.mjs`: PASS; `git diff --check`: PASS; `node --check src/auto_short/web/static/app.js`: PASS.
- Hai lượt gộp tuần tự ban đầu (nhóm KTI1/THUMB/compilation/theme và nhóm render/VERT2/kho) hết 290 s, exit 124, chưa hoàn tất, không tính PASS. Đã tách nhóm chạy lại thành công như bảng. Trong vòng sửa, test phát hiện màu JPEG/BT709 và AAC dời timestamp; đã sửa, ca pixel / silence đủ 3 s / keyframe / framemd5 hiện PASS.

### Chưa chạy / giới hạn còn lại

- `<prefix> -n auto` toàn suite và TestClient AC3: không chạy theo ràng buộc sandbox không loopback; route trực tiếp đã kiểm, chưa thay cho kiểm UI trình duyệt.
- Chạy thật 8080, gửi 10 s đầu VLT, ghép so bản cũ, bộ Cảm Ứng Thiên thiếu bìa, đợt dựng lại / upload kho 3090: để ORCHESTRATOR thực hiện sau review/merge theo contract. Không xác nhận dữ liệu thật hoặc thao tác YouTube.
- NTSC có offset theo frame (≈3.003 s), không giả định mọi clip luôn có offset đúng 3.000 s. Sửa title/cut hoặc đổi intro đã có vẫn cần đường nguồn/render hiện hành; đường không cần nguồn chỉ áp dụng thêm intro lần đầu vào nội dung được xác minh hiện hành.
- ORCHESTRATOR (2026-10-29): review diff (inventory ⊆ Owned paths; `render/intro.py` tách từ VERT2; intro encode riêng 3 s rồi concat copy trước nội dung — byte nội dung giữ nguyên nên plan TC3 không stale, clip đã giải phóng lên kho gắn intro không cần nguồn). Codex 213.755 tokens, 1 vòng.
  - Full suite `-n auto`: **3469 passed, 2 failed, 1 skipped** — `test_ollama_wait_runner.py::test_posts_compose_202_while_down`, `test_theme_render.py::test_description_refresh_on_cache_hit_without_encoding[...]`; chạy riêng (`tests/test_theme_render.py` + test Ollama) 3 lần: **42 passed** mỗi lần (test theme_render cũng chập chờn trên nhánh FIX không đụng file này).
  - Media thật (bản sao, không đụng output): VLT tập 31 `RmhVpxr-U_I.kt/k01` + thumbnail KT THUMB1 → `intro.prepend`: 29,97 fps, offset 3,003 s; 243,376 → 246,379 s; `ffmpeg -f null` không lỗi; 7294 khung nội dung framemd5 trùng bản gốc, 90 khung intro; khung 1,5 s = thumbnail đúng clip, 3,2 s = nội dung.
  - Còn: chạy thật trên 8080 (job render 1 tập VLT ≥ 31, ghép 1 video yêu thích có clip đó), đợt dựng lại theo D-KTI1-5 sau khi Cảm Ứng Thiên / Thập Thiện cài bìa KT (HUMAN LEAD chọn 2026-10-29: CƯT mẫu 3, TT mẫu 4), manual checklist.

### Vòng sửa 2 — D-KTI1-6 (2026-10-29)

IMPLEMENTER READY cho ORCHESTRATOR review; giữ nguyên D-KTI1-6 và ghi nhận review/chạy thật của vòng trước. Không commit / push / PR, agent khác, mạng thật, TestClient hoặc full suite.

- File đổi vòng này: `src/auto_short/render/intro.py`, `src/auto_short/render/stage.py`, `src/auto_short/packaging/khaithi_thumbs.py`; thêm ca/assertion vào `tests/test_khaithi_intro.py`, `tests/test_vertical_silence_intro.py`; Result contract. **Không sửa `render/full.py`**.
- KTI1 freeze khung 0 của content bằng `trim=end_frame=1` + `tpad` ngay trong graph, rồi `xfade=transition=fade:duration=1:offset=<số giây intro thực − 1>`. Prefix vẫn đúng số khung cũ (75 @ 25 fps, 90 @ 29,97), audio chỉ lấy `anullsrc`; nội dung concat copy bắt đầu lại từ khung 0. VERT2 giữ nhánh filter mặc định cũ, command / key không thêm transition.
- `intro.transition={"type":"fade","seconds":1}` nằm trong key render và stage inputs. Selector không bỏ qua intro legacy thiếu transition. Cả render mới (`_encode_one`) và clip có sẵn (`_intro_from_existing`) dùng cùng `prepend`; thay intro cũ bằng cách tách content `-c copy`, giữ `content_sha256`, `content_render_key`, offset và fingerprint nội dung. **Cập nhật giới hạn vòng trước:** thay intro đã có giờ cũng dùng được khi nguồn đã dọn, miễn content hiện hành được xác minh; sửa title/cut/config vẫn đi đường render hiện hành.
- Helper mới: `intro.metadata` gom identity hiệu ứng dùng chung cho render/selector, thay dict lặp; `intro.extract_content` tách theo offset hiện có bằng stream copy bắt buộc. Đã tra `rg -n 'def .*extract|def normalize_command|inpoint|def assemble' src/auto_short/render src/auto_short/compilation src/auto_short/theme_render`: `assemble` có fallback encode nên không phù hợp yêu cầu bắt buộc giữ packet khi thay intro; tiếp tục dùng `offset`, `content_record`, `prepend`, concat command cũ. Không thêm dependency / ảnh tĩnh trung gian.

| AC / yêu cầu vòng 2 | Test |
|---|---|
| D6, AC1/5: đầu là thumbnail, giữa hòa trộn, cuối gần khung 0, im lặng đủ 3 s, cache/key/title | `test_intro_pixels_silence_content_sha_cache_and_title` (fresh / existing), helper test `assert_fade` |
| D6, AC4/6: intro legacy → thay, selector nhận cũ, không cần nguồn, giữ content SHA/key/offset/framemd5 | `test_legacy_intro_replaced_with_fade_without_source_or_content_encode` (25 fps B-frame / NTSC; gồm stage inputs định dạng cũ), regression `test_compilation_copy_and_reencode_skip_intro` |
| VERT2 giữ nguyên, TC3 không stale | `test_kti1_fade_keeps_vert2_graph_and_command_bytes` (golden SHA graph/command lấy từ HEAD `a1f9914`, 2 fps); các ca render thật/cache VERT2 hiện có; 3 ca KTI1 của `test_theme_render.py` |

Diff **so HEAD a1f9914, chỉ vòng sửa này**: ứng dụng **+50 / −19**, test **+100 / −0** (`git diff --numstat`, không tính contract / dòng D6 HUMAN LEAD đã thêm).

Verification đã chạy (mọi pytest có `timeout 290s`, không socket):

- `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/kti1/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2 tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py tests/test_vertical_silence_intro.py`: **114 PASS**, 129.73 s.
- Cùng prefix Python, không `-n 2`, `tests/test_khaithi_intro.py -k legacy_intro` sau bổ sung stage inputs legacy chính xác: **2 PASS, 12 deselected**, 20.30 s.
- Cùng prefix Python, không `-n 2`, `tests/test_theme_render.py -k kti1`: **3 PASS, 38 deselected**, 16.20 s; kiểm approval / reference / dựng TC3 thực và framemd5.
- `node scripts/framework-check.mjs`: **PASS**; `git diff --check`: **PASS**.

Chưa chạy vòng này: full suite / TestClient (theo ràng buộc); dữ liệu thật 8080/3090 và xem hiệu ứng thực để HUMAN LEAD duyệt. Trạng thái task vẫn `IN_PROGRESS` chờ ORCHESTRATOR xác nhận các gate đó; kết quả full suite/chạy thật vòng trước giữ nguyên ở trên, không suy ra PASS cho vòng này.
- ORCHESTRATOR vòng sửa 2 (D-KTI1-6, Codex resume 471.570 tokens tích lũy): review `render/intro.py` (khung 0 nội dung đóng băng trong graph, `xfade=fade` 1 s, intro cũ được thay bằng stream copy, VERT2 giữ graph / key). Full suite `-n auto`: **3475 passed, 1 skipped**. Media thật (bản sao VLT 31 k01): giải mã không lỗi, 90 khung intro, 7294 khung nội dung trùng framemd5, offset 3,003 s; mẫu GIF / 7 s gửi HUMAN LEAD.
