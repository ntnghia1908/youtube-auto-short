# Code growth — báo cáo audit

| Metadata | Value |
|---|---|
| Status | AUDIT REPORT — NOT AUTHORITY |
| Task | `docs/tasks/AUDIT-code-growth.md` |
| Đo ngày | 2026-10-19, `main` @ `39f6c80` |
| Đầu vào | `docs/audit/code-growth-evidence.md`, `docs/audit/code-growth-prs.tsv` |

Báo cáo chỉ đề xuất. Không có thay đổi code / test / framework nào được authorize bởi file này.

## Tóm tắt (1 trang)

**Kết luận.** Code phình chủ yếu là **khối lượng tính năng do contract yêu cầu**, đóng gói trong PR lớn, cộng với **test nhiều trên mỗi AC**. Code *thừa thật sự* (trùng lặp, chết, wrapper mỏng) trong `src/` nhỏ: ≈ 0,5 % trùng lặp, ≈ 35 dòng chết, ≈ 150–250 dòng gộp được. Phần thừa lớn nhất nằm ở **script bench một lần** (≈ 3,3k dòng trong `scripts/` + `tools/`, không được `src/` / `tests/` dùng). Vấn đề hành vi rõ nhất của agent là **viết lại helper có sẵn thay vì tìm và dùng lại**. Có ca đã gây bug: CP8.15 B1 viết lại `titling.logic.clip_text` sai. Kèm theo đó là **dồn code vào god-file** (`web/app.py` 3054 dòng, `static/app.js` 3614 dòng). Code đã thêm hầu như không bị dọn sau đó: 91–100 % dòng của 8 PR được đào sâu còn nguyên tới HEAD.

**Top nguyên nhân** (nhóm theo AC3):

1. **Contract** (lớn nhất về số dòng): scope nhiều sub-feature trong một contract. Ví dụ CP8.15 có 12 AC, gồm upload, tìm ảnh từ link và security SSRF. PR stacked gom 6–7 task, như #10 (42 commit) và #82. Không có ngân sách diff, không có mục "code bị thay / xóa".
2. **Prompt delegation**: chỉ 15/73 prompt nhắc tái dùng, 21/73 nhắc xóa, 0/73 giới hạn test. Contract của 8 PR đào sâu có 0 dòng giới hạn test, trừ CP8.31.
3. **IMPLEMENTER**: không grep trước khi viết helper. Ví dụ `_now` có 7 bản giống `workspace.utc_now`, phân tích URL YouTube bị chép từ `web/urls.py` sang `post/logic.py`, `_read_json` có 7 bản. Agent cũng thêm hàm lồng trong `create_app` và gọi private `ep._label` / `ep._zip_series` thay vì tách module.
4. **Review ORCHESTRATOR**: review bắt lỗi đúng / sai (B1) nhưng không có bước kiểm trùng lặp / code chết / test-per-AC. Không review nào đo các chỉ số này.

**Đề xuất xếp theo lợi ích / chi phí** (chi tiết §5):

| # | Đề xuất | Loại | Lợi ích | Chi phí |
|---|---|---|---|---|
| F1 | Delegation + READY report bắt buộc mục "tái dùng": helper mới phải kèm bằng chứng đã tìm (grep) và lý do không dùng cái có sẵn | framework | cao (bug B1, 7 bản `_now`) | thấp |
| F2 | Contract có mục "Code bị thay / xóa" + READY report ghi dòng thêm / xóa | framework | cao cho CHANGE | thấp |
| F3 | Ngân sách test theo AC: READY report có bảng AC → test; vượt ~3 test / AC phải parametrize hoặc nêu lý do | framework | trung bình (test ≈ 1:1 code) | thấp |
| F4 | Ngân sách diff / PR: > ~800 dòng app hoặc > 1 task / PR phải tách hoặc ghi lý do trong contract | framework | trung bình (review được) | trung bình |
| F5 | Checklist review ORCHESTRATOR: chạy `jscpd` + `vulture` trên file đổi (tạm, không dependency) | framework | trung bình | thấp |
| P1 | Quyết định số phận ≈ 3,3k dòng bench một lần (xóa, giữ số liệu trong docs) | dự án | cao về dòng | thấp |
| P2 | Gộp helper JSON / thời gian / URL YouTube vào chỗ có sẵn | dự án | thấp–trung bình (≈ 100–170 dòng, giảm rủi ro lệch) | thấp |
| P3 | Fixture test chung (`tcfg`, `client`, `wait_for`, `login`, `ws`) | dự án | ≈ 150–250 dòng | trung bình (31 file) |
| P4 | Tách `web/app.py` theo router (CP8.5 / CP8.15 / CP8.31 …) | dự án | dễ đọc / review, không giảm dòng | cao (S2) |

