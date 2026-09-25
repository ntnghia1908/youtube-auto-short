# Auto Short — Checkpoint Plan

Project: ntnghia1908/youtube-auto-short
Purpose: Xây dựng pipeline local để biến video giảng Pháp tiếng Việt thành một tập Shorts có chọn lọc, có tiêu đề/hook và render hoàn chỉnh.
Execution: Thực thi lần lượt bằng Claude Code theo Framework v4.
Execution profile mặc định: single-agent, trừ khi HUMAN LEAD quyết định đổi sang dual-agent cho một checkpoint cụ thể.

## 0. Quy tắc vận hành checkpoint

Mỗi checkpoint là một milestone, không phải một prompt để Claude tự do làm toàn bộ project.

Claude phải bootstrap từ repository theo thứ tự:
1. AGENTS.md
2. docs/ai/project-profile.md
3. docs/workflow/current-state.md
4. task contract đã APPROVED nếu checkpoint là S1/S2
5. AGENTS.md gần nhất của subtree liên quan
6. source/tests/authority liên quan

Nguyên tắc Framework v4:
- Repository là source of truth.
- Phân loại S0/S1/S2 trước khi thực thi.
- HUMAN LEAD quyết boundary và các decision gate.
- S1/S2 phải có task contract và APPROVE trước implementation.
- Sau APPROVE: PLAN -> IMPLEMENT -> VERIFY -> REVIEW -> CONVERGE -> READY.
- Không tự thêm dependency.
- Không mở rộng scope.
- Single-agent vẫn phải có review phase riêng.
- Không claim PASS/READY nếu verification chưa thực sự chạy.
- READY chưa phải DONE; integration vẫn do HUMAN LEAD quyết.
- Phát sinh decision gate ngoài boundary thì STOP.
- Cùng blocker sau 2 vòng fix/review thì BLOCKED.
- Mỗi normative rule chỉ có một canonical owner.

Project áp dụng ba lớp: Framework Core / Project Layer / Tool Adapter.

---

# CP0 — Framework Bootstrap & Pilot

Class: S0/S1 pilot tùy thay đổi cụ thể.

Goal: Xác minh Framework v4 thực sự hoạt động trong repo mới trước khi xây feature chính.

Scope:
- Review Core / Project Layer / Tool Adapter.
- Chạy node scripts/framework-check.mjs và ghi evidence.
- Kiểm bootstrap của Claude Code.
- Thực hiện 1 S0 thật.
- Thực hiện 1 S1 low-risk theo task contract + approval.
- Xác minh review/convergence/READY.

Không làm:
- Whisper/Ollama/FFmpeg feature.
- dependency mới.
- CP1.
- push/PR/merge nếu HUMAN LEAD chưa yêu cầu.

Gate: Chỉ khi CP0 READY mới bắt đầu CP1.

---

# CP1 — Product Contract & Architecture Baseline

Class: S2. Checkpoint này chạm scope, architecture, dependency và project-wide convention.

Goal: Chốt chính xác Auto Short làm gì và pipeline canonical trước khi code feature.

Canonical flow:
INPUT VIDEO -> INGEST/METADATA -> AUDIO/TRANSCRIPT -> SEGMENT/CLIP CANDIDATES -> AI SELECTION -> TITLE/HOOK -> RENDER -> OUTPUT SHORTS.

Phải chốt:
- input/output contract;
- Short duration policy;
- 9:16 composition;
- subtitle policy;
- title/header/hook structure;
- workspace và intermediate artifacts;
- resume/cache semantics;
- provenance/hash strategy;
- boundary giữa deterministic code và AI decision;
- provider abstraction cần thiết;
- dependency set;
- tiêu chí clip được chọn;
- tiêu chí output hợp lệ.

Không implement pipeline thật ngoài documentation/config cần thiết để ghi decision.

Gate: HUMAN LEAD approve architecture và các decision trước CP2.

---

# CP2 — Foundation: Config / Workspace / CLI / Resume

Class: S1 sau khi CP1 đã chốt decision.

Goal: Tạo skeleton chạy được và resume được mà chưa cần AI selection.

Scope:
- typed config;
- workspace/path model;
- metadata manifest;
- stage state;
- resume convention;
- CLI entrypoint;
- logging/error boundary;
- tests cho config + resume.

