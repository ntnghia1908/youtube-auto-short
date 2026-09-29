# CP8.2 — Manual Title Override + Single-Short Rerender Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | — (T1–T6, P1 `review.json`, P2 luật hình thức + fit duyệt cùng APPROVE TASK 2026-09-27; review ACCEPTED). Sửa đổi HUMAN LEAD 2026-09-27 (CP8.5, APPROVE TASK X2, P3): `review.json` `rejected` (T1, T7). Sửa đổi HUMAN LEAD 2026-09-29 (CP9, APPROVE C1–C9): `review.json` `cuts` / `added` (T1), điểm cắt tay + Short thêm tay (T8) |
| Checkpoint | CP8.2 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` CP8.2 (re-plan HUMAN LEAD 2026-09-27: sửa title tay kéo từ CP9 lên) |
| Task contract | `docs/tasks/CP8.2-title-override.md`; sửa đổi CP8.5: `docs/tasks/CP8.5-web-review.md`; sửa đổi CP9: `docs/tasks/CP9-clip-review.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §6, §8; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP6-titling-contract.md` G5, G6, G7; `docs/decisions/CP7-render-contract.md` R2, R5, R8, R9, R11 (+ CP8.1) |

File này là **canonical owner** của artifact `review.json` v1 (title override; Short bị xóa `rejected` — sửa đổi CP8.5, T7; điểm cắt tay `cuts` và Short thêm tay `added` — sửa đổi CP9, T8), luật validate title tay, khóa override, thứ tự ưu tiên nguồn title khi render, `render_key` và luật tái dùng từng Short, luật khoảng thời gian của đoạn tay (T8), cùng lệnh CLI `auto-short title`. Nơi khác chỉ trỏ tới đây. Layout, fit chữ, cách dựng lệnh `ffmpeg` và schema `render_manifest.json`: `docs/decisions/CP7-render-contract.md`. Sửa header, approve từng Short: không làm (re-plan CP9 HUMAN LEAD 2026-09-29).

Implementation tham chiếu: `src/auto_short/review/` (`logic.py` thuần; `titles.py` hàm theo episode dùng chung CLI + web; CP9: `cuts.py` thuần — khoảng thời gian, hợp lệ, trims; `shorts.py` hàm theo episode cho web), `src/auto_short/titling/added.py` (CP9: title AI một Short thêm), `src/auto_short/render/stage.py` (áp override, đoạn tay, Short thêm, `render_key`, tái dùng, commit/dọn output), `src/auto_short/cli.py` (`title`).

## T1. `review.json` v1

- Path `work/<episode_id>/review.json`. Người sửa (qua CLI/web), không phải stage: không có entry trong `manifest.json` (stage `review` vẫn `pending`); không có file = không override.
- Thứ tự key cố định, ghi atomic (`os.replace`), JSON indent 2, không timestamp:

```json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
 "titles": [{"clip_id": "k03", "candidate_id": "c00361", "title": "Tâm thiện thì gương mặt cũng hiền hòa",
             "origin": "manual"}]}
