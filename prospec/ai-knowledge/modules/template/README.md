# Service Template

> 以 Copier 產生可客製化的單服務 repo，驗證更新與框架 example 漂移。
<!-- prospec:module-readme-format 2026-09-01 -->

<!-- prospec:auto-start -->

## Key Files

| File | Purpose |
|------|---------|
| `copier.yml` | 來源、初始化保護與持久化答案；`kernel_version` 設 `when: false`，隨 template revision 渲染、不寫入 answers |
| `template/` | 三角色、工具與通用測試起始實作 |
| `scripts/check_template.py` | snapshot 與唯一漂移判定；`REFERENCE_SOURCES` 定義 skill 參考副本的固定清單並比對副本 |
| `scripts/template-ownership.json` | 框架歷史受管路徑，保留退役偵測 |
| `scripts/check_versions.py` | plugin manifest、SKILL.md、template、kernel 五個版本來源一致性 |
| `template/.agents/skills/` | 服務內 skill（目前為 `fast-ddd/`）；`template/.claude/skills` 是指向整個 `../.agents/skills` 的 symlink |
| `template/.agents/skills/fast-ddd/` | SKILL.md 索引、`references/` 的 workflows、rules 與 decisions、由 example 產生的 `references/example/` 副本，以及 `scripts/check_kernel_version.py` |
| `template/.agents/skills/fast-ddd/references/recipes/` | 七份非預設功能 recipe，SKILL.md 的 Recipes 表索引 |
| `example/tests/template/` | 分發、更新、程序與容器驗收 |
| `docs/template-operations.md` | 框架維護與服務操作入口 |

## Public API

- `copier copy`／`update` — 建立服務與合併可選更新。
- `main(argv)`、`snapshot_repository(source, destination)` — 框架 drift CLI 與隔離輸入。
- `make template-check` — 含未提交修改的隔離漂移檢查，含 skill 參考副本與 example 的比對。
- `make template-references`（`--sync-references`）— 產生參考副本、移除 example 舊副本後 recopy，再登記 ownership；等同 recopy 覆寫。
- 服務的 `make kernel-version` — `check_kernel_version.py` 比對 SKILL.md 的 `Kernel version`／`Kernel lock` 與 lock；失敗訊息有固定前綴並列出兩邊的值，是服務 `make check` 的第一步。
- `make template-ownership` — 原子更新歷史受管路徑聯集，不同步或刪除 example。
- `read_versions(root)`、`main(argv)`（`check_versions`）— 回傳各來源版本與錯誤；`make check` 的 `tooling` 呼叫。

## Dependencies

**Depends on:** `kernel` 提供安裝套件；Copier、uv、Git、Docker 提供驗收環境。
**Used by:** `example` 的生成與框架品質檢查；`plugin` 的 SKILL.md 記載與 `copier.yml` 預設值一致的版本與來源；下游服務自行持有產物。
`scripts/check_versions.py` 讀 plugin 的兩份 manifest 與 SKILL.md 只為比對版本，屬框架工具檢查，不列為 module 相依（避免與 `plugin → template` 形成循環）。`scripts/check_template.py` 讀 example 的參考清單檔案只為產生與比對副本，同樣不列為 module 相依。

## Modification Guide

1. 改外層預設 → `template/` → generator 同步 example → root `make check`。
2. 改初始化規則 → copier.yml → 兩版更新／刪除重建／migration tests。
3. 改 runtime 測試 → `template/tests/runtime/`；維持舊 cases 的 `runtime_cases.json` 對照。
4. 改 drift → checker／snapshot owner → committed 差異、退役路徑與 dirty refusal 分別驗證；新增／退役骨架先更新 ownership 清單。
5. 改驗收環境 → `support.PYTHON_VERSION` 與共享 fixtures → Git／path／容器回歸。
6. 改服務 skill → `template/.agents/skills/` → `make template-references`（同步副本、recopy example、ownership）→ `test_service_skill_contract.py` 的結構與引用檢查；symlink 由 `_preserve_symlinks` 保留。answers 的 `_commit` 變動不提交。
7. 改 recipe → 只引用參考副本已有的測試名稱，kernel 呼叫寫出所屬模組；改 `.importlinter` 時同步 `app-lib.md` 的 diff。
8. 改版本檢查 → `check_kernel_version.py` → `test_kernel_version_check.py`（含經 `make` 執行與非 UTF-8 locale）；腳本不在服務 lint 範圍，由根目錄 `tooling` 明確傳入 ruff 與 pyright。


## Pitfalls

- 外層皆可修改；下游用 update 合併，recopy 覆寫只用於框架同步／隔離驗收。
- example answers 使用 `..`、workspace、baseline=false；baseline 不由來源重算。
- 僅初始化路徑刪除後可能重建；kernel 升級須手動改相依與 lock。
- Copier exit 0 仍可能有衝突；Git unmerged、merge-conflict gate 與完整品質皆須通過。
- HTTP Git 僅綁 loopback；host／Linux builder 沿用同一 URL 與 lock，finally 清理。
- snapshot 將內部 symlink 重定位到副本；來源外連結、逃離副本或 repo 的 example 連結皆拒絕。
- 清單只供框架使用，永久保留歷史；Copier 的 skip matcher 排除初始化檔，CI 不更新清單或自動刪檔。
- 通用測試不依賴 root 業務 helpers；驗收測試不進子服務，避免遞迴。
- Copier 9.19.1 update 會刪除 template 退役的追蹤檔，服務修改過也無衝突（如 `.claude/settings.json`）；服務已有實體 `.claude/skills` 目錄時 update 失敗。
- 複製產物做 update 測試時保留 symlink（`copytree(symlinks=True)`），否則 `.claude/skills` 被展開成目錄。
- `make` 在 recipe 失敗時一律 exit 2，skill 以失敗訊息前綴判斷版本不一致；`-d kernel_version` 覆寫只供框架測試，服務以覆寫值建立後 update 會在 SKILL.md 產生衝突。
- template 的 `ruff.toml` 排除 `.agents`；參考副本不進服務的 ruff、pyright、pytest、coverage 與 import-linter。

<!-- prospec:auto-end -->

<!-- prospec:user-start -->
<!-- Add module-specific notes, detailed modification guides, and pitfalls here. This section is preserved on regeneration. -->
<!-- prospec:user-end -->