Kinh nghiệm từ youtube-vietnamese-dubber:
- stage phải tạo artifact inspectable;
- completed stage không chạy lại vô ích;
- cache/resume là requirement vận hành;
- hash/provenance nên thiết kế từ đầu.

Acceptance: CLI chạy; input tạo workspace deterministic; rerun không phá artifact đã hoàn thành; path/model không hardcode; tests PASS.

---

# CP3 — Vietnamese Transcript Pipeline

Class: S1.

Goal: Tạo transcript timestamp ổn định làm authority cho các bước chọn clip.

Scope:
- extract audio theo contract nếu cần;
- faster-whisper;
- transcript schema;
- read/write artifact;
- resume;
- failure handling;
- schema/round-trip tests.

Segment tối thiểu: id, start, end, text.

Không làm translation, TTS, clip selection hoặc render.

Acceptance: transcript.json hợp lệ; timestamp hợp lệ; rerun không transcription lại khi artifact còn valid; lỗi không làm hỏng workspace.

Model/provider cụ thể phải nằm trong dependency/adapter đã được approve ở CP1.

---

# CP4 — Clip Candidate & AI Selection

Class: S2 nếu selection policy chưa đủ rõ ở CP1; nếu đã chốt đầy đủ thì S1.

Goal: Biến transcript và thông tin boundary/video thành danh sách clip có timestamp, duration và lý do chọn.

Nguyên tắc: Không cắt theo interval cố định. Clip phải giữ được một ý tương đối hoàn chỉnh/coherent dựa trên transcript và timestamp.

Scope:
- segment grouping;
- candidate generation;
- shot/boundary information nếu CP1 yêu cầu;
- duration constraints;
- AI selector contract;
- structured output;
- validation/repair;
- ranking/filtering;
- clips artifact;
- deterministic fallback khi AI trả output lỗi.

AI selector tối thiểu trả: clip_id, start, end, reason.

Kinh nghiệm từ youtube-vietnamese-dubber:
- AI output phải validate trước downstream;
- batch lỗi không làm mất toàn bộ kết quả đã hoàn thành;
- clip phải trace được về transcript segments;
- không để AI tạo timestamp vượt source duration.

Không thêm vector DB/RAG/hạ tầng mới chỉ để chọn clip nếu chưa có S2 decision.

Acceptance: output validate; timestamp hợp lệ; duration đúng policy; resume được; trace được clip -> transcript; có failure path rõ.

---

# CP5 — Title / Hook Generation

Class: S1 hoặc S2 nếu thay đổi project-wide presentation policy.

Goal: Sinh title/hook và tách rõ metadata nguồn với nội dung AI-generated.

Cấu trúc khái niệm:
- TOP PANEL: nguồn/series/metadata nếu có.
- BOTTOM PANEL: AI hook/title.
- VIDEO: nội dung lecture.
- SUBTITLE: transcript.

Scope:
- title input contract;
- structured output;
- length/format validation;
- titles artifact;
- clip -> title mapping;
- fallback title khi AI fail;
- tests.

Acceptance: mỗi selected clip có title/hook hợp lệ; parse được; không phá layout contract; có fallback.

Không thay selection policy ở CP5.

---

# CP6 — Render Engine

Class: S1.

Goal: Render một clip đã có transcript + title thành Short 9:16.

Scope:
- normalization nếu cần;
- crop/scale;
- yellow panel/layout theo CP1;
- subtitle overlay;
- audio policy theo CP1;
- FFmpeg command generation;
- render manifest/result;
- resumable render;
- failure handling.

Không AI selection và không title generation.

Acceptance: output playable; đúng aspect ratio, duration, audio, panel/title placement và subtitle; output hợp lệ không bị render lại.

Verification: automated tests cho command construction/validation + ít nhất một real render fixture/sample.

---

# CP7 — End-to-End MVP: VIDEO -> SHORTS

Class: S1 nếu không phát sinh architecture/dependency gate mới.

Goal: Nối toàn bộ pipeline thành một vertical slice hoàn chỉnh.

Flow: INPUT -> METADATA -> TRANSCRIPT -> CLIPS -> TITLES -> RENDER -> OUTPUT.

Scope:
- stage orchestration;
- dependency ordering;
- resume toàn pipeline;
- stage failure boundary;
- output manifest;
- full-run CLI;
- e2e fixture ngắn.

