# Service Template

> 以 Copier 產生可客製化的單服務 repo，驗證更新與框架 example 漂移。
<!-- prospec:module-readme-format 2026-09-01 -->

<!-- prospec:auto-start -->

## Key Files

| File | Purpose |
|------|---------|
| `copier.yml` | 來源、初始化保護與持久化答案 |
| `template/` | 三角色、工具與通用測試起始實作 |
| `scripts/check_template.py` | snapshot 與唯一漂移判定 |
| `scripts/template-ownership.json` | 框架歷史受管路徑，保留退役偵測 |
| `example/tests/template/` | 分發、更新、程序與容器驗收 |
| `docs/template-operations.md` | 框架維護與服務操作入口 |

## Public API

- `copier copy`／`update` — 建立服務與合併可選更新。
- `main(argv)`、`snapshot_repository(source, destination)` — 框架 drift CLI 與隔離輸入。
- `make template-check` — 含未提交修改的隔離漂移檢查。
- `make template-ownership` — 原子更新歷史受管路徑聯集，不同步或刪除 example。

## Dependencies

**Depends on:** `kernel` 提供安裝套件；Copier、uv、Git、Docker 提供驗收環境。
**Used by:** `example` 的生成與框架品質檢查；下游服務自行持有產物。

## Modification Guide

1. 改外層預設 → `template/` → generator 同步 example → root `make check`。
2. 改初始化規則 → copier.yml → 兩版更新／刪除重建／migration tests。
3. 改 runtime 測試 → `template/tests/runtime/`；維持舊 cases 的 `runtime_cases.json` 對照。
4. 改 drift → checker／snapshot owner → committed 差異、退役路徑與 dirty refusal 分別驗證；新增／退役骨架先更新 ownership 清單。
5. 改驗收環境 → `support.PYTHON_VERSION` 與共享 fixtures → Git／path／容器回歸。


## Pitfalls

- 外層皆可修改；下游用 update 合併，recopy 覆寫只用於框架同步／隔離驗收。
- example answers 使用 `..`、workspace、baseline=false；baseline 不由來源重算。
- 僅初始化路徑刪除後可能重建；kernel 升級須手動改相依與 lock。
- Copier exit 0 仍可能有衝突；Git unmerged、merge-conflict gate 與完整品質皆須通過。
- HTTP Git 僅綁 loopback；host／Linux builder 沿用同一 URL 與 lock，finally 清理。
- snapshot 將內部 symlink 重定位到副本；來源外連結、逃離副本或 repo 的 example 連結皆拒絕。
- 清單只供框架使用，永久保留歷史；Copier 的 skip matcher 排除初始化檔，CI 不更新清單或自動刪檔。
- 通用測試不依賴 root 業務 helpers；驗收測試不進子服務，避免遞迴。

<!-- prospec:auto-end -->

<!-- prospec:user-start -->
<!-- Add module-specific notes, detailed modification guides, and pitfalls here. This section is preserved on regeneration. -->
<!-- prospec:user-end -->
