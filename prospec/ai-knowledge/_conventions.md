# Coding Conventions: fast-ddd-service

> 依目前 `kernel/`、`example/` 的 source 與工具設定整理；需求中的變更須落地後再同步此處。

<!-- prospec:auto-start -->

## Naming Conventions

Python module、函式與屬性使用 snake_case，class 使用 PascalCase，常數使用 UPPER_SNAKE_CASE。業務 ID 使用 `NewType`，如 `InvoiceId`／`CustomerId`；Repository／batch 以 `Id` 泛型傳遞具名 ID，UUID 僅在 port／ORM 邊界轉換。

HTTP model 以 snake_case 宣告、camelCase aliases 交換資料。MQ envelope 使用 camelCase；`to_json(camel_case=True)` 轉換 dataclass 固定欄位，Mapping key 保留。`integration_message()` 直接序列化事件 dataclass 並排除根層 metadata；`serialization.to_camel()` 統一 serializer、error params、aliases 與 catalog。DB 欄位與 domain_event body 使用 snake_case。

## Code Patterns (Follow)

workspace 使用 uv；`uv run --frozen` 依 `uv.lock` 執行。Python 版本至少 3.13；Ruff line length 100，Pyright strict，禁止藉 type-ignore 關閉檢查。

分層為 port → adapter → core；core 不依賴 Pydantic、ORM 或入口框架。服務由 bootstrap／wiring 組裝；entry points 讀 settings，port 透過 controller 進入 use case。Repository 明訂 `tenant_scope`，自訂查詢沿用 `tenant_conditions()`。

`execute()` 協調交易與事件；`SessionProvider` 擁有外層 commit，巢狀 command 使用 SAVEPOINT。rollback journal 還原持久化 metadata 與原 events，清除載入快取；business state 由 domain 保留。交易關閉並清除 provider state 後才執行 hook snapshots，允許 hook 開新交易。背景 task 同交易 enqueue；MQ 放 after-commit hook。跨組織查詢使用有 reason 的 `system_context()`；讀寫皆驗 tenant。

value object 使用 frozen dataclass，金額使用 Decimal；現在時間使用 `pendulum.now('UTC')`。PATCH 用 MISSING → UNSET 區分未提供與 null。

wire normalizer 將可預期的數值／UTC 範圍失敗轉為既有 validation／client error；JSON Pointer 先逐 token escape，再做 URI fragment encoding，root 為 `#`。

## Error Handling

DomainError 帶穩定 error code 與 ErrorKind；port 映射為 Problem。已登錄 unique／foreign-key constraint 在 adapter 映射。MQ raw JSON 與 retry counter 在 manual ack 邊界內驗證，無效值在 handler／inbox 前送 DLQ。JSON formatter 保留 exception type／frames，省略值與 source lines；已知 library 名單由 configure_logging 擁有，library message／extras 只取受控 metadata，Uvicorn access 去掉 query 與 credentials。JWT claims 明確驗型別；OpenAPI errors 由共用安裝點處理。

## Testing Conventions

root `make check` 依序委派 `make -C kernel check` 與 `make -C example check` 執行格式檢查、lint、型別、import contracts 與 coverage。Coverage 下限 80%，pytest warnings 視為 error；DB／MQ 整合測試使用 Testcontainers，需要 Docker。兩套 DB fixture 均透過 Alembic `heads` 初始化；kernel 的 test-only branch 放在 `tests/migrations/`，不可包進 runtime wheel。兩個 `make check` 先做 `uv lock --check`；typing contract 由獨立 positive／negative fixture 驗證錯誤 ID。

## Runtime Lifecycle

worker 的 health app 共用 `health_router`，live 檢查 worker task 是否存活，ready 再以 timeout 查 DB；不等同於業務工作必定有進度。`AsyncExitStack` 以反向註冊順序清理已取得資源；worker shutdown 有時限，broker 需先連線以支援事件發送。

API／consumer 的同步組裝保留 engine／broker／HTTP transport 未連線，成功後才啟動 telemetry 並交給 Runtime 關閉。telemetry 的部分初始化與 provider 安裝失敗須清理已取得的 exporter／processor／reader；關閉一個 provider 失敗仍關閉另一個。

consumer 在 lifespan 的 finally 關閉 Runtime，不依賴成功關閉 broker 才執行的 after_shutdown。worker task 取得後立即登記 AsyncExitStack 的取消／await callback，涵蓋 health app／server 建構失敗，正常執行仍遵守 drain 時限。

## Git Conventions

Conventional Commits 使用英文；明確指定 staging path，不提交 `.tasks/`。執行格式工具僅處理本次變更檔案；完整 `make check` 是唯讀品質閘門。

<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
