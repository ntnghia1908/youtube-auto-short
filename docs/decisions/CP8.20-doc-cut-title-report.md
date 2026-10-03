# CP8.20 — Báo cáo đo: văn bản gốc cho title và điểm cắt theo câu

| Metadata | Value |
|---|---|
| Status | ACCEPTED — HUMAN LEAD 2026-10-03: chất lượng video hiện tại ổn, không đổi title / điểm cắt (§8.3: không chọn mục nào) |
| Task | `docs/tasks/CP8.20-doc-cut-title-measure.md` (S1) |
| Script | `scripts/measure_doc_cut_title.py` (không đổi `src/`) |
| Dữ liệu | bản sao `~/.cache/auto-short-cp820-test/` (work + output + `config.toml` riêng); kết quả thô `results/*.json` |
| Chạy | M1+M2 3,2 s (không GPU); M3 9 lần chạy selection ≈ 40 phút GPU; M4 50 Short ≈ 2 s/Short; M5 dựng 12 Short. Mỗi lần chạy Ollama: không stage nào `running` ở 8080, `expires_at` của Ollama không đổi trong 90 s (cách CP11 D5) |

## 1. Cách tính

- **Gióng**: toàn bộ từ transcript (chỉ speech, `normalize_word`) gióng với từ văn bản gốc (`doc.json` đã cache của bản sao, `match` 0,88 / 0,81 / 0,92) bằng `difflib.SequenceMatcher(autojunk=False)` — cùng bộ gióng D3. Từ trong khối khớp ánh xạ đúng một-một; từ trong khoảng giữa hai khối được nội suy (đánh dấu "không exact"; hiếm: 0–3 Short mỗi tập).
- **Đầu / cuối câu**: dùng đúng luật D5 (`doc.ends_sentence`): vị trí là đầu câu khi token văn bản là token đầu đoạn hoặc đứng sau token kết câu (`. ? ! …`, cho phép ngoặc đóng); là cuối câu khi chính nó kết câu hoặc kết đoạn. "Thiếu / thừa" = số token văn bản từ vị trí đó tới đầu / cuối câu; giây = chênh thời gian transcript giữa từ đó và từ đầu / cuối câu (ước lượng; với transcript từ caption YouTube thời gian cuối từ bị kéo dài qua khoảng lặng nên giây cuối chỉ tham khảo).
- **Từ của một unit / Short** = các từ của các segment `segment_ids` (một unit là dãy segment nguyên); với `head_cut` thì bỏ các từ đã cắt. Không dùng mốc giây của unit / `source_start` vì chúng có pad biên và thời gian cuối từ bị kéo dài.
- Kiểm chéo với production: `doc.compose` (D5) báo `head > 0` ở 9/11, 2/7, 12/13 Short (Bi7k / 4oOZ / yzR1) — khớp số "đầu giữa câu" của M1 (10, 1, 12).
- "Trọn câu hai đầu" của candidate = đơn vị đầu bắt đầu ở đầu câu và đơn vị cuối kết thúc ở cuối câu.
- "Capacity" = số candidate không chồng lấn tối đa (tham lam theo thời điểm kết thúc): cận trên số Short chọn được.

## 2. M1 — hiện trạng ranh giới của Short đang có

