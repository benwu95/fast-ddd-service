---
feature: runtime-foundation
status: active
last_updated: 2026-11-06
story_count: 1
req_count: 4
---

# runtime-foundation

## Who & Why

**Target users**: 維護 kernel、參考服務與後續 AI 開發 skill 的專案擁有者。

**Problem solved**: 執行角色、資源清理、診斷與需求證據需要一致且可重複的交付基準。

**Why it matters**: 驗收過的參考架構可作為 template／skill 的依據，避免以部分測試成功取代完整需求驗證。

## User Stories & Behavior Specifications

### US-1: 可診斷且可重複驗收的執行基準 [P0]

作為維護 kernel、參考服務與後續 AI 開發 skill 的專案擁有者，
我要以明確角色、health、telemetry、migration 與品質檢查操作參考服務，
以便故障可定位、資源可清理，設計與前身差異可追溯至驗收證據。

**Acceptance Scenarios:**
- WHEN 啟動或終止 API、consumer、worker，THEN 設定、health、drain 與已取得資源的清理遵守角色邊界。
- WHEN HTTP／DB／MQ／task 或 outbound HTTP 成功或失敗，THEN logs、traces 與 metrics 提供正確關聯及分類。
- WHEN 執行交付驗收，THEN 型別、分層、schema、完整測試與需求追溯均有可重現結果。

#### REQ-KERNEL-009: 可診斷的 tracing、metrics 與對外 HTTP

共用執行基礎設施提供設計要求的 logs／traces／metrics，對外 HTTP 具有明確 timeout、有限重試與敏感資料遮蔽。

- WHEN 各執行邊界產生事件或進行 I/O，THEN HTTP、MQ、背景工作及其事件可由同一 trace 關聯；HTTP／DB／MQ publish／MQ consume／task／outbound HTTP 的計數或耗時按設計維度記錄，DB 包含連線池及操作失敗分類。
- WHEN 對外 HTTP 成功、收到錯誤 response 或連線失敗，THEN outbound HTTP 收到 200 與 503 的 duration 樣本各帶正確 response status；transport error 帶錯誤類別，不以無 status 的共用 point 混合成功與失敗。
- WHEN 建立與使用對外 HTTP client，THEN HTTP client 必須明確給 timeout，僅在符合設計的冪等 method／連線層失敗進行有限重試，收到 HTTP response 後不重試；傳遞 trace，關閉時釋放 client。
- WHEN 輸出診斷或錯誤資料，THEN JSON log 不記敏感 header／body；URL 去掉 credentials 並遮蔽敏感 query 值，錯誤回應不洩漏內部例外；exporter 設定依既有方式決定，不新增獨立 telemetry 系統。

---

#### REQ-EXAMPLE-001: 角色組裝、health 與安全終止

參考服務的 API、consumer、worker 各有明確入口與角色所需健康訊號，資源與進行中工作依生命週期清理。

- WHEN 建立服務角色，THEN 設定與必要依賴缺失時啟動失敗；API 不註冊 consumer，consumer 不隱式跑在 API process，角色資源由既有 bootstrap／wiring 組裝。
- WHEN 執行角色 health probes，THEN API health 依設計檢查 process／DB，consumer health 檢查 broker；worker liveness 可確認 event loop 回應且 worker task 存活，readiness 再檢查 DB。probe 有 timeout，失敗回報不健康，不假稱能證明所有工作進度。
- WHEN 正常或異常退出角色，THEN 終止時停止接收、在設定時限內 drain／交還未完成工作，關閉 broker／DB／HTTP／telemetry 等已建立資源；各角色正常與異常退出皆有 cleanup 證據。

---

#### REQ-KERNEL-010: 可重複執行的品質與 schema 驗證
kernel 與 example 提供相同品質基準，包含型別、分層、完整測試與正式 migration schema；錯誤目錄與套件 contract 涵蓋有單一工具 owner。

