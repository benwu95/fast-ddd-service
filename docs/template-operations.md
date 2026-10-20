# 框架骨架維護

服務建立、客製化、更新、migration 與三角色操作見 [canonical 服務操作指引](../template/docs/template-operations.md)。該文件由 Copier 一併產生到服務的 `docs/template-operations.md`。

框架 repo 保留 kernel／example workspace；每個下游 microservice 使用獨立 repo。修改共通起始實作時，編輯 `template/`，再以 generator 同步 `example/`，不手工維護兩份副本。

```sh
uv sync --frozen --all-packages --all-groups
make check
make template-check
```

root `make check` 包含 tooling、kernel、example 與隔離 snapshot drift；example suite 執行 Git／path 產物、更新／衝突、分發、三角色及 Linux 容器驗收。`make template-check` 包含目前未提交、未忽略的修改，原工作目錄不被 recopy。直接執行 checker 而不帶 `--snapshot` 則要求乾淨工作目錄。

snapshot 會將來源 repo 內的 symlink 重新定位到副本內；來源外連結與逃離副本的連結會被拒絕。直接 checker 也拒絕解析至 repo 外的 `example`。

`scripts/template-ownership.json` 記錄框架曾產生的受管檔案路徑。checker 以 Copier 的空目錄渲染取得目前集合，並由同一 Copier skip matcher 排除初始化檔；新受管路徑未登錄，或退役檔案仍留在 example，CI 都會失敗。業務新增檔與初始化內容保留。清單只留在框架 repo，不產生到下游服務。

新增或退役骨架檔案時執行 `make template-ownership`，檢視清單與 example 的同步差異，再執行 `make check`。此命令對目前 working tree 建隔離 snapshot，只以原子 replace 更新清單；歷史路徑永久保留，不能因來源刪檔而刪除紀錄。退役副本由維護者確認後移除；一般 check／CI 不更新清單、不自動刪檔。

服務內 `fast-ddd` skill 的參考程式碼副本（`template/.agents/skills/fast-ddd/references/example/`）由 `scripts/check_template.py` 的 `REFERENCE_SOURCES` 清單從 example 產生。template-check 比對副本與來源：副本過期、多出清單外的檔案、來源已刪除或清單項目找不到時都會失敗。修改清單內的 example 檔案或清單本身後，執行 `make template-references`：它在暫存目錄產生副本並整批替換、移除 example 內的舊副本後 recopy，再登記 ownership，不必另外執行 recopy 或 `make template-ownership`。它和手動 recopy 一樣會覆寫 example 中 template 追蹤檔的未提交修改，執行前先保存並檢視；中途失敗時重跑同一指令即可。

若刻意同步 example，先保存並檢視其既有修改，再從 `example/` 執行 `uv run --frozen copier recopy --overwrite --defaults --vcs-ref HEAD` 並檢視 diff；它是有意的覆寫操作。answers 固定 `_src_path: ..`、`kernel_source: workspace`、`initialize_service_baseline: false`。服務初始化檔與既有 billing／notification／migrations 保留；業務內容繼續在 example 自行維護。

驗收 Git server 僅綁 `127.0.0.1`，host 與 builder 共用 `host.docker.internal` URL；host 暫時以 [Git curloptResolve](https://git-scm.com/docs/git-config/2.46.1.html#Documentation/git-config.txt-httpcurloptResolve) 解析到 loopback。Mac 使用 Docker Desktop 的 host 路由，Linux builder 使用 host network；不修改 lock 的來源，不修改系統 hosts／Git config，fixtures 結束即關閉 server。