| Tập | Short | s | AI đầu/cuối trọn | Đầu: đúng câu? (thiếu token / s) | Cuối: đúng câu? (thừa token / s) |
|---|---|---|---|---|---|
| Bi7kVGbnPfE | k01 | 90 | T/T | giữa câu (29 tok / 26.4 s) | giữa câu (2 tok / 3.6 s) |
| Bi7kVGbnPfE | k02 | 97 | T/T | giữa câu (13 tok / 8.7 s) | giữa câu (1 tok / 3.4 s) |
| Bi7kVGbnPfE | k03 | 136 | T/T | giữa câu (10 tok / 7.0 s) | giữa câu (1 tok / 2.3 s) |
| Bi7kVGbnPfE | k04 | 52 | T/T | giữa câu (36 tok / 26.9 s) | đúng |
| Bi7kVGbnPfE | k05 | 67 | T/T | giữa câu (15 tok / 8.6 s) | giữa câu (1 tok / 3.3 s) |
| Bi7kVGbnPfE | k06 | 94 | T/T | giữa câu (15 tok / 10.4 s) | đúng |
| Bi7kVGbnPfE | k07 | 87 | T/T | giữa câu (21 tok / 13.8 s) | giữa câu (1 tok / 1.1 s) |
| Bi7kVGbnPfE | k08 | 38 | T/T | giữa câu (19 tok / 9.4 s) | giữa câu (1 tok / 6.3 s) |
| Bi7kVGbnPfE | k09 | 110 | T/T | đúng | đúng |
| Bi7kVGbnPfE | k10 | 54 | T/T | giữa câu (20 tok / 7.3 s) | giữa câu (10 tok / 7.2 s) |
| Bi7kVGbnPfE | k11 | 55 | T/T | giữa câu (7 tok / 12.5 s) | giữa câu (1 tok / 2.7 s) |
| 4oOZz2CBz3g | k01 | 51 | T/T | đúng | đúng |
| 4oOZz2CBz3g | k02 | 72 | T/T | đúng | đúng |
| 4oOZz2CBz3g | k03 | 76 | T/T | đúng | giữa câu (4 tok / 0.0 s) |
| 4oOZz2CBz3g | k04 | 56 | T/T | đúng | đúng |
| 4oOZz2CBz3g | k05 | 157 | T/T | giữa câu (19 tok / 14.7 s) | đúng |
| 4oOZz2CBz3g | k06 | 51 | T/T | đúng | đúng |
| 4oOZz2CBz3g | k07 | 55 | T/T | đúng | đúng |
| yzR1eCK_iV0 | k01 | 138 | T/T | giữa câu (5 tok / 4.8 s) | đúng |
| yzR1eCK_iV0 | k02 | 124 | T/T | giữa câu (15 tok / 10.6 s) | giữa câu (1 tok / 2.1 s) |
| yzR1eCK_iV0 | k03 | 66 | T/T | giữa câu (17 tok / 9.3 s) | giữa câu (1 tok / 2.9 s) |
| yzR1eCK_iV0 | k04 | 124 | T/T | giữa câu (8 tok / 6.9 s) | giữa câu (1 tok / 2.0 s) |
| yzR1eCK_iV0 | k05 | 175 | T/T | giữa câu (12 tok / 7.8 s) | đúng |
| yzR1eCK_iV0 | k06 | 117 | T/T | đúng | giữa câu (1 tok / 2.5 s) |
| yzR1eCK_iV0 | k07 | 39 | T/T | giữa câu (25 tok / 25.7 s) | giữa câu (5 tok / 10.8 s) |
| yzR1eCK_iV0 | k08 | 49 | T/T | giữa câu (16 tok / 6.0 s) | giữa câu (1 tok / 2.4 s) |
| yzR1eCK_iV0 | k09 | 53 | T/T | giữa câu (8 tok / 5.0 s) | giữa câu (7 tok / 7.4 s) |
| yzR1eCK_iV0 | k10 | 87 | T/T | giữa câu (10 tok / 6.1 s) | giữa câu (8 tok / 11.2 s) |
| yzR1eCK_iV0 | k11 | 66 | T/T | giữa câu (13 tok / 13.7 s) | giữa câu (1 tok / 2.6 s) |
| yzR1eCK_iV0 | k12 | 141 | T/T | giữa câu (5 tok / 3.0 s) | đúng |
| yzR1eCK_iV0 | k13 | 98 | T/T | giữa câu (16 tok / 15.4 s) | giữa câu (1 tok / 5.2 s) |
| Bi7kVGbnPfE.kt | k01 | 317 | T/T | giữa câu (29 tok / 26.4 s) | giữa câu (1 tok / 1.0 s) |
| Bi7kVGbnPfE.kt | k02 | 255 | T/T | giữa câu (1 tok / 2.9 s) | giữa câu (1 tok / 2.3 s) |
| Bi7kVGbnPfE.kt | k03 | 332 | T/T | giữa câu (7 tok / 6.1 s) | giữa câu (12 tok / 7.9 s) |
| Bi7kVGbnPfE.kt | k04 | 404 | T/T | giữa câu (27 tok / 19.6 s) | giữa câu (1 tok / 2.2 s) |
| Bi7kVGbnPfE.kt | k05 | 377 | T/T | đúng | đúng |
| Bi7kVGbnPfE.kt | k06 | 277 | T/T | đúng | giữa câu (10 tok / 7.2 s) |
| 4oOZz2CBz3g.kt | k01 | 243 | T/T | đúng | đúng |
| 4oOZz2CBz3g.kt | k02 | 397 | T/T | đúng | giữa câu (5 tok / 5.4 s) |
| 4oOZz2CBz3g.kt | k03 | 245 | T/T | giữa câu (15 tok / 6.8 s) | đúng |
| 4oOZz2CBz3g.kt | k04 | 378 | T/T | đúng | giữa câu (1 tok / 5.4 s) |
| 4oOZz2CBz3g.kt | k05 | 338 | T/T | giữa câu (7 tok / 6.4 s) | đúng |
| 4oOZz2CBz3g.kt | k06 | 299 | T/T | đúng | đúng |
| yzR1eCK_iV0.kt | k01 | 306 | T/T | giữa câu (5 tok / 4.8 s) | giữa câu (1 tok / 2.1 s) |
| yzR1eCK_iV0.kt | k02 | 353 | T/T | giữa câu (17 tok / 9.3 s) | giữa câu (1 tok / 2.0 s) |
| yzR1eCK_iV0.kt | k03 | 345 | T/T | giữa câu (11 tok / 9.7 s) | giữa câu (1 tok / 2.4 s) |
| yzR1eCK_iV0.kt | k04 | 385 | T/T | giữa câu (26 tok / 16.4 s) | giữa câu (1 tok / 5.0 s) |
| yzR1eCK_iV0.kt | k05 | 347 | T/T | giữa câu (13 tok / 13.7 s) | giữa câu (1 tok / 4.5 s) |
| yzR1eCK_iV0.kt | k06 | 274 | T/T | giữa câu (12 tok / 9.4 s) | giữa câu (1 tok / 3.4 s) |
| yzR1eCK_iV0.kt | k07 | 409 | T/T | giữa câu (11 tok / 8.1 s) | giữa câu (1 tok / 3.2 s) |