- WHEN 執行 kernel 或 example 的 make check，THEN 兩個 make check 都涵蓋 format／lint、strict typing、package／import contracts、uv lock 一致性、完整 pytest 與各自 coverage≥80%；既有 106／44 個 node id 作基準，刪改有需求理由，不能降低門檻或略過必要外部工具。
- WHEN root package 下的目錄本身或任一子孫目錄含 `.py` 檔卻缺少 `__init__.py`，THEN `fast-ddd-check-packages` 以非零 exit code 結束並逐一列出每個缺少的目錄；相對於 root package 的路徑經過 `__pycache__` 或 `.` 開頭目錄的 `.py` 檔不計入，不含 `.py` 檔的子樹不要求 `__init__.py`。
- WHEN 上述範圍內的目錄名稱不是合法 Python 識別字（`str.isidentifier()` 為 `False`，如 `billing-v2`），THEN `fast-ddd-check-packages` 不論該目錄是否有 `__init__.py`，都以非零 exit code 結束並列出該目錄與 `not a valid package name`；同時缺少 `__init__.py` 時兩則訊息都列出。
- WHEN 建立、升降版或比對資料庫 schema，THEN 整合 fixture 經 Alembic 建立 kernel／service／test-only schema；正式發佈的 kernel 與 service 各一個 head，upgrade／downgrade 及 model autogenerate 無未落實差異；test-only branch 不進 runtime wheel。
- WHEN 產生錯誤目錄或執行 CI／pre-commit，THEN 錯誤代碼格式／唯一性／message params 一致性與 contract 涵蓋檢查由現有 devtools／tests 驗證；CI 與 pre-commit 使用既有品質 owner，不另建平行規則來源。

---

#### REQ-EXAMPLE-002: Phase 1 需求、前身與驗收證據追溯

專案擁有者可追溯 Phase 1 的設計需求、保留／調整行為與實際驗證結果，並以此作為後續 Python AI 開發 skill 的參考依據。

- WHEN 檢視 Phase 1 的前身比較基準，THEN 固定 ddd-service-example@21124d3d22fcd99b82f009d64ab93e51ac70564e 與前身實際 pin 的 dataclass-mixins@v0.0.3／02abf60e81863a947a4edcb32232e3db286a657a；記錄來源、版本選擇假設與設計允許差異，不宣稱目前未測的整體等價。
- WHEN 追溯 Phase 1 設計與驗收，THEN 24 個 FR 與 21 個凍結 acceptance scenarios 全數有 REQ、owner、任務與測試／檢查結果對應；原有符合者保留，缺口以證據修正，不把需求缺口隱藏成測試成功。
- WHEN 使用 Phase 1 作為後續 skill 的參考基準，THEN 建立並同步真實 Knowledge module 邊界、related_modules 與可供後續 skill 引用的修改／驗證路徑；完成獨立 review、正式 tests 記錄與 Prospec verify 的 S／A，再宣告 Phase 1 完成，最終未驗證需求為 0。

---

## Edge Cases

- HTTP 重試僅限符合冪等語意的連線層失敗，收到 response 後不重試。
- health 表示角色存活及必要依賴可用，不保證每個業務工作都有進度。
- 未連線的同步組裝與 telemetry 啟動分開；已取得的 task／provider 在後續建構或關閉失敗時仍受清理 owner 保護。

## Success Criteria

- **SC-1**: kernel 與 example 的 make check 均包含完整品質 owner、零必要案例 skip 與 coverage 至少 80%。
- **SC-2**: Phase 1 的需求、固定版本前身比較、Knowledge、review 與 S／A verify 證據可追溯。

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
| 2026-11-06 | fail-on-invalid-package-name | MODIFIED REQ-KERNEL-010 | REQ-KERNEL-010 |
| 2026-11-06 | fail-on-missing-intermediate-init | MODIFIED REQ-KERNEL-010 | REQ-KERNEL-010 |
| 2026-10-17 | replan-phase-one | 建立已驗收能力基準 | US-1, REQ-KERNEL-009, REQ-EXAMPLE-001, REQ-KERNEL-010, REQ-EXAMPLE-002 |
