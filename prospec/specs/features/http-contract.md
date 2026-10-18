---
feature: http-contract
status: active
last_updated: 2026-10-17
story_count: 1
req_count: 2
---

# http-contract

## Who & Why

**Target users**: 串接 API 的前端開發者及維護服務的 Python 開發者。

**Problem solved**: client 需要與 runtime 一致的 schema、錯誤、認證及並行更新規則。

**Why it matters**: 透過 OpenAPI 即可處理 CRUD／batch 結果，不必猜測錯誤格式或承擔跨 tenant 資料外洩。

## User Stories & Behavior Specifications

### US-1: 可依公開 contract 使用的 Invoice API [P0]

作為串接 API 的前端開發者及維護服務的 Python 開發者，
我要透過具認證、權限與版本保護的 API 操作 Invoice，
以便 client 能依 OpenAPI 正確處理成功、逐筆失敗與重試判斷。

**Acceptance Scenarios:**
- WHEN client 執行 CRUD、void、batch-void 或列表搜尋，THEN 狀態碼、JSON、headers 與公開 schema 一致。
- WHEN token、權限或組織不符合存取條件，THEN 回傳對應 401／403／404，保護受限制欄位。
- WHEN 執行有前置條件的更新，THEN 依 428／400 → 404 → 412 順序處理，PATCH 保留省略與 null 的差異。

#### REQ-KERNEL-004: 可由 client 使用的 HTTP、OpenAPI 與錯誤 contract

參考服務提供 CRUD、void、batch-void 與列表搜尋，client 能依 OpenAPI 取得與實際一致的成功、錯誤與並行修改結果。

- WHEN client 呼叫 CRUD、batch-void 或列表，THEN 建立為 201＋Location，刪除為 204，其他單筆成功為 200；batch-void 全成功或混合結果皆為 207，逐筆結果依輸入順序排列；列表具 total／items、分頁排序搜尋及設計上限。
- WHEN 請求格式不符或操作發生錯誤，THEN JSON 語法錯誤為 400、path ID 不符路由為 404、method 不支援為 405、非 JSON body 為 415、schema／重複 batch ID 為 422；INVALID 為 422、CONFLICT／ALREADY_EXISTS／lock conflict 為 409、NOT_FOUND 為 404、PRECONDITION_FAILED 為 412、未預期系統錯誤為 500，不回傳內部例外內容。
- WHEN client 執行 PATCH 或帶前置條件的操作，THEN PATCH 區分省略、null 與巢狀值的設計語意；必要 If-Match 缺少為 428、不接受的格式為 400，這兩項先於資源載入。header 有效後，資源不可見為 404，先於版本不符的 412；header／body ETag 相同，批次各筆檢查版本。
- WHEN client 依 OpenAPI 或 CORS 處理回應，THEN 七個 invoice operation 的適用 Problem 回應 model 與 application/problem+json 均列入 OpenAPI；成功／207、If-Match 與相關 headers 宣告和實際 HTTP 結果一致；CORS 支援寫入 preflight，允許來源可讀取含 X-Trace-Id 的 500。

---

#### REQ-KERNEL-005: 認證、權限與 API tenant 保護

每個非明確公開的 API 在可信身份及權限下存取資料；身份設定缺失時服務拒絕啟動。

- WHEN 請求需要身份或權限驗證，THEN JWT 驗證簽章、issuer、audience、到期／生效時間及允許演算法；缺少／無效 token 為對應 401 與 WWW-Authenticate，權限不足為 403，公開 health／文件依設定例外。
- WHEN 取得 JWKS 或啟動身份設定，THEN JWKS 可非阻塞取得並快取，未知 kid 觸發更新；claim 名稱／格式需明確設定，缺少必要設定不以預設身份啟動。
- WHEN 已驗證身份操作組織資源，THEN tenant 來自已驗證身份，body 不得覆寫 organization、doer、creator、status 等受保護欄位；跨組織資源回 404，batch 沿用對應單筆權限。
- WHEN 部署服務的對外入口，THEN body 大小、TLS 與 rate limit 保持設計的 gateway 責任，測試與文件標明此部署前提，不虛構本服務已提供 gateway 保護。

---

## Edge Cases

- 資源不存在的 404 優先於有效 header 的版本不符 412；缺少或格式錯誤 header 的 428／400 仍先於載入資源。
- 允許來源可讀取含 X-Trace-Id 的 500，錯誤內容不得洩漏內部例外。

## Success Criteria

- **SC-1**: 七個 Invoice operations 的適用成功／Problem／header 宣告與實際回應一致。
- **SC-2**: JWT／JWKS、BOLA、PATCH、ETag 與 CORS contract tests 可獨立執行。

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
| 2026-10-17 | replan-phase-one | 建立已驗收能力基準 | US-1, REQ-KERNEL-004, REQ-KERNEL-005 |
