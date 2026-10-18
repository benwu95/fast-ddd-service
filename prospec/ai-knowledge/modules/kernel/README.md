# Shared Kernel
> 以四個分層 Python package 提供服務共用機制。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `kernel/pyproject.toml` | 套件、型別與 import contracts |
| `kernel/src/fast_ddd/` | 純 domain primitive |
| `kernel/src/fast_ddd_adapter/` | ORM、交易與基礎設施 |
| `kernel/src/fast_ddd_port/` | HTTP、MQ 與 task 入口 |
| `kernel/src/fast_ddd_devtools/` | 套件與錯誤目錄工具 |
| `kernel/Makefile` | 品質檢查入口 |
| `kernel/tests/test_distribution.py` | 非 editable wheel 與型別／migration resources |

## Public API
- `AggregateRoot`、`DomainEvent` — domain 狀態與事件。
- `execute()`、`RepositoryBase` — command 邊界與持久化。
- `install_kernel()`、`subscribe()`、`build_worker()` — 程序入口整合。

## Dependencies
**Depends on:** 無內部 module；adapter 使用 PostgreSQL／RabbitMQ，port 使用 FastAPI／FastStream／PgQueuer。
**Used by:** `example` 與 `template` 產生的獨立服務。

## Modification Guide
1. 修改 domain primitive → [Core](./core.md)；先確認純 core 的 import 邊界。
2. 修改交易與儲存 → [Adapter](./adapter.md)；同步檢查入口交易生命週期。
3. 修改 wire contract → [Port](./port.md)；比對 producer 與 consumer。
4. 修改開發檢查 → [Devtools](./devtools.md)；執行 kernel 與 example 的 `make check`。
5. 改分發 → pyproject／wheel tests → Git／path 與 Linux image；四個 py.typed、正式 migrations 必須可讀，test-only branch 不進 wheel。

## Ripple Effects
- 公開型別與序列化變更影響 `example` 的 domain、controller、schema 與資料庫。

## Pitfalls
- 分層為 port → adapter → core；runtime packages 不可依賴 devtools。
- 共用設定由 composition root 注入；不可讓 core 直接讀 settings。

## Sub-Modules
- [Core](./core.md) — domain、context 與集合操作。
- [Adapter](./adapter.md) — 交易、ORM、訊息與 task enqueue。
- [Port](./port.md) — HTTP、MQ 與 worker wrappers。
- [Devtools](./devtools.md) — 靜態品質工具。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