```

- `titles` chỉ chứa clip có override, mỗi `clip_id` tối đa một entry, sắp theo thứ tự `clips.json` (entry có `clip_id` không còn trong `clips.json` ở cuối, theo `clip_id`). `origin` = `manual` (gõ tay) | `alternative` (chọn từ `titles.json` `alternatives`). `title` đã chuẩn hóa (NFC, bỏ khoảng trắng hai đầu, gộp khoảng trắng).
- Reset override cuối cùng để lại file với `titles: []` (không xóa file).
- **Sửa đổi CP8.5** (additive, giữ `schema_version: 1`; HUMAN LEAD 2026-09-27, `docs/tasks/CP8.5-web-review.md` X2): key thứ tư tùy chọn `"rejected": [{"clip_id", "candidate_id"}]` — Short bị xóa (T7). Chỉ ghi khi không rỗng (khôi phục Short cuối cùng bỏ key, file trở lại đúng dạng 3 key); cùng luật sắp xếp như `titles`.
- **Sửa đổi CP9** (additive, giữ `schema_version: 1`; HUMAN LEAD 2026-09-29, `docs/tasks/CP9-clip-review.md` C1): sau `rejected` hai key tùy chọn, theo thứ tự `cuts` rồi `added`, chỉ ghi khi không rỗng (bỏ cut / Short thêm cuối cùng → file trở lại đúng dạng trước):
  - `"cuts": [{"clip_id", "candidate_id", "start", "end"}]` — điểm cắt tay (giây, ≥ 0, tối đa 3 chữ số, `start < end`) của một Short AI hoặc Short thêm; khóa `(clip_id, candidate_id)` như T3; sắp theo thứ tự Short (clips.json rồi Short thêm).
  - `"added": [{"clip_id", "candidate_id", "start", "end", "source", "title", "ai_title", "alternatives"}]` — Short thêm tay, theo thứ tự tạo. `clip_id` = `m01`, `m02`… (không bao giờ dùng lại: số mới = lớn nhất từng thấy trong `review.json`, `publish.json`, `render_manifest.json` + 1); `source` = `proposal` (đề xuất AI còn lại, `candidate_id` = candidate của nó) | `transcript` (`candidate_id` = `"manual"`); `start` / `end` = khoảng lúc thêm (T8); `title` = title đang dùng (`null` = `untitled`), `ai_title` + `alternatives` (`[{"title", "evidence"}]`) = kết quả AI (T8). Origin của title Short thêm suy ra, không lưu: `ai` khi `title` = `ai_title`, `alternative` khi `title` là một phương án trong `alternatives`, còn lại `manual`. Không bị bỏ khi selection chạy lại.
- Kiểm khi đọc (vi phạm → lỗi, render `failed`): object đúng 3 key trên (+ `rejected`, `cuts`, `added` tùy chọn theo đúng thứ tự đó), `schema_version` 1, `episode_id` khớp, mỗi entry đúng 4 key, mọi giá trị chuỗi không rỗng, `origin` hợp lệ, `title` đã chuẩn hóa, `clip_id` không trùng; `rejected` (nếu có) là mảng không rỗng, mỗi entry đúng 2 key chuỗi không rỗng, `clip_id` không trùng; `cuts` / `added` (nếu có) là mảng không rỗng, entry đúng key trên, thời gian như trên, `added.clip_id` dạng `m<NN>`, `source` hợp lệ và khớp `candidate_id` (`manual` ⇔ `transcript`), `title` / `ai_title` `null` hoặc chuỗi đã chuẩn hóa, `clip_id` không trùng trong từng mảng. Luật hình thức T2 **không** kiểm lại khi render (chỉ kiểm lúc ghi); glyph + fit luôn được render kiểm lại (CP7 R5).

## T2. Validate title tay (lỗi → từ chối, không ghi)

Theo thứ tự, lý do đầu tiên trượt được báo:

1. Luật hình thức CP6 G5 **1–8** (`titling.logic.form_reject_reason`, cùng code với AI title) với `min_chars` = 1 và `max_chars` = `[titling] max_chars` (60): xuống dòng, rỗng, > 60 ký tự, emoji/pictograph, `#` `@` `!`, URL, bao trong ngoặc kép, viết HOA toàn bộ. **Không** áp luật evidence (G5 9–10) vì người viết.
2. Mọi ký tự có glyph trong font render (CP7 R7) → nếu không: `character(s) not in the font: …`.
3. Fit theo CP7 R5 (≤ 3 dòng, panel ≤ `title_panel_max_height`, không dưới `min_font_scale`) bằng đúng hàm render dùng (`render.stage.fit_clip_title`) → nếu không: `title does not fit: …`.

Chọn alternative N: chép nguyên title AI đó (1-based theo thứ tự `alternatives`), vẫn qua 1–3 (title AI đã qua G5 nên thực tế chỉ còn glyph + fit).

## T3. Khóa override

- Khóa `(clip_id, candidate_id)`: `candidate_id` lấy từ `titles.json` lúc ghi.
- Khi render / liệt kê: override có `clip_id` không còn trong `clips.json`, hoặc `candidate_id` khác (selection chạy lại) → **bỏ qua + cảnh báo** (`title override for clip k03 ignored: …`), không lỗi; override vẫn nằm trong file cho tới khi người dùng đặt lại/reset clip đó (đặt title mới cho clip thay entry cũ).
- Titling chạy lại không xóa override: cùng `(clip_id, candidate_id)` thì title tay vẫn thắng.

## T4. Nguồn title khi render

