# Task: CP9 — Thêm Short từ đoạn tự chọn + sửa điểm đầu/cuối

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `f39c86e` (`origin/main`) / `feature/cp9-clip-review` (worktree `../youtube-auto-short-cp9`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-29: APPROVE; nguồn đoạn = đề xuất AI còn lại + chọn trên transcript; đoạn mới = **thêm** Short mới; title Short mới = AI đặt, sửa tay được; sửa đầu/cuối = theo dòng caption + tinh chỉnh ±0.2 s; C1–C9 theo đề xuất, gồm "Nghe thử" từ video nguồn và cho phép chồng lấn)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) mở rộng `review.json` v1 (canonical `docs/decisions/CP8.2-title-override-contract.md`) với điểm cắt tay và Short thêm tay; (b) đổi luật render (CP7 R2/R3: clip ngoài `clips.json`, đoạn giữ lại không lấy từ candidate) và schema `render_manifest.json` (entry Short thêm); (c) gọi AI titling ngoài stage `titling` (CP6); (d) route API / job web mới (CP8.3 W5, W7). Không thêm dependency, không đổi security model.

## Bối cảnh

Re-plan HUMAN LEAD 2026-09-29: phần CP9 còn lại chỉ gồm hai việc; các mục khác của CP9 cũ đã làm ở CP8.x (sửa title CP8.2, xóa/khôi phục CP8.5, render lại từng Short CP8.2 T5, bộ kinh + hàng đợi CP8.7/CP8.10, "Lỗi / dở dang" + "Chạy tiếp" CP8.13). "Xử lý tất cả" một bộ kinh: không làm. CP10: đóng (không làm).

Số đo 2026-09-29 (26 tập trong `work/`): đề xuất AI không được chọn chỉ 0–5 mỗi tập (hầu hết `overlapped`); `candidates.json` có 119–2194 candidate mỗi tập nhưng không có topic/điểm. Dòng caption (`transcript.json` `segments`) thường ngắn (vd "yêu cầu tôi"), không phải câu trọn.

## Goal

Trên trang tập (Short và khai thị):

1. **Thêm Short**: chọn một đề xuất AI còn lại (topic, điểm, lý do) hoặc chọn dòng caption đầu + dòng cuối trên transcript → Short mới được AI đặt title rồi render; Short cũ không đổi số, không mất tick "Đã đăng".
2. **Sửa đầu/cuối** của bất kỳ Short nào: thêm/bớt từng dòng caption ở đầu hoặc cuối, tinh chỉnh ±0.2 s → chỉ Short đó render lại.

## Quyết định (duyệt 2026-09-29)

- **C1. Lưu ở `review.json`** (additive, giữ `schema_version: 1`, như CP8.5): hai key tùy chọn sau `rejected`, chỉ ghi khi không rỗng:
  - `"cuts": [{"clip_id", "candidate_id", "start", "end"}]` — điểm cắt tay (giây, 3 chữ số) cho clip AI hoặc clip thêm; khóa `(clip_id, candidate_id)` như CP8.2 T3 (selection chạy lại → bỏ qua + cảnh báo).
  - `"added": [{"clip_id", "candidate_id", "start", "end", "source", "title", "ai_title", "alternatives"}]` — Short thêm. `clip_id` = `m01`, `m02`… không bao giờ dùng lại (kể cả sau khi xóa); `candidate_id` = candidate của đề xuất AI được chọn, hoặc `"manual"` khi chọn trên transcript; `source` = `proposal` | `transcript`. Không bị bỏ khi selection chạy lại.
  - Title Short thêm: `title` = title đang dùng (`origin` như CP8.2), `ai_title` + `alternatives` = kết quả AI. Sửa title / xóa / khôi phục / tick "Đã đăng" dùng chung luật CP8.2 T1–T7 và W8 với khóa `(clip_id, candidate_id)`.
