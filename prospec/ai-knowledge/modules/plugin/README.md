# Agent Plugin

> 以 Claude Code、Codex 與 agy 共用的 plugin 交付只能手動呼叫的 `fast-ddd-init`。
<!-- prospec:module-readme-format 2026-09-01 -->

<!-- prospec:auto-start -->

## Key Files

| File | Purpose |
|------|---------|
| `.claude-plugin/plugin.json` | Claude 的 plugin manifest |
| `.claude-plugin/marketplace.json` | Claude／Codex 共用的 marketplace（`fast-ddd`，source `./`） |
| `plugin.json` | Agent Plugins 1.0.0 manifest，Codex 與 agy 讀取 |
| `skills/fast-ddd-init/SKILL.md` | 以 git tag 建立服務的步驟 |
| `skills/fast-ddd-init/agents/openai.yaml` | Codex 關閉模型自動觸發 |
| `README.md` | repo（即 plugin）根目錄的介紹；安裝與建立服務的指令只連到 `template/docs/template-operations.md` |
| `example/tests/template/test_plugin_contract.py` | manifest、frontmatter、步驟規則與 README 連結／make target 的 contract test |

## Public API

- `fast-ddd@fast-ddd` — Claude 與 Codex 經 marketplace 安裝的 plugin id；agy 以 repo URL 安裝。指令列於 `template/docs/template-operations.md`。
- `fast-ddd-init` — 確認名稱與目的地後，以 `v<kernel_version>` tag 執行 `copier copy`。手動呼叫方式（2026-10-19 實測）：Claude 與 agy `/fast-ddd:fast-ddd-init`、Codex `$fast-ddd:fast-ddd-init`。

## Dependencies

**Depends on:** `template` — skill 以同一 repo 的 template 建立服務；SKILL.md 的版本與來源須等於 `copier.yml` 的 `kernel_version` 與 `kernel_git_url` 預設值。
**Used by:** 使用者層級安裝的三家 host；`example` 的 `tests/template/` 承載 contract test；不產生進服務。

## Modification Guide

1. 改建立步驟 → `SKILL.md` → 同步 `test_plugin_contract.py` 的 `INIT_SKILL_RULES`（每條對應一項建立流程的保證：來源與版本、確認、停止條件、answers 核對與交接；交接第 3 點以完整句子鎖定，指向服務內 `fast-ddd` 的機密保護工作流程）→ 三家端到端重驗。
2. 改版本 → 兩份 manifest、`copier.yml` 的 `kernel_version`、`kernel/pyproject.toml` 與 SKILL.md 的 Template version 一起改，`scripts/check_versions.py` 在 `make check` 強制一致；其餘版本字面值（`template/docs/template-operations.md` 範例、`example/tests/template/` 的 fixture tag 與斷言、`example/.copier-answers.yml`）不受此檢查，以 `grep -rn '0\.1\.0'` 逐一確認。發布的 git tag 必須是 `v<版本>`。
3. 改 copier／Python 版本 → `copier.yml` 的 `_min_copier_version` 或 `support.PYTHON_VERSION` 與 SKILL.md 指令同步，contract test 比對整段指令。
4. 新增 plugin 元件 → 只交付 skill；hooks、MCP、commands 不在範圍。

## Pitfalls

- frontmatter 只用 `name`、`description` 與 `disable-model-invocation: true`；Codex 忽略後者，靠 `agents/openai.yaml`；agy 的 `disable-slash-command` 作用相反。
- 不用 `${CLAUDE_PLUGIN_ROOT}`；Codex 與 agy 不展開。skill 不讀 plugin 內的檔案：agy 以 slash command 呼叫時模型取得不到 skill 目錄，而 repo checkout 與各 host 安裝目錄結構相同、無法可靠辨認，版本與來源因此寫在 SKILL.md。
- copier 來源用 git URL，不用 plugin 安裝目錄：快取依版本分目錄且會被刪，之後 `copier update` 會失敗。
- 整個 repo 是 plugin：根目錄的開發指引不隨 plugin 載入，validate 各留一則 warning（Claude 的 `CLAUDE.md`、agy 的 `AGENTS.md`）；根目錄 `README.md` 消除 Claude 的 `README_MISSING`，validate 另建議在 README 寫安裝指令，刻意不採用以免與操作指引重複；agy 的 `--strict` 因此失敗，驗收改用非 strict 並只容許這一項。
- repo 為 private：建立服務、marketplace add 與 kernel 相依都需要 git 的 HTTPS 認證。
- host sandbox 需要網路，並需能寫入 uv 的 cache／tools 與 Copier 的 git cache；被擋時請使用者核准，不改用其他來源。

<!-- prospec:auto-end -->

<!-- prospec:user-start -->
<!-- Add module-specific notes, detailed modification guides, and pitfalls here. This section is preserved on regeneration. -->
<!-- prospec:user-end -->
