# Billing Reference Service
> 以 Invoice bounded context 示範 kernel 的完整服務組裝。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `example/app/bootstrap.py` | Runtime、共用資源與關閉 |
| `example/app/wiring.py` | HTTP、事件、consumer、task 註冊 |
| `example/app/main.py` | API factory |
| `example/app/consumer.py` | MQ consumer factory |
| `example/app/task_worker.py` | Worker entry point |
| `example/app/core/billing/domain/invoice.py` | Invoice 狀態與 value objects |
| `example/app/core/billing/use_case/invoice_use_case.py` | Domain 操作與 repository protocol |
| `example/app/adapter/controller/billing/invoice_controller.py` | 共用 application 邊界 |
| `example/app/adapter/repository/billing/invoice_repository.py` | ORM 映射與 tenant 查詢 |
| `example/alembic/env.py` | 服務 migration 環境 |
| `example/.copier-answers.yml` | workspace／既有 service branch 接管 |
| `example/tests/runtime/` | 不依賴業務 helpers 的通用 lifecycle／migration cases |

## Public API
- `create_app()` — API／consumer factory，各位於對應 entry point。
- `InvoiceController` — HTTP、MQ、task 共用業務入口。
- `/invoices` — list、get、create、patch、delete、void、batch void。
- `InvoiceIssued`／`InvoiceUpdated`／`InvoiceVoided`／`InvoiceDeleted` — billing events。

## Dependencies
**Depends on:** `kernel` 提供共用機制；`template` 提供起始實作與漂移驗收；`plugin` 的 manifest 與 skill 由 `tests/template/` 的 contract test 驗證；PostgreSQL、RabbitMQ 與 notification HTTP 服務。
**Used by:** 無內部 module；作為可執行參考服務。

## Modification Guide
1. 改規則 → domain → use case → controller → port schema／router → 各層 tests。
2. 改資料 → invoice model／repository → `make migration name="..."` → migration tests。
3. 加入口 → port wrapper → controller → wiring；composition 留在 bootstrap／entry points。
4. 加通知 → event handler enqueue → task registry → NotificationClient → transport tests。
5. 加數量無上限的大量作業 → 依 fast-ddd skill 的 `references/workflows/batch-operation.md` step 5 實作扇出與工作 → drain worker 驗證每個 UoW 的事件數。
6. 改 worker lifecycle → task_worker／settings → health、signal／cleanup tests；timeout oracle 須區分產品時限與測試 watchdog。
7. 改共通骨架 → 先改 template，再由 generator 同步；業務初始化檔與 migration chain 保留。
8. 改 skill 參考清單內的檔案（billing、customer consumer、notification、登記位置、對應測試）→ 執行 `make template-references` 同步 template 副本、example 副本與 ownership。

## Ripple Effects
- Invoice event 同時供 MQ 發送與 task enqueue；變更需檢查兩種用途。
- `CustomerDeactivated` 只排入 `billing.void_invoices` 工作；message ack 時發票尚未作廢；工作在自己的交易內以 FOR UPDATE 重查並鎖定仍屬於該客戶的有效發票，作廢事件的 user 為 `task:billing.void_invoices`、沒有 parent event。

## Pitfalls
- port 不直接依賴 repository；core 不讀 settings 或 adapter。
- notification 用 caller 決定的 key 發出 PUT，重試必須保留同一 key。
- cron 先明確跨組織列舉，再分派帶 organization 的 task。
- `make check` 先以 `make kernel-version` 比對 skill 與 workspace `../uv.lock` 的 kernel 版本，再檢查 lock、跑靜態與測試；`tests/typing_contracts/` 維持具名 ID 邊界。
- worker task 取得後立即登記 AsyncExitStack 取消／await，涵蓋 health server 建構失敗；連線、broker、runtime、telemetry 亦依序清理。
- consumer lifespan 在 broker startup 前重套 logging policy，以 finally 關閉 Runtime，涵蓋 broker stop 例外；失敗留安全 exception 診斷。
- API／consumer 先完成未連線的同步組裝，再啟動 telemetry 並交給 Runtime 關閉；worker 由 AsyncExitStack 保護取得順序。
- required notification 設定由服務自己的 root fixture 提供；通用 builders 仍走 BaseSettings 驗證與環境載入。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