## 1. Phạm vi và cách đo

- `src/` = 27,97k dòng Python. Con số "app ≈ 34,1k" trong evidence gồm cả `scripts/` (3,9k) và `tools/` (2,2k). `tests/` = 31,5k. Web JS / HTML / CSS = 6,5k.
- Công cụ cài tạm trong phiên, không vào repo: `vulture` 2.16 (`pip install --user`), `jscpd` 5.4.1 (`npx -y`), cùng script AST / blame nhỏ (lệnh chạy lại ở phụ lục A).
- Quét rộng do subagent `implementer` làm (2 lượt, chỉ đọc). Đào sâu PR và spot-check do ORCHESTRATOR làm.
- Chưa chạy được `pytest --durations`: phiên cloud không có `pytest`. Chưa có số thời gian test.

## 2. Số đo toàn repo (AC1)

### 2.1 Trùng lặp (`jscpd --min-lines 8 --min-tokens 60`)

| Nhóm | Dòng | Dòng trùng | % | Clone |
|---|---|---|---|---|
| `src/auto_short` *.py | 27 923 | 147 | 0,53 | 13 |
| `scripts` + `tools` *.py | 6 131 | 65 | 1,06 | 5 |
| `tests` *.py | 31 511 | 311 | 0,99 | 23 |
| web static + sutra (js / html / css) | 6 515 | 116 | 1,78 | 8 |

Clone khối lớn ít. Trùng *ngữ nghĩa* (helper nhỏ viết lại, jscpd không bắt vì < 8 dòng) mới là vấn đề:

| Chức năng | Số bản | Vị trí | Ghi chú |
|---|---|---|---|
| UTC now `"%Y-%m-%dT%H:%M:%SZ"` | 7 `_now` + `review/publish.utc_now` + `enhance/state.now_iso` + `sutra/store._iso` + worker | `post/doc.py:320`, `post/stage.py:56`, `web/jobs.py:144`, `web/playlists.py:129`, `review/archive.py:89`, `titling/added.py:46`, `review/publish.py:98`… | `workspace.utc_now` có từ CP2 |
| Đọc JSON tolerant (`dict | None`) | 3 giống hệt | `enhance/state.py:292`, `web/episodes.py:41`, `review/tombstone.py:27` | |
| Đọc JSON strict của stage | 4, chỉ khác exception | `analysis/` / `selection/` / `titling/` / `render/stage.py` | mẫu copy-paste stage CP4–CP7 |
| Phân tích URL YouTube | 2 | `web/urls.py:41` (CP8.3) ↔ `post/logic.py:39` (CP8.15) | chép nguyên khối, đổi exception |
| Đọc doc `entries` cũ | 2 | `post/stage.py:203` ↔ `titling/added.py:51` | |
| Helper JS `api` / `el` | 2 | `app.js:51,1032` ↔ `favorites.js:16,69` | |

Đối chứng: `workspace.atomic_write_json` được dùng lại ở 34 file và không có bản copy. Agent *có* tái dùng khi helper nổi tiếng và đã xuất hiện ở nhiều file. Helper nhỏ nằm "giấu" trong module khác thì bị viết lại.

### 2.2 Code chết (`vulture --min-confidence 60`, đã lọc tay + grep toàn repo)

190 cảnh báo. ≈ 130 là route FastAPI; phần còn lại phần lớn là hook framework / pydantic / `HTMLParser` / test hook. Kiểm bằng grep thì không route nào thiếu caller. Mục chết thật:

| file:dòng | Tên | Gọi bởi |
|---|---|---|
| `review/logic.py:278` | `added_ids` | không ai |
| `review/logic.py:343` | `without_added` | chỉ test |
| `render/plan.py:504` | `planned_video_seconds` | chỉ test |
| `web/jobs.py:650` | `active_vertical` | không ai |
| `enhance/state.py:36`, `review/tombstone.py:23`, `selection/logic.py:25` | `FACE_MODELS`, `KEYS`, `TIME_KEYS` | không ai |
| `tools/enhance_worker/worker.py:185` | `utcnow_iso` | không ai |

Tổng ≈ 35 dòng trong `src/`, ≈ 30 dòng trong `scripts/`. Code chết **không** phải vấn đề lớn.

**Bench / đo một lần** (chỉ docs lịch sử dẫn tới, không `src/` / `tests/` dùng):
- `scripts/`: `cp11_bench.py` 1163, `measure_doc_cut_title.py` 677, `enhance_quality_bench.py` 540 (+ `.ps1` 147), `enhance_bench_win.py` 338, `cp13_e1_bench.py` 312, `cp133_compare.py` 312, `sutra_pdf_measure.py` 89.
- `tools/`: `measure_adaptive_boundary.py` 42.

Tổng ≈ 3,3k dòng. Đây là phần lớn nhất của "app+" không phải sản phẩm. Ví dụ PR #73 (CHANGE CP13.3) = 852 dòng app, trong đó 852 là script bench.

### 2.3 Abstraction mỏng

21 hàm top-level chỉ là `return <call>` và có 1 call site. Ví dụ: `enhance/tokens.new_token`, `web/prepared.is_prepared`, `post/store.with_posted`, `config._default_corrections_path`. Lợi ích inline ≈ 15–25 dòng, không đáng làm riêng. Không thấy class / interface "phòng hờ" không dùng.

### 2.4 Test

| Số đo | Giá trị |
|---|---|
| File / hàm test | 116 / 1473 (122 test có parametrize) |
| Dòng test / dòng `src` | 1,13; theo package từ 0,7 (sutra, transcript) tới 1,4–1,5 (selection, theme_index) |
| Test trùng (AST chuẩn hóa, thân ≥ 4 dòng) | 3 nhóm, 7 test, ≈ 19 dòng |
| Fixture / helper cùng tên ở nhiều file | `tcfg` 31 file (12 biến thể), `client` 18, `wait_for` 13, `login` / `_login` 22, `ws` 11, `make_client` 9 |
| Test bám implementation | 11 `monkeypatch` hàm private, 10 import tên private, 16 assert HTML nguyên văn, 66 file đọc `static/*` rồi assert chuỗi, 7 assert số lần gọi mock |

Test **không trùng**. Lượng test lớn đến từ (a) nhiều test / AC (§3) và (b) mỗi file tự dựng fixture riêng. Assert HTML / JS nguyên văn là cách repo kiểm UI khi không có trình duyệt: giòn nhưng có chủ đích.

## 3. Đào sâu 8 PR (AC2)

Số đo chung. *Còn ở HEAD* = `git blame HEAD` dòng thuộc commit của PR, không tính dòng bị move. *Test / AC* = hàm `test_` mới chia số AC trong contract của PR.

| PR | Task (số contract) | Commit | app + / − | test + | Test / AC | Còn ở HEAD app / test / web |
|---|---|---|---|---|---|---|
| #10 | CP8.2 → CP8.7 (7, stacked) | 42 | 3889 / 84 | 3573 | 141 / 42 = 3,4 | 91 / 98 / 93 % |
| #82 | SR1.1–SR1.5 + SR2.1 (6) | 17 | 2198 / 23 | 1802 | 138 / 34 = 4,1 | 99 / 100 / 100 % |
| #35 | CP8.15 | 6 | 1892 / 11 | 1414 | 91 / 12 = 7,6 | 97 / 99 / 65 % |
| #98 | TC2, TC2.1–TC2.2 (3) | 18 | 1734 / 62 | 2071 | 94 / 18 = 5,2 | 99 / 97 / 38 % |
| #57 | CP13.1a (2) | 4 | 1625 / 0 | 360 | 13 / 17 = 0,8 | 97 / 100 / — |
| #74 | CP13.4 (CHANGE) | 4 | 576 / 30 | 337 | 14 / 6 = 2,3 | 100 / 100 / 92 % |
| #78 | CP8.31 (CHANGE) | 13 | 296 / 8 | 497 | 26 / 8 = 3,3 | 91 / 100 / 100 % |
| #72 | CP8.29 (CHANGE) | 5 | 181 / 67 | 327 | 14 / 6 = 2,3 | 98 / 100 / 80 % |