Tóm tắt từng tập:

| Tập | Short | đầu giữa câu | cuối giữa câu | cả hai đúng | trung vị thiếu đầu (tok / s) | trung vị thừa cuối (tok / s) | AI chấm `start_complete`=T mà đầu giữa câu | AI chấm `end_complete`=T mà cuối giữa câu |
|---|---|---|---|---|---|---|---|---|
| Bi7kVGbnPfE (Vô Lượng Thọ, caption) | 11 | 10 (91%) | 8 (73%) | 1 | 17 / 9,9 | 1 / 3,3 | 10 | 8 |
| 4oOZz2CBz3g (Cảm Ứng Thiên, Whisper) | 7 | 1 (14%) | 1 (14%) | 5 | 19 / 14,7 (1 Short) | 4 / – (1 Short) | 1 | 1 |
| yzR1eCK_iV0 (Thập Thiện, caption) | 13 | 12 (92%) | 10 (77%) | 0 | 12,5 / 7,3 | 1 / 2,8 | 12 | 10 |
| **3 tập Short** | **31** | **23 (74%)** | **19 (61%)** | **6 (19%)** | | | |
| Bi7kVGbnPfE.kt | 6 | 4 | 5 | 1 | 17 / 12,9 | 1 / 2,3 | 4 | 5 |
| 4oOZz2CBz3g.kt | 6 | 2 | 2 | 2 | 11 / 6,6 | 3 / 5,4 | 2 | 2 |
| yzR1eCK_iV0.kt | 7 | 7 | 7 | 0 | 12 / 9,4 | 1 / 3,2 | 7 | 7 |

Nhận xét:

- AI chấm 100% Short `start_complete = true` và `end_complete = true`, nhưng 74% đầu và 61% cuối thực ra giữa câu: tự đánh giá của AI (đọc caption không dấu câu) **không tin được** về ranh giới câu.
- Cuối giữa câu phần lớn chỉ thiếu **1 từ** (câu kết "…liền thành | Phật."): CP4 cắt ở khoảng lặng ≥ 3 s nằm giữa hai từ cuối câu, từ cuối thuộc unit sau. Đầu giữa câu thiếu nhiều (trung vị 12–19 token, 7–15 s) vì unit sau khoảng lặng thường bắt đầu giữa câu.
- Khác biệt giữa hai loại nguồn: 4oOZ (Whisper, segment ngắt theo hơi ngắt thật) hầu như trọn câu; hai tập caption YouTube (Bi7k, yzR1) hầu như giữa câu. Số 69% của CP8.19 (102/148) nằm giữa hai loại này.
- Không có Short thêm tay (`review.json` không tồn tại ở cả 6 tập sao).

## 3. M2 — ranh giới unit so với câu

| Tập | nguồn | unit | đầu unit đúng đầu câu | cuối unit đúng cuối câu | cả hai | cuối câu của văn bản rơi giữa unit | candidate | trong mục tiêu | candidate cả hai đầu ở câu | …và trong mục tiêu | capacity mục tiêu → sau lọc | cửa sổ có candidate mục tiêu → sau lọc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Bi7kVGbnPfE | caption | 121 | 16 (13%) | 16 (13%) | 2 (1,7%) | 248/262 (95%) | 738 | 152 | 11 (1,5%) | 3 (2,0%) | 29 → 3 | 4 → 2 |
| 4oOZz2CBz3g | Whisper | 178 | 91 (51%) | 84 (47%) | 46 (26%) | 151/228 (66%) | 1740 | 346 | 400 (23%) | 83 (24%) | 34 → 27 | 4 → 4 |
| yzR1eCK_iV0 | caption | 68 | 5 (7%) | 5 (7%) | 0 | 296/301 (98%) | 119 | 29 | 1 (0,8%) | 0 | 18 → 0 | 11 → 0 |
| Bi7kVGbnPfE.kt | caption | 121 | 16 | 16 | 2 | 248/262 | 758 | 758 | 13 | 13 | 9 → 5 | 4 → 3 |
| 4oOZz2CBz3g.kt | Whisper | 178 | 91 | 84 | 46 | 151/228 | 1700 | 1700 | 380 | 380 | 10 → 10 | 4 → 4 |
| yzR1eCK_iV0.kt | caption | 51 | 5 | 5 | 0 | 296/301 | 124 | 124 | 1 | 1 | 10 → 1 | 3 → 1 |

(Mục tiêu Short 60–90 s; khai thị 240–420 s nên mọi candidate "trong mục tiêu".)