- Title của clip = override hợp lệ theo T3 > `titles.json` `title` (clip `titled`, auto-approve AI, CP7 P1). Clip `untitled` có override → được render; không override → `skipped` (`untitled`) như CP7 R2.
- `render_manifest.shorts[].title` = title thật được render; `shorts[].title_origin` = `ai | manual | alternative` (`null` cho clip `untitled` không override). `title_source` giữ `"titles"` (CP9 thêm duyệt/loại).
- `review.json` (nếu có) nằm trong `inputs` của stage render (sau `metadata.json`, trước media nguồn) → sửa title làm render không còn up to date (`run (input changed)`).

## T5. `render_key` và tái dùng từng Short

- `render_key` = sha256 JSON canonical của: `plan_version` (`render.plan.RENDER_PLAN_VERSION`, hiện 1 — tăng khi đổi cách dựng filter graph / lệnh `ffmpeg` / hằng encode), `render_config_hash` (CP7 R10, gồm font sha256), `font_sha256`, `source_sha256`, `fps`, `segments`, `dissolves` (kế hoạch CP8.1), `layout` của clip, header (`display_lines` + `font_size`) và title (`display_lines` + `font_size`) — **nội dung** chữ, không phải path file tạm. Ghi ở `shorts[].render_key` (`null` khi `skipped`).
- Khi stage chạy (không `--force`): Short có `render_key` trùng entry `rendered` cùng `clip_id` của `render_manifest.json` cũ **và** `file` = `shorts/<clip_id>.mp4` tồn tại **và** sha256 file = `sha256` đã ghi → **tái dùng** (không encode, stderr `clip <id>: reuse (render_key unchanged)`); còn lại encode. `--force` bỏ tái dùng (encode hết). Đổi key `[render]` trong hash → `render_key` đổi → encode hết. Manifest cũ không có `render_key` (trước CP8.2) → không Short nào tái dùng lần đầu.
- Ghi output (thay R8 cũ "xóa hết trước khi chạy"):
  1. Short cần encode ghi vào `shorts/.<clip_id>.mp4.part`, `ffprobe` kiểm (CP7 R9) và giữ ở `.part`;
  2. sau khi mọi clip xong: validate R9 trên trạng thái sau commit;
  3. commit: `os.replace` từng `.part` → `shorts/<clip_id>.mp4`; xóa file của lần render trước (artifact + file trong `render_manifest.json` cũ, chỉ trong `<output_dir>/<episode_id>/`) **không** còn thuộc lần này (clip bị bỏ/`skipped`); ghi `render_manifest.json` atomic.
- Lỗi (kể cả kiểm input trước khi chạy): chỉ xóa file lần chạy đó đã ghi (`.part`; nếu lỗi xảy ra giữa commit thì cả file đã commit và `render_manifest.json`, vì manifest cũ không còn khớp file). Lỗi trước commit → output của lần render thành công trước **giữ nguyên** (mp4 + manifest khớp nhau), để lần sau vẫn tái dùng được; stage ghi `failed` như CP2.
- `RenderResult` thêm `encoded` / `reused` (số Short); stderr tổng: `rendered n/m clips (e encoded, r reused)`. Stdout CLI `render` giữ nguyên CP7 R10.

## T6. CLI `auto-short title`

```
auto-short title <episode_id> <clip_id> (--set "TEXT" | --alternative N | --reset) [--render] [--config PATH]
auto-short title <episode_id> --list [--config PATH]
```

- `--set` / `--alternative` / `--reset` ghi `review.json` (T1–T3) rồi in xem trước: stdout dòng 1 `<episode_id>\t<clip_id>\t<origin>\t<title>`, dòng 2 `  display (<cỡ> px, panel <cao> px): <dòng 1> / <dòng 2> / …` (reset clip `untitled`: `<episode_id>\t<clip_id>\tuntitled\t-` + `  not rendered: …`). `--render` chạy tiếp `render` (in thêm dòng stdout của `render`, CP7 R10).
- `--list`: mỗi clip `<clip_id>\t<candidate_id>\t<origin|untitled>\t<title render dùng|->`, rồi `  AI: …`, `  <n>: <alternative>` (đánh số cho `--alternative`), `  override (<origin>): …` nếu có; override bị bỏ qua (T3) cảnh báo ở stderr.
- Exit code CP2 D8: title không hợp lệ, clip / alternative không tồn tại, titling chưa `done`, `review.json` hỏng → 1, `review.json` không đổi; sai cú pháp (thiếu hành động, hai hành động) → argparse 2.

