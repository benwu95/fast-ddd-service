---
product: fast-ddd-service
version: phase-2
last_updated: 2026-10-20
---

# fast-ddd-service — Python DDD／Event-driven 參考架構

## Vision

提供 Python AI 開發 skill 的共用架構基礎，讓服務開發者沿用可驗證的 DDD／Event-driven 邊界，避免每個服務重建 transaction、tenant、HTTP、MQ 與背景工作機制。

Phase 1 交付可安裝的 kernel 與可執行的 billing Invoice 參考服務；Phase 2 提供可獨立使用及客製化的 Copier 服務骨架。後續再提供產生服務與 bounded context 的 skills／recipes。

## Target Users

| Role | Description | Core Need |
|------|-------------|-----------|
| Python 後端開發者 | 建立與維護 bounded context | Python 原生命名、具型別 contract 與可重用基礎設施 |
| API／MQ 整合者 | 前端及 Python、C#、Node.js consumer | 一致的 camelCase wire contract、錯誤與重送語意 |
| 架構與 skill 維護者 | 維護共用 kernel 及後續產生流程 | 可執行範例、分層限制與需求／測試追溯 |

## Feature Map

### background-work

在業務 transaction 內排入工作，明確區分重試、失敗保留、冪等通知與 cron 競爭邊界。
→ [features/background-work.md](features/background-work.md)

### http-contract

提供與 OpenAPI 一致的 Invoice API，涵蓋認證、tenant 保護、Problem 回應、PATCH 與 ETag。
→ [features/http-contract.md](features/http-contract.md)

### kernel-foundation

以具名 ID、序列化、aggregate repository、tenant 隔離及 transaction 邊界支援領域實作。
→ [features/kernel-foundation.md](features/kernel-foundation.md)

### message-contract

以固定 envelope、subscriber context、inbox 與有限重試處理跨服務事件，保留 after-commit 發送的可靠性限制。
→ [features/message-contract.md](features/message-contract.md)

### plugin-distribution

以 Claude Code、Codex 與 agy 共用的 plugin 交付只能手動呼叫的 `fast-ddd-init`，以對應版本的 git tag 建立服務；版本一致性檢查讓 plugin、template 與 kernel 使用同一版本。
→ [features/plugin-distribution.md](features/plugin-distribution.md)

### runtime-foundation

提供三個執行角色的組裝、health 與資源清理，並以 telemetry、品質工具及追溯證據支持維護。
→ [features/runtime-foundation.md](features/runtime-foundation.md)

### service-template

產生具有自有 lock／venv、三種執行角色與 migrations 的空服務；開發者可直接客製化外層，選擇更新時合併修改並處理衝突。框架 CI 驗證 example 漂移與分發產物。
→ [features/service-template.md](features/service-template.md)

## Core User Stories Summary

後端開發者可沿用 kernel 的型別、儲存與交易；API 整合者可依公開 contract 操作 Invoice；MQ consumer 可隔離處理事件；工作維護者可驗證 enqueue、重送與排程；服務維護者可執行各角色並追溯品質證據。

## Product Principles

Python domain／DB／內部事件使用 snake_case，API／MQ 固定欄位使用 camelCase，任意 map key 保留原樣。領域與 I/O 分層，非公開 API 必須認證，公開函式具測試，錯誤使用穩定結構；交易及外部副作用的保證以可重現證據與明確限制呈現。

## Roadmap Overview

| Phase | Status | Key Capabilities |
|-------|--------|------------------|
| Phase 1 | 已完成並通過 Grade S verify | kernel、Invoice 參考服務及永久行為規格 |
| Phase 2 | 已完成並通過 Grade A verify | Copier 骨架、客製化更新、產物與漂移驗收；保留 late-capture 歷史限制 |
| Phase 3 | 規劃中，尚未交付 | fast-ddd／fast-ddd-init、recipes 及 marketplace |
