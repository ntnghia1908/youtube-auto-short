# Task: FIX-title-script — Loại title AI có chữ không phải Latin (chữ Hán…)

## Status / Approval

- Status: APPROVED
- Type: BUG
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `2e4ba41` (`main`) / `fix/title-script` (worktree `../youtube-auto-short-tscript`)
- Human Lead approval: APPROVED 2026-10-09 ("duyệt FIX-title-script")
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm luật vào G5 của decision đã accepted `docs/decisions/CP6-titling-contract.md` (canonical owner); thay đổi code nhỏ.

## Bối cảnh (bug 2026-10-09)

Kinh Vô Lượng Thọ tập 14 (`nXAUHQDPQLA`), clip `k06`: render lỗi
`font BeVietnamPro-Regular.ttf has no glyph for '今' (U+4ECA), '生' (U+751F)`, chạy lại vẫn lỗi.

- `qwen3:14b` sinh title lẫn chữ Hán: "Hết phước今生, đời sau khổ không lối thoát?". G5 (luật 1–10) không có luật về chữ viết nên option này `valid` và được chọn. Tới CP7 render, `check_glyphs` mới phát hiện font không có glyph.
- Chạy lại không đổi được kết quả vì `temperature 0`, `seed 42` (G10) cho cùng response, còn titling `skipped (up to date)`.
- Quét 164 tập trong `work/`: 3 title có chữ không phải Latin, gồm 1 title chính (`nXAUHQDPQLA` k06) và 2 alternative (`R6ju1kozrwE` k02 "…cao品位", `rBvztHKbNe4` k01 "…để độ众生").
- Gỡ tạm (S0, 2026-10-09): `auto-short title nXAUHQDPQLA k06 --alternative 1` → "Thiện căn là gì? Phật nói chỉ có 3 điều này" (`review.json`).

## Goal

Option title AI có chữ cái không thuộc chữ Latin bị đánh `invalid` (`reject_reason = "non-Latin script"`). Titling sẽ chọn option valid kế tiếp, hoặc retry / `untitled` theo G6, thay vì để clip hỏng ở render. Title gõ tay (CP8.2 T2) có chữ như vậy cũng bị từ chối với cùng lý do, rõ hơn lỗi glyph hiện nay.

## Scope

- In scope:
  - `titling.logic.form_reject_reason`: thêm luật **4b** (ngay sau luật 4 emoji). Một ký tự bị coi là vi phạm khi nó là chữ cái (Unicode category `L*`) mà tên Unicode không bắt đầu bằng `LATIN`. Áp trên title đã chuẩn hóa NFC, giống các luật khác.
  - Cập nhật decision: G5 trong `docs/decisions/CP6-titling-contract.md` thêm luật 4b kèm dòng sửa đổi có ngày; CP8.2 T2 (`docs/decisions/CP8.2-title-override-contract.md`) ghi rằng "luật hình thức 1–8" đã gồm 4b.
  - Test: chữ Hán, kana, Hangul, Cyrillic và Thái bị loại. Toàn bộ chữ tiếng Việt (đ Đ ư ơ, các dấu thanh, chữ hoa / thường), chữ số và dấu câu đang hợp lệ vẫn qua. Case k06: option 1 invalid nên option 2 thành title. Title tay chữ Hán bị từ chối với `non-Latin script`.
- Out of scope:
  - Đổi prompt / `prompt_version`. Đổi prompt làm đổi `prompt_sha256`, tức đổi `config_hash`, khiến titling của mọi tập (164 tập) bị stale và có thể ra title khác.
  - Tự chạy lại titling cho tập cũ. Code validation không nằm trong `config_hash`, nên `titles.json` cũ giữ nguyên. Hai alternative lỗi chỉ bị chặn khi có người chọn chúng (`set_alternative` dùng luật hình thức).
  - Kiểm glyph theo font ở bước titling (gắn titling với `render.font_file`); `check_glyphs` ở render giữ nguyên làm lưới an toàn cuối.

## Authority / key decisions

- `docs/decisions/CP6-titling-contract.md` G5, G6, G8; `docs/decisions/CP8.2-title-override-contract.md` T2.
- Quyết định cục bộ:
  - Dùng luật theo chữ viết, không theo font: deterministic, không phụ thuộc config render, và chặn được mọi hệ chữ khác chứ không riêng CJK.
  - Đặt là 4b để khoảng "luật hình thức 1–8" mà CP8.2 tham chiếu vẫn đúng, không phải đánh số lại luật 9–10.

## Implementation approach

- Một hàm nhỏ trong `titling/logic.py` (dùng `unicodedata.category` + `unicodedata.name`), gọi trong `form_reject_reason` sau kiểm emoji. Không đổi `reject_reason`, `validate_options`, `validate_titles` vì cả ba tự nhận luật mới qua `form_reject_reason`.
- Short thêm tay (CP9 C6, `titling/added.py`) dùng chung `_title_clip`, nên tự hưởng luật mới.

## Acceptance Criteria

1. `form_reject_reason("Hết phước今生, đời sau khổ không lối thoát?", …)` trả `"non-Latin script"`. Với kana, Hangul, Cyrillic, Thái cũng vậy.
2. Title tiếng Việt hợp lệ (gồm mọi nguyên âm có dấu, đ/Đ, chữ số, `?` `,` `:` `…` `-`) không bị luật 4b loại. Các test titling / review hiện có PASS không sửa.
3. Response AI có option 1 chứa chữ Hán và option 2, 3 hợp lệ: title = option 2, alternatives = [option 3], log ghi option 1 `invalid` với `non-Latin script`.
4. `auto-short title <ep> <clip> --set "…众生"` và API web đặt title tay đều bị từ chối với lý do `non-Latin script`, không ghi `review.json`.
5. Decision CP6 G5 và CP8.2 T2 đã cập nhật (dòng sửa đổi có ngày).
6. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH = worktree `src`): AC 1–4, 6.
- `node scripts/framework-check.mjs`: AC 5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API contract (chỉ thêm một giá trị `reject_reason`). Điểm danh trên 8080 (ghim commit nhánh): trang duyệt một tập → đổi title tay thành chữ có "众生" → bị từ chối với thông báo `non-Latin script`.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
