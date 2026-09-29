# Task: CP9 — Thêm Short từ đoạn tự chọn + sửa điểm đầu/cuối

## Status / Approval

- Status: APPROVED
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

- [ ] Điện thoại + desktop: "Thêm Short" từ đề xuất AI và từ transcript, nghe Short mới, sửa title.
- [ ] "Sửa đầu/cuối": thêm/bớt dòng, ±0.2 s, "Nghe thử", lưu → nghe lại; "Về như AI chọn".
- [ ] Số `S<NN>`, tick "Đã đăng", tên file tải về của Short cũ không đổi.
- [ ] Tập khai thị làm được như trên.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