### #10 CP8.7-playlist (gồm CP8.2–CP8.7)

- **Cần thiết:** web MVP đầu tiên. Gồm `web/app.py` 606, `app.js` 934, `episodes.py` / `jobs.py` / `playlists.py` ≈ 950, cùng `review/*` (publish, titles, tombstone, archive, names). Mỗi phần ứng với một contract đã duyệt.
- **Thừa:**
  - `review/publish.utc_now`, `review/archive._now` và `review/tombstone._read_json` viết lại helper đã có ở `workspace.py`.
  - `review/logic.added_ids` chết.
  - `config._hashtags` ↔ `review/names.hashtags` cùng tên khác chỗ.
- **Nguyên nhân:**
  - Contract: 7 task stacked thành 1 PR, base là nhánh `feature/cp8.6-storage`; HUMAN LEAD review một diff 9k dòng.
  - IMPLEMENTER: không tìm helper có sẵn.
  - Contract CP8.7 có 0 dòng nhắc tái dùng hoặc xóa.

### #82 SR1 sutra reader (SR1.1–SR1.5, SR2.1)

- **Cần thiết:** ứng dụng mới.
  - `sutra/` ≈ 1,9k: `pdf.py` 740 do PDF thật nhiều biến thể (S5a), `importer.py` 438.
  - `sutra.js` 809.
  - Tỉ lệ test / src thấp nhất (0,7).
- **Thừa nhỏ:** `sutra/store._now` / `_iso` / `slugify` lặp lại cái có ở `workspace` / `ingest/source.py` (slug khác độ dài và fallback, hợp lý). `sutra/store._lock` ↔ `theme_plan._lock`. `scripts/sutra_pdf_measure.py` 89 dòng là script đo một lần.
- **Nguyên nhân:** contract (6 task 1 PR). Bản thân code gọn, đúng boundary C1 (`sutra/` không import Auto Short).

### #35 CP8.15 community post

- **Cần thiết:** 12 AC phủ text nguồn, AI + chiếu token, ảnh, upload, tìm ảnh từ link (P5b) và security SSRF (P13). `post/fetch.py` 257 + `images.py` 213 phục vụ đúng AC10–12.
- **Thừa:**
  - **`post/logic.py:39` chép nguyên khối phân tích URL YouTube từ `web/urls.py:41`**.
  - `post/stage._now`.
  - `post/stage.py:203` ↔ `titling/added.py:51`.
  - `post/stage.py:89` ↔ `pipeline.py:111` (bắt lỗi Ollama).
  - **Round 1 viết lại cắt `head_cut` thay vì dùng `titling.logic.clip_text`, ra bug B1**. Docstring còn ghi sai là HUMAN LEAD đã duyệt sự đơn giản hóa đó.
- **Test:** 91 test / 12 AC. Round 2 viết lại phần test P3 vì đổi thiết kế (P3 amendment). Đó là test bị thay, không phải test dư.
- **Nguyên nhân:**
  - IMPLEMENTER: không tái dùng; B1 cho thấy viết lại vừa thừa vừa sai.
  - Contract: scope rất rộng trong 1 task.
  - Review bắt được B1 nhưng không bắt được bản copy URL.

### #98 TC2 theme compilation planner

- **Cần thiết:** `theme_plan` 556, `theme_render` ≈ 580, `web/theme_plan.py` 407.
- **Churn:** chỉ 38 % JS còn ở HEAD. `theme_plan.js` được làm lại ở TC2.3 (`c1d3f65` "one-step thematic compile"). Đây là **thay đổi yêu cầu** sau manual test, không phải agent viết thừa.
- **Thừa nhỏ:** `theme_render/sources._duration` ↔ `web/compilations` probe; `theme_plan._lock` ↔ `sutra/store._lock`.
- **Test:** 94 / 18 = 5,2 test / AC, gồm 5 file test mới ≈ 2,1k dòng; `test_web_theme_plan.py` 811 dòng là file test lớn nhất repo.
- **Nguyên nhân:** prompt / contract không giới hạn test; IMPLEMENTER sinh test rộng.

