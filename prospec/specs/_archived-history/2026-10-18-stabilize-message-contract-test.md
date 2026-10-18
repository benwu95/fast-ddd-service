# stabilize-message-contract-test — Archive Summary

- **Archived**: 2026-10-18
- **Original Created**: 2026-10-18
- **Quality Grade**: S

## User Story

維護 kernel 的開發者可按事件身分驗證真實 producer／consumer contract，合法的非 FIFO handler 觀測不產生 false failure，跨訊息資料錯置仍被拒絕。

## Affected Modules

| Module | Impact | Description |
|---|---|---|
| kernel | 測試維護 | contract oracle、可重現的 global-first 情境與 Knowledge 慣例 |

## Requirements

Quick spec-impact 判定：無 spec impact。相對 d03c75d，review／verify 時的實作 diff 僅改 `kernel/tests/port/test_subscriber.py`、kernel README 與 freshness stamp；後續歸檔／同步另產生本摘要、raw scan 與獨立 lessons ledger 變更。未變更 production code、公開 API、schema 或 wire contract。既有 `message-contract.md:34–38` 的 REQ-KERNEL-006 保證逐事件 organization／payload 與隔離，沒有跨訊息 FIFO handler 承諾。本次移除不成立的位置式測試假設，保留既有 contract 驗證；不新增、修改或移除 Feature Spec REQ，略過 graduation。

## Completion

- **Tasks**: code 3/3（100%）；verification 1/1。
- **Acceptance Criteria**: 2/2；保持預設 concurrent delivery，另以 Event／timeout 強制 global-first。

## Review & Verify

- **Review**: 1 輪 fresh-context full-lens review，0 critical／0 major／0 minor；ticket receipt 通過，review-clean。
- **Verify**: Grade S；machine tasks／Knowledge／tests PASS，fresh Constitution 6/6 規則 PASS；quick delta-spec 與 UI design 不適用。review 與 verify 各自獨立 receipt 通過，未使用自我驗證代替。
- **Quality Log**: tasks 首輪因 `[V]` 混入 archive／PR 動作而 FAIL；修訂後獨立 WARN 僅保留 4 個 tasks 低於一般 sizing 建議的 advisory。T1 RED fixture 曾在 tasks gate 更正前啟動，已保留程序偏差；後續 oracle 修改於有效 verifier 後進行，未回寫歷史。
- **CI Root Cause**: Linux CI run 39107310967 的既有 main 測試觀測 `[None, tenant]` 卻以 `[tenant, None]` 位置式比較；本次在真實 PostgreSQL／RabbitMQ 重現同一 RED（1 failed），再以 exact count／完整 ID set／逐事件 organization 與原有 payload assertions 修正。
- **Tests**: Python 3.13.12／pytest 9.1.1，subscriber 55/55；正式完整 `make check` kernel 333/333、example 270/270、standalone git 50/50、path 50/50，全部零 skip／failure／error。所有 frozen lock、format、lint、strict typing、11/11 import contracts、真實 DB／MQ、三角色程序／容器、migration、更新／衝突與 snapshot drift 通過。
- **Coverage**: line + branch kernel 2548/2688=94.7917%、example 815/825=98.7879%、git／path 各226/234=96.5812%；生成服務各自完整 app 13/13 檔、0 excluded lines。
- **Test Attempt**: 07b57578-d343-4125-a145-9eb87f06976d，command `make check`、exit 0；before／after／review digest 均為 `74c2cc2372b8bba54059e8f9783e35f6f9d4a4c6b4777a5f38ac0c9cbbc888c7`。相同 inputs 的完整 suite 證據沿用至 verify，未重跑未變更內容。
- **Mutation Evidence**: 直接 invoke 實際測試函式；真實 serializer／parser／handler／assertions，transport 與 eventually 為 seams。兩順序 control 2/2、duplicate／missing／extra／ID／organization／cross-payload／map／postal／Decimal／enum 共20/20 mutations 由實際 assertion 拒絕。此 probe 不含 DB／MQ，不代替真實 integration suite。

## Knowledge Update

kernel 1/1 affected module 已於 final tests／review／verify 前同步並由 CLI stamp；README 記載逐事件 oracle 與觀測順序陷阱。既有 Phase 2 Grade A 與 acceptance late-capture 歷史保持原樣。