- **C2. Thứ tự và tên file:** Short thêm nằm **sau** mọi clip của `clips.json` trong `render_manifest.json` `shorts`, theo thứ tự tạo → số `S<NN>` / `KT<NN>` của Short đã có không đổi (W8).
- **C3. Chọn trên transcript → khoảng thời gian:** dòng đầu `a`, dòng cuối `b` (segment `speech`). `start` = mép lời nói trước `a` theo luật CP4 A6 (lấy `end` khoảng lặng gần `a.start` trong ±`align_tolerance`, trừ `boundary_pad`, không lấn dòng trước); `end` tương tự quanh `b.end`. Tinh chỉnh ±0.2 s cộng dồn trên điểm đó, tối đa ±2.0 s, không vượt `content` window, không cắt vào dòng kề bên quá 2.0 s. Sửa đầu/cuối Short có sẵn dùng cùng luật, bắt đầu từ `source_start`/`source_end` hiện tại.
- **C4. Điều kiện hợp lệ** (vi phạm → 422, không ghi): nằm trong `content` của `candidates.json`; không chứa segment `non_speech` / hard break (CP4 A4); `duration` sau rút khoảng lặng trong `[min_duration, max_duration]` của `candidates.json` tập đó (Short 30–180 s, khai thị theo khoảng phút). Chồng lấn Short khác: **cho phép**, UI cảnh báo. Không áp shot guard (cảnh báo nếu có chuyển shot trong 1 s đầu/cuối).
- **C5. Render đoạn tay:** `trims` tính lại từ `silences.json` cho `[start, end]` bằng đúng luật CP4 A8 (`max_pause`), không dùng `trims` của candidate; phần còn lại theo CP7 R3–R11. Clip có cut tay: header giữ nguyên, title giữ nguyên (không gọi lại AI). `render_manifest.shorts[]` thêm `origin` (`ai` | `added`) và `cut` (`null` | `{"start", "end"}`); schema giữ v1 (key thêm cuối entry). `render_key` đã gồm `segments` → chỉ Short đổi được encode (CP8.2 T5).
- **C6. Title AI cho Short thêm:** gọi đúng prompt/validate/retry của CP6 (G3–G6, `[titling]` hiện hành) cho **một** clip; AI lỗi hết lượt → Short vẫn được thêm nhưng `untitled`, chờ title tay (như CP7 R2). Log gọi AI ghi `work/<id>/review_titling_log.json` (append, không byte-stable). Chạy ở làn `ai` (CP8.10), cần Ollama preflight như W4.
- **C7. Web:**
  - Trang tập: nút "Thêm Short" → hộp thoại hai tab: "Đề xuất AI (n)" (đề xuất `overlapped` / `over_limit` / `ineligible` có candidate, hiện topic, điểm, lý do, thời lượng, chồng lấn Short nào) và "Chọn trên transcript" (danh sách dòng caption có mốc thời gian, Short hiện có tô màu; bấm dòng đầu rồi dòng cuối, hiện thời lượng + lỗi C4 ngay).
  - Mỗi thẻ Short: "Sửa đầu/cuối" → hiện chữ dòng đầu/cuối, nút [+ dòng] [− dòng] và [−0.2 s] [+0.2 s] cho mỗi đầu, thời lượng mới, "Nghe thử" (phát video nguồn 5 s quanh điểm đầu/cuối), "Lưu + render lại", "Về như AI chọn".
  - Route mới (cookie W2, cùng lock + 409 khi có job, 422 `ReviewError`): `GET /api/episodes/{id}/transcript`, `GET /api/episodes/{id}/proposals`, `POST /api/episodes/{id}/cut/preview` (không ghi), `POST /api/episodes/{id}/shorts/{clip}/cut` (`{start_segment, end_segment, start_nudge, end_nudge}` \| `{reset: true}`) → 202 `{preview, job}`, `POST /api/episodes/{id}/shorts` (thêm) → 202 `{clip_id, job}`, `GET /files/{id}/source.mp4` (Range, chỉ để nghe thử).
  - Tập đã dọn video nguồn (CP8.6): thêm / sửa đầu-cuối → 409 như `ArchivedError`.
- **C8. Không CLI mới** (như xóa/khôi phục CP8.5, chỉ web).
- **C9. Tài liệu canonical:** CP8.2 contract (T1 thêm `cuts` / `added`, T8 mới luật cut), CP7 R2/R3/R11 (sửa đổi CP9), CP8.3 W5/W7/W8 (route, job, UI), CP1 §8 bảng stage `review` (partial → CP9), `docs/ai/project-profile.md` dòng `review/`.