## T7. Xóa / khôi phục một Short (sửa đổi CP8.5)

- Khóa `(clip_id, candidate_id)` như T3: entry `rejected` có `clip_id` không còn trong `clips.json` hoặc `candidate_id` khác → **bỏ qua + cảnh báo** (`deleted Short k05 ignored: …`), clip được render lại bình thường.
- Render: clip bị xóa → `status: "skipped"`, `skip_reason: "rejected"` (CP7 R2), không file, không fit title; `title` / `title_origin` vẫn ghi title sẽ dùng khi khôi phục. Ưu tiên hơn `untitled`. File mp4 cũ bị xóa ở bước commit (T5: file của lần trước không còn thuộc lần này); các Short khác tái dùng. Stderr: `clip k05 skipped: rejected (deleted in review)` + tổng `n clip(s) deleted in review (rejected): …` (INFO, không phải cảnh báo `untitled`).
- Xóa giữ override title (khôi phục ra đúng title đó); sửa title một Short đã xóa giữ trạng thái xóa. Khôi phục = bỏ entry → render encode lại Short đó (entry `skipped` không có `render_key` nên không tái dùng); cùng title + cùng input → byte-identical bản trước khi xóa.
- `review.json` đổi → render `run (input changed)` như sửa title (T4).

## T8. Điểm cắt tay + Short thêm tay (sửa đổi CP9, HUMAN LEAD 2026-09-29)

Quyết định: `docs/tasks/CP9-clip-review.md` C1–C8. Chỉ qua web (không CLI, C8).