### #57 CP13.1a enhance worker (tools/)

- **Cần thiết:** worker Windows `worker.py` 1238 + script cài đặt `.ps1` ≈ 950. Đây là code chạy ngoài package, test phần lớn qua `fake_server.py` 329.
- **Thừa:** `utcnow_iso` chết; `srvgg.py` ↔ `scripts/enhance_bench_win.py` clone 19 dòng (kiến trúc SRVGG chép sang bench).
- **Nguyên nhân:** worker 1 file 1,2k dòng là lựa chọn đóng gói (copy 1 file sang Windows), chấp nhận được. Thừa thật chỉ ≈ 20 dòng.

### #74 CP13.4 enhance GFPGAN (CHANGE)

- **Cần thiết:** `face.py` 271 (pha khôi phục mặt), `service.py` / `state.py` +120 / −19 (chọn model).
- **Thừa:** `enhance/state.FACE_MODELS` chết; `face.py:64` ↔ `scripts/enhance_quality_bench.py:101` 13 dòng chép từ bench.
- **Đánh giá:** gọn. Tỉ lệ xóa 5 % là hợp lý vì đây là CHANGE *thêm* năng lực. Nguồn thừa: code bench được chép thay vì bench import từ worker.

### #78 CP8.31 downloads mobile (CHANGE)

- **Cần thiết:** D1–D6 (zip tick, `.docx`, nút tải, CSS mobile, enhance sang tab Theo dõi). `post/export.py` 64 gọn.
- **Thừa / cấu trúc:** +206 dòng vào `web/app.py`, gồm 8 hàm lồng trong `create_app` (`_download_fields`, `_posts_ranges`, `_export_group`, `_docx_response`…) và gọi private của module khác (`ep._label`, `ep._zip_series`, `ep._render_manifest`). Không thêm dòng chết, nhưng **god-file lớn thêm**; app.py 3054 dòng với 172 hàm lồng.
- **Test:** 1 file mới 435 dòng (26 test / 8 AC) + sửa test CP8.17 do đảo quyết định D1. Hợp lý.
- **Nguyên nhân:** IMPLEMENTER theo mẫu có sẵn trong `app.py` (mọi route + helper đều lồng). Contract không chỉ module đích. Review chấp nhận mẫu này từ CP8.3.

### #72 CP8.29 parallel prepare (CHANGE) — đối chứng

- `web/jobs.py` +129 / −49 (xóa 27 %), 1 file test 327 dòng (14 / 6).
- Không thấy trùng hoặc chết mới. Mẫu tốt: thay logic tại chỗ, xóa nhánh cũ.

## 4. Phân loại nguyên nhân (AC3)

| Nhóm | Nguyên nhân | Dẫn chứng | Ảnh hưởng (dòng) |
|---|---|---|---|
| **Contract** | Scope nhiều sub-feature / PR stacked nhiều task | #10 7 task / 42 commit; #82 6 task; CP8.15 12 AC | lớn nhất: phần lớn +34,6k là tính năng đã duyệt |
| **Contract** | Không có mục "code bị thay / xóa", không ngân sách diff / test | 0 / 8 contract có giới hạn test (trừ CP8.31 1 dòng); CP8.7 / CP8.29 / SR1.1 0 dòng tái dùng | FEATURE xóa 3 % |
| **Contract / bench** | Script đo một lần được commit vào `scripts/` như code | ≈ 3,3k dòng; #73 100 % là bench | ≈ 3,3k |
| **Prompt delegation** | Không yêu cầu tìm helper, không yêu cầu xóa, không giới hạn test | evidence §3: tái dùng 15/73, xóa 21/73, test 0/73; phiên có nhắc: 17,9 dòng viết / dòng thay vs 522,8 | gián tiếp, toàn bộ |
| **IMPLEMENTER** | Viết lại helper có sẵn | 7 `_now` vs `workspace.utc_now`; URL YouTube ×2; `_read_json` ×7; CP8.15 B1 | ≈ 100–170 + 1 bug |
| **IMPLEMENTER** | Test rộng theo từng nhánh, fixture tự dựng mỗi file | 5–7,6 test / AC ở #35 / #98; `tcfg` ×31 file | ≈ 150–250 fixture; test ≈ 1:1 code |
| **IMPLEMENTER + Review** | Bám mẫu god-file, gọi private chéo module | `web/app.py` 3054 dòng, 172 hàm lồng; 34 lời gọi `module._private(` trong `src` | cấu trúc, không phải số dòng |
| **Review** | Review đúng / sai, không đo trùng lặp / chết / test-per-AC | CP8.15 review bắt B1, không bắt bản copy URL; không review nào có số jscpd / vulture | để lọt các mục trên |
| **Yêu cầu đổi** (không phải thừa) | Làm lại UI sau manual test | TC2 JS còn 38 %, CP8.15 web 65 % | churn, đã bị thay |

