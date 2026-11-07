---
feature: kernel-foundation
status: active
last_updated: 2026-11-07
story_count: 2
req_count: 6
---

# kernel-foundation

## Who & Why

**Target users**: 建立或維護 DDD 後端的 Python 開發者。

**Problem solved**: 領域型別、跨語言資料與資料庫交易需要共用且可驗證的 contract。

**Why it matters**: 在共用 kernel 保留領域隔離、tenant 與失敗回復，服務可專注業務規則。

## User Stories & Behavior Specifications

### US-1: 具型別的領域、儲存與批次行為 [P0]

作為建立或維護 DDD 後端的 Python 開發者，
我要在 Python 使用原生具型別資料，並可靠地儲存 aggregate 與批次結果，
以便不同入口共用相同 tenant、版本、事件與交易語意。

**Acceptance Scenarios:**
- WHEN 領域資料跨 wire／ORM 邊界，THEN Python 型別與命名、公開 JSON 格式、內部資料格式遵循各自 contract。
- WHEN 操作跨 tenant、加鎖重讀或保存 aggregate，THEN 可見性、版本、子集合與事件歸屬保持一致。
- WHEN 巢狀或批次失敗，THEN 失敗範圍回復、成功效果保留一次，正常批次不退回逐筆 I/O。

#### REQ-KERNEL-001: Python 型別與跨邊界資料 contract

Python 開發者以 snake_case 的具型別 domain／訊息資料工作；API／MQ JSON 固定欄位為 camelCase，DB 與內部 domain_event body 為 snake_case，任意 map key 保留。

- WHEN 具名 aggregate ID 跨層傳遞，THEN 具名 aggregate ID 在 repository、單筆／批次 use case 與 port 邊界維持型別；正確 ID 通過 strict typing，錯把 CustomerId 傳入 invoice 邊界時型別檢查失敗。
- WHEN producer 與 consumer 交換含巢狀資料的訊息，THEN 真實 producer 的多字／巢狀固定欄位可由對應 consumer 驗證，Python 屬性保持 snake_case；業務 map 的 partner_key／en-US 等 key 原樣往返。
- WHEN UUID、Enum、Decimal 或時間進出 wire 邊界，THEN UUID 與 Enum 依設計輸出字串／value；Decimal 對外為精確字串，request 拒絕 JSON number、NaN 與 Infinity；時間為帶時區輸入、UTC RFC 3339 毫秒 Z 輸出，拒絕無時區與數字輸入。
- WHEN 獨立測試或重用 domain，THEN domain 可獨立測試，不因 wire policy 引入 Pydantic／HTTP／ORM；前身 dataclass-mixins 的相關 contract 案例依已記錄的格式差異對應至測試。

---

#### REQ-KERNEL-002: Aggregate 儲存、tenant 與事件紀錄

儲存保留 aggregate 及其子集合的變更語意、組織隔離、版本與事件來源，archive 由明確設定啟用。

- WHEN aggregate 及子集合儲存或重新載入，THEN mapping 往返包含子 entity／value object；有真實變更才遞增 version，僅子項變更亦計入，沒有變更時不增加 version，建立／更新時間依設計寫回。
- WHEN 以組織範圍或明確 system context 存取資料，THEN 組織範圍的 load／search／自訂查詢套用相同 tenant 條件；其他組織資料不可見，沒有必要 context 時明確失敗。明確 system_context 不改變每筆 aggregate／event／archive 的組織歸屬，豁免行為留下 log。
- WHEN 多筆加鎖或在原交易中重新加鎖讀取，THEN 多筆鎖定有固定順序；同一 transaction 先讀取、另一連線更新並 commit、再加鎖重讀時取得新值與 version。
- WHEN 記錄事件、啟用快照或執行 event handler，THEN domain event 記錄來源 aggregate、organization、event／parent event 與 trace；預設不寫 archive，指定 archive 後才保存對應快照；event handler context 隨事件組織設定並在結束後還原。

---

#### REQ-KERNEL-003: Transaction、批次與連鎖事件的失敗邊界

單筆與批次保留外層 transaction 的提交權，失敗範圍的資料、事件與待發訊息一起回復；正常批次以集合處理 I/O。

- WHEN 執行巢狀 command 與連鎖事件，THEN 巢狀操作成功不提前 commit，巢狀失敗只回復其失敗範圍，外層未處理例外使整個外層 rollback；連鎖事件與後續 handler 在相同交易邊界內執行。
- WHEN 批次包含逐筆失敗或整批 IntegrityError，THEN 不存在、跨 tenant、業務拒絕與版本不符可逐筆回報；整批 IntegrityError 後逐筆 fallback 保留成功效果一次，整批已暫存／失敗項目的 MQ 訊息不外洩，巢狀 fallback 保留原有外層寫入且可重存已回復的 aggregate。
- WHEN 資料庫回報 constraint 或鎖定錯誤，THEN 主鍵／已登錄 constraint、lock timeout 與 deadlock 轉成穩定 domain error；鎖衝突不進整批逐筆 fallback，非 HTTP consumer 遇暫時性逐筆失敗依設計讓整個 unit of work 可重試。
- WHEN 批次 handler 不做 DB I/O，THEN handler 不做 DB I/O 時，kernel batch-create／batch-void 與 example batch-void 各在 N=1／N=50 的 SQL 往返相同；遵守批次上限，保護回應所用 aggregate 不被 handler 再儲存而使 version／ETag 過時。