- Với tập caption, ranh giới unit **gần như không bao giờ** trùng ranh giới câu (7–13%) và 95–98% cuối câu của văn bản rơi **giữa unit**. Chỉ giữ candidate có hai đầu ở câu: còn 1,5% / 0,8% candidate; Thập Thiện 6 còn 0 candidate trong mục tiêu → **không đủ để chọn**. Tập Whisper (4oOZ) còn 24% candidate mục tiêu, capacity 34 → 27: đủ.
- Cuối câu rơi giữa unit — khoảng ngắt tại đó: tập caption trung vị 0,0 s (thời gian từ bị kéo dài, không có khoảng lặng thật để cắt); tập Whisper trung vị 1,08 s, 92/151 ≥ 0,3 s. Tách unit theo timestamp chữ chỉ hứa hẹn với transcript Whisper; với caption YouTube không biết điểm kết thúc thật của từ nên điểm cắt giữa câu có thể cắt cụt tiếng.

## 4. M3 — selection biết câu (Ollama, cùng model / prompt production, chỉ trên bản sao)

- `base` = chạy lại selection production trên bản sao; (a) = chỉ đưa candidate có hai đầu ở câu; (b) = đủ candidate, text mỗi unit có nhãn `[ĐẦU CÂU]` / `[CUỐI CÂU]` (từ văn bản gốc) + thêm một đoạn giải thích nhãn vào cuối system prompt (cần để AI hiểu nhãn; nội dung đoạn: hằng `LABEL_NOTE` trong script).
- "Trọn câu" đo bằng cách M1 trên Short kết quả.

| Tập | biến thể | Short chọn | trọn câu hai đầu | đầu / cuối trọn | score TB | trong mục tiêu | tổng giây | thời gian (s) | AI call |
|---|---|---|---|---|---|---|---|---|---|
| Bi7kVGbnPfE | base | 11 | 1 (9.1%) | 1/3 | 8.64 | 2 | 880 | 238 | 4 |
| Bi7kVGbnPfE | a | 2 | 2 (100.0%) | 2/2 | 9 | 1 | 196 | 188 | 3 |
| Bi7kVGbnPfE | b | 6 | 6 (100.0%) | 6/6 | 8.33 | 3 | 545 | 219 | 4 |
| 4oOZz2CBz3g | base | 9 | 6 (66.7%) | 6/9 | 8.67 | 2 | 624 | 232 | 4 |
| 4oOZz2CBz3g | a | 5 | 4 (80.0%) | 4/5 | 8.4 | 1 | 357 | 272 | 4 |
| 4oOZz2CBz3g | b | 12 | 10 (83.3%) | 10/12 | 8.5 | 6 | 699 | 255 | 4 |
| yzR1eCK_iV0 | base | 13 | 0 (0.0%) | 2/1 | 8.62 | 4 | 1179 | 434 | 14 |
| yzR1eCK_iV0 | a | 1 | 1 (100.0%) | 1/1 | 8 | 0 | 172 | 45 | 1 |
| yzR1eCK_iV0 | b | 8 | 1 (12.5%) | 2/2 | 8.75 | 3 | 852 | 469 | 14 |

- Lưu ý baseline: chạy lại `base` cho 4oOZ ra 9 Short, `clips.json` đã lưu có 7 (Bi7k 11 = 11, yzR1 13 = 13 khớp). Dao động giữa các lần chạy là nhiễu cần tính khi đọc 4oOZ.
- (a) cho Short trọn câu nhưng ít (2 / 5 / 1) và mất tập Thập Thiện (1 Short); AI còn trả `valid` thấp vì candidate ít.
- (b) cải thiện mạnh ở tập có nhiều ranh giới ở câu (Bi7k: 1/11 → 6/6 trọn câu hai đầu; 4oOZ: 6/9 → 10/12, số Short 9 → 12), score TB gần như không đổi (8,6 → 8,3; 8,7 → 8,5; 8,6 → 8,75), thời gian tương đương. Số Short ít hơn ở Bi7k (11 → 6, vì candidate trọn câu hiếm) và yzR1 (13 → 8, chỉ 1/8 trọn câu vì không có candidate để chọn). Tức nhãn chỉ giúp AI **chọn** trong candidate sẵn có; không tạo ranh giới mới.
- Số Short (b) ở Bi7k thấp hơn nhưng tất cả trọn câu; tổng thời lượng 880 s → 545 s.

## 5. M4 — title từ văn bản gốc

Cùng model / prompt / validate production (`titling` v2; `evidence` phải nằm trong text đưa vào — ở đây là đoạn văn bản gốc D5 nối bằng dấu cách; prompt không đổi nên vẫn nói "caption tự động không dấu câu"). 50 Short: 50/50 có title hợp lệ (không Short nào `untitled`; 0 Short bị `…`), 4 title giống hệt bản cũ. Văn bản gốc dài hơn lời nói của Short do mở rộng D5: cột "Đầu/cuối thêm" (token); title mới có thể nói về phần ngoài Short (ví dụ Bi7k k10 "May mắn gặp được kinh điển này…" từ 20 + 10 token thêm).

