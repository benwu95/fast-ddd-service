# 服務骨架操作指引

每個 microservice 使用獨立 repo。kernel 提供共用 DDD、adapter、port 與 devtools；產生的 bootstrap、entry points、wiring、工具設定與測試皆由服務擁有，可直接修改。hooks 與 Copier answers 是方便的起點，不限制客製化的位置。

## 安裝 fast-ddd plugin

`fast-ddd-init` 由 plugin 提供，在使用者層級安裝一次即可用於所有新服務。repo 為 private，先讓 Git 能以 HTTPS 認證存取（例如 `gh auth setup-git`）。

```sh
# Claude Code
claude plugin marketplace add benwu95/fast-ddd-service
claude plugin install fast-ddd@fast-ddd
# Codex CLI
codex plugin marketplace add benwu95/fast-ddd-service
codex plugin add fast-ddd@fast-ddd
# Antigravity CLI
agy plugin install https://github.com/benwu95/fast-ddd-service
```

手動呼叫 `fast-ddd-init` 時，它以 plugin 版本對應的 `v<kernel_version>` tag 作為 `--vcs-ref`，執行與下方相同的 `copier copy`。服務內的 `fast-ddd` skill 位於 `.agents/skills/`，`.claude/skills` 是指向它的 symlink；兩者屬 template 追蹤、服務可修改，隨 `copier update` 更新。

## 建立服務與環境

使用 Copier 9.19.1、uv 與 Python 3.13.12。Git 模式要求 `v<kernel_version>` tag 已存在；驗收使用的隔離 tag 不代表遠端已發布。template ref 與 kernel version 分開選擇，不使用 `_commit` 推導 kernel 版本。

```sh
TEMPLATE_REF=main
KERNEL_VERSION=0.1.0
uvx --python 3.13.12 --from copier==9.19.1 copier copy \
  --vcs-ref "$TEMPLATE_REF" --defaults \
  -d service_name=orders-service -d kernel_version="$KERNEL_VERSION" \
  https://github.com/benwu95/fast-ddd-service orders-service
cd orders-service
uv lock --python 3.13.12
uv sync --frozen --python 3.13.12
```

本機開發可改用 path。假設框架與新服務放在同一父目錄，從父目錄執行：

```sh
uvx --python 3.13.12 --from copier==9.19.1 copier copy \
  --vcs-ref HEAD --defaults -d service_name=orders-service \
  -d kernel_source=path -d kernel_path=../fast-ddd-service/kernel \
  ./fast-ddd-service ./orders-service
```

`kernel_path` 相對於產物的 `pyproject.toml`；path 模式仍使用自己的 lock 與 venv。workspace 模式供框架 `example/` 使用。生成不建立 lock、不執行 hooks、安裝或 DB migrations；lock 由服務產生並追蹤，真實機密以環境設定供應。

## Schema 與三角色

先準備 PostgreSQL、RabbitMQ，設定 `SERVICE_NAME`、`DATABASE_URL`、`RABBITMQ_URL` 與 `JWT`。JWT 可用 JSON 或 `JWT__*` 環境變數，必填 issuer、audience、jwks_url、user_id_claim、organization_id_claim、permissions_claim、permissions_format；claims 名稱須對應實際 issuer。DB URL 使用 `postgresql+asyncpg://...`。

```sh
uv run --frozen fast-ddd-alembic upgrade heads
uv run --frozen fast-ddd-alembic check
uv run --frozen uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8080
uv run --frozen faststream run --factory app.consumer:create_app --host 127.0.0.1 --port 8082
uv run --frozen python -m app.task_worker
```

三個 entry points 分別執行。API 與 worker 的 `/health/live`、`/health/ready` 成功為 200；consumer 只有 `/health/live`，MQ ping 成功為 204。worker 預設監聽 `127.0.0.1:8081`，以 `WORKER_HEALTH_HOST`、`WORKER_HEALTH_PORT`、`WORKER_HEALTH_TIMEOUT_SECONDS`、`WORKER_SHUTDOWN_TIMEOUT_SECONDS` 調整。SIGTERM 觸發有時限的 drain；health 不代表未完成工作已成功。

空服務沒有業務 subscriber、task、cron、HTTP route，也不需要 notification 設定。加入自己的 bounded context、設定與 wiring，不必加入假 handler 以啟動程序。

新增 ORM tables 後，在 `app/adapter/repository/models.py` 登錄或匯入，再建立第一個業務 revision：

```sh
make migration name="create orders"
uv run --frozen fast-ddd-alembic upgrade heads
uv run --frozen fast-ddd-alembic check
```

檢視產生的 revision；預設第一個業務 revision 接續 `service_0000`。`make migration` 已指定 `service@head` 與 `alembic/versions`，不要另造 service root。kernel 與 service 各保留一個 head。需要整個 service branch 升降版時，以 `downgrade service@base`、`upgrade heads` 操作；kernel branch 不因 service downgrade 消失。