---

### US-2: 批次處理事件連鎖並限制其規模 [P0]

作為維護服務 event handler 的 Python 開發者，
我要以批次 handler 與 `apply_event_batch` 用集合 I/O 處理連鎖事件，並讓 kernel 限制連鎖的深度與總數，
以便大批次的往返次數不隨筆數成長，失敗時仍保有逐筆語意，循環或失控扇出在明確的上限失敗。

**Acceptance Scenarios:**
- WHEN 兩代連鎖都使用批次 handler，THEN N=1 與 N=50 的 SQL 往返次數相同，同一目標只載入與儲存一次，新事件的來源指向各自的事件。
- WHEN 批次 handler 因連鎖上限以外的原因失敗，THEN 最近一層正在整批階段的批次 runner 退回逐筆處理；每筆命令只產生一個該類型事件時，結果與逐一處理的 handler 相同。
- WHEN 事件連鎖超過世代深度或事件總數上限，THEN 丟出例外，上限可由 `configure(...)` 調整。

#### REQ-KERNEL-015: 依事件類型與組織分組的批次 event handler
批次 handler 依事件的確切類型與組織分組，每組呼叫一次，讓連鎖事件的 I/O 以集合處理。
- WHEN 以 `subscribe_batch` 訂閱的事件被分派，THEN 依（事件類型, `organization_id`）分組，每組呼叫一次，組內保留事件順序，handler 在該組組織的租戶 context 中執行。
- WHEN 同一次分派同時有逐一處理與批次 handler，THEN 先依事件順序執行逐一處理的 handler，再依各組第一個事件出現的順序執行批次 handler。
- WHEN 組內只有一個事件，THEN handler 執行時的來源事件為該事件；WHEN 組內有多個事件，THEN 不設定來源事件。
- WHEN 兩代連鎖都使用批次 handler，THEN N=1 與 N=50 的 SQL 往返次數相同。

---

#### REQ-KERNEL-016: 依事件套用 domain 方法並全有或全無
`apply_event_batch` 以集合 I/O 套用多個事件，因果逐事件保留，失敗時整批不生效。
- WHEN 多個事件指向同一個目標，THEN 目標只載入、儲存一次，version 只遞增一次，每個事件的效果都套用。
- WHEN domain 方法在 `apply_event_batch` 中產生新事件，THEN 新事件的 `parent_event_id` 為觸發它的來源事件。
- WHEN 任一目標不存在，THEN 丟出 `AggregateNotFound`，不儲存任何目標。
- WHEN 批次 handler 在 `run_batch` 整批階段因連鎖上限以外的原因失敗，THEN 整批回復並逐筆 fallback；每筆命令只產生一個該類型事件時，結果與逐一處理 handler 相同。

---

#### REQ-KERNEL-017: 同一 unit of work 的事件連鎖上限
事件連鎖的世代深度與事件總數各有可設定的上限，超過時整個 unit of work 失敗。
- WHEN 事件分派的世代超過 `max_event_chain_depth`（預設 10，最外層命令的事件為第 1 代），THEN 丟出 `EventChainLimitExceededError`。
- WHEN 同一 unit of work 分派的事件總數超過 `max_events_per_unit_of_work`（預設 10,000），THEN 丟出 `EventChainLimitExceededError`；剛好等於上限時允許。
- WHEN SAVEPOINT 或 transaction 回復，THEN 回復範圍內分派過的事件不計入總數。
- WHEN `run_batch` 在整批階段遇到 `EventChainLimitExceededError`，THEN 直接往上丟出，不進入逐筆 fallback。
- WHEN 最外層 `run_batch` 的逐筆 fallback 中某一筆超限，THEN 只有該筆結果為 `UnexpectedFailure`，其他筆照常 commit；WHEN `run_batch` 巢狀在另一個 unit of work 中，THEN 逐筆階段的超限往上丟出。
- WHEN `configure(...)` 收到小於 1 的上限，THEN 丟出 `ValueError`，既有設定不變。

---

## Edge Cases

- 缺少 organization context 必須明確失敗；跨組織操作透過明確豁免保留原始組織歸屬。
- 批次 fallback 與外層 rollback 同時回復事件、持久化 metadata 與待發訊息。
- 沒有事件的分派不算一代；事件總數計入沒有訂閱者的事件，並在同一 unit of work 的多次批次之間累計。

## Success Criteria

- **SC-1**: 具名 ID 的正反 typing contract 與跨邊界序列化案例均可執行。
- **SC-2**: handler 不做 DB I/O 時，N=1／50 的正常批次 SQL 往返差值為 0。
- **SC-3**: 兩代批次 handler 連鎖在 N=1／50 的 SQL 往返差值為 0。

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
| 2026-11-07 | add-batch-event-handlers | ADDED REQ-KERNEL-015; ADDED REQ-KERNEL-016; ADDED REQ-KERNEL-017 | REQ-KERNEL-015, REQ-KERNEL-016, REQ-KERNEL-017 |
| 2026-10-17 | replan-phase-one | 建立已驗收能力基準 | US-1, REQ-KERNEL-001, REQ-KERNEL-002, REQ-KERNEL-003 |