Agent **không** thêm abstraction / interface phòng hờ đáng kể (§2.3), cũng không viết test trùng (§2.4).

## 5. Đề xuất (AC4)

### 5.1 Quy tắc framework (ai-dev-framework)

Canonical owner dự kiến: `core/docs/ai/workflow.md`. Đặt quy tắc ở §4 (task contract) và §7 (verification / review). Mẫu field nằm ở `templates/docs/tasks/_template.md`; adapter chỉ pointer tới đó.

| # | Quy tắc đề xuất | Owner | Đo hiệu quả |
|---|---|---|---|
| F1 | **Tái dùng trước khi viết.** Prompt delegation có mục "helper / module có sẵn liên quan" (ORCHESTRATOR grep trước). READY report liệt kê hàm public / helper mới kèm 1 dòng "đã tìm: <lệnh>, không dùng được vì …". | workflow §5 + template delegation | Bản copy helper mới / PR (grep tên + jscpd file đổi) → mục tiêu 0. Tỉ lệ prompt có chỉ dẫn tái dùng (evidence §3: 15/73 → ≥ 90 %). |
| F2 | **Code bị thay phải xóa.** Contract CHANGE / FEATURE có mục "Code bị thay / xóa" (có thể "không có"). READY report ghi `app + / −`. | workflow §4 + template | Tỉ lệ xóa / thêm theo Type (`code-growth-prs.tsv`, hiện FEATURE 3 %, CHANGE 34 %). Dòng viết / dòng thay (evidence §3: 26,5). |
| F3 | **Test theo AC.** READY report có bảng AC → test. Mặc định ≤ ~3 hàm test / AC, nhánh tương tự thì parametrize. Fixture dùng ≥ 2 file thì vào `conftest` / helper chung. | workflow §7 | Test / AC mỗi PR (hiện 2,3–7,6); dòng test / dòng app (hiện ≈ 1:1, BUG 1,7). |
| F4 | **Ngân sách diff.** Contract ghi ước lượng dòng app. > ~800 dòng app hoặc > 1 task / PR thì phải tách PR hoặc ghi lý do; không stack quá 2 task. | workflow §4 / §8 | Phân bố app+ / PR; số task / PR. |
| F5 | **Checklist review ORCHESTRATOR.** Chạy tạm `jscpd` + `vulture` trên file đổi (không thêm dependency). Kiểm F1–F3; kiểm module đích đúng boundary, không thêm vào god-file khi có module phù hợp. | workflow §7 | % trùng `src` (0,53 %) và số mục vulture thật (≈ 10) không tăng giữa 2 lần audit. |
| F6 | **Script đo / bench một lần.** Không commit vào `scripts/` mặc định; giữ số liệu + lệnh trong report của task. Nếu cần chạy lại thì ghi rõ "giữ vì …". | workflow §4 (Owned paths) | Dòng `scripts/` không được `src` / `tests` / docs hiện hành dẫn tới (hiện ≈ 3,3k). |

Chi phí: F1–F3 và F5 là thêm field / dòng vào template và report, gần 0 code. F4 cần HUMAN LEAD chấp nhận PR nhỏ hơn. Nên thử F1 + F2 + F3 trước trên 3–5 task, rồi đo lại bằng phụ lục A.

### 5.2 Refactor / dọn dự án (chỉ đề xuất, mỗi mục cần task riêng)

