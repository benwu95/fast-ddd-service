# bound-customer-invoice-voiding — Archive Summary

- **Archived**: 2026-11-07
- **Original Created**: 2026-11-07T07:30:26.630Z
- **Quality Grade**: A
- **Issue**: https://github.com/benwu95/fast-ddd-service/issues/19

## User Story

As a 以 fast-ddd example 為參考實作 MQ consumer 的下游服務開發者（或代為實作的 coding agent），
I want 停用客戶時把該客戶的有效發票拆成每段最多 100 張、各自在獨立 unit of work 中作廢的背景工作，
So that 有效發票再多也不會觸發事件連鎖上限而進 DLQ，且每個交易的事件數與鎖定列數都有固定上限。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| example | High | `CustomerDeactivated` subscriber 改為每 100 張排入一個 `billing.void_invoices` 工作；工作以 `SELECT ... FOR UPDATE` 重查仍屬於該客戶的有效發票後作廢；payload 上限與共用 `Reason`（`app/port/billing/fields.py`） |
| template | Medium | `fast-ddd` skill references：工作端規則只在 `batch-operation.md` step 5 完整敘述，其他 workflow 與 `decisions.md` 引用；`layering.md` 的 `app/port/` 列；reference 副本與 ownership |
| kernel | Low | 程式不變；REQ-KERNEL-008 歸屬 kernel 的 feature spec，`modules/kernel/adapter.md` 補一句做法指引 |

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-KERNEL-008 | MODIFIED | 工作執行、排程與失敗保留：新增客戶停用時每 100 張一個作廢工作、工作內重查並略過已作廢／已刪除／已改屬他人的發票 |

## Completion

- **Tasks**: 11/11 (100%), 5/5 [M]/[V] (not counted)
- **Acceptance Criteria**: 5/5（上限 150 時 250 張全部作廢、每個 unit of work 事件數 ≤ 100、重送冪等、既有行為不變、root `make check` 通過）

## Review & Verify

- **Review**: 7 round(s), 1 critical / 7 major / 2 minor（共 10 項，全數 fixed）— R3-01 critical：重查與上鎖分離，重查到上鎖之間改屬他客戶的發票仍被作廢，經獨立 verifier 確認後改為 `lock=True` 並以交錯測試釘住；R2-01 工作只信任排入時的 id 快照；R6-01 共用型別放置位置不符 `layering.md`。第 3、4、5 輪觸發 oscillation circuit breaker，三次皆由使用者以 break-glass 授權繼續；最後一輪 review-clean
- **Verify**: Grade A — task-completion PASS、tests PASS（root `make check`：kernel 477 passed、example 378 passed、template-check 一致）、delta-spec-compliance PASS（fresh-subagent）、constitution PASS 7/7（fresh-subagent）、design not-applicable；knowledge WARN 為既有的 plugin 模組缺 source_digest
- **Quality Log**: plan 與 tasks verifier 各 WARN（建議均已納入）；review 第 1、3、4、5 輪 WARN（含 circuit breaker）；verify WARN 1（plugin knowledge）

<!-- prospec:escalation-history -->
## Escalation History

Lifetime events: 3. Overrides: 3. Completeness: legacy-partial.

| Ordinal | Station | Trigger | Event | State |
|---|---|---|---|---|
| 1 | prospec-review | oscillation | review:3 | not pending |
| 2 | prospec-review | oscillation | review:4 | not pending |
| 3 | prospec-review | oscillation | review:5 | not pending |

| Event | Station | Reason | Usage |
|---|---|---|---|
| review:3 | prospec-review | R1-02 重開是文件掃描不完整，不是程式擺盪；R3-01 改為在工作內以 SELECT ... FOR UPDATE（依 id 排序）重查，重查與上鎖合一；一併全面掃描 R1-02 類別與 plan 同步，再跑一輪全 lens 複審 | consumed by prospec-review:8fb1fbf7962ff32a5c30ade01cc11fe08616fa87c01ed9e40b93c900d62e746a |
| review:4 | prospec-review | 規則只在 batch-operation.md step 5 完整寫一次、其他位置引用；補暫時鎖住仍作廢的測試、reason 上限、plan/proposal/tasks 同步；跑第 5 輪（上限），若仍有 major/minor 則記錄 review 並開後續 issue | consumed by prospec-review:b37fe4a160e7c7cc43fe93abb7bb5cd4f5b4f31ab45c85b31c467bbfe6111701 |
| review:5 | prospec-review | 把 void reason 長度型別移到傳輸中立的 port 共用模組、HTTP 與 task 兩邊 import，同步 batch-operation.md step 5 與 plan.md:66；跑第 6 輪全 lens 複審 | consumed by prospec-review:8bafea2bc1b921c1609e4ce408cdb6131c050f76f67dc3b40820ec4e9a16744e |
<!-- prospec:escalation-history-end -->
