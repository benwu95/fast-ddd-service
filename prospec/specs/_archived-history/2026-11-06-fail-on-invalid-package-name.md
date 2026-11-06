# fail-on-invalid-package-name — Archive Summary

- **Archived**: 2026-11-06
- **Original Created**: 2026-11-06
- **Quality Grade**: A
- **Issue**: #15

## User Story

As a 以 template 建立服務並新增 package 的 Python 開發者（或代為操作的 coding agent），
I want `fast-ddd-check-packages` 在 root package 下名稱不是合法識別字、且本身或子孫目錄含 `.py` 的目錄出現時失敗並指出要改名，
So that import-linter 不會靜默略過該子樹，`make check` 能攔下其中的分層違規。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| kernel | Low | `fast_ddd_devtools.check_packages.find_problems` 對 `_directories_requiring_init` 結果中 `str.isidentifier()` 為 `False` 的目錄回報 `not a valid package name`，重用既有走訪與排除條件，symlink 以連結名稱判斷 |
| template | Low | `fast-ddd` skill 的 `rules/layering.md` 與 `workflows/bounded-context.md` 描述名稱規則與改名修法 |
| example | Low | `example/.agents/skills/fast-ddd/` 為 template skill 的 copier 產物，逐字同步 |

另同步 `docs/design.md` 的 contract 涵蓋檢查段落、`prospec/ai-knowledge/modules/kernel/devtools.md` Pitfalls，以及 `service-template.md` 的 Edge Case（原「目錄名稱不是合法識別字……不在此檢查範圍」改為新行為）。

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-KERNEL-010 | MODIFIED | 新增 bullet：上述範圍內名稱不是合法識別字的目錄，不論是否有 `__init__.py` 都以非零 exit 列出並標示 `not a valid package name`；同時缺 `__init__.py` 時兩則訊息都列出 |

## Completion

- **Tasks**: 6/6 code tasks（100%）；4 個 `[V]` 皆已勾選
- **Acceptance Criteria**: 4/4（凍結 baseline revision 1，未修訂）

## Review & Verify

- **Review**: 4 輪，累計 0 critical / 0 major / 1 minor。R1-01（test-quality）：名稱規則的文件行為缺少能區分 `directory.name.isidentifier()` 與相近替代判斷的測試；第 1～3 輪各發現同類一個剩餘實例（symlink 連結名稱、keyword／非 ASCII 識別字、只有連字號／數字開頭的負例），第 3 輪後改以類別涵蓋一次收斂：正例 `class`、`café`，負例涵蓋連字號、數字開頭、點、空白、其他標點，`resolve().name`、`keyword.iskeyword`、ASCII regex、`.stem` 與黑名單等 mutation 皆轉紅。第 4 輪 full-lens re-review 無發現。fix-induced ratio 各輪 0%。
- **Verify**: Grade A。Machine：1/5 task-completion PASS、4/5 knowledge WARN（plugin module 缺 `source_digest`，main 既有狀態）、5/5 tests PASS（root `make check` exit 0：kernel 357 passed、example 367 passed、template-check 一致）。Judgment（fresh-subagent）：2/5 delta-spec-compliance PASS（REQ-KERNEL-010 1/1，HEAD 實作下 9 個新測試失敗符合 SC-001，scenario_findings 空）、3/5 constitution PASS（7/7 規則）、6 design not-applicable。
- **Quality Log**: plan verifier WARN（US-1.3 排除情境與數字開頭名稱缺專屬測試、Risk 敘述不精確、SC-003 grep 對象未明列，皆於 plan 修正）；tasks verifier WARN（service-template Edge Case 追蹤敘述矛盾、T7 grep 路徑、task sizing）；review 4 輪皆 PASS；verify WARN 1 項（knowledge-health）。另：第一次 `--record-tests` 因 Docker daemon 未啟動、testcontainers 143 errors 而記錄為失敗，啟動 Docker 後重跑通過，非程式問題。

## Knowledge Update

Module documentation checked:
- `prospec/ai-knowledge/modules/kernel/devtools.md`（Pitfalls 已記錄名稱規則、連結名稱判斷與 keyword 不在範圍內）
- `prospec/ai-knowledge/modules/template/README.md`、`prospec/ai-knowledge/modules/example/README.md`（無需內容變更，已戳記）