Cột "Từ lạ cũ / mới" là đánh dấu sơ bộ tự động: từ trong title không xuất hiện ở văn bản gốc của tập (gợi ý lỗi chính tả / thuật ngữ, hay chỉ là từ đồng nghĩa — **ORCHESTRATOR chốt**). Cột "Lỗi cũ / mới" do ORCHESTRATOR chốt (đọc title + `old_evidence` / `new_evidence` + `doc_text` trong `results/m4.json`; dò thêm cặp từ của title cũ có trong caption mà không có trong văn bản):

- **Title cũ**: 1/50 lỗi chính tả mang từ caption vào title — yzR1 k04 "không cùng tận số" (gốc "không cùng tần số"), title thành vô nghĩa. Các "từ lạ" tự động còn lại là từ thường / đồng nghĩa, không phải lỗi. Caption có lỗi ở evidence (ví dụ "nge", "Thoát Ly") nhưng AI ít khi chép nguyên vào title.
- **Title mới**: 0 lỗi chính tả. Lỗi khác: 4/50 viết thường chữ đầu (một có "phật"), 1 viết hoa thừa — do prompt vẫn nói "caption không dấu câu", sửa được bằng prompt / hậu xử lý; 3/50 lấy evidence một phần từ phần mở rộng D5 nằm ngoài Short (title có thể nói điều người xem không nghe).
- Thuật ngữ: title mới dùng đúng thuật ngữ văn bản (ví dụ "tin hiểu … hành chứng", "Ấn Tổ", "nhất chân pháp giới"); về nội dung hai cột ngang nhau, không bên nào rõ ràng hay hơn.


#### Bi7kVGbnPfE

| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới | Lỗi cũ | Lỗi mới |
|---|---|---|---|---|---|---|---|---|
| k01 | 90 | Mỗi bộ kinh đều có 4 phần quan trọng | Bộ Kinh nào cũng có 4 phần quan trọng | 31/1 | 4 | 4 | - | viết hoa thừa "Bộ Kinh" |
| k02 | 97 | Chữ Phật nghĩa là gì? Ai cũng biết | Chữ Phật được tạo ra như thế nào? | 13/1 | - | - | - | - |
| k03 | 136 | Làm sao biết mình đã giác ngộ? | Nghe khen vui, nghe chê khó chịu là chưa giác ngộ | 11/1 | - | khen | - | - |
| k04 | 52 | Không giúp người, không thể phá được chướng ngại | Không giúp người, không thể phá được chướng ngại | 36/8 | ngại | ngại | - | - |
| k05 | 67 | Học Phật rồi khổ sẽ hết mãi mãi? | Không thành Phật, bạn sẽ phải chịu khổ mãi mãi? | 15/1 | mãi, mãi | mãi, mãi | - | - |
| k06 | 94 | Làm giường nghỉ ngơi bên cạnh niệm Phật đường | Niệm mệt thì nghỉ, khỏe lại niệm tiếp | 15/0 | - | - | - | - |
| k07 | 87 | Phật pháp cần người trẻ phát tâm hoằng pháp | 48 người thành Phật thì còn gì bằng? | 21/1 | - | - | - | - |
| k08 | 38 | Cách làm công đức lớn nhất theo Phật dạy | Làm công đức to lớn nhất như thế nào? | 19/1 | theo | - | - | - |
| k09 | 110 | Phật dạy chỉ có một con đường thành Phật | Pháp nhất thừa là pháp thành Phật | 0/0 | - | - | - | - |
| k10 | 54 | Mỗi câu kinh đều nói về quả Phật | May mắn gặp được kinh điển này là điều hiếm có | 20/10 | - | hiếm | - | - |
| k11 | 55 | Niệm Phật là nhân, quả báo sẽ đến như thế nào? | Niệm Phật mỗi ngày, quả báo hiện tiền | 0/1 | - | - | - | - |

#### 4oOZz2CBz3g

| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới | Lỗi cũ | Lỗi mới |
|---|---|---|---|---|---|---|---|---|
| k01 | 51 | Phân biệt thế pháp và Phật pháp từ tâm bạn | Tâm có vọng tưởng là thế gian pháp | 0/0 | - | - | - | - |
| k02 | 72 | Làm sao được thần linh bảo hộ? | Giữ tâm thiện, nói lời thiện, làm việc thiện thì sao? | 17/1 | - | - | - | - |
| k03 | 76 | Giúp người già thay đổi suy nghĩ về cái chết | Sinh tử là chuyển đổi, không phải kết thúc | 0/0 | - | - | - | - |
| k04 | 56 | Vì sao trồng dưa được dưa, trồng đậu được đậu? | Trồng nhân thiện được quả thiện, trồng nhân ác nhận ác báo | 0/0 | - | - | - | - |
| k05 | 157 | Điều kiện đầu tiên để thành đạo là gì? | Tại sao người phàm phu dễ bị hoàn cảnh ảnh hưởng? | 27/19 | - | dễ | - | evidence một phần ngoài Short (phần mở rộng D5) |
| k06 | 51 | Làm sao kết duyên với thiện tri thức mỗi ngày | Học Phật mỗi ngày như thế nào? | 0/0 | - | - | - | - |
| k07 | 55 | Làm sao hóa giải kiếp nạn đang đến? | Thiên tai nhân họa có phải do ác nghiệp gây ra? | 0/11 | - | gây | - | evidence một phần ngoài Short (phần mở rộng D5) |

