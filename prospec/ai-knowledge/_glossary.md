# Project Glossary

> 專案 ubiquitous language；定義以目前 source 為依據。

| Term | English / Alias | Definition |
| :--- | :--- | :--- |
| 共用核心 | kernel | `kernel` workspace member；可安裝套件包含 core、adapter、port、devtools 四個 Python package。 |
| 參考服務 | example | `example` workspace member；以 billing bounded context 示範三種程序的服務組裝。 |
| 服務骨架 | template / scaffold | Copier 產生的單服務 repo；外層程式、工具與測試由服務直接修改，可自行選擇合併上游更新。 |
| 初始化檔 | initialization-only | 存在時不被生成覆寫；刪除後可能按 template 與持久化 baseline 答案重建的服務擁有檔案。 |
| 骨架漂移 | template drift | 僅框架 template／example 配對的一致性檢查；不限制下游客製化服務。 |
| 發票 | Invoice | Billing aggregate，含 customer、lines、狀態、版本與事件；可開立、修改、作廢或刪除。 |
| 值物件 | Value Object | 以 frozen dataclass 表達的業務資料，如 Customer、InvoiceLine、InvoiceContent。 |
| 工作單元 | Unit of Work / UoW | 一次入口執行的身分、organization、trace 與交易脈絡；由 wrappers 建立並在結束復原。 |
| 交易提供者 | SessionProvider | 持有 session、巢狀深度、hooks、待 dispatch 事件及已載入 model；外層負責 commit。 |
| 組織 | organization / tenant | Tenant 隔離單位；organization-scoped repository 缺少 context 時拒絕執行。 |
| 系統脈絡 | system_context | 帶 reason 的明確 tenant 豁免；不等同於 organization 為 null。 |
| 領域事件 | DomainEvent | Aggregate 在交易內產生並儲存的事件，含 doer、來源、trace 與 parent metadata。 |
| 整合訊息 | integration message | DomainEvent 的跨服務 envelope，含 eventId、eventName、eventVersion、organizationId、occurredAt、data。 |
| 收件去重 | inbox / ProcessedMessage | 以 subscriber 與 event ID 在同交易宣告處理權，避免重複業務效果。 |
| 背景工作 | task / PgQueuer | 與業務資料同交易 enqueue 的工作；worker wrapper 提供 context、retry 與失敗保留。 |
| 定期排程 | cron / schedule | Registry 註冊的 PgQueuer 排程；以 system identity、無 organization 執行 handler。 |
| 批次降級 | batch fallback | 整批非預期失敗後逐項執行；非 HTTP 呼叫可要求 transient failure 重試整個 UoW。 |
| 批次 handler | batch event handler | `subscribe_batch` 註冊、每次分派依事件類型與 organization 分組收到 list 的 handler；全有或全無。 |
| 事件連鎖上限 | event chain limit | 同一 UoW 的分派世代（預設 10）與事件總數（預設 10,000）上限，由 `configure` 調整。 |
| wire contract | JSON 契約 | 跨程序固定欄位名稱、值格式與 schema；任意業務 map key 不參與名稱轉換。 |
