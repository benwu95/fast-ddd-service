# add-batch-event-handlers — Archive Summary

- **Archived**: 2026-11-07
- **Original Created**: 2026-11-07T02:08:33.275Z
- **Quality Grade**: A
- **Issue**: https://github.com/benwu95/fast-ddd-service/issues/8
- **Plan Decision**: hybrid (graded_by: in-session)

## User Story

As a 維護服務 event handler 的 Python 開發者，
I want 以 `subscribe_batch` 一次收到同類型、同組織的事件清單，並用 `apply_event_batch` 對目標 aggregate 集合套用 domain 方法，
So that 大批次的連鎖事件只花固定次數的資料庫往返，同時保留因果與租戶隔離。

另兩個 story：批次 handler 全有或全無、失敗時由批次 runner 逐筆 fallback 並與逐一處理結果相同（US-2）；同一 unit of work 的事件連鎖有可由 `configure(...)` 調整的深度與總數上限（US-3）。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| kernel | High | `EventBus.subscribe_batch` 與分組分派、`fast_ddd.batch.apply_event_batch`、`event_scope` 的 `event_id` 可為 None；`SessionProvider` 的連鎖計數（`Mark.dispatched`、`dispatching()`）、`_run_command` 的上限檢查、`EventChainLimitExceededError`、`run_batch` 的超限規則、`configure()` 的兩個上限 |
| template | Low | `fast-ddd` skill references（event-handler、batch-operation、decisions、rules/api）補上連鎖上限與 `run_batch` 超限規則 |
| example | Low | 同上 skill references 的 example 副本（與 template 相同）；程式碼不變 |

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-KERNEL-015 | ADDED | 依事件類型與組織分組的批次 event handler |
| REQ-KERNEL-016 | ADDED | 依事件套用 domain 方法並全有或全無 |
| REQ-KERNEL-017 | ADDED | 同一 unit of work 的事件連鎖上限 |

## Completion

- **Tasks**: 17/17 (100%), 1/1 [M]/[V] (not counted)
- **Acceptance Criteria**: 12/12 frozen scenarios（verify 2/5 無語意偏差）

## Review & Verify

- **Review**: 6 round(s), 0 critical / 6 major / 3 minor（F-5 恆真斷言、F-6 fallback「每次一個事件」缺條件、F-9 批次 runner 偽碼未列超限例外），全部修正；第 4 輪起無 open major、第 6 輪 review-clean。major：超限不 fallback 的理由敘述錯誤（F-1）、`fast-ddd` skill references 未提連鎖上限（F-2）、「空分派不算一代」與「dispatching 失敗時回復深度」未被測試釘住（F-3、F-4，mutation 存活）；第 2 輪新增 `_reset` 歸零總數未釘測（F-7），第 3 輪新增最外層 `run_batch` 逐筆階段超限時已 commit 卻整請求 500（F-8，改為只讓該筆失敗）。第 5 輪 F-1 重開觸發 oscillation circuit breaker，經使用者 break-glass 改為以 `docs/design.md` 第 8.2 節批次 runner 為單一來源。
- **Verify**: Grade A — 1/5 PASS、2/5 PASS（fresh-subagent，REQ 3/3）、3/5 PASS（7/7 rules）、4/5 WARN（既有 `plugin` 模組缺少目前版本的 `source_digest`，非本 change 範圍）、5/5 PASS、6 not-applicable；root `make check` exit 0。兩代批次 handler 連鎖 N=1／N=50 皆 15 次 SQL（main 77c343f 逐一處理一代連鎖為 8／204）。
- **Quality Log**: new-story WARN（INVEST：US-2 依賴 US-1）；plan WARN（verifier 6 項：example 分段 `run_batch` 跨段累計總數、fallback 判斷措辭、循環測試須每代寫新 aggregate、baseline 指令、`dispatch` 的 Iterable 實體化、API 路徑）皆已修入；tasks PASS；review 第 1～3、5 輪 WARN、第 4、6 輪 PASS；verify A。

## Knowledge Update

- `prospec/ai-knowledge/modules/kernel/core.md`、`prospec/ai-knowledge/modules/kernel/adapter.md`、`prospec/ai-knowledge/_glossary.md`、`prospec/ai-knowledge/module-map.yaml`

<!-- prospec:escalation-history -->
## Escalation History

Lifetime events: 1. Overrides: 1. Completeness: legacy-partial.

| Ordinal | Station | Trigger | Event | State |
|---|---|---|---|---|
| 1 | prospec-review | oscillation | review:5 | not pending |

| Event | Station | Reason | Usage |
|---|---|---|---|
| review:5 | prospec-review | 使用者選擇「Break-glass，改為引用單一來源」——剩餘 F-1／F-9 為文件措辭，不再逐處重寫規則，改以 docs/design.md 第 8.2 節批次 runner 為單一來源，其他位置引用之 | consumed by prospec-review:8f14eaa661e6ddae9f8a8e3b3cb9a7c4f331c766d7b26707c7e8aa9893424442 |
<!-- prospec:escalation-history-end -->