#### yzR1eCK_iV0

| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới | Lỗi cũ | Lỗi mới |
|---|---|---|---|---|---|---|---|---|
| k01 | 138 | Tâm không loạn, mọi kinh đều hiện ra | Tâm loạn thì pháp giới thay đổi như thế nào? | 5/0 | - | - | - | - |
| k02 | 124 | Có thể quay về quá khứ nếu vượt qua tốc độ ánh sáng? | Có thể quay về quá khứ nếu vượt qua tốc độ ánh sáng? | 15/1 | - | - | - | - |
| k03 | 66 | Phật không trụ nơi nào cả, chỉ đến nơi có duyên | Phật không trụ nơi nào, chỉ đến nơi có duyên | 17/1 | - | - | - | - |
| k04 | 124 | Đi vào không gian không cùng tận số | Người mạt pháp nên tu pháp môn nào? | 8/1 | - | - | chính tả từ caption: "tận số" (gốc "tần số") → title vô nghĩa | - |
| k05 | 175 | Tâm không định được, làm sao tu thành? | tụng niệm khó giữ tâm được không? | 12/0 | - | giữ | - | viết thường chữ đầu |
| k06 | 117 | Tất cả pháp như mộng, không nên chấp trước | Tất cả pháp như mộng huyễn, không nên chấp trước | 0/1 | - | - | - | - |
| k07 | 39 | Đại tỳ kheo khác gì tỳ kheo thường? | Số lượng trong kinh có ý nghĩa gì? | 25/2 | - | - | - | evidence một phần ngoài Short (phần mở rộng D5) |
| k08 | 49 | Tại sao đoàn thể Phật tử được tôn trọng nhất? | Tại sao đoàn thể Phật tử được tôn kính nhất? | 16/1 | - | - | - | - |
| k09 | 53 | Tâm nghĩ thiện hay ác quyết định nghiệp thiện ác | Hành động của bạn bắt nguồn từ suy nghĩ nào? | 8/8 | - | nguồn | - | - |
| k10 | 87 | Tại sao xã hội và thế giới có hòa bình hay không? | muốn hiểu xã hội, hãy xem tâm người | 10/8 | - | - | - | viết thường chữ đầu |
| k11 | 66 | Tham Phật pháp cũng đọa cõi ngạ quỷ? | Tham Phật pháp cũng đọa cõi ngạ quỷ? | 13/1 | - | - | - | - |
| k12 | 141 | Tham Phật pháp có phải điều tốt không? | phật pháp không phải để tham | 5/0 | - | - | - | viết thường chữ đầu, "phật" |
| k13 | 98 | Cách nhìn người khác quyết định thế giới bạn sống | Cách nhìn người quyết định môi trường sống | 16/1 | - | - | - | - |

#### Bi7kVGbnPfE.kt

| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới | Lỗi cũ | Lỗi mới |
|---|---|---|---|---|---|---|---|---|
| k01 | 317 | Học kinh không chỉ hiểu mà phải thực hành | học kinh không chỉ tin hiểu mà phải hành chứng | 31/1 | hiểu | hiểu | - | viết thường chữ đầu |
| k02 | 255 | Học Phật phải luôn tỉnh thức mỗi lúc | Học Phật mà không tự kiểm điểm thì chưa phải là Phật | 16/1 | - | - | - | - |
| k03 | 332 | Không giúp người, không thể thành Phật | Không giúp người, không thể thành Phật | 7/12 | - | - | - | - |
| k04 | 404 | Vì sao duyên khác, kết quả khác | Tại sao gặp chánh pháp vẫn thoái tâm? | 26/1 | kết | - | - | - |
| k05 | 377 | 48 người cùng chí nguyện niệm Phật có thể thành Phật | 48 người cùng chí hướng có thể thành Phật | 0/0 | - | - | - | - |
| k06 | 277 | Phật dạy chỉ có một pháp duy nhất để thành Phật | Phật nói ba thừa, hai thừa là để làm gì? | 0/10 | duy | - | - | - |

#### 4oOZz2CBz3g.kt

| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới | Lỗi cũ | Lỗi mới |
|---|---|---|---|---|---|---|---|---|
| k01 | 243 | Tâm có vọng tưởng là thế gian pháp | Phân biệt pháp từ tâm hay từ pháp? | 0/0 | - | - | - | - |
| k02 | 397 | Ba cuốn sách này cứu được kiếp nạn | Ba cuốn sách giúp cứu kiếp nạn theo lời Ấn Tổ | 0/5 | cuốn | cuốn | - | - |
| k03 | 245 | Vì sao dịch sách này ra nhiều thứ tiếng? | Dịch sách ra nhiều thứ tiếng giúp mọi người hiểu rõ hơn | 13/1 | - | - | - | - |
| k04 | 378 | Cảm ứng là đạo lý gì? | Một ý niệm nhỏ cũng ảnh hưởng lớn | 0/1 | - | - | - | - |
| k05 | 338 | Tại sao phải hiểu rõ bốn câu này? | Tại sao người phàm phu dễ bị ảnh hưởng bởi môi trường? | 36/1 | - | dễ, môi, trường | - | - |
| k06 | 299 | Tại sao mỗi người đều phải chịu báo ứng? | Báo ứng cá nhân và gia đình có thật không? | 0/0 | - | cá | - | - |

#### yzR1eCK_iV0.kt

| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới | Lỗi cũ | Lỗi mới |
|---|---|---|---|---|---|---|---|---|
| k01 | 306 | Thời gian không gian có thật không? | Tâm quy nhất, một niệm không sanh là gì? | 5/1 | - | - | - | - |
| k02 | 353 | Phật không trụ nơi nào cả, chỉ đến nơi có duyên | Phật không trụ nơi nào, chỉ đến nơi có duyên | 17/1 | - | - | - | - |
| k03 | 345 | Tất cả pháp chỉ là ảo ảnh, không nên chấp trước | Tất cả pháp đều như giấc mộng | 11/1 | ảo | giấc | - | - |
| k04 | 385 | Cảnh giới địa ngục do tâm tưởng của chính mình tạo ra | Tâm nghĩ khác, nghiệp tạo khác | 26/1 | - | - | - | - |
| k05 | 347 | Tham Phật pháp cũng đọa cõi ngạ quỷ? | Tâm tham có thể đưa bạn đến cõi ngạ quỷ | 13/1 | - | đưa | - | - |
| k06 | 274 | Chướng ngại của bạn là gì? Tìm ra để vượt qua | Người niệm Phật mà không vãng sanh là vì sao? | 12/1 | - | - | - | - |
| k07 | 409 | Chỉ nhìn khuyết điểm người khác, cuộc đời hỏng ngay | Tất cả mọi việc đều do tâm mình tạo ra | 11/1 | - | - | - | - |

## 6. M5 — mẫu để xem / nghe

Biến thể (b) là biến thể tốt hơn. Mỗi cặp: Short `base` (chạy lại selection production) và Short (b) chồng lấn nhau. Dựng bằng stage `titling` + `render` production trong workspace phụ `<id>-m5base` / `<id>-m5b` (bản sao). File mẫu:

