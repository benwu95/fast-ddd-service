# Infrastructure Adapter
> 集中處理交易、持久化與對外基礎設施。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `kernel/src/fast_ddd_adapter/session.py` | UoW、SAVEPOINT 與 hooks |
| `kernel/src/fast_ddd_adapter/controller.py` | Command 與 batch fallback |
| `kernel/src/fast_ddd_adapter/repository.py` | Tenant、版本、事件與 archive |
| `kernel/src/fast_ddd_adapter/messaging.py` | MQ envelope、inbox、commit 後發送 |
| `kernel/src/fast_ddd_adapter/tasks.py` | 同交易寫入 PgQueuer |
| `kernel/src/fast_ddd_adapter/migrations/` | Kernel Alembic branch |
| `kernel/src/fast_ddd_adapter/http_client.py` | HTTP timeout、retry 與 tracing |
| `kernel/src/fast_ddd_adapter/observability.py` | Logging、metrics 與 telemetry |

## Public API
- `SessionProvider`、`execute()`、`run_batch()` — 交易與 command 執行。
- `configure(max_event_chain_depth=10, max_events_per_unit_of_work=10_000)` — 連鎖上限；超過丟 `EventChainLimitExceededError`。
- `RepositoryBase` — 服務實作 entity／model 映射與 scope。
- `integration_message()`、`publish_after_commit()` — 跨服務發送。
- `TaskQueue.enqueue()` — 工作與業務資料原子提交。
- `add_kernel_versions()` — 在 Alembic 載入前附加 migration 位置。
- `include_object()`、`render_item()` — 服務 `alembic/env.py` 兩處 `context.configure` 的 hooks：排除 PgQueuer 表；autogenerate 將 `UtcDateTime` 寫成 `sa.DateTime(timezone=True)`。

## Dependencies
**Depends on:** kernel core；SQLAlchemy、asyncpg、PgQueuer、FastStream、httpx2、OpenTelemetry。
**Used by:** kernel port、`example` adapter 與 composition root。

## Modification Guide
1. 新增 repository → 宣告 `RepositoryBase[Id, A, M]`、tenant scope → model 映射與 tenant tests。
2. 修改 rollback → session journal／mark／restore（含 `Mark.dispatched`）→ metadata、事件順序、hook 重入、連鎖計數與 commit 失敗測試。
3. 修改外部 I/O → HTTP client／messaging → producer／consumer 與 status／error metrics 測試。

## Ripple Effects
- 事件 dispatch 在交易內，分派前檢查連鎖世代與事件總數；after-commit hooks 在外層 commit 後執行。

## Pitfalls
- 事件總數跨同一 UoW 的多次 `run_batch` 累計、隨 SAVEPOINT 回復；超限在 `run_batch` 整批階段與巢狀的逐筆階段丟出；最外層的逐筆階段只讓該筆成為 `UnexpectedFailure`。
- load 與 save 都檢查 tenant；`system_context(reason)` 才可明確跳過組織限制。
- after-commit 發送沒有 durable outbox；commit 後程序終止可能遺失訊息。
- PgQueuer 使用 session 的同一 raw connection；dedupe 衝突須受 SAVEPOINT 保護。
- 交易先關閉並清除 provider state，再執行 hooks；on_rollback 僅屬最外層 rollback。
- JsonFormatter 限制已知 library 的 message／extras，保留 exception 型別與 frame；Uvicorn access 只記 method、path、status 與 client。
- telemetry 以 ExitStack 交接 exporter／processor／reader 的 ownership；部分建構或安裝失敗也清理，trace 關閉失敗仍關閉 metrics。
- kernel fixture 由 `kernel/tests/migrations/` 與 kernel Alembic branch 建 DB，不可用 create_all 取代。
- Alembic 以 module 全名渲染定義在 `sqlalchemy` 以外的型別且不補 import；新增供服務 model 使用的自訂型別時須擴充 `render_item`，否則 autogenerate 的 revision 在執行 upgrade／downgrade 時 `NameError`（寫檔與 `heads` 仍成功）。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
