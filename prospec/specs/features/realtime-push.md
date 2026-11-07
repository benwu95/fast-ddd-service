---
feature: realtime-push
status: active
last_updated: 2026-11-07
story_count: 3
req_count: 4
---

# realtime-push

## Who & Why

**Target users**: 以 Socket.IO 接收即時更新的前端開發者，及在服務中推播變更的 Python 開發者。

**Problem solved**: 即時推播需要與 HTTP 相同的認證、權限與 tenant 隔離，且只能推送已 commit 的資料、只送給指定對象；交給各服務自行實作時無法保證。

**Why it matters**: 安裝 `fast-ddd-kernel[realtime]` 的服務直接取得這些保證，未採用的服務的相依與 import 不受影響。

## User Stories & Behavior Specifications

### US-1: 只有通過認證的連線能收到自己組織的推播 [P0]

作為以 Socket.IO 接收即時更新的前端開發者，
我要在連線時以 JWT 認證，並只能加入自己有權限的 room，
以便即時推播與 HTTP API 遵守相同的認證、權限與 tenant 隔離。

**Acceptance Scenarios:**
- WHEN client 沒有有效 token，THEN 連線被拒絕且不送出任何事件。
- WHEN client 以有效 token 連線，THEN 自動收到自己 org 與 user room 的推播，client 自行提供的組織與使用者被忽略。
- WHEN client 要求加入資源 room，THEN 依登記的權限決定，其他組織的同名資源永遠收不到。

#### REQ-KERNEL-011: 經 JWT 認證的即時推播連線
即時推播連線只在 JWT 驗證成功後建立，身份與 tenant 一律取自 token。
- WHEN client 連線時沒有 token、token 無效或已過期，THEN 連線被拒絕（`connect_error`），server 結束其 Engine.IO session 且不送出事件。
- WHEN client 以有效 token 連線，THEN 自動加入 `user:{user_id}`，token 帶組織時另加入 `org:{organization_id}`，client 不必送訂閱事件即可收到推給這些 room 的訊息。
- WHEN client 在連線參數或事件內容中提供組織或使用者，THEN 這些值不影響加入的 room。
- WHEN transport 在連線逾時內沒有已認證的 Socket.IO 連線，THEN server 結束其 Engine.IO session。

---

#### REQ-KERNEL-012: 以權限與組織前綴保護的資源 room
資源 room 的加入遵守與 HTTP 相同的權限規則，且 room 名稱由 kernel 以 token 的組織為前綴產生。
- WHEN client 要求加入已登記的資源 room 且 token 具備登記的權限，THEN ack 的 `status` 為 `ok`，該連線開始收到推給 `org:{organization_id}:{resource}:{id}` 的訊息。
- WHEN token 缺少登記的權限，THEN ack 的 `status` 為 `error`，`error` 為 `auth.permission_denied` 的 problem+json，連線不加入 room。
- WHEN 資源名稱未登記、資源 ID 不是 UUID 或 token 沒有組織，THEN 加入要求被拒絕並回傳 problem+json。
- WHEN 不同組織的使用者以相同資源名稱與 ID 加入，THEN 各自加入以自己組織為前綴的 room，收不到其他組織的推播。
- WHEN 單一連線已加入的資源 room 數量達到設定上限，THEN 加入新的資源 room 被拒絕，`error.code` 為 `rate_limit.exceeded`。

---

### US-2: 推播只在 commit 後送給指定的對象 [P0]

作為維護服務的 Python 開發者，
我要用 kernel 的 publisher 在 use case 中登記推播，
以便推播與資料一致、不會誤推給所有連線，且在同一服務的多個實例間都送達。

**Acceptance Scenarios:**
- WHEN 交易 commit，THEN 推播送出；rollback 或 SAVEPOINT 回復時不送出。
- WHEN 推播沒有對象或資料不是 JSON，THEN 登記當下即失敗。
- WHEN 同一服務有多個實例，THEN 推播送達連在任一實例的 client，其他服務收不到。

#### REQ-KERNEL-013: commit 後才送出且必有對象的推播
推播只在資料 commit 後送出，且只送給明確指定的 room。
- WHEN 在 unit of work 內登記推播，THEN 最外層 commit 成功後才送出；rollback 或該推播所屬 SAVEPOINT 回復時不送出。
- WHEN 登記推播時沒有指定 room，或在沒有組織的 context 中指定 org／資源 room，THEN 登記當下拋出錯誤，不送出任何推播。
- WHEN client 收到推播，THEN 固定欄位為 `eventName`、`eventVersion`、`data`，`data` 為服務傳入的原樣。
- WHEN 同一服務的多個實例共用 RabbitMQ，THEN 任一實例送出的推播送達目標 room 中連在其他實例的 client；不同服務即使共用 broker，推播也只送達自己服務的 client。
- WHEN commit 後送出推播失敗，THEN 只寫 log，不影響已 commit 的資料（與 REQ-KERNEL-006 的 after-commit 取捨相同）。

---

### US-3: 未採用推播的服務不受影響 [P0]

作為不使用即時推播的服務開發者，
我要讓推播相依只在安裝 `realtime` extra 時存在，
以便既有服務的相依、import 與分層規則維持不變。

**Acceptance Scenarios:**
- WHEN 未安裝 extra，THEN 三個 runtime 套件照常 import。
- WHEN core 引用 `socketio`，THEN import contracts 檢查失敗。
- WHEN client 使用 long-polling，THEN 連線被拒絕。

#### REQ-KERNEL-014: 以 optional extra 提供且只開放 WebSocket
python-socketio 只隨 `realtime` extra 安裝，未採用的服務不受影響；連線只走 WebSocket。
- WHEN 環境未安裝 `realtime` extra，THEN `fast_ddd`、`fast_ddd_adapter`、`fast_ddd_port` 照常 import，import realtime 模組時錯誤訊息指出需要 `fast-ddd-kernel[realtime]`。
- WHEN `fast_ddd` 的模組 import `socketio`，THEN kernel 的 import contracts 檢查失敗。
- WHEN client 以 long-polling 連線到掛載的 realtime 路徑，THEN 連線被拒絕；WebSocket 連線可建立。

---

## Edge Cases

- 權限只在連線與加入 room 時檢查；連線期間 token 過期或權限被撤銷不會中斷連線或移出 room。
- commit 後推播沒有 durable outbox；發送失敗只寫 log，推播可能遺失（與 MQ 的 after-commit 取捨相同）。
- client 收到 `connect_error` 後仍保持 transport 時，server 已結束其 Engine.IO session 並停止 ping，transport 於 ping_interval + ping_timeout 內關閉。
- 重新連線後自動回到 org／user room；資源 room 需重新加入。

## Success Criteria

- **SC-1**: 以真實 Socket.IO client、RabbitMQ 4 與 PostgreSQL 執行認證拒絕、room 權限、跨組織隔離、commit／rollback 時機與跨實例分送的測試。
- **SC-2**: 未安裝 extra 時三個 runtime 套件可 import，wheel 的 python-socketio 相依只帶 `realtime` extra 標記。

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
| 2026-11-07 | add-realtime-push-extra | 新增即時推播 optional extra | US-1, US-2, US-3, REQ-KERNEL-011, REQ-KERNEL-012, REQ-KERNEL-013, REQ-KERNEL-014 |