Acceptance: input test đi từ đầu đến cuối và tạo nhiều Shorts; rerun không phá artifact; lỗi ở stage N cho phép resume từ stage N.

Không làm performance optimization lớn, distributed processing hoặc web UI.

---

# CP8 — Quality / Evaluation / Guardrails

Class: S2 vì metric/quality policy là project-wide behavior.

Goal: Đánh giá output về chất lượng chứ không chỉ kiểm tra pipeline chạy được.

Evaluate:
- clip coherence;
- start/end quality;
- duration;
- duplicate/near-duplicate clips;
- title validity/relevance;
- subtitle synchronization;
- visual composition;
- render correctness;
- artifact consistency;
- AI invalid-output rate.

Deliverables: observable evaluation criteria, validation checks, sample dataset/fixtures và report artifact.

Không tối ưu model hoặc thay selection algorithm chỉ vì cảm giác trước khi có evidence.

Acceptance: sample set cho biết output PASS/FAIL, lý do FAIL và artifact chứng minh.

---

# CP9 — Batch / Reliability / Performance Hardening

Class: S1; nâng S2 nếu xuất hiện architecture/dependency gate.

Goal: Biến MVP thành pipeline dùng thường xuyên.

Scope:
- batch nhiều video;
- retry policy trong boundary;
- cache/resume hardening;
- concurrency chỉ khi architecture cho phép;
- resource/error reporting;
- cleanup policy;
- regression tests.

Kinh nghiệm từ dubbing project:
- failed item không làm mất completed items;
- từng stage phải resume;
- không process lại artifact không đổi;
- performance phải đo trên máy thực tế trước khi tối ưu.

Auto Short không áp dụng translation/TTS/glossary của project cũ.

Acceptance: batch ổn định; failed item được cô lập; resume chính xác; không duplicate output ngoài policy; regression PASS.

---

# CP10 — Release Readiness

Class: S2.

Goal: Chốt project ở trạng thái có thể sử dụng lặp lại và bảo trì.

Scope:
- onboarding;
- README usage;
- config example;
- sample run;
- troubleshooting;
- architecture map;
- known limitations;
- release checklist;
- framework-check;
- regression/e2e verification;
- current-state/docs review.

Acceptance: session mới bootstrap từ repository, hiểu artifact flow và chạy sample mà không cần transcript của session cũ.

---

# Cross-Checkpoint Invariants

1. Roadmap không thay thế task contract và approval.
2. Repository là source of truth.
3. Mọi meaningful change phải được classify S0/S1/S2.
4. Không tự hạ class khi phát sinh decision gate.
5. Không claim PASS/READY nếu verification chưa chạy.
6. Single-agent vẫn review riêng.
7. AI-generated artifacts phải inspectable, schema-valid, traceable, resumable và cache-aware khi phù hợp.
8. Claude không tự đổi architecture, thêm dependency, đổi project policy hoặc approve S2 decision.
9. Finding thuộc CP sau phải ghi nhận, không tự implement.

# Checkpoint Transition Rules

CPn implementation -> VERIFY -> REVIEW -> FIX/RETEST nếu có blocker -> READY -> HUMAN LEAD integration decision -> CPn+1.

STOP khi có:
- new scope;
- new architecture decision;
- new dependency;
- DB/schema change;
- security model change;
- public API/breaking change;
- new shared abstraction;
- verification unavailable/fails;
- authority conflict;
- cùng blocker sau 2 vòng fix/review.

# Reference Boundary

youtube-vietnamese-dubber chỉ là engineering reference.

Được học:
- stage-based pipeline;
- intermediate artifacts;
- resume/cache;
- provenance/hash;
- structured AI output validation;
- batch failure isolation;
- human review ở điểm AI nhạy cảm;
- performance measurement trên môi trường thực.

Không mang sang:
- translation;
- TTS;
- dubbing;
- glossary phục vụ dịch;
- code dependency;
- project-specific rules;
- model/provider decision chưa được CP1 approve.

# Final Roadmap

CP0 -> CP1 -> CP2 -> CP3 -> CP4 -> CP5 -> CP6 -> CP7 -> CP8 -> CP9 -> CP10

Rule: CPn chỉ hoàn tất khi READY. CPn+1 chỉ được mở sau quyết định integration của HUMAN LEAD.