## Scope

- In scope: `src/auto_short/review/` (logic cut + added, hàm theo episode), `src/auto_short/render/stage.py` (đoạn tay, clip thêm, manifest), `src/auto_short/titling/` (hàm titling một clip, không đổi stage), `src/auto_short/web/` (route, job, UI trang tập Short + khai thị), tests, docs theo C9, `AUTO_SHORT_CHECKPOINT_PLAN.md`, `docs/workflow/current-state.md`.
- Out of scope: "Xử lý tất cả" bộ kinh; CP10 (đo chất lượng); CLI; sửa header; đổi title tự động khi sửa đầu/cuối; tự chống chồng lấn; cắt mức từ (word) ngoài tinh chỉnh ±0.2 s; render lại tập cũ tự động; đổi prompt selection/titling.

## Acceptance Criteria

1. `review.json` có `cuts` / `added` đọc/ghi/validate đúng C1; file không có hai key vẫn đọc như CP8.2/CP8.5; bỏ Short thêm / cut cuối cùng đưa file về byte-identical trước đó.
2. Sửa đầu/cuối một Short → chỉ Short đó encode lại (các Short khác reuse byte-identical); `render_manifest` ghi `cut`; "Về như AI chọn" → encode lại ra byte-identical bản gốc.
3. Đoạn không hợp lệ theo C4 → 422 với lý do đọc được, `review.json` không đổi.
4. Thêm Short từ đề xuất AI và từ transcript → AI đặt title (hoặc `untitled` chờ title tay khi AI lỗi), render ra `m01.mp4`; số `S<NN>` và tick "Đã đăng" của Short cũ không đổi; tên tải về / zip theo W8.
5. Short thêm sửa title / xóa / khôi phục / tick / sửa đầu-cuối được như Short AI.
6. Selection chạy lại: `cuts` của clip AI bị bỏ qua + cảnh báo; `added` giữ nguyên.
7. Tập khai thị (`.kt`) làm được 1–5 với khoảng thời lượng của tập đó.
8. Tập đã dọn nguồn → 409; job đang chạy → 409.
9. Toàn bộ test suite PASS.

## Required verification

- `conda run -n auto-short python -m pytest -q` — toàn bộ PASS (AC 1–9, test mới cho logic cut/added, trims C5, render reuse, route web).
- Chạy thật trên một tập Short và một tập `.kt` (bản sao trong thư mục test, không ghi đè `work/` / `output/` chính): sửa đầu/cuối 1 Short, thêm 1 Short từ đề xuất AI và 1 từ transcript; ghi số encode/reuse, sha256, thời gian vào Result (AC 2, 4, 7).
- Mẫu nghe (theo thói quen HUMAN LEAD): gửi file Short trước/sau khi sửa đầu/cuối để HUMAN LEAD nghe.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (route web mới) → manual test là gate trước integration.

Kết quả: **ĐẠT** — HUMAN LEAD 2026-09-29, server test 8081 (code `206ba3b`, bản sao `7axON1RpRjo`, `4oOZz2CBz3g`, `4oOZz2CBz3g.kt` ở `~/.cache/auto-short-cp9-test/`).

- [x] Điện thoại + desktop: "Thêm Short" từ đề xuất AI và từ transcript, nghe Short mới, sửa title.
- [x] "Sửa đầu/cuối": thêm/bớt dòng, ±0.2 s, "Nghe thử", lưu → nghe lại; "Về như AI chọn".
- [x] Số `S<NN>`, tick "Đã đăng", tên file tải về của Short cũ không đổi.
- [x] Tập khai thị làm được như trên.

## Result