- **Khoảng từ dòng caption (C3):** dòng đầu `a`, dòng cuối `b` là segment `speech` của `transcript.json`. `start` = mép lời nói trước `a` theo CP4 A6: `end` của khoảng lặng (`silences.json`) giao `[a.start − align_tolerance, a.start + align_tolerance]` có `end` gần `a.start` nhất (chỉ khoảng lặng kết thúc trước `a.end`, như giới hạn của A6), trừ `boundary_pad`, không nhỏ hơn `start` của khoảng lặng đó; không có khoảng lặng → `a.start` (không lùi vào dòng trước: ≥ `min(end dòng trước, a.start)`); kẹp ≥ `content.start`. `end` đối xứng quanh `b.end` (`start` của khoảng lặng gần nhất, chỉ khoảng lặng bắt đầu sau `b.start`, + `boundary_pad`, ≤ `end` khoảng lặng; không có → `b.end`, ≤ `max(start dòng sau, b.end)`; ≤ `content.end`). Tham số lấy từ `candidates.json` `params` / `content` của tập (tập khai thị: giá trị hiệu lực CP8.9 K2).
- **Tinh chỉnh:** `start_nudge` / `end_nudge` bội của 0.2 s, |x| ≤ 2.0 s, cộng trên điểm gốc; sau tinh chỉnh không ra ngoài `content`, không lấn quá 2.0 s vào dòng kề bên (`start ≥ end dòng trước − 2.0`, `end ≤ start dòng sau + 2.0`), `start < end`; sai → `ReviewError` (422).
- **Sửa Short có sẵn:** khoảng hiện tại = cut hợp lệ nếu có, không thì khoảng gốc (clip AI: `clips.json` `source_start`/`source_end`, đã gồm head cut CP5 B11; Short thêm: `added` `start`/`end`). Dòng đầu / cuối của một khoảng = segment `speech` đầu / cuối có trung điểm nằm trong khoảng. Nếu dòng đầu (cuối) gửi lên trùng dòng đầu (cuối) hiện tại → điểm gốc là `start` (`end`) hiện tại; dòng khác → điểm C3 của dòng đó. Khoảng mới bằng khoảng gốc → bỏ entry `cuts` ("Về như AI chọn" = bỏ entry).
- **Đề xuất AI còn lại:** đề xuất `selection_log.json` có `candidate_id` (trong `candidates.json`) và status `overlapped` / `over_limit` / `ineligible` (mỗi candidate một lần); khoảng = `[head_cut.source_start ?? candidate.source_start, candidate.source_end]` (B11 của đề xuất). `selection_log.json` phải khớp `candidates.json` (`candidates_sha256`).
- **Hợp lệ (C4, vi phạm → 422, không ghi):** trong `content`; không giao segment `non_speech` (trừ nhãn ngắn của tập khai thị, CP8.9 A3.1: `params.soft_label_max_seconds`); không chứa trọn một khoảng lặng ≥ `hard_break_silence`; `duration` (sau rút khoảng lặng, dưới) trong `[min_duration, max_duration]` của `candidates.json`. Chồng lấn Short khác (khoảng hiện tại, trừ Short đã xóa) và chuyển shot trong `shot_guard` đầu / cuối: chỉ cảnh báo.
- **Trims + render (C5):** khoảng tay (cut hoặc Short thêm) có `trims` = CP4 A8 (`max_pause`) tính lại trên `silences.json` cho `[start, end]` (không dùng `trims` của candidate); `silences.json` phải khớp `candidates.json.silences_sha256`. `segments` / `duration` từ đó (CP7 R3). Header, title giữ nguyên (không gọi lại AI khi sửa đầu/cuối). `render_key` đã gồm `segments` → chỉ Short đổi được encode (T5); bỏ cut → encode lại ra byte-identical bản gốc.
- **Thứ tự (C2):** Short thêm nằm sau mọi clip của `clips.json` trong render (`render_manifest.shorts`), theo thứ tự tạo → số `S<NN>` / `KT<NN>` (CP8.3 W8) của Short đã có không đổi.
- **Khóa:** cut có `(clip_id, candidate_id)` không khớp Short nào (selection chạy lại) → bỏ qua + cảnh báo (`cut of clip k03 ignored: …`) như T3; `added` luôn giữ. Sửa title / xóa / khôi phục / "Đã đăng" của Short thêm dùng chung luật T2, T7 và W8 với khóa `(clip_id, candidate_id)`; sửa title Short thêm ghi thẳng `added[].title` (không vào `titles`).
- **Title AI của Short thêm (C6):** đúng prompt / validate / retry CP6 G4–G6 với `[titling]` hiện hành cho một clip; text (G3 áp cho đoạn tay) = `text` các dòng `speech` có trung điểm trong khoảng lúc thêm, nối một khoảng trắng; `Thời lượng Short` = `duration` sau trims. Kết quả ghi `ai_title`, `alternatives` và `title` (nếu chưa có). Hết lượt không option hợp lệ, hoặc không lần nào đúng schema → Short `untitled`, chờ title tay (CP7 R2). Mỗi lần gọi append vào `work/<id>/review_titling_log.json` (`{"schema_version": 1, "episode_id", "entries": [{"at", "clip_id", "candidate_id", "source", "model", "prompt_version", "prompt_sha256", "system_prompt", "response_format", "duration", "text", "ai_calls" (như CP6 G7), "status", "title", "alternatives", "error"}]}`; có timestamp, không byte-stable). Web chạy ở làn `ai` sau Ollama preflight (CP8.3 W5).
- **Archived (CP8.6):** `set_cut`, `reset_cut`, `add_short` → `ArchivedError`.

## Hàm dùng chung (CLI + web CP8.3)

`from auto_short.review import …` — mỗi hàm đọc lại episode từ workspace (không giữ state), yêu cầu titling `done` và `titles.json` khớp `clips.json` (id, `candidate_id`, thứ tự); lỗi → `ReviewError(message)` (thông báo dùng được trực tiếp cho người dùng). Không gọi AI, không render (gọi `auto_short.render.run_render(episode_id, config)` sau). **Sửa đổi CP8.6:** episode đã dọn video nguồn → `set_title`, `set_alternative`, `reset_title`, `restore_clip` raise `ArchivedError` (con của `ReviewError`; web 409); `preview_title`, `list_titles`, `reject_clip` vẫn chạy. Canonical: `docs/decisions/CP8.3-web-contract.md` W9.

