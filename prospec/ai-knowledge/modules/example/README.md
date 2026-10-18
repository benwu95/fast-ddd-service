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

## Public API
- `create_app()` — API／consumer factory，各位於對應 entry point。
- `InvoiceController` — HTTP、MQ、task 共用業務入口。
- `/invoices` — list、get、create、patch、delete、void、batch void。
- `InvoiceIssued`／`InvoiceUpdated`／`InvoiceVoided`／`InvoiceDeleted` — billing events。

## Dependencies
**Depends on:** `kernel` 提供共用機制；PostgreSQL、RabbitMQ 與 notification HTTP 服務。
**Used by:** 無內部 module；作為可執行參考服務。

## Modification Guide
1. 改規則 → domain → use case → controller → port schema／router → 各層 tests。
2. 改資料 → invoice model／repository → `make migration name="..."` → migration tests。
3. 加入口 → port wrapper → controller → wiring；composition 留在 bootstrap／entry points。
4. 加通知 → event handler enqueue → task registry → NotificationClient → transport tests。
5. 改 worker lifecycle → task_worker／settings → health、signal／cleanup tests；timeout oracle 須區分產品時限與測試 watchdog。

## Ripple Effects
- Invoice event 同時供 MQ 發送與 task enqueue；變更需檢查兩種用途。

## Pitfalls
- port 不直接依賴 repository；core 不讀 settings 或 adapter。
- notification 用 caller 決定的 key 發出 PUT，重試必須保留同一 key。
- cron 先明確跨組織列舉，再分派帶 organization 的 task。
- `make check` 先檢查 lock，再跑靜態與測試；`tests/typing_contracts/` 維持具名 ID 邊界。
- worker task 取得後立即登記 AsyncExitStack 取消／await，涵蓋 health server 建構失敗；連線、broker、runtime、telemetry 亦依序清理。
- consumer lifespan 在 broker startup 前重套 logging policy，以 finally 關閉 Runtime，涵蓋 broker stop 例外；失敗留安全 exception 診斷。
- API／consumer 先完成未連線的同步組裝，再啟動 telemetry 並交給 Runtime 關閉；worker 由 AsyncExitStack 保護取得順序。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