`initialize_service_baseline` 預設 true，持久化後不因 kernel 來源改變而重算。接管已有 service branch 的 repo 時設 false；框架 example 使用 false。若自行改名或替換 baseline，亦須確認此答案，避免再次產生固定 baseline 檔。

## 品質與容器

```sh
make check
git init -b main
git add .
git commit -m "chore: initialize service"
uv run --frozen pre-commit install --install-hooks
uv run --frozen pre-commit run --all-files
```

`make check` 包含 lock、format、lint、strict typing、分層與 package 檢查、正式 migrations、tests 與 coverage。Docker 必須可用。`tests/runtime/` 自備通用 fixtures；在其他 test packages 擴充業務測試與服務專屬設定。coverage source 為完整 `app`，預設門檻 80，可用 `coverage_minimum` 提高至 100；提高門檻不保證目前 coverage 已達標，應補測試而非排除 runtime。

容器以 Git 模式的服務 lock 建置，不使用 host venv 或 sibling kernel：

```sh
docker build -t orders-service .
docker run --rm --env-file /path/to/runtime.env -p 127.0.0.1:8080:8080 orders-service
```

同一 image 可覆寫命令為 `faststream run --factory app.consumer:create_app --host 0.0.0.0 --port 8080` 或 `python -m app.task_worker`。worker 需設定 `WORKER_HEALTH_HOST=0.0.0.0`、`WORKER_HEALTH_PORT=8080`；DB／MQ URL 必須由容器可達。用 `docker stop --timeout 10` 停止，並核對 health 關閉與連線釋放；worker 正常為 0，API／consumer 可為 0 或 SIGTERM 的 143，不能只看返回碼。

## 可選的骨架更新

外層可任意修改，是否接受上游更新由服務維護者決定。先將當前服務內容存入 Git checkpoint，工作目錄保持乾淨；Copier 不負責保存未提交的修改。

```sh
git status --short
CHECKPOINT=$(git rev-parse HEAD)
TEMPLATE_REF=main
uvx --python 3.13.12 --from copier==9.19.1 copier update \
  --defaults --conflict inline --vcs-ref "$TEMPLATE_REF"
git diff --name-only --diff-filter=U
git diff --check
uv run --frozen pre-commit run check-merge-conflict --all-files
make check
```

Copier 可能在 exit 0 時留下衝突。必須檢視雙方內容、解決標記並 `git add`，確認 Git 沒有 unmerged paths，merge-conflict gate 與完整品質檢查皆通過後，才提交更新。runtime、工具與通用測試的修改由 Copier 合併；同一 hunk 的修改須由服務維護者處理。

僅初始化的檔案為 `pyproject.toml`、`app/settings.py`、`app/wiring.py`、`app/adapter/resources.py`、`app/adapter/repository/models.py`、`tests/conftest.py`、`tests/support.py` 與既有 `alembic/versions/*`。存在時保留服務內容；刪除後若該路徑仍由 template 產生，就按新預設重建。baseline 關閉時不重建固定 baseline；後續 revisions、業務檔與 lock 保留。一般追蹤檔刻意刪除後，合併更新保留刪除。接線新增 required Settings 時，同步擴充服務擁有的 root test fixtures。

template 退役的追蹤檔，update 會從服務刪除，即使服務修改過也不產生衝突。目前退役的檔案是 `.claude/settings.json`（Phase 2 產生的服務才有）。更新後以 `git status --short` 檢查 `D` 狀態；要保留時執行 `git restore --source "$CHECKPOINT" --staged --worktree -- .claude/settings.json`。

`.claude/skills` 由 template 產生為 symlink。若服務已有同名的實體目錄，update 會失敗；更新前先把其中的 skill 移到 `.agents/skills/`，刪除該目錄並提交，再執行 update。

template 更新不等於 kernel 已升級。保留自己的相依，手動修改 `pyproject.toml` 的 kernel Git tag 或 path，執行 `uv lock --upgrade-package fast-ddd-kernel`、`uv sync --frozen`、完整 `make check` 並檢視 lock diff。若更新 `kernel_version` 答案，同次明確傳入 `-d kernel_version=...`；答案改變不會替你改寫相依或 lock。

更新失敗時先檢視 `git diff "$CHECKPOINT"`。要恢復該 checkpoint 的追蹤檔，可執行 `git restore --source "$CHECKPOINT" --staged --worktree -- .`；再用 `git status --short` 檢視未追蹤檔，只移除本次生成且確定不要的項目。Git 復原不會復原資料庫；Copier 本身不會執行 migrations。

`recopy --overwrite` 會覆掉追蹤檔的客製化，只用於框架 canonical example 同步或隔離驗收。下游一般升級使用上述 `update`；框架的 template／example drift gate 不適用於下游客製化服務。