```python
@dataclass(frozen=True)
class TitlePreview:
    clip_id: str
    title: str            # đã chuẩn hóa, đúng chuỗi được lưu/render
    origin: str           # "ai" | "manual" | "alternative"
    display_lines: list[str]
    font_size: int        # px
    panel_height: int     # px

def load_overrides(episode_id: str, config: Config) -> list[dict]
    # entry T1 {"clip_id", "candidate_id", "title", "origin"} theo thứ tự file; [] nếu không có file
def list_titles(episode_id: str, config: Config) -> dict
    # {"episode_id", "clips": [{"clip_id", "candidate_id", "status", "ai_title",
    #   "alternatives": [{"n", "title"}], "override": {"title", "origin"} | None,
    #   "title", "origin"}], "ignored": [cảnh báo T3]}
def preview_title(episode_id: str, config: Config, clip_id: str, text: str) -> TitlePreview   # không ghi
def set_title(episode_id: str, config: Config, clip_id: str, text: str) -> TitlePreview
def set_alternative(episode_id: str, config: Config, clip_id: str, n: int) -> TitlePreview    # n 1-based
def reset_title(episode_id: str, config: Config, clip_id: str) -> TitlePreview | None         # None: untitled
# CP8.5 (T7): True khi review.json đổi; clip không có → ReviewError
def reject_clip(episode_id: str, config: Config, clip_id: str) -> bool
def restore_clip(episode_id: str, config: Config, clip_id: str) -> bool
```

`list_titles` (CP8.5): mỗi clip thêm `"rejected": bool` (key cuối); `ignored` gồm cả cảnh báo entry `rejected` bị bỏ qua.

Hàm thuần ở `auto_short.review.logic`: `read_review`, `check_review`, `manual_title_error`, `resolve_titles` (`ResolvedTitle.rejected`, CP8.5), `with_override`, `without_override`, `with_rejected`, `without_rejected` (CP8.5); CP9: `added_entries`, `added_origin`, `resolve_cuts`, `with_cut`, `without_cut`, `with_added`, `without_added`, `next_added_id`. Hằng: `REVIEW_NAME`, `AI`, `MANUAL`, `ALTERNATIVE`.

**Sửa đổi CP9** (T8): `list_titles` liệt kê cả Short thêm (sau clip của `clips.json`, key cuối `"added": bool`; `override` = title khi origin `manual` / `alternative`); `set_title`, `set_alternative`, `reset_title`, `reject_clip`, `restore_clip` nhận `clip_id` của Short thêm. `auto_short.review.shorts` (web, không gọi AI, không render):

```python
def transcript_view(episode_id, config) -> dict      # {episode_id, content, min_duration, max_duration,
    # segments: [{id, start, end, kind, text}], shorts: [{clip_id, candidate_id, origin, start, end, start_segment,
    # end_segment, original_start, original_end, cut, rejected}], ignored}
def list_proposals(episode_id, config) -> dict       # {episode_id, proposals: [{candidate_id, topic, reason, score,
    # status, reject_reason, start, end, duration, start_segment, end_segment, start_text, end_text, error,
    # warnings, overlaps, added_as}]}
def preview_cut(episode_id, config, *, clip_id, start_segment, end_segment, start_nudge=0, end_nudge=0) -> dict
    # không ghi: {clip_id, start, end, duration, source_duration, start_segment, end_segment, start_text, end_text,
    # error (C4 | None), warnings, overlaps[, original, changed]}
def set_cut(episode_id, config, clip_id, *, start_segment, end_segment, start_nudge=0, end_nudge=0) -> dict
def reset_cut(episode_id, config, clip_id) -> dict   # preview khoảng gốc + "changed"
def add_short(episode_id, config, *, candidate_id=None, start_segment=None, end_segment=None,
              start_nudge=0, end_nudge=0) -> Added   # Added(clip_id, preview); Short chưa có title
def added_titling_input(episode_id, config, clip_id) -> dict
def set_added_ai_title(episode_id, config, clip_id, *, title, alternatives) -> bool
```

`auto_short.titling.added.title_added(episode_id, config, clip_id, *, client=None, sleep=time.sleep) -> AddedTitle` (`status`, `title`, `alternatives`, `error`, `stored`).

## Quyết định khi implement (không có trong task contract)

