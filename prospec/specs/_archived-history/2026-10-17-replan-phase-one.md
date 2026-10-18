# replan-phase-one — 封存摘要

- **Archived**: 2026-10-17
- **Original Created**: 2026-10-17T18:45:39.023000+00:00
- **Quality Grade**: S
- **Plan Decision**: option-a (graded_by: in-session)
- **Evidence Bundle**: `.prospec/archive/2026-10-17-replan-phase-one/`

## User Story

作為以 Python AI 開發 skill 建立後端服務的開發者，我需要可安裝的 DDD／Event-driven kernel 與可執行的 billing Invoice 參考架構，讓領域、儲存、HTTP、MQ、背景工作及操作品質都有可追溯的規格與驗收。Phase 2 copier 與 Phase 3 skill／marketplace 不在本輪。

## Affected Modules

| Module | Impact | Description |
|---|---|---|
| kernel | High | 具名 ID、序列化、tenant／transaction、HTTP／MQ／task、telemetry、migration 與品質工具。 |
| example | High | Invoice 組裝、三個角色的 health／資源清理、工作與排程、完整驗收示例。 |

## Requirements

| REQ ID | Status | Description |
|---|---|---|
| REQ-KERNEL-001 | ADDED | Python 型別與跨邊界資料 contract |
| REQ-KERNEL-002 | ADDED | Aggregate 儲存、tenant 與事件紀錄 |
| REQ-KERNEL-003 | ADDED | Transaction、批次與連鎖事件的失敗邊界 |
| REQ-KERNEL-004 | ADDED | 可由 client 使用的 HTTP、OpenAPI 與錯誤 contract |
| REQ-KERNEL-005 | ADDED | 認證、權限與 API tenant 保護 |
| REQ-KERNEL-006 | ADDED | MQ envelope、inbox 與可重送處理 |
| REQ-KERNEL-007 | ADDED | 與業務資料一致的工作排入 |
| REQ-KERNEL-008 | ADDED | 工作執行、排程與失敗保留 |
| REQ-KERNEL-009 | ADDED | 可診斷的 tracing、metrics 與對外 HTTP |
| REQ-EXAMPLE-001 | ADDED | 角色組裝、health 與安全終止 |
| REQ-KERNEL-010 | ADDED | 可重複執行的品質與 schema 驗證 |
| REQ-EXAMPLE-002 | ADDED | Phase 1 需求、前身與驗收證據追溯 |

## Completion

- **Tasks**: code 22/22（100%）；verification 2/2；manual 0，沒有未完成項目。
- **Acceptance Criteria**: 12/12 REQ 與 21/21 凍結情境完成核對，24 個 FR 可追溯；UI Scope 為 none。
- **Naming Contract**: Python／DB／內部 domain_event body 使用 snake_case；API／MQ JSON 固定欄位使用 camelCase；任意業務 map key 保留。

## Review & Verify

- **Review**: 6 個 recorded rounds，累計 11 critical／2 major，13/13 fixed；最後 fresh-context full-lens 為 0 critical／0 major。逐項位置與重現命令見 `review.md`；修正涵蓋 transaction rollback／hooks、MQ invalid／retry、logging、ETag／validation pointer，以及 consumer／worker 資源 ownership。
- **Verify**: 最終 Grade S；task completion、Knowledge、tests 三個 machine dimensions PASS，需求與 Constitution fresh-context PASS，UI design not-applicable。首輪 C 及後續修正保留於 `verify.md`。
- **Tests**: 正式 `make check` 的 kernel 331/331、coverage 95%；example 126/126、coverage 99%，pytest 零 skip；原 150/150 node IDs 全保留。format／lint／strict typing／package checks／11 個 import contracts／uv lock 通過；正式 attempt 61db7e9a-69a2-4af8-b45b-a76a3711f73e。
- **Quality Log**: 初始 Knowledge 缺口、If-Match 優先順序／client 組裝描述及 T24 verification-kind 的 FAIL／WARN 已修正；Story 範圍與部分任務粒度的非阻擋提醒保留。review 過渡 WARN 最後收斂為 PASS；日期 verifier 曾中止一次，已獨立重試完成；verify 的 C 因生命週期與公開 API 測試缺口修正後取得 S。

## Knowledge Update

kernel（10 個 REQ）與 example（2 個 REQ）的 README／recipes 已於最後 review／tests 前同步，last_verified 為 2026-10-17T21:51:06.554Z；封存入口再確認 Knowledge 與 provenance 均 PASS。歷史 proposal 的初始缺口敘述保留，不改寫為事後狀態。封存後再次確認 kernel 10/10、example 2/2 REQ 的 Knowledge 內容。

`prospec knowledge init --raw-scan-only` 已成功刷新；CLI 2.8.0 僅掃 Git tracked files，本次為 4 個檔案，尚未納入 untracked 的 kernel／example。此 snapshot 不代表完整新架構，後續納入版本控制後應重新產生；既有 module-map／README 未被覆寫。

## 限制與後續

MQ 仍為 after-commit，沒有 durable outbox；通知採冪等 PUT key 的邊界模擬、cron 僅證明正常競爭。JWT 使用真 RSA／離線 JWKS，shutdown 驗證 callback／drain，未在部署平台實測 SIGTERM；TLS／body size／rate limit 屬 gateway 責任。CI 為本地等價檢查，未 push；固定前身 SHA 的 source 對照不代表未知部署版本整體等價。

封存僅完成 Prospec lifecycle；未執行 git commit／push、發布或部署。封存後 lesson harvest 僅累積 ledger，未自動提升 playbook／Constitution。

## Archive 結果

CLI archive identity 為 `2026-10-17-replan-phase-one`；5 份永久 Feature Specs、5 個 Story、12 個 REQ 與 44/44 驗收條件完成語意收斂，產品脈絡及 Feature Map 已補齊，沒有 TBD。CLI finalize 已同步歷史摘要並確認計數一致；結構檢查 20/22 PASS、0 FAIL、0 WARN、2 SKIP（JS／TS import-direction 與未設定 budget override）。

243 個原始 artifacts 全數保留，242 個內容相同，metadata 僅由 CLI 更新 status／archived_at；146/146 Python 檔案與最終 verify manifest 相同。lesson harvest 12/12 upsert 成功，未完成 manual tasks 為 0；結構／安全 regression pins 的 family contract test 候選僅記入 ledger，沒有自動 promotion。
