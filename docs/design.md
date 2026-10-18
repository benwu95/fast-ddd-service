# fast-ddd-service 設計計劃

> 狀態：草案（2026-10-17）
> 前身：[benwu95/ddd-service-example](https://github.com/benwu95/ddd-service-example)、[benwu95/dataclass-mixins](https://github.com/benwu95/dataclass-mixins)

## 1. 目的與範圍

讓我（單一使用者）能用一套**已驗證過的 DDD + Event-Driven 架構**，透過 AI 快速建立後端服務。

- 交付形式是可經由 Claude Code plugin marketplace 安裝的 skill，搭配一份可執行的參考服務、共用 kernel 與服務骨架 template。
- 原 repo 的 `copy_tool.py`（複製佔位檔再手動改名填寫）由 skill 取代；固定的骨架檔案由 copier 產生。
- 範圍內的架構改動只有以下幾類，其餘一律忠實搬移：
  - 新 tech stack 強制的改動；
  - 本計劃明確列出的改善項目：紀錄機制（第 7.5 節）、批次處理（第 8 節）、API 設計（第 9 節）、背景工作（第 11.1 節）、預設產生的範圍（第 14 節）；
  - 原版既有的資安漏洞修正（第 10 節）；
  - 原版缺少的執行環境基礎設施（第 12 節）。

## 2. 設計原則

1. **忠實搬移**：已驗證的架構照原樣搬過去，只在新 stack 或新目標強制時才改，並在第 5 節的對照表寫下理由。
2. **寫得囉嗦但明確，勝過魔法**：AI 讓樣板程式碼幾乎沒有成本，所以優先選擇明確的寫法（DTO 和 domain 之間手寫 mapping、ORM model 和 domain 分開），讓 AI 和 reviewer 都容易驗證。
3. **規範由工具強制執行**：分層、型別、時間處理、路由、錯誤代碼的規則都要有對應的 linter 或測試；只寫在 SKILL.md 的規則不算數。
4. **I/O 以集合為單位，業務規則以 aggregate 為單位**：見第 8 節。
5. **共用核心不讓 AI 修改**：`ddd_base` 這類共用程式碼放進外部相依（kernel），不放在服務的原始碼裡，避免各服務各自修改後逐漸分歧。
6. **預設只產生 CRUD，其他操作由需求決定**：見第 14 節。

## 3. Repo 結構與交付物

```
fast-ddd-service/
  .claude-plugin/
    marketplace.json      # plugins: [{ "name": "fast-ddd", "source": "./" }]
    plugin.json           # 明確寫 version，與 git tag 同步
  skills/
    fast-ddd/             # 主 skill：工作流程、規則、決策紀錄
      SKILL.md
      references/
        recipes/          # 非預設功能的做法說明（export 等）
    fast-ddd-init/        # 呼叫 copier 建立服務骨架（只能由使用者手動呼叫）
      SKILL.md
  kernel/                 # fast-ddd-kernel（內部分層見第 6.1 節）
  example/                # 參考服務：包含一個完整的 bounded context，CI 實際執行測試
  template/               # copier template
  copier.yml              # _subdirectory: template
  docs/
```

- **plugin source 用 `"./"`**：整個 repo 就是 plugin，skill 直接用 `${CLAUDE_PLUGIN_ROOT}/example/...` 引用參考服務，不需要同步機制。使用者只有我一個人，多複製一些檔案沒有影響。
- **kernel 用 git tag 相依**：`fast-ddd-kernel @ git+https://github.com/benwu95/fast-ddd-service@vX.Y.Z#subdirectory=kernel`，不發布到 PyPI。
- **`example/` 的 kernel 來源**：`example/` 必須測試同一個 repo 裡的 kernel，不能用已發布的 tag。copier template 提供一個問題 `kernel_source`（`git`／`path`，預設 `git`）：一般服務用 `git`，相依寫成上面的 git tag；`example/` 的 `.copier-answers.yml` 記錄 `path`，相依寫成相對路徑 `../kernel`。這樣 recopy 的比對不會因為相依來源不同而出現差異。
- **git tag 的版本號**：template 中的 kernel 版本是一個明確的常數（`copier.yml` 的 `kernel_version`，發布時和 plugin.json 的 `version` 一起調整），不使用 copier 的 `_commit` 變數。`_commit` 是 template 的 git describe 字串（例如 `v0.1.0-3-ga9258e4`），每個 commit 都不同，也不是有效的 kernel 版本；任何骨架檔案都不可以渲染 `{{ _commit }}`。
- **版本**：plugin、kernel、template 共用同一個版本號和 git tag。plugin.json 的 `version` 沒變時，已安裝的使用者不會收到更新，所以發布時一定要同步調整。
- **自動啟用**：template 產生的服務在 `.claude/settings.json` 寫入 `extraKnownMarketplaces` 和 `enabledPlugins`（`fast-ddd@<marketplace>`）。plugin source 是 relative path，所以 trust 這個 repo 後就會自動載入。
- **機密檔案的保護**：同一份 `.claude/settings.json` 的 `permissions.deny` 禁止讀取 `.env*`、`*.pem`、`*.key`、憑證檔案，以及執行 `env`、`printenv` 這類會輸出環境變數的指令。設定和機密一律從環境變數讀取，不寫進任何會被 commit 的檔案（包括 pytest 設定）。
- **template 和參考服務的關係**：Phase 1 先手寫 `example/`；Phase 2 從 `example/` 抽出 template。之後 CI 對 `example/` 執行 `copier recopy --overwrite --defaults --vcs-ref HEAD`（以 `.copier-answers.yml` 的答案、用目前這個 commit 的 template 重新產生骨架檔案），再用 `git diff --exit-code -- example ':(exclude)example/.copier-answers.yml'` 確認骨架檔案沒有差異。`.copier-answers.yml` 必須排除：copier 會把 template 的 commit（`_commit`）寫進這個檔案，而已 commit 的檔案不可能包含自己所在 commit 的 hash，比對永遠會有差異（已實測，copier 9.19）。必須加 `--vcs-ref HEAD`：不指定時 copier 會改用最新的 git tag（`copier recopy --help` 的說明），比對到的是上一次發布的 template。不用 `copier update`：它是三方合併，會保留 `example/` 裡的手動修改，偵測不到骨架檔案被直接改動。
- **skill 的開發流程**：發布前，把本機的 repo 路徑加成 marketplace 來源，載入未發布的版本測試；確認後再調整 version、打 tag。

## 4. Tech stack

| 用途 | 選擇 | 版本（2026-10-17 於 PyPI 查證） |
|---|---|---|
| Web framework | FastAPI（code-first OpenAPI） | 0.143.x |
| DTO／驗證 | Pydantic v2 | 2.14.x |
| 設定 | pydantic-settings | — |
| ORM | SQLAlchemy async | 2.1.x（需要 Python ≥ 3.11） |
| Migration | Alembic（async `env.py`） | 1.20.x |
| DB | PostgreSQL（asyncpg） | — |
| MQ | FastStream（預設 RabbitMQ） | 0.7.x |
| 時間 | pendulum | 3.3.x（有 `py.typed`，支援 3.10–3.14） |
| JWT | PyJWT | 2.15.x |
| HTTP client（JWKS、測試） | httpx2 | 2.13.x |
| 背景工作 | PgQueuer（asyncpg driver），包在 kernel 的 `TaskQueue` 介面後面 | 1.6.x，鎖定版本 |
| 型別檢查 | pyright strict | 1.1.41x |
| 套件管理 | uv | — |
| Lint／format | ruff | — |
| 架構檢查 | import-linter | — |
| 測試 | pytest、testcontainers | — |
| 可觀測性 | OpenTelemetry（tracing 和 metrics） | SDK 1.45.x |
| Git hook | pre-commit、conventional-pre-commit | 4.7.x、4.4.x |
| 即時推播（recipe） | python-socketio（RabbitMQ manager 需要 aio-pika） | 5.17.x |

Python 最低版本訂為 3.13，與原 repo 的 `pyproject.toml` 一致。PEP 695 泛型語法（原 repo 已經使用 `type` 語句）也需要 ≥ 3.12。

不採用 fastapi-filter：3.0.0 鎖定 `SQLAlchemy>=2.0,<2.1`，和 SQLAlchemy 2.1 不相容；篩選邏輯沿用原版 repository 的寫法。

## 5. 架構搬移對照

| 原架構 | 新架構 | 改動原因 |
|---|---|---|
| Connexion + `openapi/*.yml`（spec-first） | FastAPI router + Pydantic model（code-first） | stack 更換 |
| pika `RabbitMqPublisher` | FastStream `RabbitBroker` | stack 更換 |
| `werkzeug.LocalProxy` + `# type: ignore` | `ContextVar` + 有型別的 getter | 拿掉 Connexion 後 werkzeug 只剩這個用途；pyright strict 也無法通過 |
| `TypeVar`／`Generic` | PEP 695 泛型 | typing 目標 |
| `app/config.py` | pydantic-settings | 型別化、從環境變數讀取 |
| gunicorn + uvicorn worker | uvicorn 單一 process | 每個容器一個 process，由平台橫向擴展；見第 12.4 節 |
| `ddd_base` 複製進每個服務 | kernel 拆成依層命名的套件 | 見第 6.1 節 |
| datetime 對外輸出 unix timestamp（domain_event body 卻用 `isoformat()`） | 統一為 RFC 3339 字串（UTC、`Z`、毫秒） | 主流指南和多數 API 的做法；見第 7.1 節 |
| dataclass-mixins（controller 的 request／response，原版放在 adapter 層的 `request.py`／`response.py`） | port 層的 Pydantic `RequestModel`／`ResponseModel`，加上 adapter 層的 command dataclass | FastAPI／FastStream 本身就用 Pydantic 驗證和產生 schema；adapter 不可以 import port，所以 controller 的輸入改用 adapter 層自己的型別。見第 7.1 節 |
| dataclass-mixins（domain 層的 `create_strictly`） | 直接呼叫建構子 | `create(**data)` 對 pyright 隱藏了欄位名稱；改用建構子就能做靜態檢查 |
| dataclass-mixins（repository 的 JSONB 轉換） | 手寫 mapping | 見第 7.2 節 |
| `DomainEvent.serialize` 的自訂轉換 | kernel 提供不依賴 Pydantic 的序列化工具 | 見第 7.4 節 |
| ID 為 `str`，DB 欄位 `UUID(as_uuid=False)` | ID 為 `uuid.UUID`（每個 aggregate 一個 `NewType`） | 和 path convertor `{id:uuid}` 的型別一致；見第 7.2 節 |
| `Tracer` 自己產生 UUID 格式的 trace／span id | trace id 沿用 OpenTelemetry；事件用 `event_id` 串連因果關係 | 見第 12.1 節 |
| `UseCaseBase` 用 instance 屬性（`_trace_id`、`_parent_event`）傳遞 tracing，處理第一個 aggregate 後就清掉 parent | 改用 `fast_ddd.context` 的 ContextVar；use case 改為一般類別，kernel 不提供 `UseCaseBase` | controller 是 module 層級的單一實例（原版 `app/adapter/controller/__init__.py`），並行請求會互相覆蓋；批次中只有第一個 aggregate 帶到 parent。見第 12.1 節 |
| `SessionProvider` 巢狀計數，但 `__aexit__` 不論有無例外都 commit；`EventHandlerHelper` 在巢狀 scope 中直接 `rollback()` | 只有最外層 scope 可以 commit 或 rollback；`__aexit__` 遇到例外時 rollback | 巢狀 scope 的 rollback 會丟掉外層的 transaction。見第 8.2 節 |
| import 時建立全域預設的 `SessionProvider` 和 publisher，HTTP middleware 再逐請求覆蓋 | 不在 import 時建立；由 kernel 的 HTTP unit-of-work middleware 和 MQ subscriber wrapper 為每個請求、每則訊息建立並在結束時清除 | FastStream 同時處理多則訊息時會共用同一個 session。見第 12.6 節 |
| adapter import `app.port.storage.sql.postgres.DB_Session` | `app/bootstrap.py` 建立 engine、session factory、broker，注入 kernel | 新的分層 contract 禁止 adapter → port。見第 6.3 節 |
| controller 用 `*requests` 參數，回傳 `list[str] \| str` | 單筆和批次分開，回傳型別明確 | typing 目標；code-first schema 不要出現 `oneOf` |
| 逐筆 load／save、每筆一個 transaction | 批次 I/O 加逐筆 fallback | 見第 8 節 |
| `POST /your-aggregates/command`（`cmd` + 無型別 `payload`） | 資源導向 endpoint 加 `/action` | 見第 9 節 |
| 所有回應包一層 `{code, traceId, data}` | 成功回應直接回傳資源；錯誤用 RFC 9457 problem+json 加錯誤代碼 | 見第 9.4–9.6 節 |
| `decode_token` 是空殼（TODO，固定回傳 user `"test"`） | kernel 提供完整的 JWT 驗證 | 資安，見第 10 節 |
| repository 沒有 organization 過濾 | kernel `RepositoryBase` 強制 tenant 過濾 | 資安，見第 10 節 |
| `limit <= 0` 表示不設上限；匯出沒有筆數上限 | 所有數量都有上限 | 資安，見第 10 節 |
| export 是預設功能 | 改成 recipe，需要時才加 | 見第 14 節 |
| 每次寫入都把整列快照到 archive 表 | archive 由 aggregate 自行開啟，預設關閉 | 資料量，見第 7.5 節 |
| `AggregateRoot.is_archive` | 移除 | 它永遠等於「有沒有待處理的事件」；改由 repository 決定是否快照 |
| `operation_histories` 存在主表的 JSONB 陣列 | 不屬於 kernel；需要時改用獨立資料表或從 domain_event 查詢 | 資料量，見第 7.5 節 |
| `domain_event.body` 的 GIN index | 新增 `aggregate_type`、`aggregate_id` 欄位配 btree index；GIN 需要時才加 | 寫入成本，見第 7.5 節 |
| 每個 aggregate 都有 `status` enum（`CREATED`、`VOIDED`） | 只有需要狀態轉換的 aggregate 才有 `status` | 見第 14.1 節 |
| **保留不變** | `AggregateRoot`（`is_delete`、`domain_events`；新增的技術欄位見第 7.5 節）、`DomainEvent`（tracing 欄位改名見第 12.1 節；新增來源 aggregate 的基底欄位見第 8.2 節）、`UseCaseBase` 透過 parent event 串連事件的概念、`SessionProvider` 的巢狀使用、process 內的 `EventBus`、`domain_event` 事件紀錄表（結構調整見第 7.5 節）、commit 後才發送 MQ 訊息、restful server 和 MQ consumer 分成兩個 process | 已驗證過的設計 |

## 6. 分層與相依規則

分層：`port → adapter → core`，`core` 不得 import `adapter` 和 `port`。

| 層 | 可以使用 | 不可以使用 |
|---|---|---|
| `core`（domain、use case） | stdlib dataclass、pendulum、`fast_ddd` | Pydantic、SQLAlchemy、框架、`fast_ddd_adapter`、`fast_ddd_port` |
| `adapter`（controller、repository、event handler、MQ publisher） | SQLAlchemy、FastStream publisher、`fast_ddd_adapter` | FastAPI、`fast_ddd_port` |
| `port`（restful、message_queue subscriber） | FastAPI、FastStream、Pydantic、`fast_ddd_port` | 直接存取 repository |

### 6.1 kernel 的內部分層

import-linter 不會分析已安裝外部套件的內部，而且外部套件只能禁止到最上層的套件名稱（[forbidden contract 文件](https://github.com/seddonym/import-linter/blob/master/docs/contract_types/forbidden.md)：可以寫 `django`，不能寫 `django.db.models`）。kernel 對服務來說是外部套件，如果只有一個 `fast_ddd_kernel` 套件，服務端的 contract 既偵測不到「`app.core` 透過 kernel 間接用到 SQLAlchemy」，也無法只禁止 kernel 的某個子套件。

因此 kernel 在同一個 distribution（`fast-ddd-kernel`）裡提供三個依層命名的最上層套件，另加一個開發工具套件 `fast_ddd_devtools`（contract 涵蓋檢查、錯誤代碼目錄產生器；三個 runtime 套件都不得 import 它）：

| 套件 | 層 | 內容 | 允許的外部相依 |
|---|---|---|---|
| `fast_ddd` | core | `AggregateRoot`、`DomainEvent`、`EventBus`、`BatchResult` 和批次流程 helper、`SearchPage`（列表結果）、`DomainError` 和 `ErrorKind`、`Repository[Id, Aggregate]` Protocol（`load_many`／`save_many`，批次 helper 依賴它，pyright strict 才能檢查型別）、ID 型別、事件序列化工具、`context`（目前的使用者、organization id、trace id、parent event id 的 ContextVar，只依賴 stdlib；controller 從這裡取得使用者，組成 domain 方法需要的 `doer` 參數） | pendulum |
| `fast_ddd_adapter` | adapter | `SessionProvider`、`RepositoryBase`（實作 `fast_ddd` 的 `Repository` Protocol：`load_many`／`save_many`、`search`（第 9.7 節）、tenant 過濾和給自訂查詢用的 `tenant_conditions()`、archive）、`UNSET` sentinel（PATCH command 用，第 7.1 節）、`TypeDecorator`、domain_event ORM model、MQ inbox ORM model、controller base 和批次 runner（`fast_ddd_adapter.controller` 的 `execute()`／`run_batch()` 函式，含事件分派，第 8.2 節步驟 4）、IntegrityError 轉換、MQ publisher 和 `create_broker()`（訊息暫存由 `SessionProvider` 擁有）、`TaskQueue` 介面和 PgQueuer 實作（第 11.1 節）、kernel 的 Alembic migration 和 `fast-ddd-alembic` 指令（第 7.2 節）、OpenTelemetry 設定、DB metrics、JSON log（第 12 節）、對外 HTTP client 工廠（第 12.5 節）、`system_context()`、SQL 語句計數器 | SQLAlchemy、FastStream、pendulum、PgQueuer、OpenTelemetry、httpx2 |
| `fast_ddd_port` | port | `KernelSettings` 和 `load_settings()`、`RequestModel`／`ResponseModel`／`MessageModel`、`Timestamp`、`DecimalStr`、PATCH 用的 `unset_if_missing()`／`convert_unless_missing()`、`PageResponse`、`BatchResponse`、`MAX_BATCH_ITEMS`、problem+json 和錯誤代碼處理、JWT 驗證、權限 dependency、CORS 設定、health endpoint、HTTP 的 unit-of-work middleware（第 12.6 節）、MQ 的 subscriber wrapper（第 11 節，同時負責每則訊息的 context）、背景工作的 task wrapper（第 11.1 節）、給服務測試用的 `testing.TokenFactory`（簽發測試用 JWT，搭配離線的 JWKS） | FastAPI、Pydantic、FastStream、OpenTelemetry、pendulum、PyJWT、httpx2、PgQueuer |

### 6.2 import-linter contracts

服務端（根設定要有 `include_external_packages = True`）：

- `layers`：`app.port` > `app.adapter` > `app.core`。
- `forbidden`：`app.core` 不得 import `fast_ddd_adapter`、`fast_ddd_port`、`pydantic`、`sqlalchemy`、`fastapi`、`faststream`。
- `forbidden`：`app.adapter` 不得 import `fast_ddd_port`、`fastapi`。
- `forbidden`：`app.port` 不得 import `app.adapter.repository`（port 只能透過 controller 使用 adapter，不直接存取 repository），設定 `allow_indirect_imports = True`。forbidden contract 預設會檢查間接 import，而 port → controller → repository 正是設計要求的路徑；實測（import-linter）不設定時這條鏈會被判定為違規。
- `independence`：各 bounded context 的 `core` 之間互相獨立。
- 根設定加上 `unmatched_ignore_imports_alerting = error`：`ignore_imports` 中已經不存在的例外會直接報錯，例外清單只能縮小、不會殘留失效的項目。
- **contract 涵蓋檢查**：import-linter（底層的 grimp）不分析沒有 `__init__.py` 的目錄，裡面的 import 會被靜默略過。kernel 提供一個檢查指令，納入 `make check`：`app/` 下每個目錄都必須是一般套件（有 `__init__.py`），而且每個最上層模組都至少出現在一條 contract 中。這個檢查本身也要有測試。
- `forbidden`：`app.core`、`app.adapter` 不得 import `app.settings`（第 6.3 節）。
- `forbidden`：`app.core`、`app.adapter`、`app.port` 不得 import `app.bootstrap`、`app.wiring`、`app.main`、`app.consumer`、`app.task_worker`（第 6.3 節：只有進入點可以 import 組裝點和接線）。
- `forbidden`：`app.core`、`app.adapter`、`app.port` 不得 import `pgqueuer`（第 11.1 節：PgQueuer 只能出現在 kernel 的實作中，服務一律透過 `TaskQueue` 介面使用）。

kernel 端（根設定同樣要有 `include_external_packages = True`；實測不設定時，禁止外部套件的 forbidden contract 會直接報錯）：

- `layers`：`fast_ddd_port` > `fast_ddd_adapter` > `fast_ddd`。
- `forbidden`：`fast_ddd` 不得 import `pydantic`、`sqlalchemy`、`fastapi`、`faststream`。
- `forbidden`：`fast_ddd_adapter` 不得 import `fastapi`、`pydantic`（`layers` 只擋 `fast_ddd_port`，擋不到直接 import 外部套件；已實測）。
- `forbidden`：`fast_ddd`、`fast_ddd_adapter`、`fast_ddd_port` 不得 import `fast_ddd_devtools`。

服務端的 contracts 寫在獨立的 `.importlinter`（INI 格式；`root_packages` 即使只有 `app` 一個值，也要寫成多行清單，寫成單行時 import-linter 會把字串逐字元當成套件名稱，已實測）。

### 6.3 組裝點與分層外的模組

`app` 最上層的模組不屬於任何一層，不受 `layers` contract 限制：

| 模組 | 內容 | 誰可以 import |
|---|---|---|
| `app/settings.py` | 服務自己的設定（不是 template 檔案，第一次產生後由服務維護）：繼承 kernel 提供的 `KernelSettings`（`fast_ddd_port`，包含 DB、broker、JWT、CORS 等 kernel 需要的設定），再加上服務自己的欄位（例如其他服務的 URL） | port、`app/bootstrap.py`、`app/wiring.py`；core 和 adapter 都不可以（`app.settings` 繼承了 `fast_ddd_port` 的 `KernelSettings`，adapter import 它會間接 import `fast_ddd_port`，違反「`app.adapter` 不得 import `fast_ddd_port`」的 contract，已實測）。adapter 需要的設定值由 `wire_resources(settings)` 或 kernel 的 `configure(...)` 在啟動時傳入。另加 `forbidden`：`app.core`、`app.adapter` 不得 import `app.settings` |
| `app/bootstrap.py` | 組裝點（template 檔案，各服務不修改）：建立 engine、session factory、FastStream broker、publisher、`EventBus` 實例，注入 kernel（例如 `fast_ddd_adapter.configure(session_factory=..., event_bus=...)`）；設定 OpenTelemetry 和 log；呼叫 `wire_resources(settings)` 和 `wire_events(bus)`。分成兩個函式：`configure_process(settings)` 設定整個 process 的 log 和 OpenTelemetry（每個 process 一次），`build_runtime(settings, role=...)` 建立其餘的元件並回傳 `Runtime`（測試直接用 `build_runtime` 或自行組出 `Runtime`，不碰 process 層級的設定）。`role` 是 `api`／`consumer`／`worker`，組成連線的 `application_name` | 只有 `app/main.py`、`app/consumer.py`、`app/task_worker.py` |
| `app/wiring.py` | 服務自己的接線（不是 template 檔案），依角色分成五個函式：`wire_resources(settings)` 建立服務自己的基礎設施（例如呼叫其他服務的 HTTP client），存進服務自己的 `app/adapter/resources.py`（有型別的 getter，未設定時報錯，和 kernel 的 `configure` 同樣模式），回傳需要在關閉時釋放的資源，由 FastAPI lifespan／FastStream 的 shutdown 釋放；`wire_events(bus)` 註冊 in-process event handler（`bus.subscribe(EventType, handler)`，兩個 process 都需要）；`wire_http(app)` 註冊 FastAPI router；`wire_consumer(broker, session_factory)` 註冊 FastStream subscriber，回傳需要宣告 DLQ 的 queue 名稱；`wire_tasks(registry)` 註冊背景工作的 handler 和排程（第 11.1 節）。不在 import 時用 decorator 註冊到全域的 `event_bus`（原版的做法），因為 `EventBus` 實例改由 bootstrap 建立 | `app/bootstrap.py`、`app/main.py`、`app/consumer.py`、`app/task_worker.py` |
| `app/main.py` | template 檔案：`build_app(runtime, verifier)` 建立 FastAPI app（lifespan 中連線 broker、關閉時釋放 `Runtime`）、掛上 kernel 的 middleware、呼叫 `wire_http(app)`；`create_app()` 讀取設定並呼叫 bootstrap，以 `uvicorn --factory app.main:create_app` 啟動 | 進入點，沒有人 import |
| `app/consumer.py` | template 檔案：`build_consumer(runtime)` 建立 `AsgiFastStream`（`/health/live` 用 FastStream 的 ping 檢查 broker 連線；啟動後宣告各 queue 的 DLQ）、呼叫 `wire_consumer`；`create_app()` 讀取設定並呼叫 bootstrap，以 `faststream run --factory app.consumer:create_app` 啟動 | 進入點，沒有人 import |
| `app/task_worker.py` | template 檔案：`build_task_worker(runtime, connection)` 建立背景工作的 worker、呼叫 `wire_tasks(registry)`（第 11.1 節）；`main()` 為 PgQueuer 另開一條 asyncpg 連線（LISTEN 用，DSN 由 `database_url` 去掉 `+asyncpg` 而來），收到 SIGTERM／SIGINT 時處理完手上的工作後停止，以 `python -m app.task_worker` 啟動 | 進入點，沒有人 import |

原版的 `app.trace`、`app.logger`、`app.package_instance` 分別由 `fast_ddd.context`、`app/bootstrap.py` 的 log 設定、kernel 的 unit-of-work middleware 取代。

## 7. 資料轉換、時間與紀錄

### 7.1 port 層的 DTO

對外格式：欄位用 camelCase、Enum 輸出為 value、UUID 輸出為字串（以上沿用 dataclass-mixins）；Decimal 輸出為字串（例如 `"10.50"`，避免金額在 JS Number 中失去精度）；datetime 改為 RFC 3339 字串，一律轉成 UTC、以 `Z` 結尾、毫秒精度，例如 `"2026-10-17T02:00:00.123Z"`。

datetime 不沿用原版的 unix timestamp，原因（2026-10-17 查證）：

- Google AIP-142、Azure、Microsoft Graph、Zalando #169、JSON:API、OpenAPI `format: date-time` 都採用 RFC 3339／ISO 8601 字串。Zalando 明確反對數字 timestamp，因為看不出單位是秒還是毫秒。
- 抽樣的 11 個公開 API 中，GitHub、Shopify、PayPal、Square、Jira、Salesforce、Google Calendar 用字串；Stripe、AWS、Slack 用 epoch 數字；Twilio 用 RFC 2822。
- 原版本身就有兩種格式：API 輸出 timestamp，`DomainEvent.serialize` 寫進 domain_event 的卻是 `isoformat()`。改用 RFC 3339 後，API、domain_event、MQ 訊息統一成同一種格式（第 7.4 節）。
- 一定要輸出 `Z`：JavaScript 的 `Date` 會把不帶時區偏移的日期時間字串當成本地時間。

kernel（`fast_ddd_port`）提供以下 base model。實測（pydantic 2.14）顯示 request 和 response 的需求互相衝突，不能共用一個：

- 只設 camelCase alias 時，無法用欄位名稱（snake_case）建構 model，`from_attributes` 從物件轉換也會失敗（`missing`）；
- 開啟 `populate_by_name` 或 `validate_by_name` 之後，client 送 snake_case 的 `created_by` 也會被接受，request 的 contract 就變成兩種寫法都收。

| base model | 設定 | 用途 |
|---|---|---|
| `RequestModel` | `alias_generator=to_camel`、只接受 alias、`extra="forbid"` | HTTP request body、query；client 只能送 camelCase |
| `ResponseModel` | `alias_generator=to_camel`、允許用欄位名稱驗證 | response；由手寫的 `from_domain()` 建構 |
| `MessageModel` | `alias_generator=to_camel`、只接受 alias、`extra="ignore"` | 接收的 MQ 訊息。不能用 `extra="forbid"`：發送方新增欄位時，consumer 會把每則訊息都拒絕、送進 DLQ |

**port 和 controller 之間的型別**（依第 2 節原則 2，每一層之間都是手寫轉換）：

- **輸入**：controller 的方法接收 adapter 層定義的 command（`@dataclass(frozen=True, slots=True)`），不接收 port 的 `RequestModel`（adapter 不可以 import port）。port 的 handler 把 `RequestModel` 逐欄轉成 command。
- **PATCH 的「沒送」和「送 `null`」**：
  - port 的 PATCH `RequestModel` 欄位宣告為 `T | MISSING = MISSING`（Optional 欄位為 `T | None | MISSING = MISSING`），`MISSING` 是 pydantic 2.14 提供的 sentinel。實測：沒送的欄位維持 `MISSING`；非 Optional 欄位送 `null` 回 422 `string_type`；OpenAPI schema 為原本的型別、不是必填；pyright strict 0 errors。直覺的寫法 `name: str = Field(default=None)` 執行期正確，但 pyright strict 會報 `"None" is not assignable to "str"`。
  - `fast_ddd_adapter` 提供 `UNSET` sentinel（型別 `Unset`，只依賴 stdlib）。PATCH 的 command 欄位型別為 `T | Unset`（Optional 欄位為 `T | Unset | None`）；port 用 kernel 的 `unset_if_missing(value)` 把 `MISSING` 轉成 `UNSET`、`None` 維持 `None`，需要同時轉換型別的欄位（例如巢狀 body 轉成 value object）用 `convert_unless_missing(value, convert)`。`MISSING` 從 `pydantic` 直接 import（pydantic 2.14 起 `pydantic.experimental.missing_sentinel` 已標示為 deprecated）。`UNSET` 放在 adapter 而不是 core：core 不需要這個概念，放在 adapter 後，現有的 forbidden contract（`app.core` 不得 import `fast_ddd_adapter`）就能機械化保證 core 用不到它。
  - controller 依此和 aggregate 合併（第 9.2 節）。
- **輸出**：controller 回傳 domain 物件（aggregate 或 `BatchOutcome`）；port 的每個 `ResponseModel` 寫一個 `from_domain(entity)` classmethod 逐欄建構，不用 `from_attributes`。原因：回應需要 domain 沒有的欄位（例如由 `version` 算出的 `etag`，第 9.8 節），手寫轉換也讓 pyright 能檢查每一個欄位。kernel 提供 `etag_of(version)` helper。

`Timestamp`：`Annotated[pendulum.DateTime, PlainValidator(...), PlainSerializer(...), WithJsonSchema(...)]`。

- 輸入：接受帶時區偏移的 ISO 8601 字串（用 `datetime.fromisoformat` 解析），以及帶時區的 `datetime`／`pendulum.DateTime` 物件（`from_domain()` 建構回應時傳入的就是這種物件），一律轉成 UTC 的 `pendulum.DateTime`；沒有時區偏移的字串、沒有時區的 `datetime`、數字一律拒絕（422）。
- 輸出：`astimezone(UTC).isoformat(timespec="milliseconds")`，再把 `+00:00` 換成 `Z`。資料庫保留微秒，對外輸出截到毫秒。
- 已在 Python 3.13、pydantic 2.14、pendulum 3.3 實測：`"2026-10-17T10:00:00+08:00"` 輸出為 `"2026-10-17T02:00:00.000Z"`；沒有時區偏移的字串和數字被拒絕；執行期型別是真正的 `pendulum.DateTime`；OpenAPI schema 為 `{"type": "string", "format": "date-time"}`；pyright strict 0 errors。
- 必須用 `PlainValidator`；`BeforeValidator` 仍會要求產生 `pendulum.DateTime` 本身的 schema，結果丟出 `PydanticSchemaGenerationError`。
- 不使用 `pydantic_extra_types.pendulum_dt.DateTime`：它的執行期型別是自己的子類別，pyright 不接受把 `pendulum.now()` 傳給這種型別的欄位，而且沒有時區的字串會被默默當成 UTC。

`DecimalStr`：`Annotated[Decimal, ..., WithJsonSchema({"type": "string", "format": "decimal"})]`。實測（pydantic 2.14）：純 `Decimal` 欄位在 JSON 輸出時已經是字串（`"10.50"`），但 OpenAPI schema 是 `anyOf: [number, string]`，前端產生的 client 會得到 `number | string` 的聯集型別。kernel 的 `DecimalStr` 把 schema 固定為字串；輸入只接受有限值的字串和 `Decimal` 物件（後者給 `from_domain()` 使用），JSON 數字、`NaN`、`Infinity` 回 422；`NaN` 不先擋下時，後面的 `ge` 等限制會丟出 `decimal.InvalidOperation`，變成 500（已實測）。`Field(ge=..., max_digits=..., decimal_places=...)` 可以疊在 `DecimalStr` 上照常生效。原因（已實測）：JSON 數字在解析時會先變成 float，`12345678901234567.89` 會變成 `Decimal("12345678901234568")`，金額超過約 15–17 位有效數字時會失去精度；同一個值用字串送則完全精確。輸出 `"10.50"`，schema 為 `{"type": "string", "format": "decimal"}`。

把 dataclass-mixins 中和對外格式有關的測試案例（camelCase 對應、Enum、datetime、UUID、巢狀結構）改寫成 `RequestModel`／`ResponseModel`／`Timestamp` 的 contract test，證明輸出和原架構一致。datetime 的案例是刻意的例外：改成驗證 RFC 3339 的輸入與輸出。

### 7.2 domain ↔ 儲存

- domain 的 value object 使用 `@dataclass(frozen=True, slots=True)`，時間欄位標註 `pendulum.DateTime`。
- **ID**：`fast_ddd` 以 `uuid.UUID` 為 ID 的基礎型別，每個 aggregate 定義自己的 `NewType`（例如 `YourAggregateId = NewType("YourAggregateId", UUID)`），避免把不同 aggregate 的 ID 互相傳錯。DB 欄位用 `UUID(as_uuid=True)`；JSON 輸出為字串。使用 UUIDv4（`uuid.uuid4()`）；client 提供的 id（第 9.9 節）也必須是 UUID。
- repository 手寫 `model_to_entity`／`entity_to_model`，逐欄明確轉換。不用 `TypeAdapter`，原因有兩個：Pydantic 處理不了純 `pendulum.DateTime` 標註；要讓它能處理，domain 就得 import pydantic。
- JSONB 欄位新增欄位時，domain dataclass 必須明確給預設值（取代 dataclass-mixins 自動補 `None` 的行為）。舊資料缺欄位時該用什麼值，是 domain 的決策。
- kernel 提供 SQLAlchemy `TypeDecorator`：讀出時轉成 `pendulum.DateTime`，寫入時拒絕沒有時區的 datetime。ORM 欄位標註為 `Mapped[pendulum.DateTime]`，kernel 的 declarative base 在 `type_annotation_map` 中明確登記 `pendulum.DateTime` 對應這個 `TypeDecorator`，不依賴 SQLAlchemy 從父類別 `datetime` 推斷型別。（Phase 1 spike 已實測，SQLAlchemy 2.1.5、PostgreSQL 18：欄位為 `timestamptz`，讀出為 UTC 的 `pendulum.DateTime`，寫入沒有時區的 datetime 會被拒絕。）
- ORM model 的 ID 欄位標註為 `Mapped[uuid.UUID]`；aggregate 專屬的 `NewType` 只用在 domain 和 port，由 repository 的手寫 mapping 轉換。
- **時間戳由應用程式設定，ORM 不使用 `server_default`／`onupdate`**：資料庫產生的時間戳需要回讀，會讓 UPDATE 無法合併成 executemany，201 回應也拿不到 `created_at`。`created_at` 由 aggregate 建立時設定，`updated_at` 由 `save_many` 設定（第 8.2 節），兩者都是 `pendulum.now("UTC")`。
- **子集合的 mapping**：沒有識別的 value object 集合（例如 frozen dataclass 的 list），儲存時整批替換（刪除舊列、插入新列）；有識別的子 entity 依 id 比對新增、修改、刪除。
- **刪除**：維持原版的實體刪除。子資料表的 foreign key 設 `ON DELETE CASCADE`，ORM relationship 設 `passive_deletes=True`，由資料庫刪除子資料列，不逐筆載入。
- **constraint 命名**：kernel 的 `MetaData` 設定 `naming_convention`（例如 `pk_%(table_name)s`、`uq_%(table_name)s_%(column_0_name)s`），constraint 名稱固定，IntegrityError 才能依名稱對應錯誤代碼（第 9.5 節）。
- **kernel 資料表的 migration**：kernel 擁有的資料表（`domain_event`、`processed_message`）由 kernel 隨版本提供 Alembic migration，放在 kernel 套件內的獨立 version location，使用自己的 branch label（例如 `fast_ddd`）。Alembic 在執行 `env.py` 之前就依 `version_locations` 建好 script directory，`env.py` 來不及加入 kernel 的位置（已實測），所以由 kernel 提供 `fast-ddd-alembic` 指令（參數和 `alembic` 相同，執行前把 kernel 的 version location 加進設定；服務的 `alembic.ini` 必須設 `path_separator = os`），測試則對自己建立的 `Config` 呼叫 `add_kernel_versions(config)`。服務執行 `fast-ddd-alembic upgrade heads` 時一併套用。template 的 `env.py` import 服務自己的 `app/adapter/repository/models.py`（服務擁有，列出每個定義 ORM model 的模組），資料表才會登記在 `Base.metadata` 上。kernel 的 ORM model 使用和服務相同的 `MetaData`，服務 autogenerate 時不會把 kernel 的資料表當成多出來或缺少的表。升級 kernel 版本後，新的 kernel migration 會隨 `upgrade heads` 自動套用。（Phase 1 spike 已實測，Alembic 1.20：兩個 branch 各有一個 head，`alembic upgrade heads` 會套用兩者，資料庫和 model 一致時 `alembic check` 通過、model 多出欄位時失敗。設定多個 version location 後，`alembic revision` 必須指定 `--version-path` 和 `--head <branch>@head`，template 的 `make migration` 把這兩個參數包起來。）

### 7.3 時間處理規則

- 一律使用 `pendulum.now("UTC")`。
- ruff 開啟 `DTZ`；用 `TID251`（banned-api）禁止 `datetime.datetime.now`／`utcnow` 等 API，錯誤訊息指向 pendulum。kernel 中需要 `isinstance(value, datetime)` 的轉換函式用 per-file-ignores 排除。

### 7.4 事件與 MQ 訊息的序列化

aggregate 用手寫 mapping，但事件是通用結構，不可能每個都手寫。

- `fast_ddd` 提供一個只依賴 stdlib 和 pendulum 的 dataclass → JSON 轉換器（沿用原版 `DomainEvent.serialize` 的做法）：Enum → value、`pendulum.DateTime` → 和第 7.1 節一致的時間格式、UUID → 字串、Decimal → 字串、巢狀 dataclass 和集合遞迴處理。
- **domain_event 的 body** 用 snake_case 欄位名（內部儲存）。
- **對外發送的 MQ 訊息**是服務之間的 contract，格式固定為：

  ```json
  {
    "eventId": "…", "eventName": "YourAggregateVoided", "eventVersion": 1,
    "organizationId": "…", "occurredAt": "2026-10-17T02:00:00.000Z",
    "data": { "yourAggregateId": "…" }
  }
  ```

  欄位用 camelCase；trace context 透過 message header 傳遞（見第 12.1 節），不放在 body。
- **`organizationId` 取自發出事件的 aggregate**，不取自 context（第 10.2 節）。`tenant_scope = "global"` 的 aggregate 發出的事件，`organizationId` 為 `null`。
- **接收的 MQ 訊息**在 port 層用 `MessageModel` 驗證（第 7.1 節，忽略未知欄位）。`organizationId` 欄位必須存在：缺少欄位的訊息直接拒絕，送進 DLQ（第 11 節）；值為 `null` 的全域事件，只有宣告接受全域事件的 subscriber 才會處理，而且 handler 呼叫的 controller 只能存取 `tenant_scope = "global"` 的 repository，或在 `system_context()` 中執行；沒有宣告的 subscriber 收到全域事件時直接 ack 並略過（不是錯誤，不送進 DLQ）。

### 7.5 紀錄機制

**原版的問題。** 原版每次寫入同時觸發三套紀錄：

1. **domain_event**：每個事件寫入一筆，包含 body、doer、tracing（`RepositoryBase._save`）。
2. **archive**：`add_event` 會把 `is_archive` 設為 true，所以幾乎每次修改（包括刪除）都會把整列 model 複製進 archive 表（`RepositoryBase._archive`）。archive 原本是為了錢相關的訂單功能加入的。
3. **operation_histories**：存在主表那一列的 JSONB 陣列，每次操作追加一筆修改前後的值。

問題如下：

- **archive 儲存量隨修改次數平方成長**：`YourAggregateArchiveModel` 繼承 `YourAggregateMixin`，快照也包含 `operation_histories`，第 k 次修改的快照有 k 筆 history。舉例：一個 aggregate 修改 100 次、每筆 history 約 200 bytes，主表那一列約 20KB，archive 累積約 1MB（壓縮前）；一萬個這樣的 aggregate 約 10GB。
- **寫入放大**：主表那一列持續變大，PostgreSQL 每次 UPDATE 都要改寫整個 TOAST 化的 JSONB；`domain_event.body` 的 GIN index 讓每筆事件寫入都更貴。批次操作會把這些成本一起放大。
- **只寫不讀**：除了測試，沒有任何程式碼讀取 archive 或 domain_event。

**決定：**

| 機制 | 預設 | 內容 |
|---|---|---|
| domain_event | 開啟 | event-driven 和 tracing 的核心，本身就記錄了「誰在什麼時候做了什麼」。新增 `organization_id`、`aggregate_type`、`aggregate_id` 欄位，配 `(organization_id, aggregate_type, aggregate_id)` 的 btree index，查詢某筆資料的事件不需要 GIN；body 的 GIN index 需要時才加。預設永久保留；資料量大到需要清理時，再依 `created_at` 按月做 range partition，過期直接 drop partition（v1 不做，見第 17 節） |
| archive | 關閉 | kernel `RepositoryBase` 預設 `archive_model_class = None`，由 aggregate 自行設定。適用於需要「查某個時間點完整狀態」的 aggregate，例如訂單、付款。domain_event 無法取代它：從事件反推狀態必須重播所有事件，而事件格式會演進（`DomainEvent.VERSION`），重播很脆弱；快照是糾紛和對帳的直接證據 |
| operation history | 不屬於 kernel | 給使用者在 UI 上看修改紀錄的 domain 功能，需要時才加。存在獨立的資料表（一筆紀錄一列），或用 `aggregate_id` 從 domain_event 查詢；不再存在主表的 JSONB 陣列，也不被 archive 快照複製 |

**`AggregateRoot` 的技術欄位**：`is_delete`、`domain_events`、`version`（第 8.2、9.8 節）、`organization_id`（第 10.2 節；global aggregate 為 `None`）、`created_at`、`updated_at`（第 7.2 節）。這些欄位描述的是持久化的生命週期（新建 → 已存在 → 已刪除）和歸屬，不是業務狀態；業務狀態的規則見第 14.1 節。

批次的影響：預設情況下，batch-void 100 筆只寫入 100 筆 domain_event，用一次 insertmanyvalues 完成；開啟 archive 的 aggregate 才會多出 100 筆快照。

## 8. 批次處理

### 8.1 現況分析（原架構）

批次指令從 `app/port/restful/handler/your_bounded_context/your_aggregate_handler.py` 的 `command()` 進來：對 `payload` 的每一筆分別呼叫 controller，每次呼叫都是一個獨立的 transaction（`ControllerBase.connect_db_session`），最後回傳 `{success: [...], failure: [...]}`。也就是說，**現有 contract 是「逐筆獨立成敗」（partial success）**。

以一筆 UPDATE 為例，資料庫的往返次數：

| 步驟 | 位置 | SQL |
|---|---|---|
| 開始 transaction | `SessionProvider.__aenter__` | BEGIN |
| 載入 | `RepositoryBase._load`，`session.get(..., with_for_update=True)` | SELECT … FOR UPDATE |
| 儲存 | `RepositoryBase._save` → `flush()` | UPDATE、INSERT archive、每個 event 一筆 INSERT domain_event |
| event handler | `event_bus.publish_all` 在同一個 transaction 內同步執行 | 依 handler 而定，通常又是 load + save |
| 結束 | `SessionProvider.__aexit__` | COMMIT |

N 筆就要大約 6N 次往返，再加上 handler 的負擔。另外還有兩個問題：

- **鎖定順序**：依照請求內的順序逐筆 `FOR UPDATE`。兩個批次以不同順序鎖到重疊的資料列時，可能形成 deadlock。
- **每筆各自 flush**：SQLAlchemy 無法把多筆 INSERT 合併成 insertmanyvalues。

### 8.2 設計

核心原則：**aggregate 仍然是一致性邊界，domain 方法維持逐一處理單一 aggregate；批次只影響 I/O 和流程編排。** domain 層不新增任何批次概念。

**Repository（adapter）**

- 基本操作改成集合：`load_many(ids, *, lock) -> dict[Id, Aggregate]`，產生單一查詢 `SELECT … WHERE organization_id = :org AND id = ANY(:ids) ORDER BY id [FOR UPDATE]`。固定的鎖定順序可以消除前面提到的 deadlock。子資料表一律用 `selectinload`，搭配 relationship 預設 `lazy="raise"`，讓 N+1 無法發生。（`selectinload` 另外發出不加鎖的查詢；子資料只透過 aggregate root 修改，鎖住 root 就足夠。）
- `load_many(lock=True)` 一律加上 `execution_options(populate_existing=True)`：同一個 transaction 中如果先前已經用不加鎖的方式讀過同一列，identity map 裡的舊物件不會被 `FOR UPDATE` 的結果覆蓋，version 檢查就會用到舊資料。SQLAlchemy 文件建議 `with_for_update` 搭配 `populate_existing`。（Phase 1 spike 已實測：沒有 `populate_existing` 時，`FOR UPDATE` 的結果仍是 identity map 中的舊值；加上之後拿到另一個連線已 commit 的新值。）
- `save_many(aggregates)`：把所有 model、domain_event（以及有開啟時的 archive）加進 session 後只 flush 一次。
  - **新建與既有的判斷**：`version == 0` 代表新建，不需要先查資料庫（原版用 `session.get` 判斷，每個新 id 都多一次查詢）。
  - **version 和時間戳**：新建時 `version` 設為 1，`created_at` 和 `updated_at` 相同；既有的 aggregate 經過 `entity_to_model` 後，只要整個 aggregate 有任何變更，`version` 加 1、`updated_at` 更新為現在時間。「有變更」以整個 aggregate 判斷：root 的 ORM model、每一個已載入的子 entity model 任一個 `session.is_modified()` 為真，或有子資料列被新增、刪除。只檢查 root 不夠：實測（SQLAlchemy 2.1.5）只改子 entity 的欄位時，`session.is_modified(root)` 回傳 `False`，version 不會遞增，兩個持有同一個 ETag 的使用者會互相覆蓋對方對子資料的修改。沒有變更時兩者都不變。依「資料是否變更」判斷，不依「有沒有事件」判斷：如果某個 domain 方法改了狀態卻忘了發事件，version 照樣會遞增，ETag 的保護不會失效。新的值寫回 domain 物件，回應的 `ETag` 和時間才會正確。
  - **event handler 不可以再儲存「這次指令本身」儲存的 aggregate**：controller base 或批次 runner 記錄自己這次呼叫的 use case 所儲存的 aggregate（也就是回應會用到的那些；紀錄放在 `SessionProvider` 中，和 MQ 訊息暫存一樣隨 SAVEPOINT 標記與回復，見下方批次 runner），event handler（步驟 4）再次儲存其中任何一個時丟出例外。其他 aggregate 不受限制：例如 A、B 兩個事件的 handler 都去更新同一個父 aggregate P，P 在同一個 transaction 中被儲存兩次是允許的（每次儲存都依變更遞增 version）。如果限制所有 aggregate，這種常見的寫法會讓整批失敗、重送後仍然失敗，最後整則訊息送進 DLQ。原因：回應是由步驟 3 寫回的 domain 物件建構的，handler 再修改同一個 aggregate，回應的 body 和 `ETag` 就會過時，前端下一次帶 `If-Match` 會得到 412。需要連帶修改同一個 aggregate 的邏輯，應該寫在原本的 domain 方法裡。（原版的 `handle_your_aggregate_created` 就是在 handler 中修改同一個 aggregate，新版不沿用這個寫法。）
- **鎖定逾時與連線保護**：kernel 透過 asyncpg 連線的 `server_settings`（SQLAlchemy `create_async_engine(connect_args={"server_settings": {...}})`）設定 `lock_timeout`（預設 5 秒）、`statement_timeout`（預設 30 秒）、`idle_in_transaction_session_timeout`（預設 60 秒，避免忘了結束的 transaction 一直持有鎖和連線）、`application_name`（服務名稱加 process 角色，例如 `my-service:api`，在 `pg_stat_activity` 中辨識連線來源），可由設定調整。在連線層設定，不需要每個 transaction 多一次 `SET LOCAL` 往返。一次鎖住 100 列時，遇到衝突不會無限等待；逾時和 deadlock 回 409 `concurrency.lock_conflict`（第 9.5 節）。
- 單筆的 `load`／`save` 只是 `load_many([id])`／`save_many([agg])` 的包裝，kernel 只維護一套實作。
- **服務的 repository 要提供的部分**：`aggregate_class`、`model_class`、`tenant_scope`、`model_to_entity`／`entity_to_model`，有子資料表時再加 `load_options()`（`selectinload`）和 `child_models()`（變更偵測用）；aggregate 的 ORM model 繼承 kernel 的 `AggregateModel`（`id`、`organization_id`、`version`、`created_at`、`updated_at`），archive model 繼承 `ArchiveModel`。自訂查詢一律加上 `*self.tenant_conditions()`，和 `load_many`、`search` 使用同一個 tenant 過濾。
- **載入的 ORM 物件由 `SessionProvider` 強參照保存**：SQLAlchemy 的 identity map 只保存弱參照，`model_to_entity` 之後 ORM 物件就可能被回收，`save_many` 重新取得時會遺失 `load_options`，`lazy="raise"` 的 relationship 直接報錯（已實測）。`load_many` 把載入的物件交給 `SessionProvider.keep_loaded()`，存活到 unit of work 結束。
- **沒有識別的子集合只在有變更時整批替換**：每次都替換會讓 `is_modified` 永遠為真，沒有變更的 aggregate 也會遞增 version。`entity_to_model` 先比對內容，不同時才替換（參考服務的發票明細）。
- 查不到的 id 不丟例外，由呼叫端根據 `load_many` 回傳的 dict 判斷。
- `tenant_scope = "organization"` 的 repository，`load_many` 和搜尋一律帶 tenant 過濾（見第 10.2 節；`"global"` 的 repository 和 `system_context()` 例外），所以批次中屬於其他組織的 id 會被當成「找不到」。

**Use case（core）**：每個批次操作提供單筆方法（例如 `void`）和批次方法（例如 `void_many`）。批次方法在目前的 transaction 中執行，由 `fast_ddd` 的 helper 完成以下步驟，use case 只需要提供「對單一 aggregate 要做什麼」：

```
1. load_many(ids, lock=True)                     # 1 次查詢
2. 逐一比對 expected_version，再執行 domain 方法（在記憶體中）
   - 找不到的 id、version 不符、DomainError → 記入 BatchResult 的失敗清單，丟棄該 aggregate
3. save_many(成功的 aggregates)                    # 1 次 flush
4. 發送 domain events（event bus）—— 不在 core 中執行，見下方
```

- **步驟 4 由 adapter 執行**：core 的 helper 只做步驟 1–3，回傳成功的 aggregate（帶著待發送的事件）。事件的收集不依賴 use case 的回傳值：`save_many` 每儲存一個 aggregate，就把它待發送的事件加進 `SessionProvider` 中目前 scope 的待分派清單（和「已儲存的 aggregate」紀錄一樣隨 SAVEPOINT 標記與回復）。controller base（單筆）和批次 runner（批次）在 use case 回傳後，取出自己這個 scope 的清單，交給 `EventBus` 分派。這樣 use case 順帶儲存、卻沒有回傳的其他 aggregate，它們的事件也會被分派；use case 的回傳值只用來建構回應。`EventBus` 的類別定義在 `fast_ddd`，實例由 `app/bootstrap.py` 建立並注入 `fast_ddd_adapter.configure(event_bus=...)`；core 不持有、也不 import 任何 `EventBus` 實例。這樣 controller、use case 仍然可以是 import 時建立的單一實例，不需要在建構時注入 bus。

- core 只認識 `expected_version`（`int | None`）；HTTP 的 `ETag`／`If-Match` 由 port 層轉換（第 9.8 節），HTTP 的寫入一律帶值。`None` 代表不比對 version，只給內部呼叫者（event handler、MQ consumer）使用。
- core 的 `BatchResult` 失敗項目一律是 `DomainError`：找不到為 `NOT_FOUND`，version 不符為 `PRECONDITION_FAILED`（第 9.5 節）。資料庫層級的錯誤由 adapter 轉換（見下方批次 runner）。
- adapter 批次 runner 的最終結果（`BatchOutcome`）每一筆是三種之一：成功、`DomainError`、`UnexpectedFailure`（未預期的例外，對應 500 `server.internal_error`，不附例外內容）。`UnexpectedFailure` 只在 runner 的逐筆 fallback 中產生，不屬於 domain。
- **batch-create 沒有步驟 1–2 的載入**：直接用 factory 建立每個 aggregate（domain 例外記為失敗），再進入步驟 3。client 提供的 id 和既有資料重複時，步驟 3 的 flush 丟出 IntegrityError，由 runner 進入逐筆 fallback，重複的那一筆在逐筆模式中轉成 `ALREADY_EXISTS`。

controller base 和批次 runner 實作為 `fast_ddd_adapter.controller` 的兩個函式 `execute(operation)`、`run_batch(items, batch=..., single=..., raise_on_transient=...)`，不是基底類別；服務的 controller 是一般類別，每個方法呼叫其中一個。

**批次 runner（adapter，controller 層）**：transaction 由 adapter 層的 `SessionProvider` 管理，core 無法開啟或 rollback transaction，所以 fallback 放在 `fast_ddd_adapter` 的批次 runner：

```
整批處理階段：開啟 transaction（或 SAVEPOINT），呼叫 use case 的批次方法（步驟 1–3），再分派事件（步驟 4）
  - 鎖定逾時、deadlock → 整個請求回 409（見下方）
  - 其他任何例外（IntegrityError、event handler 失敗、domain 方法的 bug 等）→ rollback，進入逐筆 fallback
逐筆 fallback 階段：對每一筆各開一個 transaction（或 SAVEPOINT），呼叫 use case 的單筆方法並分派事件
  - 失敗的那一筆 rollback；結果依例外類型為 DomainError（含轉換後的資料庫錯誤）或 UnexpectedFailure
```

- rollback（不論是 transaction 還是 SAVEPOINT）時，`SessionProvider` 一併丟棄該範圍內暫存的 MQ 訊息；訊息只在最外層 commit 之後發送（第 11 節）。

- **runner 不是最外層時，改用 SAVEPOINT。** `SessionProvider` 支援巢狀使用；批次可能在 event handler、MQ 的 subscriber wrapper（第 11 節）這類已經開啟 transaction 的地方被呼叫，這時不能 rollback 整個 transaction，否則會丟掉外層的工作。做法：
  - 整批處理（步驟 1–4）包在一個 SAVEPOINT 中；失敗時 rollback 到這個 SAVEPOINT。
  - 逐筆 fallback 時，每一筆各包一個 SAVEPOINT，取代「每筆一個 transaction」。
  - MQ 訊息暫存和「已儲存的 aggregate」紀錄都支援標記與回復，由 `SessionProvider.savepoint()` 統一處理：rollback 到某個 SAVEPOINT 時，同時丟棄這個 SAVEPOINT 之後暫存的訊息和儲存紀錄。否則整批處理已經儲存過的 aggregate，在逐筆 fallback 中再次儲存時會被誤判為重複儲存。
  - 訊息仍然在最外層 commit 之後才發送。
  - 這樣 MQ 分段處理大量作業時，確定性的失敗（`DomainError`，例如資料已作廢）只影響那一筆：其他筆數照常 commit，失敗的筆數寫 warning log。
  - **非 HTTP 呼叫者的 `BatchOutcome`**（MQ subscriber、event handler 中的批次）：沒有 207 回應可以回報。只要有任何一筆是暫時性失敗（`concurrency.lock_conflict` 或 `UnexpectedFailure`），runner 在逐筆處理結束後丟出例外，讓 subscriber wrapper rollback 整則訊息並重新排隊（第 11 節），由重送整批重試，重試次數用完後送進 DLQ。因為整則訊息都被 rollback，沒有部分 commit，重送時不會重複套用成功的筆數。
- **`SessionProvider` 的規則**（修正原版）：只有最外層 scope（計數歸零時）可以 commit 或 rollback；巢狀 scope 遇到例外只往上丟，不呼叫 `rollback()`；`__aexit__` 收到例外時 rollback，沒有例外才 commit。原版的 `EventHandlerHelper.connect_db_session` 在巢狀 scope 中直接 rollback、`__aexit__` 不檢查例外就 commit，兩者都不沿用。
- **巢狀 scope 不可以吞掉資料庫例外**：PostgreSQL 在 SQL 失敗後會把整個 transaction 標成 aborted，之後的語句全部失敗。巢狀呼叫者如果需要「這一段失敗也不影響外層」，必須用 SAVEPOINT（`session.begin_nested()`）包住那一段，kernel 的 `SessionProvider` 提供對應的 `savepoint()`。
- **資料庫錯誤的轉換在 adapter，單筆和批次都一樣**：controller base（單筆）和批次 runner（逐筆模式）都依 constraint 名稱（第 7.2 節的 `naming_convention`）把 IntegrityError 轉成 `DomainError`，例如主鍵重複轉成 `ALREADY_EXISTS`。constraint 名稱從 `IntegrityError.orig.__cause__.constraint_name`（asyncpg 的例外）取得，錯誤類型依 `sqlstate` 判斷：`23505` 唯一鍵重複、`55P03` 鎖定逾時（`lock_not_available`）、`40P01` deadlock。（Phase 1 spike 已實測 23505 和 55P03。）
- **逐筆模式中的未預期例外**（例如 event handler 再次失敗）：該筆結果為 500 `server.internal_error`，不附例外內容，例外寫進 log；其他筆數照常處理。
- **鎖定逾時或 deadlock**：runner 的規則以「階段 + 例外類型」決定，不以步驟決定（整批處理階段中，步驟 1–3 在同一次 use case 呼叫內，runner 無法分辨例外來自哪一步）：
  - 整批處理階段發生時：整個請求回 409 `concurrency.lock_conflict`，不進入 fallback。鎖定衝突是暫時性的，逐筆重試只會再撞一次，由 client 重送整批即可。
  - 逐筆 fallback 階段發生時：只有該筆結果為 409 `concurrency.lock_conflict`（adapter 轉成 `ErrorKind.CONFLICT` 的 `DomainError`）。
- **transaction 由誰開啟**：HTTP 端，第 12.6 節的 middleware 只建立新的 `SessionProvider`，不開啟 transaction；最外層的 scope 由 controller base（單筆操作）或批次 runner（批次操作）開啟。MQ 端由 kernel 的 subscriber wrapper 開啟最外層 scope（見第 11 節）。
- **`SessionProvider` 的 after-commit 和 rollback hook**：`SessionProvider` 提供兩種 hook，MQ 訊息暫存是 after-commit hook 的一種用法，即時推播（第 14.3 節）也是。
  - `after_commit(callable)`：最外層 commit 成功後依序執行，只能做 I/O（發送 MQ 訊息、推播），不可以再寫資料庫。註冊時記在目前的 scope，rollback 和 SAVEPOINT 回復時，該範圍內註冊的 hook 一併丟棄。
  - `on_rollback(callable)`：最外層 rollback 之後執行，用於需要在另一個 transaction 中記錄失敗的情況（例如把某筆工作標記為失敗）；它自行開啟新的 transaction。
  - 「已儲存的 aggregate」紀錄和待分派事件清單也放在 `SessionProvider` 中，同樣隨 rollback 和 SAVEPOINT 回復。
- **MQ 訊息暫存由 `SessionProvider` 擁有**：adapter 的 publisher 把訊息註冊為 after-commit hook；最外層 `__aexit__` commit 成功後由 `SessionProvider` 執行這些 hook。controller base、批次 runner、subscriber wrapper 都不自己發送，也不需要判斷自己是不是最外層。after-commit hook 失敗時，`SessionProvider` 只寫 error log，不丟出例外，其餘 hook 照常執行：資料已經 commit，回 500 會讓 client 重送、得到 409，逐筆 fallback 中也會中斷剩下的筆數。HTTP 和 MQ 都適用這條規則（第 11 節「發送失敗仍然 ack」是它的結果）。
- **巢狀呼叫一律包 SAVEPOINT**：controller base 和批次 runner 不是最外層時（例如在 event handler 或 MQ subscriber 中被呼叫），把這次呼叫包在 `SessionProvider.savepoint()` 中。被轉換成 `DomainError` 的資料庫錯誤因此只會 rollback 這個 SAVEPOINT，外層呼叫者可以安全地捕捉它並繼續，不會在已經 aborted 的 transaction 上執行。
- **event handler 丟出的 `DomainError`**：分派事件的 controller base 或批次 runner 把它當成未預期的失敗（`UnexpectedFailure`）處理：HTTP 回 500，MQ 依「其他例外」重新排隊。原因：handler 的失敗不是這個指令本身的業務拒絕；如果照錯誤本身的類型處理，HTTP client 會收到一個指向它沒有操作過的資源的 404，MQ 則會 rollback 後 ack，讓這則訊息的工作靜默消失。
- **所有 use case 呼叫都經過 controller base 或批次 runner**：HTTP handler、MQ subscriber、in-process event handler 都一樣。它們在目前的 scope 下巢狀執行，並負責步驟 4 的事件分派。event handler 呼叫 use case 後產生的事件，因此也會被分派、也能被 adapter 的 event handler 放進 MQ 暫存。原版的 `EventHandlerHelper` 直接呼叫 use case、由 `UseCaseBase._save` 分派事件；新版事件分派已移出 core，照原版寫法直接呼叫 use case，新產生的事件會寫進 domain_event 卻沒有被分派，而且不會報錯。所以 kernel 不提供 `EventHandlerHelper`，event handler 一律透過 controller 呼叫 use case。
- 正常情況下的往返次數是常數，和 N 無關；只有遇到資料庫層級的衝突時，才會退回原本的成本。
- 對呼叫端來說，成功和失敗的集合與原本的逐筆語意一致。差別只在成功的那些筆數會在同一次 commit 寫入。對外的回應格式見第 9.4 節。
- 這個做法成立的前提，正是第 7.2 節的手寫 mapping：domain 物件不在 session 裡，丟棄失敗的 aggregate 不需要任何清理。
- 規則：domain 方法必須先檢查、再修改狀態。（就算違反，aggregate 也會被丟棄，但這條規則讓逐筆 fallback 的行為可以預期。）
- 規則：同一批次內出現重複的 id 時，整個請求以驗證錯誤拒絕（422）。重複 id 的執行順序語意不明確，不支援。

**Event handler**

- v1 只保留原本逐一處理事件的 `subscribe(event_types=[...])`。一次收到同類型 `list[Event]` 的批次 handler 改成 recipe：它會多一條分派路徑，也會帶來「依類型分組處理」的不同語意。
- 逐一處理的 handler 如果要讀寫資料庫，I/O 會隨批次筆數增加；需要時再採用批次 handler 的 recipe。
- 處理 `*Deleted` 事件的 handler 只能使用事件本身的資料：flush 之後 aggregate 已經不存在，載入不到。
- **事件帶有來源 aggregate 的資訊**：`DomainEvent` 的基底欄位新增 `organization_id`、`aggregate_type`、`aggregate_id`，由 `AggregateRoot.add_event` 從 aggregate 複製過去。`save_many` 寫入 domain_event、adapter 組成 MQ 訊息時，都從事件讀取這些值，不需要再載入 aggregate，也不依賴 context。
- **哪些事件要送到 MQ**：沿用原版的做法，由 adapter 的 event handler 決定。它訂閱需要對外發送的事件，組成第 7.4 節格式的訊息，放進 MQ 訊息暫存。core 不直接發送 MQ 訊息，所以 core 不定義 publisher 的 Protocol。

**API（port）**：endpoint 格式和回應見第 9 節。批次 payload 用 Pydantic `max_length` 限制筆數上限（預設 100，可由各服務設定調整），控制鎖定時間和請求大小。常見 API 的上限（2026-10-17 查證）：SQS、SNS 為 10；Microsoft Graph `$batch` 為 20、DynamoDB BatchWriteItem 為 25；DynamoDB BatchGetItem 和 TransactWriteItems、HubSpot CRM 為 100、Salesforce sObject Collections 為 200；Kinesis PutRecords 為 500、Pub/Sub 和 Google Calendar 為 1000。需要整批原子性的 API 上限偏小，允許部分成功的 API 上限偏大；本專案是部分成功，但整批寫入時會鎖住所有資料列，所以取中間值 100。超過上限的大量作業，改走 MQ 分段處理。

**不做的事**：不提供繞過 aggregate 的整批 SQL UPDATE。那樣做會跳過 domain 規則、archive 和事件紀錄，破壞已驗證架構的稽核能力。

### 8.3 驗證

- kernel 提供一個 SQL 語句計數器的測試工具（掛在 SQLAlchemy 的 `before_cursor_execute` 事件上）。
- **測試用的 aggregate**：`example/` 只有 batch-void，而 batch-void 無法自然產生 IntegrityError、也沒有 batch-create。kernel 的測試套件另外定義一個只用於測試的 aggregate，具備 batch-create、batch-void 和一個 unique constraint，下面的往返次數和 fallback 測試都在 kernel 中以它執行；`example/` 的 batch-void 另外跑往返次數測試。
- 批次 use case 的驗收條件：N=1 和 N=50 的往返次數相同（包括 batch-create）。前提是相關的 event handler 不做資料庫 I/O（或沒有 handler）；逐一處理的 handler 本來就會隨 N 增加 I/O。
- ORM 的 UPDATE 能不能合併成 executemany，取決於欄位集合是否一致。時間戳已改由應用程式設定（第 7.2 節），不需要回讀；Phase 1 仍要實測。如果無法合併，`save_many` 的 UPDATE 改用 ORM bulk UPDATE by primary key（`session.execute(update(Model), [...])`）。
- `populate_existing` 的測試：同一個 transaction 中先不加鎖讀取、由另一個連線修改並 commit、再加鎖讀取，確認拿到的是新資料。
- `SessionProvider` 的測試：巢狀 scope 丟出例外時外層 transaction 沒有被 rollback；`__aexit__` 收到例外時 rollback。
- 連鎖事件的測試：事件 A 的 handler 透過 controller 呼叫 use case 產生事件 B，確認 B 的 handler 有被執行、B 對應的 MQ 訊息有放進暫存，而且只在最外層 commit 之後才發送。
- fallback 路徑的測試：在批次中刻意製造一筆 IntegrityError，確認其他筆數仍然成功、失敗清單正確，而且整批處理時暫存的 MQ 訊息沒有被送出。
- 巢狀呼叫的測試：在外層 transaction 中呼叫批次 runner 並製造 IntegrityError，確認以 SAVEPOINT 完成逐筆 fallback、外層 transaction 之前的寫入沒有被 rollback、失敗那一筆暫存的 MQ 訊息被丟棄、整批處理階段已儲存過的 aggregate 在逐筆 fallback 中可以再次儲存。

## 9. API 設計

目標：前端容易串接、符合 REST 慣例、符合第 10 節的資安要求。

### 9.1 原版的問題

原版是「REST 讀取 + 一個 RPC 風格的 command endpoint」。`POST /your-aggregates/command` 用 `cmd` 列舉值分派 CREATE／UPDATE／DELETE／VOID，問題如下：

- **schema 沒有型別**：`payload` 是 `{type: object}` 的陣列，搭配 `oneOf`，前端產生 client 時拿不到型別。
- **權限只能整體控管**：所有寫入操作共用同一個路徑和 scope，無法依操作設定權限或 rate limit（OWASP API5）。
- **部分成功時回傳 400**：成功的筆數其實已經 commit，前端整批重送會重複建立資料。
- **錯誤訊息洩漏內部資訊**：失敗時的 `detail` 直接放 `str(e)`，IntegrityError 會帶出資料表、constraint 名稱和資料值（OWASP API8）。
- **外殼裡的 `code` 沒有發揮 i18n 的作用**：放的是 `"Bad Request"` 這類 HTTP 狀態描述，和 HTTP 狀態碼重複。

### 9.2 Endpoint

| 操作 | 單筆 | 批次 | 成功回應 | 層次（見第 14 節） |
|---|---|---|---|---|
| 列表／搜尋 | `GET /your-aggregates` | — | 200 | 預設 |
| 取得 | `GET /your-aggregates/{id}` | — | 200 + `ETag` | 預設 |
| 建立 | `POST /your-aggregates` | `POST /your-aggregates/batch-create` | 201 + `Location` + `ETag` + 完整資源；批次 207 | 預設；批次為 recipe |
| 更新 | `PATCH /your-aggregates/{id}` | `POST /your-aggregates/batch-update` | 200 + `ETag` + 完整資源；批次 207 | 預設；批次為 recipe |
| 刪除 | `DELETE /your-aggregates/{id}` | `POST /your-aggregates/batch-delete` | 204；批次 207 | 預設；批次為 recipe |
| 作廢（domain 指令） | `POST /your-aggregates/{id}/void` | `POST /your-aggregates/batch-void` | 200 + `ETag` + 完整資源；批次 207 | 參考服務範例 |
| 匯出 | `GET /your-aggregates/export` | — | 200 + 檔案 | recipe |

- 不提供 PUT（AIP-134 不建議用 PUT 做更新）。
- **PATCH 的語意**：
  - 欄位全部可省略：沒送的欄位為 pydantic 的 `MISSING`，port 轉成 command 的 `UNSET`（第 7.1 節）；沒送的欄位維持原值。
  - 明確送 `null`：只有型別為 Optional 的欄位可以，代表清空；非 Optional 的欄位送 `null` 回 422。
  - 巢狀的 value object 整個替換，不做深層合併（value object 是 frozen dataclass，沒有部分修改的概念）。
  - 合併由 controller 負責：controller 先透過 repository 以不加鎖的方式載入 aggregate，把 patch 的內容合併成完整的值，再以「完整的值 + `expected_version`」呼叫 use case。use case 照常以加鎖的方式重新載入並比對 version（第 8.2 節），所以不加鎖的那次讀取即使過時，也會在 version 比對時被擋下（412）。代價是多一次 SELECT。core 不需要「未設定」的特殊值。
  - Content-Type 用 `application/json`。
- 寫入成功一律回傳完整資源和新的 `ETag`，前端不需要再 GET 一次。
- 刪除不存在的資源回 404（和取得一致）。前端重送 DELETE 收到 404 時，可以視為已經刪除。

### 9.3 路由規則

- 動作用 `/action`，不用 Google／Azure 的 `:action`。主流公開 API 都用 `/action`：Stripe `POST /v1/invoices/{id}/void`、GitHub `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`、Shopify `POST /admin/api/.../orders/{order_id}/cancel.json`。
- 所有 id 型別的 path 參數一律寫成 Starlette convertor `{xxx_id:uuid}`。
  - 實測（FastAPI 0.143）：用一般的 `{item_id}` 且宣告在前面時，`GET /items/export` 會被它接走，回傳 422 `uuid_parsing`。改用 `{item_id:uuid}` 後，不管宣告順序如何，`/items/export`、`/items/batch-void`、`/items/{uuid}`、`/items/{uuid}/void` 都能正確對應，而且 OpenAPI 上顯示的路徑仍然是 `/items/{item_id}`。
  - 格式錯誤的 id 不會對應到任何路由，自然回 404（見第 9.5 節）。
  - 所有 aggregate 的 ID 都是 UUID（第 7.2 節），不支援 slug 這類非 UUID 的 ID。
- 動作用動詞、限定 POST、命名用 kebab-case；子資源用名詞。光看路徑就能分辨 `/void` 是動作、`/lines` 是子資源。
- 集合層級的批次操作用 `batch-` 前綴：`/your-aggregates/batch-void`。
- 不採用 Zalando「把動作建模成資源」的做法（例如用 `PUT /article-locks/{id}` 代替 lock 動作），用在狀態轉換上很彆扭，主流 API 也不這樣做。

### 9.4 回應格式

- **成功回應不包外殼**：直接回傳資源。
- **trace id** 放在 response header `X-Trace-Id`（值為 OpenTelemetry trace id，見第 12.1 節），並加入 CORS 的 expose 清單（第 9.11 節）。不使用 `traceparent`：那是 W3C Trace Context 定義在 request 方向傳遞用的 header。
- **錯誤用 RFC 9457 `application/problem+json`**，欄位和錯誤代碼的設計見第 9.6 節。
- **批次請求的格式**：body 為 `{"items": [...]}`，筆數上限見第 8.2 節。
  - batch-create：每一筆和單筆建立的 body 相同（`id` 可省略，見第 9.9 節）。
  - batch-update：每一筆為 `{"id": …, "etag": …}` 加上和 PATCH 相同的欄位。
  - batch-delete、batch-void 等 domain 指令：每一筆為 `{"id": …, "etag": …}`，指令需要參數時再加上對應欄位。
- **批次回應用 207 Multi-Status**（Zalando #152）。`results` 依請求順序排列（AIP-231），每一筆附上自己的 HTTP 狀態；失敗的項目附上和單筆錯誤相同結構的 `error`：

  ```json
  { "results": [
    { "index": 0, "status": 200, "data": { "id": "…", "etag": "\"3\"", "…": "…" } },
    { "index": 1, "status": 409, "error": {
        "type": "/problems/your_bounded_context.your_aggregate.already_voided",
        "title": "Your aggregate is already voided", "status": 409,
        "code": "your_bounded_context.your_aggregate.already_voided",
        "params": { "yourAggregateId": "…" } } }
  ] }
  ```

  - 單筆的 `status`：batch-create 成功為 201、附 `data`；batch-delete 成功為 204、不附 `data`；其他操作成功為 200、附 `data`。失敗時附 `error`。
  - 全部成功、全部失敗都回 207；只有和個別資料無關的錯誤（驗證失敗、未認證、權限不足、超過筆數上限、鎖定逾時）才回對應的 4xx。
  - 207 定義在 RFC 4918 §11.1（WebDAV），該 RFC 規定的 body 是 XML 的 `multistatus`；這裡的 JSON body 是 Zalando 採用的慣例，不是 RFC 4918 規定的格式。
- 每個 response（包括 problem+json 和 207 的結果）都要在 OpenAPI 上宣告 model。

### 9.5 HTTP status code

依據 RFC 9110（HTTP Semantics）、RFC 6585、RFC 6750、RFC 4918，並參考 Zalando、Google AIP-193、Azure 的做法（2026-10-17 查證）。

| 情境 | status | 依據 | 錯誤代碼 |
|---|---|---|---|
| 讀取、更新、domain 指令成功 | 200 OK | RFC 9110 §15.3.1 | — |
| 建立成功 | 201 Created + `Location` | RFC 9110 §15.3.2 | — |
| 刪除成功 | 204 No Content | RFC 9110 §15.3.5 | — |
| 批次（不論成敗） | 207 Multi-Status | RFC 4918 §11.1、Zalando #152 | 逐筆附在 `results` |
| JSON 語法錯誤 | 400 Bad Request | RFC 9110 §15.5.1 | `request.malformed_json` |
| `If-Match` 格式不接受（`*`、多個值、weak ETag） | 400 Bad Request | RFC 9110 §15.5.1 | `concurrency.invalid_if_match` |
| 格式正確但內容驗證失敗（schema、批次超過筆數上限、批次內重複 id） | 422 Unprocessable Content | RFC 9110 §15.5.21；RFC 9457 的驗證錯誤範例也用 422 | `validation.failed`（逐欄錯誤見第 9.6 節；重複 id 時，最上層仍是 `validation.failed`，`errors[]` 中對應的那一筆為 `validation.duplicate_id`） |
| 業務規則拒絕輸入內容（和目前狀態無關，例如金額超過上限） | 422 Unprocessable Content | RFC 9110 §15.5.21 | `<bc>.<aggregate>.<reason>` |
| 沒帶 token | 401 Unauthorized + `WWW-Authenticate: Bearer` | RFC 9110 §15.5.2、RFC 6750 §3.1（不帶 error 參數） | `auth.unauthenticated` |
| token 無效、過期、被撤銷 | 401 Unauthorized + `WWW-Authenticate: Bearer error="invalid_token"` | RFC 6750 §3.1 | `auth.token_invalid`、`auth.token_expired` |
| 已認證但權限不足 | 403 Forbidden | RFC 9110 §15.5.4、RFC 6750 §3.1 `insufficient_scope` | `auth.permission_denied` |
| 資源不存在、屬於其他組織 | 404 Not Found | RFC 9110 §15.5.4 允許以 404 隱藏資源是否存在 | `<bc>.<aggregate>.not_found` |
| 路由不存在、path id 格式錯誤（不符合 `{id:uuid}`，請求不會進到 handler） | 404 Not Found | RFC 9110 §15.5.5 | `request.route_not_found` |
| method 不支援 | 405 Method Not Allowed | RFC 9110 §15.5.6 | `request.method_not_allowed` |
| 和資源目前的狀態衝突（例如作廢已作廢的資料） | 409 Conflict | RFC 9110 §15.5.10：使用者可以解決衝突後重送 | `<bc>.<aggregate>.<reason>` |
| 重複建立（client 提供的 id 已存在） | 409 Conflict | Google AIP-131（ALREADY_EXISTS） | `<bc>.<aggregate>.already_exists` |
| 鎖定逾時、deadlock（可以重試） | 409 Conflict | RFC 9110 §15.5.10；Google 的 ABORTED（並行衝突）也對應 409 | `concurrency.lock_conflict` |
| `If-Match` 和目前的 ETag 不符 | 412 Precondition Failed | RFC 9110 §13.1.1、§15.5.13 | `concurrency.etag_mismatch` |
| 需要 `If-Match` 但沒有帶 | 428 Precondition Required | RFC 6585 §3 | `concurrency.precondition_required` |
| body 超過大小上限 | 413 Content Too Large | RFC 9110 §15.5.14 | `request.content_too_large`（由 reverse proxy 回應時可能不是 problem+json） |
| Content-Type 不支援 | 415 Unsupported Media Type | RFC 9110 §15.5.16 | `request.unsupported_media_type` |
| 超過 rate limit | 429 Too Many Requests + `Retry-After` | RFC 6585 §4 | `rate_limit.exceeded`（由 gateway 回應） |
| 未預期的錯誤 | 500 Internal Server Error | RFC 9110 §15.6.1 | `server.internal_error` |
| 依賴的服務不可用、readiness 失敗 | 503 Service Unavailable（可帶 `Retry-After`） | RFC 9110 §15.6.4 | `server.unavailable` |

實作要點：

- FastAPI 預設對 JSON 語法錯誤回 422（`json_invalid`），kernel 的 exception handler 要改成 400。
- FastAPI 對 Content-Type 不是 JSON 的請求（例如 `text/plain` 或沒有 Content-Type）回 422 `model_attributes_type`，不會回 415（已實測）。kernel 在 unit-of-work middleware 中檢查：有 body 的請求，Content-Type 不是 `application/json` 時回 415 `request.unsupported_media_type`。
- 409 和 422 的分界：同一個請求在資源處於其他狀態時可能成功 → 409；不論資源狀態如何都不會成功 → 422。
- domain 層不知道 HTTP。`fast_ddd` 的 `DomainError` 帶一個 `ErrorKind`（`INVALID`、`CONFLICT`、`NOT_FOUND`、`ALREADY_EXISTS`、`PRECONDITION_FAILED`），由 `fast_ddd_port` 對應到 422／409／404／409／412。`PRECONDITION_FAILED` 用於 `expected_version` 不符，錯誤代碼為 `concurrency.etag_mismatch`。
- IntegrityError 由 adapter 依 constraint 名稱轉成 `DomainError`（第 8.2 節）：主鍵重複 → `ALREADY_EXISTS`（409；`RepositoryBase` 在類別定義時自動登記 `pk_<table>`）；其他 unique 或 foreign key → 服務以 `register_constraint_error("<constraint 名稱>", ErrorClass)` 登記的錯誤（例如參考服務的 `uq_billing_invoice_organization_id_number` → `billing.invoice.number_taken`）；無法對應的 → 500。port 層只處理 `DomainError`，不認識 IntegrityError。
- PostgreSQL 的鎖定逾時（`lock_not_available`）和 deadlock（`deadlock_detected`）由 adapter 轉成 `concurrency.lock_conflict`。

### 9.6 錯誤代碼與 i18n

**分工**：

- **後端的錯誤訊息一律是英文**：`title`、`detail`、逐欄錯誤的 `detail` 都是英文，不依 `Accept-Language` 或任何語系設定改變。後端不做在地化。
- **i18n 由前端自行處理**：後端提供穩定的錯誤代碼和參數，前端依此組出在地化的訊息；沒有對應翻譯時，才退回顯示英文訊息。

**problem+json 的欄位**：

| 欄位 | 內容 | 前端用途 |
|---|---|---|
| `type` | `/problems/<code>`，相對路徑、不保證可以開啟（Zalando 的做法；RFC 9457 §3.1.1 建議用絕對 URI，但允許不可解析） | 不需要使用 |
| `title` | 英文的統一錯誤訊息，同一個錯誤代碼固定不變（RFC 9457 §3.1.3 允許在地化，本專案不做） | 沒有翻譯時的最後備援 |
| `status` | HTTP status | 沒有對應翻譯時，依 status 顯示通用訊息 |
| `detail` | 英文、給開發者看的說明，可以包含這次請求的細節（RFC 9457 §3.1.4：client 不應解析它） | 不顯示給使用者 |
| `code`（擴充） | 錯誤代碼，i18n 的 key | 主要依據 |
| `params`（擴充） | 組訊息用的參數 | 插入翻譯字串 |
| `errors`（擴充） | 422 時的逐欄錯誤 | 顯示在對應的表單欄位旁 |
| `traceId`（擴充） | 同 `X-Trace-Id` | 讓使用者回報問題時附上 |

範例：

```json
HTTP/1.1 409 Conflict
Content-Type: application/problem+json
X-Trace-Id: 4bf92f3577b34da6a3ce929d0e0e4736

{
  "type": "/problems/your_bounded_context.your_aggregate.already_voided",
  "title": "Your aggregate is already voided",
  "status": 409,
  "detail": "Your aggregate 0b6f… was voided at 2026-10-17T02:00:00Z",
  "code": "your_bounded_context.your_aggregate.already_voided",
  "params": { "yourAggregateId": "0b6f…", "voidedAt": "2026-10-17T02:00:00.000Z" },
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

**錯誤代碼格式**：

- 全小寫，以 `.` 分段，每段是 snake_case：`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$`，最長 63 字元（和 Google AIP-193 `ErrorInfo.reason` 的長度上限一致）。
- kernel 共用的錯誤代碼：`<category>.<reason>`，category 包括 `request`、`validation`、`auth`、`concurrency`、`rate_limit`、`server`。所有服務共用同一組代碼，前端只需要翻譯一次。
- domain 的錯誤代碼：`<bounded_context>.<aggregate>.<reason>`，例如 `your_bounded_context.your_aggregate.already_voided`。`not_found`、`already_exists` 由 kernel 依 aggregate 名稱自動產生。

**params 規則**（參考 Google AIP-193 的 `ErrorInfo.metadata`：組訊息所需的資料都要放在結構化欄位，讓 client 不必解析訊息字串）：

- 扁平物件；key 用 lowerCamelCase；value 只能是字串、數字、布林。時間用和第 7.1 節一致的格式。
- 不放已經組好的英文字串，也不放個人資料（email、電話等）。
- 每個錯誤代碼的 params key 是 contract：可以新增 key，不能移除或改名。

**422 的逐欄錯誤**：

```json
{
  "type": "/problems/validation.failed", "title": "Validation failed", "status": 422,
  "code": "validation.failed",
  "errors": [
    { "pointer": "#/yourValueObject/propertyA", "code": "validation.string_too_long", "params": { "maxLength": 50 },
      "detail": "String should have at most 50 characters" },
    { "parameter": "limit", "code": "validation.less_than_equal", "params": { "le": 100 },
      "detail": "Input should be less than or equal to 100" }
  ]
}
```

- 每一筆逐欄錯誤都附上英文的 `detail`（取自 Pydantic 的錯誤訊息），前端沒有對應翻譯時可以直接顯示。
- body 欄位用 `pointer`（JSON Pointer，欄位名稱用 camelCase alias，和 RFC 9457 §3 的範例一致）；query、path、header 參數用 `parameter`。
- 逐欄的 `code` 由 Pydantic 的錯誤 `type` 轉成 `validation.<type>`，並由 kernel 明確列出對應表（例如 `missing`、`string_too_long`、`string_too_short`、`greater_than`、`less_than_equal`、`too_long`、`extra_forbidden`、`enum`、`uuid_parsing`）。不在對應表內的類型一律轉成 `validation.invalid`，避免 Pydantic 改版時錯誤代碼跟著改變。
- params 取自 Pydantic 錯誤的 `ctx`，key 改成 lowerCamelCase（`max_length` → `maxLength`）。`enum`／`literal_error` 的 `expected`、`uuid_parsing`／`json_invalid` 的 `error` 是已經組好的英文字串，不放進 params。
- 批次內重複的 id 由 kernel 檢查，錯誤代碼為 `validation.duplicate_id`，`pointer` 指向重複的那一筆（例如 `#/items/3/id`）。

**錯誤代碼的定義方式**：

- domain 錯誤在 core 以 `DomainError` 的子類別定義，宣告 `code`、`kind`、英文訊息範本，以及 params 的欄位（以 dataclass 欄位宣告，pyright 可以檢查）。類別以它拒絕的業務規則命名，不加 `Error` 後綴（例如 `InvoiceAlreadyVoided`；ruff 的 N818 因此關閉），`title` 由類別名稱產生（`Invoice already voided`），同一個代碼的 `title` 因此固定不變。
- kernel 提供 `make error-catalog`，輸出所有錯誤代碼、對應的 status、params key 和英文預設訊息（JSON），作為前端翻譯檔的來源。OpenAPI 上的 problem+json 只宣告共用的 schema，不逐一列出每個 endpoint 可能的錯誤代碼（v1 不做，見第 17 節）。
- 測試：錯誤代碼不重複、符合格式、英文訊息範本的佔位符和 params 欄位一致、每個 `DomainError` 子類別都有出現在目錄中。

**穩定性**：

- 錯誤代碼是 API contract：不改名、不重複使用。同樣的錯誤條件必須回傳同樣的代碼（參考 Azure：條件相同但回傳不同代碼才算 breaking change）。
- 新增錯誤代碼不算 breaking change：前端必須依下面的順序處理未知代碼。

**前端的顯示順序**：

1. 用 `code` 和 `params` 查翻譯；
2. 沒有翻譯時，依 `status` 顯示通用訊息（例如 `http.409`）；
3. 最後才顯示 `title`。

`detail` 不顯示給使用者；回報問題時附上 `traceId`。

### 9.7 列表與搜尋

- 分頁維持 offset + limit + total：後台表格需要頁碼和總筆數。cursor 分頁留到匯出或同步場景再考慮。
- `limit` 用 Pydantic `le=100`（`MAX_BATCH_ITEMS`）限制；移除原版 `RepositoryBase._search` 中 `limit <= 0` 表示不設上限的行為。`offset` 也有上限。
- 排序沿用 `sortBy=-createdAt`（和 JSON:API、Zalando 相同），可排序的欄位採白名單。沒有指定時依 `created_at` 由新到舊；一律再以 `id` 排序，分頁結果才穩定。
- 搜尋沿用原版的 `searchKeyField`／`searchKey`（`starts:`／`ends:`／`equals:` 運算子，欄位採白名單），另外限制 `searchKey` 的數量和長度。多個 `searchKey` 以 OR 組合；原版的 `^a|b` 只把 `^` 套在第一個值上，新版用括號分組（`^(a|b)`）。
- **實作**：kernel 的 `RepositoryBase.search(filters, *, search_key_fields, search_keys, sort_by, offset, limit)` 回傳 `SearchPage`（`total` 和該頁的 aggregate），自動帶 tenant 過濾；服務的 repository 用 `search_key_fields`／`sort_by_fields`（snake_case 名稱 → 欄位）宣告白名單，再包一個有具名參數的 `search_<aggregates>()` 組出業務篩選條件。白名單同時寫在 port 的 query model（`Field(pattern=...)`，例如 `^((starts|ends|equals):)?(number|customerName)$`），不在白名單上的值回 422，OpenAPI 上也看得到可用的值；port 再把 camelCase 轉成 snake_case 交給 controller。query model 繼承 `RequestModel`，未知的 query 參數同樣回 422。回應為 `PageResponse[T]`（`total`、`items`）。
- 列表中的每一筆資源都包含 `etag` 欄位，讓前端從列表直接發動批次操作時有 etag 可用（第 9.8 節）。
- 不提供 sparse fieldsets、通用 filter 語言、`POST .../search`；有需要時再加。

### 9.8 並行控制

- aggregate 的 `version` 規則見第 8.2 節（新建為 1，資料有變更時加 1）。ETag 為 strong ETag（例如 `"3"`）：`If-Match` 依 RFC 9110 §13.1.1 使用 strong comparison。
- GET、建立、更新、domain 指令的回應都帶 `ETag` header；資源本身也包含 `etag` 欄位（同 Google AIP-154 的做法），讓列表和批次可以使用。body 中 `etag` 的字串和 header 的值完全相同（包含雙引號，例如 `"\"3\""`），前端可以直接放進 `If-Match`。
- port 層把 `If-Match`／`etag` 轉成整數的 `expected_version` 交給 core；core 不認識 ETag。
- **PATCH、DELETE 和 domain 指令必須帶 `If-Match`**：沒帶回 428，不符回 412。只接受單一的 strong ETag；`*`、多個值、weak ETag（`W/` 開頭）回 400 `concurrency.invalid_if_match`。
- 批次的每一筆必須帶 `etag` 欄位（batch-create 除外，新建的資源還沒有 etag）：缺少時整個請求回 422；不符時該筆結果為 412。
- **檢查順序**（依 FastAPI 0.143 的實際執行順序訂定，已實測：body 的 JSON 解析早於 dependency；dependency 早於 body 的 schema 驗證）：
  1. 認證（401），在 unit-of-work middleware 中；
  2. Content-Type（415）和 JSON 語法（400）；
  3. 權限（403），`require()` dependency；
  4. 缺少 `If-Match`（428）或格式不接受（400），kernel 提供的 dependency；
  5. request 的 schema 驗證（422）；
  6. 載入資料，不存在或屬於其他組織（404）；
  7. 比對 version（412）；
  8. 執行 domain 方法（409／422）。

  依 RFC 9110 §13.2.1，回應本來就不是 2xx 時不評估前置條件，所以 404 優先於 412。
- `If-Match` 的 dependency 把 header 宣告為選填（宣告為必填的話，FastAPI 會在缺少時回 422 而不是 428），再由 kernel 在產生 OpenAPI 時後處理 schema（`install_kernel` 掛上的 `install_openapi_fixups`），把 `If-Match` 標示為必填，前端產生的 client 才會要求帶這個 header。
- 原因：原版的 `FOR UPDATE` 只能保護同一個 transaction 裡的操作，擋不住「A 讀到資料、B 改了、A 用舊資料覆蓋」這種跨使用者的 lost update。如果 `If-Match` 是選填，前端不帶時 lost update 一樣會發生。

### 9.9 冪等性

- create（單筆和批次）允許 client 提供 UUID 當 `id`。重送時撞到主鍵 constraint，回 409 `already_exists`；前端在重送後收到這個錯誤時，改用 GET 取得資源。
- Zalando 對「可安全重送的建立」建議回 200／204 而不是 409。本專案選擇 409，因為 server 無法確認重送的內容和第一次相同，回 409 讓前端明確知道資源早已存在。
- client 提供的 id 如果剛好屬於其他組織，回 409 會洩漏「這個 id 存在」。UUID 實際上猜不到，可以接受。
- 不採用 `Idempotency-Key` header：IETF draft 已經在 2026-04 過期，沒有成為 RFC，而且需要另外維護一個 key 的儲存機制。

### 9.10 命名

- JSON 欄位和 query 參數用 camelCase（和 Azure、Graph 一致，也符合前端 JS 習慣）。
- 路徑用 kebab-case、集合用複數。
- enum 值用小寫，和原版 API 輸出的格式一致（例如 `voided`）。AIP 和 Zalando 建議 UPPER_SNAKE；新服務沒有舊資料，所以這是和既有前端寫法保持一致的選擇，不是遷移成本的考量。參考服務中「未作廢」的狀態值用 `active`（原版的 `created` 只代表資料存在，見第 14.1 節）。
- `operationId` 用 FastAPI 的 `generate_unique_id_function`（kernel 的 `operation_id`）由 route 函式名稱轉成 camelCase，例如 `void_invoice` → `voidInvoice`、`batch_void_invoices` → `batchVoidInvoices`；route 函式名稱因此必須在整個服務中唯一，而且以「動詞 + 資源」命名。

### 9.11 前端串接

**client 產生**：前端用 code-first OpenAPI 自動產生有型別的 client。目前活躍的工具（2026-10-17 於 npm 查證）：

- orval 8.43（可以直接產生 TanStack Query hooks）；
- @hey-api/openapi-ts 0.99；
- openapi-typescript 7.13 搭配 openapi-fetch 0.17。

後端要配合第 9.4、9.6、9.10 節的規則：每個 response 都有 model、`operationId` 可讀、不出現 `oneOf` 加任意 object 的寫法。錯誤代碼的完整清單由 `make error-catalog` 提供。

**認證方式**：前端用 `Authorization: Bearer <token>` header 帶 token，不使用 cookie。因此不需要 CSRF 防護；如果日後改用 cookie（例如加上 BFF），必須同時加上 CSRF 防護和 `SameSite` 設定。

**CORS**（`fast_ddd_port` 提供，由設定檔控制）：

- `allow_origins`：明確列出前端網域，不用 `*`。
- `allow_methods`：`GET`、`POST`、`PATCH`、`DELETE`。Starlette `CORSMiddleware` 的預設值只有 `("GET",)`（已確認），不設定的話，所有寫入請求的 preflight 都會失敗。
- `allow_headers`：`Authorization`、`Content-Type`、`If-Match`。
- `expose_headers`：`ETag`、`Location`、`X-Trace-Id`、`Retry-After`。沒有列出的 header，前端 JS 讀不到，`If-Match` 的流程就無法運作。

### 9.12 和主流指南不同的地方

| 項目 | 本專案 | 指南的立場 |
|---|---|---|
| 批次語意 | 同步、逐筆成功或失敗，回 207 | Google AIP-233/234/235 要求同步批次必須原子性，部分成功只能透過 long-running operation；Zalando #152 規定 207 加逐筆狀態；Microsoft Graph 回 200 加逐筆狀態 |
| 動作路徑 | `/action` | Google AIP-136、Azure 用 `:action`；Zalando 禁止 URL 中出現動詞 |
| 內容驗證失敗 | 422 | RFC 9110、RFC 9457 範例、FastAPI 預設用 422；Zalando、Azure、Google 用 400 |
| 狀態衝突 | 409 | RFC 9110 §15.5.10；Google 的 FAILED_PRECONDITION 對應 400 |
| 其他組織的資源 | 404 | RFC 9110 §15.5.4、Azure 用 404 隱藏資源是否存在；Google AIP-193 一律先檢查權限，回 403 |
| ETag 不符 | 412 | RFC 9110、Zalando、Azure；Google AIP-154 用 ABORTED（409） |
| 分頁 | offset + total | Google AIP-158、Zalando #160 偏好 cursor；Zalando #254、Azure 不建議回傳 total |
| enum 值 | 小寫 | Zalando #240、AIP-126 用 UPPER_SNAKE |
| 錯誤格式 | RFC 9457 + `code`／`params` | Zalando 採用 RFC 9457；Google AIP-193 和 Azure 用各自的格式 |

參考來源：[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110)、[RFC 6585](https://www.rfc-editor.org/rfc/rfc6585)、[RFC 6750](https://www.rfc-editor.org/rfc/rfc6750)、[RFC 4918](https://www.rfc-editor.org/rfc/rfc4918)、[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html)、[Google AIP](https://google.aip.dev/)、[Microsoft API Guidelines](https://github.com/microsoft/api-guidelines)、[Zalando RESTful API Guidelines](https://opensource.zalando.com/restful-api-guidelines/)、[JSON:API](https://jsonapi.org/format/)、[OWASP API Security Top 10 2023](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)。

## 10. 資安

依 OWASP API Security Top 10 2023 檢查原版後，以下項目都做成 kernel 層的強制行為，不交給各服務自己記得處理。

### 10.1 總覽

| 項目 | 原版現況 | 處理方式 |
|---|---|---|
| 認證 | `port/restful/handler/token.py` 的 `decode_token` 是 TODO，固定回傳 user `"test"` | 見第 10.3 節 |
| API1 BOLA | `User` 有 `organization_id`，但 `RepositoryBase._load`／`_search` 都沒有用它過濾 | 見第 10.2 節 |
| API3 BOPLA | request 由 dataclass-mixins 寬鬆建立；回應來自 entity 的通用轉換 | `RequestModel` 設 `extra="forbid"`，每個操作各自一個 model，body 不接受 `status`、`creator`、`doer`、`organizationId` 等欄位（create 的 `id` 例外，見第 9.9 節）；`ResponseModel` 明確列出可回傳的欄位 |
| API4 資源消耗沒有上限 | `limit <= 0` 不設上限；匯出沒有筆數上限；批次沒有筆數上限 | `limit` 上限、批次筆數上限、`searchKey` 數量和長度上限、匯出筆數上限。FastAPI／Starlette 沒有內建的 request body 大小上限，由 reverse proxy 設定（413）；rate limit 由 gateway 處理（429 + `Retry-After`） |
| API5 BFLA | 所有 endpoint 共用 `jwt: ['secret']` | 每個 endpoint 宣告自己需要的權限，例如 `Security(require("your_aggregate:void"))`；命名規則見第 10.3 節 |
| API8 錯誤訊息洩漏 | 批次失敗回傳 `str(e)` | 見第 9.5、9.6 節：例外對應到錯誤代碼，500 不回傳例外內容 |

**部署假設**：服務前面有 reverse proxy 或 API gateway，負責 TLS、request body 大小上限和 rate limit。沒有 gateway 的部署方式必須另外補上這三項。

補充：原版的搜尋用了 `re.escape`，沒有 ReDoS 風險；但 regex 比對和 JSONB jsonpath `like_regex` 都用不到 btree index，只能全表掃描。需要做模糊搜尋的欄位，之後可以考慮用 generated column 加上 `pg_trgm` 的 GIN index。

### 10.2 Tenant 隔離

- **欄位與 index**：每個 aggregate 的資料表、archive 表、domain_event 表都有 `organization_id`。所有複合 index 都以 `organization_id` 開頭，否則搜尋和 `count(*)` 會很慢。
- **強制宣告**：`RepositoryBase` 的子類別必須宣告 `tenant_scope`（`"organization"` 或 `"global"`），沒有預設值，漏寫時在類別定義階段就報錯。`"global"` 用於不分組織的資料（例如系統設定），必須在程式碼中明確寫出。
- **過濾**：`tenant_scope = "organization"` 的 repository，`load_many`、搜尋、匯出一律加上目前 tenant 的條件。查詢其他組織的資料一律回 404。
- **aggregate 自己帶 `organization_id`**（`AggregateRoot` 的技術欄位）：
  - 建立時，會建立 aggregate 的 use case 方法有一個明確的 `organization_id` 參數，傳給 aggregate 的 factory。controller 從 `fast_ddd.context` 取得目前的 organization id 填入；在 `system_context()` 中則由呼叫者明確指定。core 不讀取 context 中的 organization id，也不需要知道目前是否在 `system_context()` 中。
  - 儲存、寫入 domain_event、發送 MQ 訊息時，`organization_id` 一律取自 aggregate，不取自 context。這樣在 `system_context()` 下一次處理多個組織的資料時，每個事件仍然帶著正確的組織。
  - `tenant_scope = "global"` 的 aggregate，`organization_id` 為 `None`，事件的 `organizationId` 為 `null`（第 7.4 節）。
- **tenant context 的來源**（存在 `fast_ddd.context` 的 ContextVar，由第 12.6 節的 middleware 設定和清除）：
  - HTTP request：從 JWT 的組織 claim 取得（第 10.3 節）。
  - MQ consumer：從訊息的 `organizationId` 取得（第 7.4 節）。
  - process 內的 event handler：`EventBus` 分派事件時，把 organization context 設為事件的 `organization_id`，並取消 `system_context()` 的豁免，handler 結束後還原（和 parent event id 的處理方式相同，第 12.1 節）。handler 一律在事件所屬組織的範圍內執行，不會因為觸發它的指令剛好在 `system_context()` 中而失去 tenant 過濾。
  - 需要跨 tenant 的操作（例如處理全域事件的 MQ handler）：使用 `fast_ddd_adapter` 提供的 `system_context()` 明確豁免過濾，每次使用都寫 log。`system_context()` 只在既有的 unit of work（HTTP 請求或 MQ 訊息）中切換「豁免 tenant 過濾」，不建立 `SessionProvider` 或其他 context。在 `system_context()` 中建立 aggregate 時，呼叫者必須明確傳入 `organization_id` 參數。
  - 定期執行的工作由背景工作的排程觸發（第 11.1 節），走 task wrapper 的 unit of work；排程工作沒有組織 context，需要處理組織資料時使用 `system_context()`，並逐一明確指定 `organization_id`。CLI 這類其他進入點，v1 不支援（第 17 節）。測試則由 kernel 的測試工具建立和 middleware 相同的 context。
- **沒有 organization context 時**：organization id 為 `None`（例如處理全域事件時）且不在 `system_context()` 中，`tenant_scope = "organization"` 的 repository 被呼叫、或 controller 要建立 organization 範圍的 aggregate 時，一律丟出程式錯誤（500），不靜默查不到資料，也不建立沒有組織的資料。

### 10.3 認證與授權

- **JWT 驗證**（`fast_ddd_port`）：
  - 在第 12.6 節的 HTTP unit-of-work middleware 中驗證，驗證通過後才設定 organization id 等 context；這樣 context 在進入 router 之前就已經確定。不需要認證的路徑（health、OpenAPI 文件）由設定列出白名單。權限檢查（`require()`）仍是 endpoint 的 dependency，讀取 middleware 驗證過的 claims。
  - 簽章金鑰從 JWKS URL 取得並快取；遇到未知的 `kid` 時重新取得，以支援金鑰輪替。
  - 函式庫：簽章驗證用 PyJWT（2.15）；JWKS 用 httpx2（2.13，pydantic 維護）的 async client 取得，由 kernel 自行快取。不用 PyJWT 內建的 `PyJWKClient`：它以同步的 urllib 取得 JWKS，快取過期時會阻塞 event loop。選 httpx2 而不是 httpx，是因為 Starlette 1.8 的 `TestClient` 已經提示 httpx 改用 httpx2（實測時的 deprecation warning），測試和正式程式碼用同一個 HTTP client。
  - 驗證 `iss`、`aud`、`exp`、`nbf`；演算法採白名單（例如 RS256、ES256），拒絕 `none`。
  - 失敗時依第 9.5 節回 401，並帶 `WWW-Authenticate`。
- **claim 對應沒有預設值**：使用者 id、組織 id、權限所在的 claim 名稱（以及權限 claim 的格式，例如以空白分隔的字串或陣列）都必須在每個服務的設定檔中明確指定；缺少任何一項時，服務啟動失敗。實際的 claim 名稱取決於使用的 identity provider，kernel 不做任何假設。
- **權限**：`require("<resource>:<action>")` 檢查 token 的權限；不足時回 403 `auth.permission_denied`。
  - 命名：`<aggregate>:<action>`，兩段都用 snake_case，例如 `your_aggregate:read`、`your_aggregate:create`、`your_aggregate:update`、`your_aggregate:delete`、`your_aggregate:void`、`your_aggregate:export`。
  - 批次操作沿用對應單筆操作的權限：batch-void 需要 `your_aggregate:void`，batch-create 需要 `your_aggregate:create`。批次只是同一個操作做很多次，不另外定義權限。

## 11. Message queue

- port 層的 subscriber 直接使用 FastStream，接受它和特定 broker 綁定。FastStream 只統一了 handler 寫法、Pydantic payload 驗證、依賴注入和 `TestBroker`；各 broker 的 class 和 routing 參數（RabbitMQ 的 `RabbitExchange`／`RabbitQueue`、Kafka 的 topic）都不同。
- 發送：adapter 的 event handler 組成訊息並放進暫存（第 8.2 節），`fast_ddd_adapter` 的 publisher 用 FastStream 在最外層 commit 後發送。
- 沿用原本「commit 後才發送」的做法：訊息先暫存在 `SessionProvider` 中（第 8.2 節），最外層 commit 成功後才發送，rollback 和 SAVEPOINT 回復時丟棄對應範圍的訊息。已知限制：commit 成功但發送失敗時會遺失訊息。這是原架構既有的取捨，v1 不改成 outbox。
- 訊息格式見第 7.4 節；tenant context 和 trace context 的設定見第 10.2、12.1 節。
- consumer 是獨立的 process（`faststream run`），不掛在 FastAPI 裡。restful server 只負責發送，broker 連線在 FastAPI 的 lifespan 中建立和關閉。API process 的 broker 上不註冊任何 subscriber（`wire_consumer` 只由 `app/consumer.py` 呼叫）：FastStream 啟動 broker 時會一併啟動所有已註冊的 subscriber，註冊了的話 API pod 也會開始消費訊息。
- **subscriber wrapper**（`fast_ddd_port`；它需要 FastStream 的 ack 控制，以及 adapter 的 inbox model 和 `SessionProvider`）：kernel 包裝每個 subscriber，負責開啟最外層 transaction、寫入 inbox、呼叫 handler、離開最外層 scope（由 `SessionProvider` commit 並發送暫存的 MQ 訊息）、ack。handler 只寫業務邏輯。註冊方式：`subscribe(broker, name=..., queue=kernel_queue(name, routing_key=...), exchange=..., payload=<MessageModel>, handler=..., session_factory=...)`；handler 的簽名是 `handler(envelope, data)`，`Envelope` 是外層格式（不做泛型），`data` 由各 subscriber 的 `MessageModel` 驗證。broker 一律用 kernel 的 `create_broker(url)` 建立（掛上 trace 傳遞和 metrics 的 middleware，第 12.1 節）。
- **ack 與重送**：
  - 順序：handler 成功 → transaction commit → 發送暫存的 MQ 訊息 → ack。發送失敗只寫 log，仍然 ack：重送時 inbox 會判定為已處理而略過，不 ack 也無法補發（和第 11 節「commit 後才發送」的取捨一致）。
  - handler 丟出 `DomainError` 時依類型處理（業務上的拒絕是確定的，重試也不會改變結果）：
    - 任何 `DomainError`：subscriber wrapper 先 rollback 最外層 transaction（包括 inbox 的插入），再決定 ack、重新排隊或送進 DLQ。只有成功的路徑會 commit inbox。原因：handler 在丟出例外前可能已經寫入資料；而由 IntegrityError、鎖定錯誤轉成的 `DomainError` 發生時，transaction 已經是 aborted 狀態，無法 commit。
    - `NOT_FOUND`、`CONFLICT`、`ALREADY_EXISTS`、`PRECONDITION_FAILED`：寫 warning log，ack 並略過。例外是 `concurrency.lock_conflict`，它是暫時性的，比照下一項重新排隊。
    - `INVALID`：直接送進 DLQ，保留訊息供人工檢查。
  - 其他例外：重新排隊，最多重試 N 次（預設 3 次），超過後送進 DLQ。重試次數由 subscriber wrapper 自己計算：ack 原訊息、帶著遞增的 `x-retry-count` header 重新發送到同一個 queue，超過 `max_retries` 才 reject 進 DLQ。原因：RabbitMQ 4 的 quorum queue 對 `nack(requeue=True)` 不會遞增 delivery count（實測同一則訊息在 3 秒內被重送 1128 次），`x-delivery-limit`（kernel 預設 10）只在 consumer 處理到一半中斷時生效。
  - payload 驗證失敗、缺少 `organizationId` 這類重試也不會成功的訊息：不重試，直接送進 DLQ。
  - 每個 subscriber 的 queue 都設定 dead letter exchange 和對應的 DLQ。
  - FastStream 0.7 的 RabbitMQ subscriber 預設 ack 策略是 `REJECT_ON_ERROR`（未處理的例外會 reject、不重新排隊）。kernel 一律改用 `AckPolicy.MANUAL`，由 subscriber wrapper 依上面的規則自己 ack、重新排隊或 reject，不交給各 subscriber 自行決定。queue 宣告為 quorum queue（FastStream 的 `RabbitQueue` 支援 `QueueType.QUORUM` 和 `x-delivery-limit` 參數）。（Phase 1 spike 已查證原始碼。）
- **冪等性（inbox）**：RabbitMQ 是 at-least-once，同一則訊息可能被處理多次。kernel 提供 `processed_message` 表（主鍵為 `(subscriber, event_id)`）：consumer 在處理訊息的同一個 transaction 中插入這一組值，插入衝突代表這個 subscriber 已經處理過，直接 ack 並略過。主鍵包含 subscriber 名稱，因為同一個服務裡可能有多個 subscriber 處理同一個事件，只用 `eventId` 會讓第二個 subscriber 被誤判為已處理。
- 測試：`TestRabbitBroker` 做單元測試（不支援 dynamic subscriber）；整合測試用 testcontainers 起真正的 RabbitMQ，涵蓋重送、DLQ 和重複訊息。

### 11.1 背景工作（TaskQueue）

**用途與分工**：MQ（FastStream）負責服務之間的整合事件；背景工作負責服務自己觸發、需要非同步執行的工作，例如匯出、匯入、需要退避重試的外部呼叫、延遲執行、定期執行。兩者分開：背景工作不能遺失（使用者看得到「工作不見了」），所以用 Postgres 當佇列，排入工作和業務資料寫在同一個 transaction 裡，沒有 MQ「commit 之後才發送、發送失敗就遺失」的問題。

**介面**：`fast_ddd_adapter` 定義 `TaskQueue` 介面，v1 用 PgQueuer 實作。

- 介面只包含需要的操作：`enqueue(task_name, data, *, organization_id, delay=None, dedupe_key=None) -> bool`（adapter 以 `fast_ddd_adapter.infrastructure.task_queue()` 取得實例），以及在 worker 端註冊 handler 和 cron 排程（`TaskRegistry.task(name, payload_model, handler)`、`TaskRegistry.cron(name, expression, handler)`）。
- PgQueuer 只能出現在 kernel 的實作中，服務的程式碼一律透過 `TaskQueue` 使用（import-linter 的 forbidden contract，第 6.2 節）。PgQueuer 的 1.0 在 2026 年 5 月才發布、只有一位維護者，這層介面讓日後換成其他實作（例如 Procrastinate，或自己寫的 Postgres 佇列）時，只需要改 kernel。
- PgQueuer 鎖定版本；升級時檢查它的資料表結構是否變更（見下方 migration）。

**誰排入工作**：和 MQ 訊息相同的做法（第 8.2 節），由 adapter 的 event handler 依 domain event 決定要排入哪些工作；core 不知道背景工作的存在。event handler 在步驟 4 分派時仍然在同一個 transaction 中，所以排入工作和業務資料一起 commit、一起 rollback。

**同一個 transaction**：`TaskQueue` 的 PgQueuer 實作從 `SessionProvider` 目前的 SQLAlchemy `AsyncSession` 取得底層的 asyncpg 連線（`get_raw_connection()` 的 `driver_connection`），交給 PgQueuer 的 asyncpg driver 執行 enqueue。（Phase 1 spike 已實測，PgQueuer 1.6.0：用 `AsyncpgDriver(raw.driver_connection)` 在同一個 transaction 中 enqueue，rollback 時工作和業務資料一起消失，commit 時兩者一起寫入。）

**工作的內容**：

- payload 用第 7.4 節的序列化工具轉成 JSON，外層帶 `organizationId`（取自觸發的事件，和 MQ 訊息相同的規則）、`taskVersion`。
- headers 同時帶 W3C trace context（`traceparent`）和 `trace-id`，worker 為每個工作開一個 `task <name>` 的 CONSUMER span，接續同一個 trace（第 12.1 節）。
- 同一件事不應重複排入時，用 `dedupe_key`：同一個 key 的工作還在等待或執行中時，`enqueue` 回傳 `False`、不排入。PgQueuer 以 unique violation 表示重複，這會讓呼叫者的整個 transaction 進入 aborted 狀態（實測），所以帶 `dedupe_key` 的 enqueue 包在 SAVEPOINT 中執行，重複時只回復到 SAVEPOINT。SQLAlchemy ORM 的 `begin_nested()` 會延到下一個 ORM 語句才送出 SAVEPOINT，而 enqueue 走的是底層連線，所以進入 SAVEPOINT 後先呼叫 `session.connection()` 讓它立刻送出（實測：不這樣做時 SAVEPOINT 根本沒有送出）。同理，SQLAlchemy 的 asyncpg adapter 在自己的第一個語句才送出 `BEGIN`，unit of work 中第一個語句就是 enqueue 時，kernel 先執行一次 `SELECT 1`，否則這筆工作會在 transaction 之外自行 commit（實測）。

**worker**：獨立的進入點 `app/task_worker.py`（第 6.3 節），和 API、MQ consumer 分開部署和擴展。kernel 的 task wrapper（`fast_ddd_port`）包裝每個 handler，角色和 MQ 的 subscriber wrapper 相同：

- 建立 unit of work（新的 `SessionProvider`；organization context 取自 payload；使用者為 worker 的系統身分；trace context 取自 headers）；
- handler 透過 controller 呼叫 use case（第 8.2 節），handler 只寫業務邏輯；
- 錯誤處理依 `ErrorKind`（和第 11 節 MQ 的規則一致）：先 rollback；確定性的 `DomainError` 標記為失敗、不重試；`concurrency.lock_conflict` 和其他例外以指數退避重試，超過次數（預設 3 次）後標記為失敗；
- 失敗的工作保留，不刪除（PgQueuer 的 `on_failure` 預設是 `"delete"`，kernel 一律改成 `"hold"`），供人工檢查和重新排入；
- 工作可能被執行不只一次（worker 中斷後，heartbeat 逾時的工作會被重新認領），handler 必須是冪等的。

**排程**：定期執行的工作用 PgQueuer 的 cron 排程（`schedule()`），在 worker 中執行，不需要另外的排程 process；多個 worker 實例也不會重複觸發（Phase 1 實測）。排程工作的 unit of work 沒有組織 context（第 10.2 節）。

**使用者看得到的工作狀態**：PgQueuer 的資料表是佇列內部用的，不直接對外。需要讓前端查詢進度的工作（例如匯出），由 domain 自己的 aggregate 記錄狀態（例如 `ExportJob` 的 `pending`／`running`／`done`／`failed`），和排入工作在同一個 transaction 中建立。

**migration**：PgQueuer 的資料表放進 kernel 的 Alembic branch（第 7.2 節），由 kernel 隨版本提供，不使用 PgQueuer 自己的安裝和升級指令直接改資料庫，所有 schema 變更都經過 Alembic。

**observability**：worker 的 metrics 和 MQ consumer 相同（第 12.2 節）：排入數（`fast_ddd.task.enqueued`，commit 後才計數，rollback 的不算）、處理數、耗時、重試數、失敗數（同一個 histogram `fast_ddd.task.duration`，依 `task` 和 `outcome`：`success`／`retried`／`failed`）。health check 檢查 DB 連線和 worker 的執行迴圈。

**測試**：單元測試用 PgQueuer 的 in-memory adapter；整合測試用 testcontainers 的 PostgreSQL，涵蓋同一個 transaction 中 rollback 時工作不會被排入、重試和失敗、重複執行的冪等性、cron 不重複觸發。

## 12. 可觀測性與執行環境

### 12.1 Tracing

原版的 `Tracer` 自己產生 UUID 格式的 `trace_id` 和 `span_id`，加入 OpenTelemetry 後會變成兩套互不相通的 trace id。調整如下：

- `DomainEvent` 的 `trace_id` 沿用 OpenTelemetry 目前的 trace id（W3C 格式），domain_event 表上記錄的 trace id 可以直接在 tracing 系統中查到。
- 原版的 `span_id`／`parent_span_id` 實際上是在串連事件之間的因果關係，改名為 `event_id`／`parent_event_id`，避免和 OpenTelemetry 的 span 混淆。
- **傳遞方式改用 ContextVar**：原版 `UseCaseBase` 把 `_trace_id`、`_parent_event` 存成 instance 屬性，而 controller 是 module 層級的單一實例，並行請求會互相覆蓋；`_save_tracing` 處理完第一個 aggregate 就清掉 parent，批次中只有第一筆帶到 parent。改為：
  - `fast_ddd.context` 提供目前的 trace id 和 parent event id 兩個 ContextVar。trace id 由第 12.6 節的 middleware 從 OpenTelemetry 取得後設定，core 不 import OpenTelemetry。
  - `EventBus` 分派事件給 handler 時，把 parent event id 設為該事件的 `event_id`、organization context 設為事件的 `organization_id`（第 10.2 節），handler 結束後還原。
  - 新事件建立時，從 ContextVar 讀取 trace id 和 parent event id。同一個 handler 中產生的所有事件（包括批次中的每一筆）都帶到同一個 parent。
  - tracing 狀態全部在 `fast_ddd.context`，use case 是沒有可變狀態的一般類別（kernel 不提供 `UseCaseBase`），controller 和 use case 可以安全地作為單一實例共用。
- `X-Trace-Id` response header 回傳同一個 trace id（第 9.4 節）。
- MQ 訊息透過 message header 傳遞 W3C trace context，consumer 接續同一個 trace。由 FastStream 的 `RabbitTelemetryMiddleware`（`faststream.rabbit.opentelemetry`）負責，kernel 的 `create_broker(url)` 一律掛上它；背景工作的傳遞方式見第 11.1 節。
- **trace id 的來源順序**：訊息或工作帶來的 `trace-id` header → 目前的 OpenTelemetry span → 新產生（`resolve_trace_id()`）。發送端有 span 時，`trace-id` 和傳遞過來的 span 是同一個 trace id；沒有安裝 OpenTelemetry SDK 時，`trace-id` header 仍然讓 consumer 和 worker 沿用同一個 id。
- HTTP 的 span 和 metrics 由 `opentelemetry-instrumentation-fastapi` 產生（`install_kernel` 掛上，排除兩個 health endpoint）；它把自己的 middleware 放在最外層，符合第 12.6 節的順序。

### 12.2 Metrics

kernel 用 OpenTelemetry metrics 提供以下指標，服務不需要自己加：

| 範圍 | 指標 |
|---|---|
| HTTP | 請求數、耗時（依 route、method、status code） |
| DB | 連線池的使用中／閒置數和上限（`db.client.connection.count`、`db.client.connection.max`）、查詢耗時（`db.client.operation.duration`，失敗時帶 driver 的錯誤類別） |
| MQ consumer | 處理的訊息數、耗時（`fast_ddd.mq.consume.duration`，依 subscriber、結果：`success`／`skipped`／`requeued`／`dead_lettered`） |
| MQ publisher | 發送數、發送失敗數 |
| 背景工作 | 排入數、處理數、耗時、重試數、失敗數（依工作名稱） |
| 對外 HTTP | 呼叫數、耗時、失敗數（`http.client.request.duration`，依目標服務、method、status 或錯誤類別） |

- HTTP 的指標由 FastAPI instrumentation 提供（預設的 semantic conventions 下是 `http.server.duration`，route 以樣板記錄，例如 `/invoices/{invoice_id}`）；MQ publisher 的發送數和失敗數由 FastStream 的 telemetry middleware 提供。
- DB 的指標由 kernel 自己用 SQLAlchemy 的 engine event 產生（`create_engine` 自動掛上）。不使用 `opentelemetry-instrumentation-sqlalchemy`：它宣告只支援 `sqlalchemy<2.1`。SQLAlchemy 沒有公開「等待連線的數量」，連線池耗盡改以「使用中的連線數達到上限」判斷。
- 匯出方式由 `KernelSettings.telemetry_exporter`（`none`／`console`／`otlp`）決定，OTLP 的位址等設定沿用標準的 `OTEL_EXPORTER_OTLP_*` 環境變數。SDK 的 provider 一律安裝（`setup_telemetry()`），沒有 exporter 時 trace id 仍然存在並能傳遞。需要 Prometheus 時由 OpenTelemetry Collector 轉換，不在服務的 process 中開 scrape endpoint。

### 12.3 Log

- 結構化（JSON）log，每筆都帶 `trace_id`，以及有的話 `organization_id`、`user_id`。kernel 提供 `JsonFormatter` 和 `configure_logging(level)`（`KernelSettings.log_level`）；`logger.info(..., extra={...})` 的欄位會一併輸出。unit of work 之外的 log 用目前 span 的 trace id。
- 不記錄 token、密碼等敏感資料；500 錯誤的例外內容只寫進 log，不回傳給 client。

### 12.4 設定、health 與執行方式

- **設定**：pydantic-settings 從環境變數讀取（取代原版的 `config.py`），以 kernel 的 `load_settings(Settings)` 建立（直接呼叫 `Settings()` 時，pyright strict 會把必填欄位視為缺少的參數）。kernel 提供 `KernelSettings`，服務的 `app/settings.py` 繼承它並加上自己的欄位，由 `app/bootstrap.py` 組裝時使用；core 不讀設定（第 6.3 節）。
- **health**：
  - API：`GET /health/live`（process 存活即回 200）；`GET /health/ready` 只檢查 DB 連線，失敗回 503。不檢查 broker：RabbitMQ 短暫斷線時，寫入資料庫仍然會成功（第 11 節已接受訊息可能遺失），不該讓所有 API pod 被判定為未就緒。
  - MQ consumer：由 consumer process 自己的 health check 檢查 broker 連線。
  - 背景工作 worker：檢查 DB 連線和 worker 的執行迴圈。
- **API server**：uvicorn 單一 process（`uvicorn --factory app.main:create_app`），每個容器一個 process，由平台橫向擴展；不使用原版的 gunicorn + uvicorn worker。
- **MQ consumer**：`faststream run --factory app.consumer:create_app`，獨立 process。
- **背景工作 worker**：`python -m app.task_worker`，獨立 process（第 11.1 節）。
- **migration**：`fast-ddd-alembic upgrade heads`（第 7.2 節），在部署新版本前執行。
- **graceful shutdown**：收到終止訊號後，consumer 停止接收新訊息，在時限內處理完手上的訊息（未處理完的不 ack，交給 broker 重送）；API 停止接收新請求，等進行中的請求結束。這兩個時限都必須小於平台給的終止寬限時間（例如 Kubernetes 的 `terminationGracePeriodSeconds`），否則 process 會在處理到一半時被強制終止。

### 12.5 對外 HTTP client

`wire_resources` 建立的對外 HTTP client（第 6.3 節）一律由 kernel 的工廠 `create_http_client(service, *, base_url, timeout, retries=2, ...)` 建立（`timeout` 沒有預設值，必須明確指定），統一以下行為：

- 每個目標服務一個共用的 client（連線池），在關閉時釋放；
- 必須明確設定 timeout，沒有預設的無限等待；
- 只在連線層錯誤（連線失敗、逾時）時重試，而且只重試冪等的 method（GET、PUT、DELETE）；收到 HTTP 回應後不重試；
- 自動傳遞 W3C trace context；
- 記錄每次呼叫的 log 和 metrics（第 12.2 節），記錄前遮蔽個人資料和金鑰：log 只記 method、URL、status、耗時，不記 header 和 body；URL 去掉帳號密碼，名稱看起來是金鑰的 query 參數（含 `auth`、`token`、`password`、`secret`、`key`、`signature`、`session`）的值換成 `REDACTED`。

### 12.6 每個請求、每則訊息的 context

原版在 import 時就建立全域預設的 `SessionProvider` 和 publisher（`app/adapter/repository/base.py`、`app/package_instance.py`），HTTP middleware 再逐請求覆蓋（`app/middleware.py`）。新版不在 import 時建立任何預設值，ContextVar 沒有設定時直接報錯。

每個 unit of work（一個 HTTP 請求或一則 MQ 訊息）開始時設定下表的 context、結束時用 token 還原。HTTP 由 `fast_ddd_port` 的 unit-of-work middleware 負責；它只建立 context，不開啟 transaction，transaction 由 controller base、批次 runner 開啟（第 8.2 節）。MQ 由 subscriber wrapper（第 11 節）一併負責，不另外設一個 MQ middleware：解析訊息外層格式、`organizationId` 缺少時送進 DLQ、略過未宣告接受的全域事件、設定 context、inbox、transaction、ack 都在同一個元件中，避免兩個元件分工不清。

| 項目 | 來源 |
|---|---|
| `SessionProvider` | 新建一個，使用 `app/bootstrap.py` 注入的 session factory；內含空的 MQ 訊息暫存和儲存紀錄 |
| 使用者與 organization id | HTTP：middleware 驗證 JWT 後取得（第 10.3 節）；MQ：訊息的 `organizationId`，使用者為 consumer 的系統身分 |
| trace id | OpenTelemetry 目前的 trace id |
| parent event id | HTTP：無；MQ：訊息的 `eventId` |

- HTTP 用純 ASGI middleware 實作，不用 Starlette 的 `BaseHTTPMiddleware`，避免 ContextVar 在 middleware 和 endpoint 之間傳遞的問題。
- middleware 的順序（由外到內）：OpenTelemetry 的 instrumentation → CORS → unit-of-work middleware（含 JWT 驗證）→ router。OpenTelemetry 必須在最外層，unit-of-work middleware 讀取 trace id 時 span 才已經存在；CORS 必須在 JWT 驗證之外，preflight 的 `OPTIONS` 請求不帶 token。
- **unit-of-work middleware 負責 415、500 和 `X-Trace-Id`**：
  - 有 body 的請求，Content-Type 不是 `application/json` 時回 415（第 9.5 節）。
  - 它攔截所有未處理的例外，寫 log，自己產生 500 的 problem+json（`server.internal_error`）。不交給 FastAPI 的 `Exception` handler：實測（FastAPI 0.143、Starlette 1.8）`Exception` handler 由最外層的 `ServerErrorMiddleware` 執行，回應不會經過 CORS，500 沒有 `Access-Control-Allow-Origin`，瀏覽器會擋下回應，前端讀不到 `traceId`。
  - 它在每個回應（包括 401、500）加上 `X-Trace-Id`。
  - `DomainError`、驗證錯誤等已知例外仍由 FastAPI 的 exception handler 轉成 problem+json，這些 handler 在 middleware 內層執行，回應會經過 CORS。
- MQ 的 subscriber wrapper 以 FastStream 的 `BaseMiddleware`（`consume_scope`）或 subscriber decorator 實作，搭配 `AckPolicy.MANUAL`（第 11 節）。FastStream 同時處理多則訊息時，每則訊息都有自己的 context，不會共用 session。

## 13. 型別、測試與品質檢查

- pyright strict；排除 `alembic/versions`。kernel 附 `py.typed`。不允許用 `# type: ignore` 繞過檢查：`enableTypeIgnoreComments: false`、`reportUnnecessaryTypeIgnoreComment: error`。
- ruff（format 和 lint，lint 含 `DTZ`、`TID251`）、import-linter 和 contract 涵蓋檢查（第 6.2 節）、pytest。
- pytest：`filterwarnings = error`，warning 一律視為錯誤，第三方套件的 warning 以範圍明確的例外排除；需要外部工具的測試在 CI 中不可以被略過（缺少工具時失敗，而不是 skip）。
- coverage：template 預設 `fail_under = 80`，各服務可以調高，不可以調低。設定 `concurrency = greenlet, thread`：SQLAlchemy 的 asyncio 層以 greenlet 切換執行，不設定時 DB await 之後的程式碼不會被記錄（實測 router 和 use case 的程式碼明明有執行，卻顯示未涵蓋）。
- 測試資料庫一律以 Alembic migration 建立（不用 `metadata.create_all`），migration 本身也會被測到；測試之間以 rollback 或 truncate 隔離。
- **migration 的檢查**：CI 確認 Alembic 只有一個 head（kernel 的 branch 和服務的 branch 各一個，第 7.2 節），並執行 `alembic check`，確認 ORM model 沒有尚未產生的 migration。`env.py` 開啟 `compare_type` 和 `compare_server_default`；migration 檔名加上日期前綴（`file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s`），依檔名就能看出順序。
- **pre-commit**：template 提供 `.pre-commit-config.yaml`，安裝 `pre-commit` 和 `commit-msg` 兩種 hook：
  - commit 前：ruff format、ruff lint、pyright、import-linter 和 contract 涵蓋檢查、`uv lock --check`、trailing whitespace、檔案結尾換行、大型檔案檢查；
  - commit message：Conventional Commits 格式（`conventional-pre-commit`）。
- 在 CI 和 skill 中統一成一個 `make check`（包含上述所有檢查和測試）：skill 的完成條件就是 `make check` 全部通過。pre-commit 只是提早發現問題，CI 的 `make check` 才是最終關卡。
- **每個 aggregate 至少要有的測試**（skill 產生程式碼時一併產生；沒有測試時 `make check` 一樣會過，所以必須明確規定）：

| 類別 | 內容 |
|---|---|
| domain 單元測試 | 每個 domain 方法的成功路徑；每個不變條件被違反時丟出對應的 `DomainError`；有 `status` 時，每個狀態轉換的允許與拒絕 |
| repository 整合測試（testcontainers PostgreSQL） | mapping 往返一致（包括子集合）；只修改子 entity 時 `version` 仍然遞增；tenant 過濾（其他組織的資料讀不到）；`load_many` 的鎖定順序；`version` 和 `updated_at` 的更新與寫回 |
| API 測試 | 第 9.5 節表中適用的每個 status code 和錯誤代碼；BOLA（存取其他組織的資料回 404）；ETag（缺少回 428、不符回 412、格式不接受回 400、404 優先於 412）；Content-Type 不是 JSON 時回 415；PATCH 的 `null` 和巢狀 value object 語意；有批次操作時，207 的逐筆結果 |
| MQ consumer 測試（有 subscriber 時） | payload 驗證失敗和缺少 `organizationId` 時送進 DLQ；未知欄位被忽略；重複的 `eventId` 只處理一次；handler 寫入資料後丟出 `DomainError` 時，寫入和 inbox 都被 rollback |
| 背景工作測試（有 task handler 時） | 排入工作的 transaction rollback 時工作不會被排入；確定性錯誤不重試、暫時性錯誤重試後標記失敗；同一個工作執行兩次的結果相同 |
| 錯誤代碼目錄 | 第 9.6 節的格式、唯一性、訊息範本與 params 一致 |

## 14. Skill 設計

### 14.1 三個層次

DRF 預設只有 CRUD，因為它以資料為中心。DDD 的核心是 domain 行為，所以參考服務還必須示範 CRUD 以外的寫法；但這些寫法不該每個 aggregate 都產生。

| 層次 | 內容 | 決定方式 |
|---|---|---|
| 預設產生（每個 aggregate 都有） | list、get、create、PATCH、delete | 對應 DRF 的 `ModelViewSet`，不提供 PUT |
| 參考服務（每種寫法示範一次） | 加上一個 domain 指令（void）、一個批次操作（batch-void）、event handler、MQ consumer | skill 需要範本的寫法才放進來 |
| recipe（使用者要求時才加） | export、其他批次操作、archive 快照、operation history、批次 event handler、即時推播（第 14.3 節） | 寫在 `skills/fast-ddd/references/recipes/`，有需要才照著加 |

- **void 留在參考服務**：它示範了 CRUD 示範不到的 domain 指令寫法。domain 方法先檢查不變條件（已經作廢就丟出 `YourAggregateAlreadyVoided`，對應 409），再改變狀態、發出 `YourAggregateVoided` 事件。沒有這個範例，AI 新增業務操作時容易把狀態轉換寫成 PATCH 一個 `status` 欄位，等於把 domain 規則搬到 client 端。
- **業務狀態跟著 domain 指令一起出現**：DDD 沒有規定一組基本狀態。預設產生的 aggregate 只有第 7.5 節的技術欄位，沒有 `status` enum；原版的 `CREATED` 只代表「資料存在」，沒有業務意義。當使用者要求的第一個 domain 指令需要狀態轉換時，才一起加入 `status` enum、狀態轉換的檢查、對應的錯誤代碼和事件。參考服務的 void 示範了這個完整過程（`active` → `voided`）。
- **delete 和 void 的分工**：delete 的稽核紀錄由 domain_event 保留（開啟 archive 時再加上快照）。void 用在資料必須繼續出現在列表和查詢中、只是不能再使用的情境，例如發票號碼必須連續、法規要求保留作廢紀錄。
- **batch-void 當批次範例**：同時涵蓋 domain 指令和批次 I/O（第 8 節、第 9.4 節的 207），一個範例就能看到兩者怎麼組合。
- **export 改成 recipe**：它不示範任何新的架構寫法（只是在搜尋結果外面加一層格式轉換），又依賴 openpyxl，還有資源消耗的風險。

### 14.2 Skill 內容

- **`fast-ddd`**（主 skill，由 AI 自動觸發）：
  - 工作流程：新增 bounded context、aggregate（只產生預設 CRUD 和使用者明確要求的 domain 指令）、domain 指令、批次操作、event handler、MQ consumer。每個工作流程都要產生第 13 節規定的測試。
  - 透過 progressive disclosure 載入各層的 reference，並直接引用 `example/` 中的程式碼。
  - 規則：第 6 節的分層、第 7.3 節的時間處理、第 9.3 節的路由、第 9.5–9.6 節的 status code 和錯誤代碼、第 10 節的資安。
  - **決策紀錄**（從程式碼讀不出來的部分，重寫參考服務時逐條補上）：事件紀錄為什麼要存 tracing、什麼時候該開啟 archive、什麼時候用 event handler 而不是直接呼叫 use case、`SessionProvider` 巢狀使用的規則（只有最外層可以 commit／rollback）、批次 use case 的寫法、什麼時候該寫 domain 指令而不是 PATCH、409 和 422 怎麼區分、什麼時候 repository 可以宣告 `tenant_scope = "global"`、為什麼 `organization_id` 取自 aggregate 而不是 context。
  - 第一步先讀服務鎖定的 kernel 版本；低於 skill 支援的範圍時，要求先升級。
- **`fast-ddd-init`**（設 `disable-model-invocation: true`）：執行 copier 建立服務骨架。
- frontmatter 只用開放標準的欄位，只有 `fast-ddd-init` 例外。

### 14.3 即時推播 recipe 的設計規則

需要把變更即時推給前端時才加入。recipe 必須遵守以下規則：

- **技術**：Socket.IO（python-socketio），以 ASGI app 掛在 API 同一個 FastAPI app 的固定路徑下（例如 `/realtime`），不另開 process。多個 API 實例之間的推播分送使用 python-socketio 的 RabbitMQ manager（`AsyncAioPikaManager`），沿用既有的 RabbitMQ，不另外引入 Redis。
- **分層**：socket 的事件 handler 屬於 port 層（和 HTTP router 同層），一樣透過 controller 呼叫 use case。推播由 adapter 層的 publisher 發出，core 不知道推播的存在；要推播什麼，由 adapter 的 event handler 依 domain event 決定（和 MQ 訊息相同的做法，第 8.2 節）。
- **commit 之後才推播**：推播一律註冊為 `SessionProvider` 的 after-commit hook（第 8.2 節），rollback 時不會送出。
- **認證**：連線時必須驗證 JWT（和 HTTP 使用同一套驗證，第 10.3 節），沒有 token 或驗證失敗一律拒絕連線，不建立連線後再送錯誤事件。
- **tenant**：組織和使用者一律取自 token，不接受 client 在 query string 或事件內容中自行指定。
- **room**：`org:{organization_id}`、`user:{user_id}`，以及依資源而定的 room（例如 `your_aggregate:{id}`）。連線時自動加入自己的 org 和 user room；加入資源 room 前，必須先檢查權限（和 HTTP 相同的 `require()` 規則）。依使用者的 room 推播，重新連線後不需要重新訂閱也能收到。
- **不允許沒有對象的推播**：kernel 的 publisher 拒絕沒有指定 room 的推播，避免誤推給所有連線。
- **訊息格式**：推播內容和 HTTP 回應使用相同的 `ResponseModel`（camelCase、RFC 3339），並帶 `eventName` 和 `eventVersion`；需要回應的事件，ack 使用固定格式 `{"status": "ok" | "error", "data": …, "error": <problem+json>}`。
- **部署**：只允許 WebSocket transport（不使用 long-polling 備援），多實例時不需要 sticky session。
- **測試**：用真正的 Socket.IO client 連線測試認證拒絕、room 權限、commit 前不推播、rollback 不推播。

## 15. 實作階段

| 階段 | 內容 | 驗收條件 |
|---|---|---|
| Phase 1：kernel + 參考服務 | 依第 6.1 節建立 kernel 的三個套件：搬移 `ddd_base`、repository／controller base（含修正後的 `SessionProvider` 和 `savepoint()`）；新增 `fast_ddd.context`、`RequestModel`／`ResponseModel`／`MessageModel`、`Timestamp`、`DecimalStr`、`TypeDecorator`、事件序列化工具、`BatchResult` 和批次 runner、IntegrityError 和鎖定錯誤的轉換、`DomainError` 和錯誤代碼處理、錯誤代碼目錄、SQL 語句計數器、JWT 驗證、tenant 隔離、權限 dependency、CORS、health、HTTP 的 unit-of-work middleware、tracing 整合、MQ 的 subscriber wrapper（ack／DLQ 設定和 inbox）、`TaskQueue` 介面、PgQueuer 實作和 task wrapper、選擇性開啟的 archive、domain_event 的新欄位。`example/` 手寫一個完整的 bounded context（預設 CRUD、void、batch-void、event handler、MQ consumer），以及 `app/settings.py`、`app/bootstrap.py`、`app/wiring.py`、`app/main.py`、`app/consumer.py`、`app/task_worker.py`；參考 bounded context 加入一個由 event handler 排入的背景工作和一個 cron 排程 | `make check` 全部通過，包含 kernel 和 `example/` 的 import-linter contract；第 7.1 節的 contract test；第 8.3 節的往返次數、fallback、巢狀呼叫、`populate_existing`、`SessionProvider` 測試（使用 kernel 的測試用 aggregate）；500 回應帶有 CORS header 和 `X-Trace-Id` 的測試；第 9.3 節的路由測試；第 13 節規定的測試；kernel 的 archive 測試（預設不寫入快照，設定 `archive_model_class` 後才寫入）；並行測試（兩個請求同時執行時，事件的 trace id 和 parent event 不互相干擾）；CORS preflight 測試（POST、PATCH、DELETE）；第 11.1 節的背景工作測試，以及「透過 SQLAlchemy 的 asyncpg 連線在同一個 transaction 中排入工作」的實測 |
| Phase 2：copier template | 從 `example/` 抽出骨架，檔案分成兩種歸屬。**template 擁有**（服務不修改，recopy 比對的對象）：Dockerfile、`alembic.ini`、alembic 的 `env.py` 和 `script.py.mako`、`ruff.toml`、`pyrightconfig.json`、`.importlinter`、`pytest.ini`、`.coveragerc`、`.pre-commit-config.yaml`、Makefile、`app/bootstrap.py`、`app/main.py`、`app/consumer.py`、`app/task_worker.py`、`.claude/settings.json`（含第 3 節的 deny 清單）；工具設定放在獨立檔案、不放在 `pyproject.toml`，template 才能單獨擁有它們。**服務擁有**（只在第一次產生時建立，copier 的 `_skip_if_exists`，之後由服務維護，recopy 時不覆蓋）：`pyproject.toml`（服務自己的相依，例如 export recipe 加入的 openpyxl）、`app/settings.py`、`app/wiring.py`、`app/adapter/resources.py`、`app/adapter/repository/models.py`。`.importlinter` 用 `app.core.*` 表示所有 bounded context，`make error-catalog` 從 `app.wiring` 載入所有錯誤類別，兩者都不需要隨 bounded context 修改。（Phase 2 實測 `_skip_if_exists` 在 `recopy --overwrite` 下的行為） | 用 `copier copy --vcs-ref HEAD`（`kernel_source=path`，測試 repo 內的 kernel）產生的空服務能通過 `make check`；`copier update` 能套用 template 的更新；CI 對 `example/` 執行 `copier recopy --overwrite --defaults --vcs-ref HEAD` 後，骨架檔案沒有差異 |
| Phase 3：skill + marketplace | 撰寫 `fast-ddd` 和 `fast-ddd-init`、recipe（export、其他批次操作、archive 快照、operation history、批次 event handler、即時推播，和第 14.1 節的清單相同）、`marketplace.json`、`plugin.json` | `claude plugin validate` 通過；從本機 marketplace 載入後，在一個新服務中由 skill 產生一個新的 bounded context，產出能通過 `make check` |

## 16. 待決事項

目前沒有待決事項。

## 17. v1 不做的事

- 架構：transactional outbox 和 relay、DI container、domain_event 的 partition、批次 event handler（改為 recipe）、HTTP、MQ、背景工作以外的進入點（例如 CLI）。
- 錯誤代碼：在 OpenAPI 中逐一列出每個 endpoint 可能的錯誤代碼 enum、enum 驗證錯誤的可用值清單（`params.allowed`）。
- 發布：copier 的 broker 選項、kernel 發布到 PyPI、skill evals、`openapi.json` 快照。
- API：cursor 分頁、sparse fieldsets、通用 filter 語言、`POST .../search`、HTTP QUERY method（RFC 10008，框架和 proxy 的支援情況未驗證）、`Idempotency-Key` header、RateLimit headers（IETF draft 仍在進行中）、非同步匯出 job、後端在地化錯誤訊息（`Accept-Language`）、cookie 認證。

這些等實際有需要時再加。