- Main changes:
  - `src/auto_short/review/logic.py`: `review.json` `cuts` / `added` (C1: đọc / ghi / validate, thứ tự key, chỉ ghi khi không rỗng), `resolve_cuts` (khóa `(clip_id, candidate_id)`), origin suy ra của title Short thêm, `next_added_id`.
  - `src/auto_short/review/cuts.py` (mới, thuần): điểm C3 theo CP4 A6, tinh chỉnh ±0.2 s (≤ ±2.0 s, content, ≤ 2 s vào dòng kề), dòng thuộc khoảng, C4, trims C5 (`analysis.candidates.plan_trims`).
  - `src/auto_short/review/shorts.py` (mới): `transcript_view`, `list_proposals`, `preview_cut`, `set_cut`, `reset_cut`, `add_short`, `added_titling_input`, `set_added_ai_title`; `ArchivedError` khi đã dọn nguồn. `review/titles.py`: sửa title / phương án / reset / xóa / khôi phục Short thêm.
  - `src/auto_short/titling/added.py` (mới): title AI một Short thêm bằng prompt / validate / retry CP6, log `review_titling_log.json` (C6).
  - `src/auto_short/render/stage.py`: `render_targets` (clip `clips.json` rồi Short thêm, C2), khoảng tay với trims từ `silences.json` (C5), manifest thêm `origin`, `cut` (key cuối), R9 theo targets; `render_key` không đổi cách tính.
  - `src/auto_short/web/`: route C7 (`transcript`, `proposals`, `cut/preview`, `shorts/{clip}/cut`, `shorts`, `files/{id}/source.mp4`), job `add` (làn `ai` → `render`), `origin` / `cut` trong `shorts[]`; UI trang tập (Short + khai thị): "+ Thêm Short" (2 tab), "Sửa đầu/cuối", trình phát "Nghe thử".
  - Docs canonical (C9): CP8.2 T1 + T8 mới + hàm dùng chung + quyết định khi implement; CP7 R2, R3, R9, R11; CP8.3 W5, W6, W7, W8; CP1 §8; project profile; `AUTO_SHORT_CHECKPOINT_PLAN.md` CP9.
- Tests: `PYTHONPATH=src python -m pytest -q` (conda env `auto-short`) → **961 passed** (trước CP9: 898). Mới: `tests/test_review_cp9.py` (C1 schema, round-trip byte-identical, C3/C4/C5, hàm theo episode, archived, selection chạy lại, khai thị), `tests/test_render_cp9.py` (ffmpeg thật: cut → 1 encode + reuse byte-identical, reset → byte-identical, Short thêm sau clip, untitled / xóa / khôi phục / cut Short thêm, cut stale bị bỏ qua, silences không khớp), `tests/test_titling_added_cp9.py`, `tests/test_web_cp9.py` (route, 409 job / archived, 422, 503, job `add`, lanes + serial). Test cũ sửa vì schema đổi theo contract: `test_render_stage.py` (+ `origin`, `cut`), `test_review.py` (+ `added`).
- Chạy thật (2026-09-29, bản sao trong scratch, config test riêng; không ghi `work/` / `output/` chính; qua web app + render thật + Ollama `qwen3:14b` thật; máy có render nền `youtube:rerender` chạy song song):

  | Tập | Bước | Thời gian job | Encode / reuse | sha256 (12) |
  |---|---|---|---|---|
  | `7axON1RpRjo` (12 clip, 11 Short) | `k02` sửa đầu/cuối: đầu −0.2 s, cuối + 1 dòng ("hôm nay"): 159.588–210.122 → 159.388–215.751, 41.4 → 43.5 s | 22.2 s | 1 / 10 | `9ae5348ec29c` |
  | | "Về như AI chọn" | 20.2 s | 1 / 10 | `9ed2bed020a8` = bản gốc (byte-identical) |
  | | thêm từ đề xuất AI (`overlapped`, chồng lấn `k03`) → `m01` "tại gia có nhiều bồ tát hơn xuất gia", 46.0 s | 28.3 s (title 5.3 s) | 1 / 11 | `d6bc3d9ad1b1` |
  | | thêm từ transcript `s00037`–`s00056` → `m02` "Tại sao nói pháp ở mọi nơi, từ vũ trụ đến một sợi lông?", 63.6 s | 34.2 s (title 3.1 s) | 1 / 12 | `8a4cd65e3ef8` |
  | `4oOZz2CBz3g.kt` (6 video, 4–7 phút) | `k01` đầu −0.2 s, cuối + 1 dòng: 243.1 → 245.9 s | 113.1 s | 1 / 5 | `8adf32e7623f` |
  | | "Về như AI chọn" | 113.0 s | 1 / 5 | `9b038af3d0b7` = bản gốc (byte-identical) |
  | | thêm từ đề xuất AI (`overlapped`, chồng lấn `k05`) → `m01` "muốn thành công trên đường tu, điều kiện đầu tiên là gì?", 277.4 s | 149.8 s | 1 / 6 | `b5e96c377fe6` |
  | | thêm từ transcript `s00014`–`s00252` → `m02` "tâm có vọng tưởng là thế gian pháp", 419.0 s | 175.3 s | 1 / 7 | `964b0c9215f6` |

  Sau mọi bước, mọi Short gốc không đổi byte (11/11 và 6/6). Số `S<NN>` / `KT<NN>` của Short cũ giữ nguyên, Short thêm là `S13`/`S14` (sau 12 clip, gồm `k01` bỏ qua `untitled`), `KT07`/`KT08` — kiểm bằng tên tải về (vd `Tập7_S13_tại gia có nhiều bồ tát hơn xuất gia.mp4`). Mẫu nghe (scratch của phiên IMPLEMENTER, `…/scratchpad/cp9/samples/`): `7axON1RpRjo_before_k02.mp4`, `7axON1RpRjo_after_cut_k02.mp4`, `7axON1RpRjo_added_m01.mp4`, `7axON1RpRjo_added_m02.mp4`, `4oOZz2CBz3g.kt_before_k01.mp4`, `4oOZz2CBz3g.kt_after_cut_k01.mp4`, `4oOZz2CBz3g.kt_added_m01.mp4`, `4oOZz2CBz3g.kt_added_m02.mp4`.