| # | Việc | Ước giảm | Rủi ro / class |
|---|---|---|---|
| P1 | Bench một lần (§2.2): xóa hoặc chuyển ra ngoài repo; số liệu đã nằm trong docs task | ≈ 3,3k dòng | thấp; docs còn trích lệnh, cần ghi commit lịch sử. HUMAN LEAD quyết (guide GPU Windows còn dùng `enhance_quality_bench.py`?) |
| P2 | Gộp helper: `_now` → `workspace.utc_now`; `_read_json` tolerant / strict vào `workspace`; URL YouTube `post/logic` → `web/urls` (hoặc module chung); `favorites.js` dùng helper `app.js` | ≈ 100–170 dòng | thấp (S1); kiểm bản `_now` nào được inject trong test |
| P3 | Xóa code chết §2.2 (+ test chỉ phục vụ nó) | ≈ 35 src + ≈ 30 scripts | thấp |
| P4 | Fixture test chung: `tcfg`, `client` / `make_client`, `wait_for` (gắn FIX test chập chờn CP8.10 ở current-state), `login`, `ws` | ≈ 150–250 dòng test | trung bình (31 file) |
| P5 | Tách `web/app.py` thành router theo nhóm route, bỏ gọi private chéo module | ≈ 0 dòng; giảm god-file | cao, S2: đụng public API boundary CP8.3, cần decision |

Tổng P1–P4 ≈ 3,6–4,0k dòng (≈ 5–6 % của ≈ 72k dòng code + test). Không kể P1 thì chỉ ≈ 0,3–0,5k. Phần lớn kích thước repo là tính năng đã duyệt, không phải thừa.

## Phụ lục A — lệnh chạy lại

Các script dưới đây nằm ngoài repo (scratchpad phiên). Nội dung đủ ngắn để chép lại khi cần.

```bash
# công cụ tạm (không thêm vào repo)
pip install --user vulture==2.16
J="npx -y jscpd@5.4.1 --min-lines 8 --min-tokens 60 --reporters json --silent"
$J --format python --output /tmp/a src/auto_short
$J --format python --output /tmp/b scripts tools
$J --format python --output /tmp/c tests
$J --format javascript,markup,css --output /tmp/d src/auto_short/web/static src/auto_short/sutra
python3 -m vulture src/auto_short scripts tools --min-confidence 60   # lọc tay route / hook (§2.2)

# helper viết lại
grep -rnE "^\s*def (_now|utc_now|now_iso|_iso|_read_json)\(" src tools

# test / AC của một PR (merge M, contract trong docs/tasks/ mà PR sửa)
git diff M^1 M -- tests | grep -cE '^\+\s*def test_'

# dòng còn ở HEAD: blame HEAD các file PR sửa, đếm dòng có commit ∈ git rev-list M^1..M^2,
# nhóm app / test / web như code-growth-prs.tsv (script ≈ 25 dòng, cần clone đầy đủ: git fetch --unshallow)
```

Quét test (AST): parse `tests/**/*.py`. Chuẩn hóa thân hàm (tên biến / hằng thành placeholder), so `ast.dump` để tìm test trùng, helper cùng tên ở nhiều file và chuỗi test liền kề chưa parametrize. Test bám implementation đếm bằng `grep -rEn` các mẫu `monkeypatch.setattr(.*\._`, `from auto_short.* import _`, `in r.text`, `read_text` trên `static/`, `call_count|assert_called`.

## Phụ lục B — giới hạn

- Transcript prompt chỉ có trên VM. Số §3 của evidence được dùng nguyên, không đo lại.
- `git blame` không theo dòng bị move (`-M` / `-C` không dùng): % còn ở HEAD có thể thấp hơn thực một chút.
- Gán test theo package là heuristic theo import. Mẫu "bám implementation" là số dòng khớp regex, chưa lọc tay.
- Quét JS chỉ bắt `function name(` / `const name = … =>`. Route kiểm bằng grep path, có thể sót URL dựng động.
- Không chạy được `pytest` (thiếu trong môi trường cloud) nên không có số thời gian test.
- Dependency FW-TOKEN-01 (ai-dev-framework) chưa kiểm được từ phiên này vì repo ngoài quyền truy cập. Đề xuất §5.1 dựa trên mô tả trong contract.
