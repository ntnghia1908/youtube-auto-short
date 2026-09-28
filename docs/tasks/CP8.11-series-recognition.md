# Task: CP8.11 — Tự nhận dạng tên bộ kinh / số tập từ tiêu đề video

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `7e347a3` (`main`, sau merge PR #19) / `feature/cp8.11-series-recognition` (worktree `../youtube-auto-short-cp811`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE, D1–D4 theo đề xuất + thêm ô "Tên bộ kinh" sửa được trên trang bộ kinh, ưu tiên **dự phòng** — D5–D7)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa rule header deterministic của CP6 G2 (decision record) và key config `[titling.header]` (G11); rule dùng chung với W10 L1 (`episode` của entry bộ kinh). Không thêm dependency, không chạm security model / HTTP API, không đổi prompt, không đổi thành phần `config_hash`. Thêm trường tùy chọn vào `_playlists/<id>.json` (W10 L1) và endpoint HTTP API mới (W7, dùng auth hiện có — không đổi security model).

ID: CP8.10 đã dành cho tối ưu hàng đợi (`AUTO_SHORT_CHECKPOINT_PLAN.md`); task này làm trước, lấy CP8.11.

## Bối cảnh (đo 2026-09-28, `work/` repo chính)

- `c_6QuBGFzY4.kt` (khai thị) titling `failed`: `Tập 11/128: Giảng "Thái Thượng Cảm Ứng Thiên" | Tịnh Không Lão Pháp sư chủ giảng` không khớp `title_pattern` mặc định `^(?:Phật Thuyết\s+)?(?P<series>.+?)\s+tập\s+(?P<episode>\d+)\b` (chữ `Tập` hoa, đứng đầu). `Igfvn755QV4` (tập 4, cùng bộ) sẽ gặp lỗi tương tự khi tới titling.
- Hai bộ kinh đã lưu: 80 title dạng `Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập N - …` (khớp pattern cũ) + 128 title dạng `Tập N/128: Giảng "Thái Thượng Cảm Ứng Thiên" | …` (không khớp; `episode` của entry bộ kinh hiện `null`).
- Thử nghiệm pattern mới (bên dưới, D2) trên 208 title đã biết: 80 khớp pattern cũ, 128 khớp pattern mới → series `Thái Thượng Cảm Ứng Thiên`; 0 không khớp.
- Stale: `config_hash` titling (G9) chỉ gồm `header.lines` **đã resolve**, không gồm `title_pattern` thô. ⇒ Tập nào resolve ra cùng dòng header như trước thì không stale, không gọi lại AI.

## Quyết định cần HUMAN LEAD (đề xuất)

- **D1 — Nguồn chính: danh sách pattern trên tiêu đề video; tên bộ kinh do người dùng đặt chỉ là nguồn dự phòng (D5).** Không lấy tự động từ tên playlist: tên playlist cần làm sạch heuristic (`Thái Thượng Cảm Ứng Thiên (128 tập) - Pháp Sư Tịnh Không`); không truyền từ web như `--series` (cờ không được lưu, G9 → "Chạy tiếp" resolve khác). Pattern đã phủ 208/208 title đã biết.
- **D2 — Pattern mặc định = danh sách, khớp đầu tiên thắng**, pattern cũ đứng đầu (bảo đảm title đang khớp resolve y hệt):
  1. `^(?:Phật Thuyết\s+)?(?P<series>.+?)\s+tập\s+(?P<episode>\d+)\b` (không đổi)
  2. `^Tập\s+(?P<episode>\d+)(?:\s*/\s*\d+)?\s*:\s*(?:Giảng\s+)?["“](?P<series>[^"”]+?)\s*["”]`
  Kết quả ví dụ: `["HT.Tịnh Không", "Thái Thượng Cảm Ứng Thiên (tập 11)"]`, hashtag mặc định `#TháiThượngCảmỨngThiên`.
- **D3 — Config:** key mới `[titling.header] title_patterns` (list chuỗi regex; `[]` = tắt). `title_pattern` (chuỗi) vẫn nhận, tương đương list một phần tử (rỗng = tắt); đặt cả hai → lỗi config. Mỗi phần tử phải là regex hợp lệ, không rỗng. Match trên `metadata.title` NFC bằng `re.search`, theo thứ tự; pattern đầu tiên khớp cung cấp mọi group của nó (không trộn group giữa các pattern).
- **D4 — W10 L1:** `episode` của entry bộ kinh dùng cùng danh sách (`auto_short.web.playlists`); áp khi liệt kê / "Cập nhật danh sách" (không tự ghi lại file đã lưu).

- **D5 — "Tên bộ kinh" (HUMAN LEAD 2026-09-28, dự phòng):**
  - Lưu: trường tùy chọn `"series": "<chuỗi>"` trong `_playlists/<playlist_id>.json` (sau `hashtags`; `schema_version` giữ 1); chuẩn hóa NFC + gộp khoảng trắng, 1–100 ký tự sau chuẩn hóa; không có trường / không phải chuỗi / rỗng = chưa đặt. Ghi atomic dưới lock của store; "Cập nhật danh sách" giữ trường (như `hashtags`, H5); "Xóa bộ kinh" xóa luôn.
  - Resolve (G2): thứ tự thành CLI > config > pattern (metadata) > **bộ kinh** (source `"playlist"`). Chỉ dùng khi **không pattern nào khớp** tiêu đề video: `series` = tên đã đặt của bộ kinh đầu tiên (theo `playlist_id`, như CP8.8 H4) có đặt tên và có entry `video_id` = id YouTube của tập (`metadata.youtube.id`; tập `.kt` dùng cùng video nguồn); `episode` = `entry.episode` nếu có, không thì `str(entry.index)`. CLI / config vẫn thắng từng trường như cũ.
  - Hệ quả stale: tập khớp pattern không bao giờ đọc tên bộ kinh → không đổi hash. Tập dùng nguồn bộ kinh: đổi / xóa tên sau khi đã titling → lần chạy sau titling chạy lại (G9 như cờ CLI) — UI ghi rõ.
- **D6 — Hướng import:** hàm đọc thuần (chỉ đọc, không lock) `_playlists/*.json` → `(series, episode)` cho một video id đặt ở core (`src/auto_short/titling/` hoặc module core mới; không import `auto_short.web`); `auto_short.web.playlists` ghi trường và dùng lại hàm chuẩn hóa. CLI `auto-short titling/run` cũng thấy nguồn này (không phụ thuộc web đang chạy).
- **D7 — API + UI:**
  - `PUT /api/playlists/{pid}/series` `{series}` → 200 `{playlist_id, series, series_custom: true}`; sai kiểu / rỗng / > 100 ký tự → 422, không ghi; 404. `DELETE /api/playlists/{pid}/series` → 200 `{playlist_id, series: null, series_custom: false}`; 404. Không tạo job, gọi được khi có job chạy.
  - `GET /api/playlists/{pid}` thêm `series` (tên đã đặt | null), `series_suggested` (series của pattern trên title entry đầu tiên khớp | null), `unrecognized` (số entry `available` không khớp pattern nào).
  - Trang bộ kinh: khung "Tên bộ kinh" — ô nhập (placeholder = `series_suggested`), "Lưu", "Bỏ tên" (xác nhận); dòng giải thích "Chỉ dùng cho tập mà tiêu đề video không nhận ra tên bộ kinh / số tập (hiện: n tập). Đổi tên sau khi tập đã xử lý → lần chạy sau tạo lại tiêu đề AI của tập đó." Poll trang không ghi đè ô đang sửa; ≤ 640 px: nút rộng hết, ≥ 40 px (như CP8.8).

## Goal

Video có tiêu đề dạng `Tập N/M: Giảng "<Tên>" | …` tự có header `<speaker>` / `<Tên> (tập N)` mà không cần cờ hay sửa config; các tập Short / khai thị đã có không bị stale (titling skip, không gọi AI, không render lại). Bộ kinh có tiêu đề video lạ: người dùng đặt "Tên bộ kinh" trên trang bộ kinh → các tập của nó có header mà không cần cờ.

## Scope

- In scope: D5–D7 (trường `series` bộ kinh, hàm đọc core, resolve dự phòng, API, UI trang bộ kinh); `TitlingHeaderConfig` + parse config (D3); `resolve_header` duyệt danh sách (D2); message lỗi khi không pattern nào khớp; `web/playlists.py` dùng danh sách (D4); `config.example.toml`; tests; cập nhật CP6 contract G2/G11 (+ "Sửa đổi CP8.11"), CP8.3 W7 (endpoint) + W10 (trường `series`, khung UI, pointer G2), `AUTO_SHORT_CHECKPOINT_PLAN.md` (mục CP8.11), project-profile (dòng authority), `README` nếu nhắc `title_pattern`.
- Out of scope: tên bộ kinh ghi đè pattern; tự suy tên từ tên playlist; đổi `lines`, `speaker`, prompt, `config_hash`; UI web; migration / ghi lại `_playlists/*.json`; chạy lại tập đã có trên dữ liệu thật; repin worktree web (HUMAN LEAD làm sau merge); CP8.10.

## Authority / key decisions

- `docs/decisions/CP6-titling-contract.md` G2 (header), G9 (hash / skip), G11 (config) — sửa đổi theo D2, D3.
- `docs/decisions/CP8.3-web-contract.md` W10 L1 (`episode` của entry) — D4.
- `docs/decisions/CP2-workspace-contract.md` (skip / stale theo `config_hash`) — không đổi.

## Implementation approach

- Store / API / UI bộ kinh theo mẫu `hashtags` của CP8.8 (`set_hashtags`, giữ trường khi refresh, khung thu gọn trên trang).

- `config.py`: `DEFAULT_TITLE_PATTERNS` (tuple, D2); `TitlingHeaderConfig.title_patterns: tuple[str, ...]` thay `title_pattern`; parser nhận cả hai key (D3).
- `titling/logic.py`: tách hàm thuần `match_title(patterns, title) -> re.Match | None` (dùng lại ở `web/playlists.py`); phần còn lại của `resolve_header` giữ nguyên thứ tự CLI > config > metadata.
- Không đụng `titling/stage.py` ngoài chỗ bắt buộc; `used_config` / hash giữ nguyên.

## Acceptance Criteria

1. Title `Tập 11/128: Giảng "Thái Thượng Cảm Ứng Thiên" | Tịnh Không Lão Pháp sư chủ giảng` → `fields` `{speaker: "HT.Tịnh Không", series: "Thái Thượng Cảm Ứng Thiên", episode: "11"}`, `sources` series/episode `metadata`, `lines` `["HT.Tịnh Không", "Thái Thượng Cảm Ứng Thiên (tập 11)"]`. Biến thể `“…”`, khoảng trắng quanh `/` và `:`, không có `/M`, không có `Giảng` đều khớp.
2. Mọi title khớp pattern cũ cho kết quả `resolve_header` y hệt code `main` (test bảng gồm title thật của cả hai bộ kinh + test hiện có không sửa).
3. **Không stale:** script (scratch, chỉ đọc) tính `config_hash` titling cho mọi `work/<id>` có titling `done` bằng code `main` và code mới → trùng 100 %; `auto-short run` trên bản sao scratch (hardlink) của một tập Short và một tập `.kt` đã xong → mọi stage `skipped`, không gọi Ollama.
4. Config: `title_patterns` list hợp lệ; `title_pattern` chuỗi vẫn chạy; cả hai → lỗi; phần tử không phải chuỗi / rỗng / regex hỏng → lỗi nêu chỉ số; `[]` hoặc `title_pattern = ""` = tắt. Pattern đầu khớp thắng, không trộn group.
5. Không khớp pattern nào → `failed` với message như cũ, nêu `title_patterns`.
6. Entry bộ kinh (W10 L1) của title dạng mới có `episode` = số tập.
7. Tên bộ kinh (D5): tập có title không khớp pattern, nằm trong bộ kinh đã đặt `series` → header `<series> (tập <episode|index>)`, `sources` series/episode `"playlist"`; không đặt tên → `failed` như AC5 (message gợi ý đặt "Tên bộ kinh"). Tập khớp pattern: có / không / đổi tên bộ kinh → `resolve_header` và hash không đổi. Nhiều bộ kinh → `playlist_id` nhỏ nhất có tên. CLI > config > pattern > bộ kinh theo từng trường.
8. API / store (D7): PUT / DELETE / GET như D7 (422 không ghi, 404); "Cập nhật danh sách" giữ `series` và `hashtags`; file thiếu / hỏng trường `series` = chưa đặt. UI: lưu, bỏ tên, placeholder gợi ý, số tập không nhận dạng, poll không ghi đè ô đang sửa.
9. Chạy thật trên bản sao scratch của `c_6QuBGFzY4.kt` (Ollama `127.0.0.1:11437`): titling `done`, header `Thái Thượng Cảm Ứng Thiên (tập 11)`; render chạy tiếp.
10. Test suite, `node scripts/framework-check.mjs` PASS.

## Required verification

- `conda run -n auto-short python -m pytest -q` — AC1, AC2, AC4–AC8.
- Script so hash (scratch, không ghi `work/`) — AC3.
- `auto-short run` trên bản sao scratch (config trỏ `work/` scratch) — AC3, AC9.
- `node scripts/framework-check.mjs` — AC10.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API. Manual test sau automated verification là điểm danh:

- [ ] Sau merge + repin web: "Chạy tiếp" tập khai thị `c_6QuBGFzY4.kt` → xong, header `Thái Thượng Cảm Ứng Thiên (tập 11)`.
- [ ] Các tập Thập Thiện đã có: không tập nào chạy lại titling (tiêu đề AI giữ nguyên, trạng thái đã đăng giữ nguyên).
- [ ] Trang bộ kinh Thái Thượng sau "Cập nhật danh sách": cột "tập N" có số; khung "Tên bộ kinh" hiện gợi ý `Thái Thượng Cảm Ứng Thiên`, "0 tập không nhận dạng".
- [ ] Đặt / bỏ "Tên bộ kinh" trên điện thoại (≤ 640 px): lưu được, không tập nào chạy lại.

## Result

- Main changes:
  - `config.py`: `DEFAULT_TITLE_PATTERNS` (pattern CP6 gốc đứng đầu + pattern D2), `TitlingHeaderConfig.title_patterns`; parser nhận `title_patterns` (list) hoặc `title_pattern` (chuỗi, `""` = tắt), cả hai → lỗi; phần tử sai kiểu / rỗng / regex hỏng → lỗi nêu chỉ số.
  - `titling/logic.py`: `match_title(patterns, title)` (khớp đầu tiên thắng, một match cho mọi group); `resolve_header(..., playlist=callable)` CLI > config > pattern > bộ kinh (callable chỉ được gọi khi không pattern nào khớp); message lỗi nêu `title_patterns` + gợi ý "Tên bộ kinh".
  - `titling/playlist.py` (mới, core): `normalize_series`, `stored_series`, `playlist_header(workspace_dir, video_id)` (chỉ đọc, không lock, không import web); `PLAYLISTS_DIR` chuyển về đây, `web/playlists.py` import lại.
  - `titling/stage.py`: truyền lookup theo `metadata.youtube.id` (tập `.kt` = video nguồn). `used_config` / hash không đổi.
  - `web/playlists.py`: `episode_number` + `title_series` dùng danh sách; `set_series` (atomic dưới lock); refresh giữ `hashtags` + `series` (thứ tự key `…, entries, hashtags, series`); view thêm `series`, `series_suggested`, `unrecognized`.
  - `web/app.py`: `PUT` / `DELETE /api/playlists/{pid}/series`. UI trang bộ kinh: khung "Tên bộ kinh" (placeholder gợi ý, số tập không nhận dạng, Lưu, Bỏ tên + xác nhận, poll không ghi đè ô đang sửa, ≤ 640 px nút rộng hết).
  - `config.example.toml`, `README.md`; docs: CP6 G2 / G7 / config (+ "Sửa đổi CP8.11"), CP8.3 W7 + W10, `AUTO_SHORT_CHECKPOINT_PLAN.md` (CP8.11), project-profile.
- Tests:
  - `conda run -n auto-short python -m pytest -q` → **854 passed** (base 822 + 32 mới: `tests/test_series_cp811.py`, `tests/test_web_series_cp811.py`; fixture `tests/fixtures/cp811_titles.json` = 208 title thật của hai bộ kinh đã lưu, kèm kết quả `resolve_header` của code `7e347a3`). AC1, AC2 (80/80 title khớp pattern cũ y hệt `main`; 128/128 title dạng mới → `Thái Thượng Cảm Ứng Thiên (tập N)`), AC4–AC8.
  - Test cũ duy nhất sửa: `tests/test_titling_logic.py` dòng `replace(H, title_pattern="")` → `replace(H, title_patterns=())` (đổi tên trường dataclass theo contract; cùng ý nghĩa "pattern tắt").
  - `node scripts/framework-check.mjs` → PASS (AC10).
  - AC3 hash (scratch, chỉ đọc `work/` repo chính, config repo chính): 12/12 tập có titling `done` (8 Short + 4 `.kt`) → `config_hash` code `main` = code mới = hash trong manifest (output hai lần chạy giống byte); `header.lines` = `titles.json` đã lưu 12/12.
  - AC3 run (bản sao scratch, mp4 hardlink, json copy; `OLLAMA_HOST=http://127.0.0.1:9` đóng + `--no-preflight` ⇒ mọi lời gọi Ollama sẽ lỗi): `run https://youtu.be/7axON1RpRjo` → 6/6 stage skip, exit 0, `done (11/12 Shorts)`; `run https://youtu.be/X8ao0_7ufto --khai-thi` → 6/6 stage skip, `done (5/5 Shorts)`.
  - AC9 (bản sao scratch `c_6QuBGFzY4.kt`, Ollama `127.0.0.1:11437`, preflight ok): titling `done`, header `HT.Tịnh Không | Thái Thượng Cảm Ứng Thiên (tập 11)` (sources series/episode `metadata`), 4/4 clip titled (4 lần gọi, 14.6 s); render chạy tiếp → `done (4/4 Shorts)` (477.7 s), exit 0.
- Review: chưa (chờ ORCHESTRATOR / HUMAN LEAD).
- Important findings / decisions:
  - Ngoài scope (có sẵn ở `7e347a3`, không do CP8.11): 4 tập `.kt` làm trước commit `c76d55e` (CP8.9 A3.1) có `analysis` stale theo code hiện tại — `7axON1RpRjo.kt`, `7w4nSj3PguI.kt`, `W2d-xS4ttTw.kt`, `c_6QuBGFzY4.kt` (so hash analysis: code `main` và code mới cho cùng kết quả; `X8ao0_7ufto.kt` và mọi tập Short không stale). Hệ quả: "Chạy tiếp" `c_6QuBGFzY4.kt` (manual test mục 1) sẽ chạy lại analysis + selection (AI chọn lại đoạn), không chỉ titling — AC9 cũng vậy (analysis 95.5 s, selection 248.1 s). Chạy lại 3 tập `.kt` còn lại cũng sẽ làm lại analysis → selection → titling → render.
  - `PUT …/series` body `{series: null}` / `{}` → 422 (không coi là xóa; xóa dùng `DELETE`).
  - `series` trong file hỏng (không phải chuỗi / rỗng / > 100 ký tự sau chuẩn hóa) = chưa đặt (cả web lẫn titling).
  - Khung "Tên bộ kinh" tự mở lần tải đầu khi có tập không nhận dạng và chưa đặt tên.
- Known limitations:
  - UI (lưu / bỏ tên / placeholder / poll không ghi đè) chỉ kiểm bằng test markup + JS tĩnh và API; chưa kiểm trên trình duyệt / điện thoại (manual test checklist).
  - `episode` của entry bộ kinh đã lưu trước CP8.11 vẫn `null` tới khi "Cập nhật danh sách" (D4: không tự ghi lại file); nguồn "Tên bộ kinh" khi đó dùng `index`.
  - Nguồn local (không `metadata.youtube.id`) không dùng được "Tên bộ kinh".
- PR: chưa (push / PR sau READY + HUMAN LEAD approval).
