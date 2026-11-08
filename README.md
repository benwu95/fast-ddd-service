# fast-ddd-service

讓 coding agent 快速建立 Python 後端服務的框架：以已驗證過的 DDD + Event-Driven 架構作為起點，共用核心放在可安裝的 kernel，服務外層由 Copier 產生、交給各服務自行修改，服務內附的 `fast-ddd` skill 引導 agent 依固定的分層與測試規則擴充功能。

這套架構的原型來自 [benwu95/ddd-service-example](https://github.com/benwu95/ddd-service-example)，以及它用於序列化與對外格式的 [benwu95/dataclass-mixins](https://github.com/benwu95/dataclass-mixins)；搬移時保留與調整的部分見 [設計文件第 5 節](docs/design.md#5-架構搬移對照)。

每個產生的服務是獨立 repo，擁有自己的 lock、venv 與部署生命週期；同一服務的 API、MQ consumer、背景工作 worker 是三種執行角色，不是三個服務。

FastAPI、Pydantic v2、SQLAlchemy 2.1（async）、Alembic、PostgreSQL、FastStream（RabbitMQ）、PgQueuer、pendulum、OpenTelemetry；以 uv 管理套件，Python 3.13。品質工具為 ruff、Pyright strict、import-linter、pytest 與 testcontainers。版本與選型理由見 [設計文件第 4 節](docs/design.md#4-tech-stack)。

## Repo 結構

| 路徑 | 內容 |
|---|---|
| [`kernel/`](kernel/) | `fast-ddd-kernel` 套件：`fast_ddd`（core）、`fast_ddd_adapter`、`fast_ddd_port` 與開發工具 `fast_ddd_devtools`；交易、租戶隔離、事件分派、批次、訊息契約、背景工作與可選的即時推播（`realtime` extra） |
| [`template/`](template/) | Copier template：產生單一服務的骨架、工具設定、通用測試與服務內的 `fast-ddd` skill |
| [`example/`](example/) | 可執行的 billing 參考服務，由 template 產生後加入完整的 bounded context；CI 實際執行它的測試，skill 的參考程式碼由它產生 |
| [`skills/fast-ddd-init/`](skills/fast-ddd-init/SKILL.md) | 建立服務用的 plugin skill，只能由使用者手動呼叫 |
| [`.claude-plugin/`](.claude-plugin/)、[`plugin.json`](plugin.json) | Claude Code、Codex CLI 與 Antigravity CLI 共用的 plugin manifest；repo 根目錄就是 plugin |
| [`scripts/`](scripts/) | 框架的檢查工具：template 漂移、skill 參考副本、版本一致性 |
| [`docs/`](docs/) | 設計文件與框架維護指引 |

## 建立服務

1. 在使用者層級安裝 plugin，再於 agent 中手動呼叫 `fast-ddd-init`；它以 plugin 版本對應的 git tag 執行 Copier。
2. 也可以直接執行 Copier。安裝指令、建立服務、lock 與環境、三種角色的執行方式都在 [服務操作指引](template/docs/template-operations.md)，這份文件也會產生到每個服務的 `docs/template-operations.md`。
3. 在新服務中開啟 agent session，先依服務內 `fast-ddd` 的機密保護工作流程設定 host，再開始開發。

## 服務內的 fast-ddd skill

產生的服務在 `.agents/skills/fast-ddd/` 帶有主 skill（`.claude/skills` 是指向它的 symlink），版本隨 template 更新。skill 的第一步一律執行服務 Makefile 的 `kernel-version` target，確認 skill 與鎖定的 kernel 版本一致。

- **工作流程**：bounded context、aggregate（預設只產生 list、get、create、PATCH、delete）、domain 指令、批次操作、event handler、MQ consumer、背景工作與 cron、機密保護。
- **規則與決策紀錄**：分層、時間與序列化、API、資安、測試，以及程式碼讀不出來的設計理由。
- **Recipe**：非預設功能，只在使用者要求時才加入：匯出（有筆數上限）、其他批次操作、archive 快照、operation history、批次 event handler、即時推播、服務內跨 bounded context 的共用程式碼（`app/lib`）。

skill 的索引在 [`template/.agents/skills/fast-ddd/SKILL.md.jinja`](template/.agents/skills/fast-ddd/SKILL.md.jinja)。

## 開發與驗證

需要 uv、Python 3.13 與執行中的 Docker（整合測試使用 testcontainers）。

```sh
uv sync --frozen --all-packages --all-groups
make check
```

`make check` 依序執行框架工具檢查、`kernel/` 與 `example/` 各自的 `make check`，以及 `make template-check`（template 與 example 的漂移、skill 參考副本）。修改 template 或 skill 後以 `make template-references` 同步 example；新增或退役骨架檔案時執行 `make template-ownership`。細節見 [框架骨架維護](docs/template-operations.md)。

## 文件

- [設計文件](docs/design.md)：架構、分層、批次、API、資安、skill 與實作階段。
- [框架骨架維護](docs/template-operations.md)：template、example 與漂移檢查的維護方式。
- [服務操作指引](template/docs/template-operations.md)：安裝 plugin、建立與更新服務、migration、三種角色與容器。
- 授權：[MIT](LICENSE)。