- `render_key` gồm cả `render_config_hash` (mọi key `[render]` trong hash) thay vì chỉ các key encode: bảo thủ, mọi thay đổi config render đều encode lại; `threads`/`output_dir` vẫn ngoài hash (Short encode với `threads` khác vẫn được tái dùng).
- Short encode giữ ở `.part` tới khi mọi clip xong (không `os.replace` ngay như CP7) → lỗi giữa chừng không đụng output cũ; tốn tạm thêm dung lượng bằng các Short đổi.
- Lỗi kiểm input trước khi chạy (titling chưa `done`, sha mismatch…) cũng không xóa output cũ (CP7 R8 cũ xóa hết): cùng luật "chỉ xóa file của lần chạy đó".
- Title AI cũ không bị kiểm lại luật T2 khi reset; `reset_title` chỉ tính fit để xem trước (fit lỗi → `ReviewError` sau khi đã ghi, render cũng sẽ `failed`).
- `titling.logic.form_reject_reason` tách từ `reject_reason` (luật 1–8), hành vi CP6 không đổi.
- Chưa có khóa ghi đồng thời (CLI + web cùng lúc): ghi atomic, lần ghi sau thắng.
- CP8.5: `rejected` chỉ ghi khi không rỗng → file không có Short bị xóa giữ đúng dạng CP8.2 (server CP8.3 cũ vẫn đọc được; khôi phục đưa `review.json` về byte-identical). `reject_clip` / `restore_clip` không đổi gì (trả `False`, file không ghi lại) khi Short đã ở trạng thái đó; web vẫn tạo job render (render skip nếu up to date). Xóa / khôi phục chỉ qua web ở CP8.5 (không có CLI).

- CP9 (ORCHESTRATOR chấp nhận 2026-09-29): title Short thêm lưu thẳng ở `added[].title` (không vào `titles`), origin suy ra (đúng 8 key C1); text gửi AI cho Short thêm = các dòng `speech` có trung điểm trong khoảng (cả hai nguồn, không bỏ từ head cut); khoảng của đề xuất gồm head cut B11 của đề xuất, trims luôn tính lại (C5); `cut/preview` trả vi phạm C4 trong `error` (HTTP 200), 422 chỉ khi input sai; AI không cho title → Short `untitled`, render vẫn chạy, job `failed`; số `m<NN>` tính từ `review.json` + `publish.json` + `render_manifest.json` (không dùng lại); "Nghe thử" = media fragment trên video nguồn, 5 s đầu / 5 s cuối của khoảng, chưa rút khoảng lặng; điểm C3 chỉ xét khoảng lặng kết thúc trước `a.end` / bắt đầu sau `b.start` (lỗi thấy khi chạy thật: dòng caption có mốc nằm trong khoảng lặng của dòng trước làm "+ dòng" không đổi điểm cuối).

## Đo thực tế (2026-09-27, `rbjfCfFq3Dk`, 13 Short, worktree CP8.2, máy 48 core có tải khác)

- Lần đầu sau CP8.2 cần `render --force` để manifest có `render_key` (manifest CP8.1 không có): 13 encode, 308.9 s; 13/13 mp4 **byte-identical** bản CP8.1.
- `title k03 --set "Tâm thiện thì gương mặt cũng hiền hòa" --render`: `run (input changed)`, 1 encode + 12 reuse, stage 38.1 s (k03 encode 36.7 s), cả lệnh 38.5 s (≈ 1/8 lượt 13 Short); 12 sha256 không đổi, `k03` đổi; manifest `k03` `title_origin: manual`, 3 dòng 88 px panel 353 px.
- `--alternative 1` → "Tâm xấu khiến người khác sợ hãi", `alternative`, 2 dòng panel 292 px: 1 encode + 12 reuse, 38.5 s.
- 8 title không hợp lệ (61 ký tự, rỗng, toàn khoảng trắng, emoji, `心`, HOA toàn bộ, từ dài không fit, xuống dòng) + alternative 9 + clip `k99` → exit 1, `review.json` byte không đổi, render sau đó skip.
- `render` lần hai → `skip (up to date)`. Xóa `k07.mp4` → `run (artifact missing)`, chỉ `k07` encode (28.9 s), ra byte-identical bản trước.
- `--reset` → `k03` encode lại (38.6 s), 13/13 mp4 byte-identical bản baseline, mọi `title_origin` = `ai`.

## Giới hạn đã biết

- Đổi phiên bản `ffmpeg`/x264 có thể đổi byte output nhưng không vào `render_key` (như CP7: không vào config hash); tăng `RENDER_PLAN_VERSION` hoặc `--force` khi nâng.
- Kiểm sha256 file tái dùng đọc lại mọi mp4 (≈ 0.2 GB/13 Short, dưới 1 s trên máy test).
- Ngắt dòng title tay theo đúng R5 (cân dòng) nên có thể ra 3 dòng ngắn như title AI (vd `Tâm thiện thì / gương mặt / cũng hiền hòa`) — xem CP7 § Giới hạn đã biết.