- Review: ACCEPTED (ORCHESTRATOR 2026-09-29): diff theo contract C1–C9, AC 1–9; pytest chạy lại 961 passed; quyết định khi implement (CP8.2 T8) chấp nhận. Manual test checklist (public API) là gate trước integration.
- Important findings / decisions:
  - Quyết định khi implement (ORCHESTRATOR chấp nhận, ghi ở CP8.2 § Quyết định khi implement): title Short thêm lưu ở `added[].title`, origin suy ra; text AI = các dòng thuộc khoảng; khoảng đề xuất gồm head cut B11 của đề xuất, trims luôn tính lại; `cut/preview` trả lỗi C4 trong `error` (200); AI lỗi → Short `untitled`, render vẫn chạy, job `failed`; `m<NN>` không dùng lại (review + publish + render manifest); "Nghe thử" = media fragment trên nguồn (5 s đầu / cuối, chưa rút khoảng lặng).
  - Chạy thật thấy hai lỗi ở luật dòng (đã sửa + test hồi quy): (1) điểm C3 chọn nhầm khoảng lặng của dòng trước khi mốc caption của dòng nằm trong khoảng lặng đó → nay chỉ xét khoảng lặng kết thúc trước `a.end` / bắt đầu sau `b.start` như A6; (2) dòng thuộc khoảng xét theo trung điểm caption để sót dòng ngắn bị caption kéo dài qua khoảng lặng ("nhân sinh" của `k02`) → nay theo khoảng lời nói căn audio của chính dòng đó. Trước khi sửa, "+ dòng" ở cuối `k02` không đổi điểm cuối.
- Known limitations:
  - Tổng số Short vượt 99 do thêm → độ rộng số tải về đổi (`S<NN>` → `S<NNN>`) cho mọi Short (W8).
  - Mốc caption tự động gần đúng; điểm C3 có thể lệch lời nói, dùng ±0.2 s + "Nghe thử". "Nghe thử" phát nguồn chưa rút khoảng lặng.
  - Title AI có thể bắt đầu chữ thường (`4oOZz2CBz3g.kt` `m02`); CP6 G5 không bắt luật này — sửa tay được.
  - `GET /transcript` tập khai thị dài ~1.7 s (tính dòng thuộc khoảng cho mọi Short); chấp nhận.
- Manual test: ĐẠT (HUMAN LEAD 2026-09-29, 8081).
- PR: `feature/cp9-clip-review` → `main` (HUMAN LEAD 2026-09-29: push + PR).
