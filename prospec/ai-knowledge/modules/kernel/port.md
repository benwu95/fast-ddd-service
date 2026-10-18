# Service Ports
> 在 HTTP、MQ 與 task 入口建立驗證、context 與交易邊界。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `kernel/src/fast_ddd_port/http.py` | 安裝 middleware、health 與 response helpers |
| `kernel/src/fast_ddd_port/models.py` | Request／response／message 型別 |
| `kernel/src/fast_ddd_port/problems.py` | Problem 與例外映射 |
| `kernel/src/fast_ddd_port/preconditions.py` | If-Match 與 OpenAPI 修正 |
| `kernel/src/fast_ddd_port/auth.py` | JWT、JWKS 與 permission |
| `kernel/src/fast_ddd_port/middleware.py` | Request context 與 provider scope |
| `kernel/src/fast_ddd_port/subscriber.py` | Inbox、ack、retry 與 DLQ |
| `kernel/src/fast_ddd_port/tasks.py` | Registry、worker 與 cron wrappers |

## Public API
- `install_kernel()`、`health_router()` — FastAPI 共用設定。
- `RequestModel`、`ResponseModel`、`MessageModel` — snake_case 屬性與 camelCase aliases。
- `subscribe()` — typed payload handler 與 consumer 交易。
- `TaskRegistry.task()`／`cron()`、`build_worker()` — 背景工作註冊。

## Dependencies
**Depends on:** kernel adapter／core；FastAPI、Pydantic、FastStream、PgQueuer。
**Used by:** `example` port 與 entry points。

## Modification Guide
1. 新增 API → schema／router／controller → preconditions 共用 OpenAPI 安裝點與實際 response 比對。
2. 新增 consumer → MessageModel、subscribe → 驗證 raw JSON／root、非負 retry counter、DLQ、inbox 與 tenant policy。
3. 新增 task／cron → registry → 驗證 context、transaction 與失敗保留。

## Ripple Effects
- 修改 aliases、Problem 或 If-Match 時須比對 wire／OpenAPI 的 schema、media type 與 headers。

## Pitfalls
- HTTP request 拒絕未知欄位；MQ 忽略未知欄位以支援向前相容。
- `organizationId=null` 的 MQ 預設略過；接受 global 需明確設定。
- cron 以 system identity、無 organization 執行；跨組織查詢仍須明確豁免。
- health 的角色 callback 只確認程序工作存活；DB timeout 不代表業務進度檢查。
- JWT user／organization／permissions claim 拒絕錯誤型別，不以 str() 接受不合法身份。
- Timestamp 的 UTC overflow 轉為 validation error；JSON Pointer 使用 RFC 6901 fragment escaping，root 為 #。
- ETag 的 integer 轉換失敗沿既有 400 處理；不得讓 oversized digits 變成 500。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