| Tập | cặp | vai | clip | source (giây) | file |
|---|---|---|---|---|---|
| 4oOZz2CBz3g | 1 | base | k02 | 488–552 (54 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/4oOZz2CBz3g_pair1_base_k02.mp4` |
| 4oOZz2CBz3g | 1 | b | k02 | 488–552 (54 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/4oOZz2CBz3g_pair1_b_k02.mp4` |
| 4oOZz2CBz3g | 2 | base | k06 | 2287–2434 (110 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/4oOZz2CBz3g_pair2_base_k06.mp4` |
| 4oOZz2CBz3g | 2 | b | k08 | 2287–2361 (63 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/4oOZz2CBz3g_pair2_b_k08.mp4` |
| Bi7kVGbnPfE | 1 | base | k03 | 875–1036 (136 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair1_base_k03.mp4` |
| Bi7kVGbnPfE | 1 | b | k01 | 959–1069 (86 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair1_b_k01.mp4` |
| Bi7kVGbnPfE | 2 | base | k04 | 1161–1224 (52 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair2_base_k04.mp4` |
| Bi7kVGbnPfE | 2 | b | k02 | 1079–1224 (116 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair2_b_k02.mp4` |
| Bi7kVGbnPfE | 3 | base | k05 | 1615–1696 (67 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair3_base_k05.mp4` |
| Bi7kVGbnPfE | 3 | b | k03 | 1590–1678 (67 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair3_b_k03.mp4` |
| Bi7kVGbnPfE | 4 | base | k09 | 3150–3267 (110 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair4_base_k09.mp4` |
| Bi7kVGbnPfE | 4 | b | k06 | 3150–3267 (110 s) | `/home/ntnghia/.cache/auto-short-cp820-test/samples/Bi7kVGbnPfE_pair4_b_k06.mp4` |

Title của các mẫu là title production (caption) của từng workspace phụ, không phải title M4. Cặp 4oOZ-1 và Bi7k-4 là cùng một đoạn ở cả hai biến thể (đối chứng, đã trọn câu hai đầu). Cặp 4oOZ-2: cùng điểm đầu, (b) cắt cuối ở câu (ngắn hơn 47 s). Cặp Bi7k-1, -2, -3: đoạn khác nhau chồng lấn một phần (xem cột source).

## 7. Giới hạn của phép đo

- Mẫu nhỏ: 3 tập (31 Short + 19 khai thị), chỉ 1 tập dùng Whisper; số lượng và tỷ lệ mang tính định hướng.
- Văn bản gốc là bản đã biên tập (có câu thêm / bớt); phép gióng nội suy ở chỗ không khớp (0–3 đầu / cuối mỗi tập) nên một số "thiếu token" ước lượng.
- Chạy lại selection có nhiễu (4oOZ base 9 ≠ 7); mỗi biến thể chỉ chạy một lần.
- Trong lúc M5 chạy, Ollama có model `qwen3:14b` nạp sẵn (không phải job 8080; `expires_at` không đổi, `running_stages` rỗng) — thời gian M5 không dùng làm số đo.
- M3 / M5 không chạy cho tập `.kt` (prompt `kt1`, cửa sổ lớn hơn); M1, M2, M4 có.
- Thay đổi file ở repo chính trong lúc chạy (web 8080 của HUMAN LEAD: `archive.json` các tập này, `review.json` / render các tập khác) không do script: script từ chối `workspace.dir` / `output_dir` thuộc repo chính và chỉ ghi vào bản sao.

## 8. Khuyến nghị (PROPOSED — chưa có quyết định HUMAN LEAD)

### 8.1 Title từ văn bản gốc — PROPOSED: không làm bây giờ

- Lợi: tránh lỗi chính tả từ caption, nhưng lỗi này hiếm (1/50 title ở 3 tập) và HUMAN LEAD đã sửa title tay được (CP8.2 / CP9).
- Giá: CP6 đổi nguồn text + prompt mới → hash stage `titling` đổi → mọi tập cũ có `titles.json` stale (chạy lại titling + render, tick "Đã đăng" thành stale); titling phụ thuộc `post/doc.py` + mạng (`ph.tinhtong.vn`); phải cắt text về phần gióng trực tiếp (bỏ mở rộng D5) để title không nói về đoạn ngoài Short; sửa prompt để viết hoa đúng.
- Nếu HUMAN LEAD vẫn muốn: làm S2 riêng, chỉ áp dụng khi tập có văn bản (`match` ≥ 0,8), text = phần gióng trực tiếp, chỉ áp cho tập mới (không tự render lại tập cũ).

### 8.2 Điểm cắt theo câu — PROPOSED: "ưu tiên" (biến thể b), chỉ áp cho tập mới

- **Bắt buộc (a)**: không khả thi — tập caption YouTube còn 0–3 candidate trong mục tiêu (Thập Thiện 6: 0).
- **Ưu tiên (b)**: nhãn `[ĐẦU CÂU]` / `[CUỐI CÂU]` trong text đưa AI + đoạn giải thích trong prompt. Trọn câu hai đầu: Bi7k 1/11 → 6/6, 4oOZ 6/9 → 10/12; score gần như không đổi; thời gian như cũ. Không giúp khi candidate không có ranh giới câu (yzR1 1/8) và có thể giảm số Short (Bi7k 11 → 6). Giá: CP5 (prompt version mới, selection phụ thuộc `post/doc.py`, fallback = không nhãn khi không có văn bản); hash `selection` → `titling` → `render` đổi → tập cũ stale nếu chạy lại. Đề xuất: khi làm, đo lại trên 2–3 tập mới (mỗi biến thể chạy ≥ 2 lần vì nhiễu).
- **Gốc rễ (đổi CP4)**: tách unit tại ranh giới câu theo timestamp chữ. Chỉ hợp với Whisper (khoảng ngắt thật ở 92/151 điểm); caption YouTube không có thời điểm kết thúc thật của từ → dễ cắt cụt tiếng. Muốn áp cho tập caption phải chuyển các tập đó sang Whisper (chậm hơn, xem CP11) — lớn, để sau (b).
- **Rẻ nhất, độc lập**: lỗi cuối câu thiếu đúng **1 từ** (19/31 Short cuối giữa câu, phần lớn 1 token) vì CP4 cắt ở khoảng lặng giữa hai từ cuối câu. Một sửa nhỏ ở bước dựng đoạn (kéo điểm cuối tới hết từ kết câu khi có văn bản) có thể xử lý đa số "cuối giữa câu" mà không cần đổi selection — nên đo riêng trước (b).
- **Nguồn transcript quyết định nhiều hơn mọi thứ**: tập Whisper (4oOZ) đã trọn câu 5/7 không cần làm gì; tập caption 0–1/11–13.

### 8.3 HUMAN LEAD chọn

1. Title từ văn bản: không (đề xuất) / có, chỉ tập mới.
2. Điểm cắt: không / ưu tiên (b) (đề xuất) / sửa "thiếu 1 từ cuối" trước / đổi CP4 + Whisper.

Mỗi lựa chọn "có" là một task S2 riêng; không đổi production trước khi HUMAN LEAD duyệt.

**Quyết định (HUMAN LEAD 2026-10-03):** không làm — title giữ từ caption, điểm cắt giữ như hiện tại. Các khuyến nghị trên lưu làm tham khảo nếu sau này cần.
