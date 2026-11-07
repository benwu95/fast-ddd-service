---
feature: background-work
status: active
last_updated: 2026-11-07
story_count: 1
req_count: 2
---

# background-work

## Who & Why

**Target users**: 需要背景通知與定期作業的 Python 服務開發者。

**Problem solved**: 工作排入與業務資料需要原子性，外部副作用與排程競爭則有各自的重送邊界。

**Why it matters**: 共用 TaskQueue 與 worker wrappers 保留 tenant／trace，避免每個服務重做 enqueue、retry 與 cron。

## User Stories & Behavior Specifications

### US-1: 與業務交易一致的工作與排程 [P0]

作為需要背景通知與定期作業的 Python 服務開發者，
我要在同一交易排入具 context 的工作，並以獨立 worker 執行重試及 cron，
以便業務與 queue 資料一致，工作重送與跨組織排程結果可追蹤。

**Acceptance Scenarios:**
- WHEN 業務交易 commit 或 rollback，THEN 工作與業務資料一起保留或消失，dedupe 不破壞外層交易。
- WHEN 工作無效、暫時失敗或耗盡重試，THEN 依分類停止、退避或保留失敗供檢查。
- WHEN 多個 worker 競爭同次 cron，THEN 正常運作時只執行一次，跨組織衍生工作帶各自 context。

#### REQ-KERNEL-007: 與業務資料一致的工作排入

工作排入與呼叫端業務資料使用相同 DB transaction，支援延遲與重複 key，Python 呼叫者經既定 TaskQueue 使用此能力。

- WHEN 業務交易排入工作，THEN 使用當前 SQLAlchemy asyncpg 連線排入工作時，commit 同時保存工作與業務資料，rollback 兩者皆消失；不另開可獨立 commit 的 enqueue 交易。
- WHEN 排入重複 key 或延遲工作，THEN 重複 dedupe key 按設計回報略過，並不使外層 transaction aborted；延遲工作不在到期前執行。
- WHEN 呼叫 TaskQueue 或接收工作 envelope，THEN 工作攜帶明確 organization 與 trace context，未設定必要 TaskQueue 時明確報錯；既有 taskVersion／organizationId／data contract 可接收。

---

#### REQ-KERNEL-008: 工作執行、排程與失敗保留

背景工作與 cron 在獨立 context 中處理，重送維持冪等效果，暫時性錯誤退避重試，確定性／耗盡錯誤保留供檢查。

- WHEN 工作無效、失敗或重送，THEN 無效 payload／確定性 domain error 不反覆重試；暫時性錯誤依設定退避至上限，失敗工作保留而非刪除；重送同一工作不造成重複通知效果。
- WHEN 兩個獨立 worker 競爭同次到期排程，THEN 兩個獨立 worker 的 scheduler 同時競爭同一次到期排程時，正常運作情境只有一次 handler 執行；實際驗證 context、transaction 與 trace，不以只驗 registry 代替。
- WHEN 排程衍生跨組織工作，THEN 排程本身沒有組織 context；跨組織彙總明確取得所需組織並逐組織衍生工作，衍生工作保留各自 organization，不把全域豁免帶進一般 handler。
- WHEN 執行 Invoice 通知或每日彙總，THEN 參考服務完整示範 invoice event→通知工作與 cron→每日彙總；外部通知採用原介面的可重送識別 key，測試外部成功後本地失敗的重送結果，不將 DB rollback 解讀成撤銷外部 HTTP。
- WHEN 參考服務收到 `CustomerDeactivated`，THEN subscriber 在處理 message 的交易內查出該客戶在該組織的有效發票，每 100 張排入一個作廢工作，與 inbox 紀錄一起 commit，本身不作廢發票；每個作廢工作在自己的 unit of work 中重新查出所帶發票裡仍屬於該客戶的有效發票並作廢，任一 unit of work 分派的事件數不超過 100，與有效發票總數無關。
- WHEN 同一 `CustomerDeactivated` 重送，或作廢工作重試，THEN 相同 eventId 由 inbox 略過、不再排入工作；工作對已作廢、已刪除或已改屬其他客戶的發票記 warning 並略過，發票狀態與 `InvoiceVoided` 事件數與只處理一次相同。

---

## Edge Cases

- 外部 HTTP 成功不會被 DB rollback 撤銷；重送依賴相同 PUT 識別 key 的冪等介面。
- 排程競爭保證範圍是正常運作的單次 occurrence，不擴張為 crash 下 exactly-once。

## Success Criteria

- **SC-1**: enqueue／rollback／dedupe／延遲與有限 retry 的資料結果可實測。
- **SC-2**: 兩個完整 worker 的 cron 競爭與通知成功後本地失敗重送均有執行案例。

## Maintenance Rules

1. **Replace-in-Place**：MODIFIED Story 與 REQ 直接取代原版本。
2. **Functional Grouping**：需求置於對應的 User Story。
3. **No Inline Provenance**：變更歸屬只記錄於 Change History。
4. **Deprecation over Deletion**：移除需求保留於 Deprecated Requirements。

## Deprecated Requirements

無。

## Change History

| Date | Change | Impact | Stories/REQs |
|------|--------|--------|-------------|
| 2026-11-07 | bound-customer-invoice-voiding | MODIFIED REQ-KERNEL-008 | REQ-KERNEL-008 |
| 2026-10-17 | replan-phase-one | 建立已驗收能力基準 | US-1, REQ-KERNEL-007, REQ-KERNEL-008 |
