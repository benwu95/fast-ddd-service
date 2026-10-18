---
feature: message-contract
status: active
last_updated: 2026-10-17
story_count: 1
req_count: 1
---

# message-contract

## Who & Why

**Target users**: 以 Python、C# 或 Node.js 整合服務的後端開發者。

**Problem solved**: 跨語言訊息需要穩定格式，重送、錯誤與 context 不應造成重複效果或污染。

**Why it matters**: Python 開發者使用 snake_case 屬性，交換 camelCase JSON 時仍有型別、tenant 與交易保護。

## User Stories & Behavior Specifications

### US-1: 可互通且可重送處理的 MQ 訊息 [P0]

作為以 Python、C# 或 Node.js 整合服務的後端開發者，
我要透過固定 envelope／payload contract 發送與接收事件，
以便在隔離的執行 context 中處理重送，並以一致規則重試、略過或送 DLQ。

**Acceptance Scenarios:**
- WHEN producer 發出含巢狀固定欄位與業務 map 的事件，THEN consumer 可接收 camelCase JSON，map key 原樣保留。
- WHEN 訊息無效、屬全域範圍或重送，THEN subscriber 依驗證、global opt-in 與 inbox 規則處理。
- WHEN handler 失敗或 transaction 回復，THEN 業務資料與 inbox 一起回復，只有成功 commit 後才嘗試發送。

#### REQ-KERNEL-006: MQ envelope、inbox 與可重送處理

服務以 camelCase envelope／payload 交換訊息，每則訊息擁有自己的執行 context，成功效果按 subscriber 去重。命名及值型別依 REQ-KERNEL-001。

- WHEN subscriber 收到 envelope 與 payload，THEN 必要 envelope 欄位可驗證，organizationId 必須存在且來源為發出事件的 aggregate；未知 payload 欄位被忽略以接受相容新增，無效 payload／缺必要欄位進 DLQ。
- WHEN 接收全域或並行訊息，THEN 全域事件只由明確接受的 subscriber 處理；組織、系統身份、trace 與 parent event 在每則訊息隔離、結束後還原，並行訊息不共用 session 或污染其他 context。
- WHEN 事件重送或 handler 失敗，THEN 相同 eventId 對同一 subscriber 的成功效果一次；handler 寫入後失敗時資料與 inbox 一起 rollback。INVALID 送 DLQ，其他確定性拒絕略過，鎖衝突與未預期錯誤有限重試後送 DLQ。
- WHEN 交易提交、回復或發送 hook 失敗，THEN rollback／失敗範圍不發送暫存訊息，最外層 commit 後才嘗試發送再 ack；發送 hook 失敗有 log 且不阻止後續 hooks。保留 commit 後發送可能遺失的設計限制，不宣稱 outbox 保證。

---

## Edge Cases

- 全域訊息只交給明確接受的 subscriber；並行訊息不共用 session 或 context。
- after-commit 不是 durable outbox；commit 後程序終止可能遺失訊息。

## Success Criteria

- **SC-1**: 真實 producer → broker → typed consumer 的互通、重送、DLQ 與並行 context 案例可執行。
- **SC-2**: 未預期錯誤及鎖衝突的重試有上限，成功訊息對每個 subscriber 只生效一次。

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
| 2026-10-17 | replan-phase-one | 建立已驗收能力基準 | US-1, REQ-KERNEL-006 |
