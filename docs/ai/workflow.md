# AI Development Workflow

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Version | 4 |
| Accepted by | CP0 framework adoption |

> HUMAN LEAD quyết boundary. Agent tự thực thi bên trong boundary đã duyệt.

## 1. Vai trò

**HUMAN LEAD** quyết scope, architecture, dependency, security model, public API contract, breaking change, significant shared abstraction, project-wide policy/convention, task approval, commit/push, PR và merge.

**ORCHESTRATOR** thảo luận decision mới với HUMAN LEAD, viết task contract, lập plan, điều phối sau approval, review diff-first, điều phối fix/retest, cập nhật tài liệu trong boundary và báo READY.

**IMPLEMENTER** là người viết chính: implement, chạy required verification, sửa blocking finding trong boundary và retest. IMPLEMENTER chỉ bắt đầu khi có task contract, base commit, `Implementation authorized: YES` và plan ngắn; thiếu approval, contract hoặc base khớp → BLOCKED.

Vai trò được phân cho người/tool/model nào là việc của execution profile; mỗi task chọn một profile.

## 2. Phân loại — S-class

S-class là trục quyết định mức quy trình.

| Class | Điều kiện | Quy trình |
|---|---|---|
| **S0** | Mechanical only: typo, format, broken link, wording không đổi nghĩa/decision, đồng bộ state/pointer theo decision đã accepted. Không có source, test, config, SQL, script, dependency hay behavior change. | `INSPECT → CHANGE → VERIFY → INTEGRATION` |
| **S1** | Có code, test, config, script hoặc behavior nhưng không chạm decision gate và không tạo rule vượt task/feature. | `INSPECT → CLASSIFY → CONTRACT → APPROVE → EXECUTE → REVIEW → CONVERGE → READY → INTEGRATION` |
| **S2** | Chạm decision gate, thay đổi tài liệu class B, hoặc tạo rule tái sử dụng xuyên feature/module/project. | `DISCUSS → DECIDE → DOCUMENT → CONTRACT → APPROVE → EXECUTE → REVIEW → CONVERGE → READY → INTEGRATION` |

Class cao nhất thắng. S1 gặp decision gate → nâng S2. Không chắc S0 → tối thiểu S1.

## 3. Decision gates

Cần HUMAN LEAD quyết trước khi làm khi chạm: scope; architecture; dependency; security model; public API contract; breaking change; significant shared abstraction; project-wide policy/convention. Database/schema gate được giữ trong workflow vì framework có thể áp dụng cho project có database, nhưng project này hiện không có database authority.

**Dependency proposal:**

```text
Library:
Purpose:
Why current stack is insufficient:
Alternative:
Impact:
```

Khi cần phá boundary:

```text
Issue → Evidence → Impact → Options → Recommendation → HUMAN LEAD Decision
```

Không dùng cập nhật tài liệu để tạo decision mới.

## 4. Task contract

Task là một lát cắt dọc vừa phải: behavior rõ, test và review độc lập. Một lát cắt có một owner chính. Task S1/S2 bắt buộc có `Type`, `Change class`, `Owner`, `Execution profile`, Goal, Scope in/out, Acceptance Criteria, Required verification và authority/reference khi cần.

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. `DONE = READY + integrated into target branch`, suy ra từ Git.

`APPROVE TASK` duyệt goal, boundary, decisions, approach, AC và verification, authorize toàn bộ vòng thực thi tới READY.

## 5. Approval và thực thi

Sau approval mặc định:

```text
PLAN → IMPLEMENT + REQUIRED VERIFICATION → REVIEW → FIX / RETEST / VERIFY → UPDATE DOCS → READY → STOP
```

Một writer trên một branch. Song song chỉ khi tập file không giao nhau, mỗi writer một branch. Không dùng song song để lách circuit breaker.

## 6. Dừng và BLOCKED

Dừng khi: chạm decision gate; required verification không chạy hoặc không PASS; base/authority conflict; cùng một blocking issue chưa giải quyết sau hai lần sửa; review mở rộng vượt boundary.

Circuit breaker:

```text
same blocker → fix 1 → review → fix 2 → review → still failing = BLOCKED
```

Finding ngoài scope phải ghi nhận và báo HUMAN LEAD, không tự sửa.

## 7. Verification và review

Required verification phải trực tiếp chứng minh AC và tất cả phải PASS trước READY. Review theo `task contract → diff → AC → verification evidence`; review không phải pha redesign.

Blocking finding: AC fail, bug, regression, security risk thực tế, vi phạm authority/rule hoặc maintainability risk đáng kể. Non-blocking tối đa 3 note có giá trị; không chặn READY.

Single-agent vẫn bắt buộc có pha review riêng trước READY.

## 8. Integration

Mọi thay đổi đi qua integration mechanism của project. Tại READY, dừng chờ HUMAN LEAD approve. Sau approval, agent có thể push/tạo PR theo mechanism; merge do HUMAN LEAD quyết.

Definition of Done: AC đạt, required verification PASS, blocking finding giải quyết, documentation impact xử lý, review ACCEPTED, thay đổi đã integrate và integration không làm hỏng target branch.
