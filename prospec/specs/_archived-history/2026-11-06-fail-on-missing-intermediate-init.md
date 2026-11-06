# fail-on-missing-intermediate-init — Archive Summary

- **Archived**: 2026-11-06
- **Original Created**: 2026-11-06
- **Quality Grade**: A
- **Issue**: #12

## User Story

As a 以 template 建立服務並新增 package 的 Python 開發者（或代為操作的 coding agent），
I want `fast-ddd-check-packages` 在 root package 下任一目錄本身或子孫目錄含 `.py` 卻缺少 `__init__.py` 時失敗並列出該目錄，
So that import-linter 不會靜默略過子樹，`make check` 能攔下其中的分層違規。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| kernel | Medium | `fast_ddd_devtools.check_packages` 改以含 `.py` 的目錄及其祖先推導 marker 要求，跟隨 symlink 目錄並剪除迴圈，無法讀取的目錄拋錯 |
| template | Low | `fast-ddd` skill 的 `rules/layering.md` 與四份 workflow 改為描述新行為，移除手動 `find` 補檢 |
| example | Low | `example/.agents/skills/fast-ddd/` 為 template skill 的 copier 產物，逐字同步 |

另同步 `docs/design.md` 的 contract 涵蓋檢查段落、`prospec/ai-knowledge/modules/kernel/devtools.md` Pitfalls，以及 `service-template.md` 的 Edge Case。

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-KERNEL-010 | MODIFIED | 新增 bullet：root package 下本身或子孫目錄含 `.py` 卻缺 `__init__.py` 的目錄逐一列出並以非零 exit 結束；`__pycache__`、`.` 開頭目錄與無 `.py` 子樹不要求 |

## Completion

- **Tasks**: 7/7 code tasks（100%）；4 個 `[V]` 皆已勾選
- **Acceptance Criteria**: 4/4（凍結 baseline revision 1，未修訂）

## Review & Verify

- **Review**: 6 輪（5 輪 + 一次 break-glass 授權輪），累計 1 critical / 0 major / 8 minor。R1-01（critical）：`rglob("*.py")` 不進入 symlink 目錄，與 grimp 的 `os.walk(followlinks=True)` 不一致，改以 `Path.walk(follow_symlinks=True)` 加實際路徑祖先鏈修正並以 regression pin 釘住。R2-03 類（walk 期間吞掉 filesystem 錯誤）在第 3、4 輪連續由修正引入新邊界，觸發 fix-induced circuit breaker；開發者選擇 revert `_stat_symlinks`，保留 `on_error=_raise`，「root package 第二層以下、目標無法 stat 的 symlink 子樹略過」列為已知限制（grimp 同樣略過）。R2-01（非識別字目錄名稱被 grimp 略過）為 HEAD 既有行為，列為範圍外的後續 issue 候選；R4-02 隨 revert 失效。最後一輪 review-clean。
- **Verify**: Grade A。Machine：1/5 task-completion PASS、4/5 knowledge WARN（plugin module 缺 `source_digest`，main 既有狀態）、5/5 tests PASS（root `make check` exit 0：kernel 345 passed、example 367 passed、template-check 一致）。Judgment（fresh-subagent）：2/5 delta-spec-compliance PASS（REQ-KERNEL-010 1/1，scenario_findings 空）、3/5 constitution PASS（7/7 規則）、6 design not-applicable。
- **Quality Log**: plan 第 1 輪 verifier FLAWS（漏列 example skill 副本、`rules/layering.md`、`docs/design.md` 與 SC-003 grep 涵蓋不足），修訂後 WARN；tasks verifier WARN（`[M]` 標記誤用、`knowledge verify` 缺參數、task sizing）；review 兩次 `fix_induced_threshold_exceeded` escalation，第一次 revert-and-redesign、第二次以開發者理由 break-glass；verify WARN 1 項（knowledge-health）。

## Knowledge Update

Module documentation checked:
- `prospec/ai-knowledge/modules/kernel/devtools.md`（Pitfalls 已記錄新判斷規則與已知限制）
- `prospec/ai-knowledge/modules/template/README.md`、`prospec/ai-knowledge/modules/example/README.md`（無需內容變更，已戳記）

<!-- prospec:escalation-history -->
## Escalation History

Lifetime events: 2. Overrides: 1. Completeness: legacy-partial.

| Ordinal | Station | Trigger | Event | State |
|---|---|---|---|---|
| 1 | prospec-review | fix_induced_threshold_exceeded | review:4 | not pending |
| 2 | prospec-review | fix_induced_threshold_exceeded | review:5 | not pending |

| Event | Station | Reason | Usage |
|---|---|---|---|
| review:5 | prospec-review | review 已達 5 輪上限，第 2 到第 5 輪皆 0 critical，比例觸發來自 minor 文件與測試補強，程式已 revert 至穩定版本且測試全綠 | consumed by prospec-review:a4aece1a872b4f5a2d3e329d8fe03c9f41aff149c4771f109a28adbb4cbbc2ea |
<!-- prospec:escalation-history-end -->
