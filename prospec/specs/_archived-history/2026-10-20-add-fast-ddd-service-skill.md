# add-fast-ddd-service-skill — Archive Summary

- **Archived**: 2026-10-20
- **Original Created**: 2026-10-20T05:10:31.039Z
- **Quality Grade**: A
- **Issue**: #6
- **Plan Decision**: hybrid (graded_by: in-session)

## User Story

作為以 agent 開發服務的後端開發者，我要在服務 repo 中依 `fast-ddd` 的工作流程新增 bounded context、aggregate、domain 指令、批次操作、event handler、MQ consumer、背景工作與 cron，以便產出符合分層與第 13 節測試要求，且 `make check` 通過；版本不一致時 skill 與品質檢查都停止，參考程式碼副本與 example 保持一致，機密保護由 skill 引導使用者層級設定。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| template | High | `kernel_version` 不持久化；`check_kernel_version.py` 與 `make kernel-version`；skill 的 SKILL.md、workflows、rules、decisions；`check_template.py` 的參考副本清單、比對與 `--sync-references`；`ruff.toml` 排除 `.agents` |
| example | Medium | recopy 同步 skill 與副本、answers 移除 `kernel_version`；`tests/template/` 新增版本檢查與 skill contract 測試，改寫 update、drift、configuration 等測試 |
| plugin | Low | `fast-ddd-init` 交接步驟指向服務內的機密保護工作流程 |

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-TEMPLATE-009 | ADDED | 服務的 kernel 版本檢查 |
| REQ-TEMPLATE-010 | ADDED | skill 內的參考程式碼副本 |
| REQ-TEMPLATE-011 | ADDED | skill 的工作流程與規則 |
| REQ-TEMPLATE-012 | ADDED | 機密保護設定工作流程 |
| REQ-TEMPLATE-001 | MODIFIED | 可獨立驗收的空服務產生（範例業務限定於 `app/`、`tests/`、`alembic/`） |
| REQ-TEMPLATE-008 | MODIFIED | skill 對應的 kernel 版本隨 template revision 更新 |
| REQ-PLUGIN-002 | MODIFIED | 交接步驟指向服務內 `fast-ddd` 的機密保護工作流程 |

## Completion

- **Tasks**: 26/26 code tasks（100%）；[V] T28 完成；[M] T29（三家 host 端到端）未執行，依使用者決定延後，於 PR 標示待辦。
- **Acceptance Criteria**: 7/7 REQ 的自動化部分成立；REQ-TEMPLATE-009 與 011 的三家 host 手動部分（US-1.4、US-3.4）未驗收。

## Review & Verify

- **Review**: 5 輪（第 1 個 loop 4 輪、第 2 個 loop 1 輪），5 critical／6 major／7 minor。critical 為 skill 以 make 的 exit code 判斷版本不一致（C-1）、失敗訊息未列兩邊版本（C-3）、機密探測會印出值（S-1）、允許在 repo 建 `.env`（S-2）、操作文件宣稱覆寫版本會在 update 還原（C-2），皆經獨立 verifier 確認並以 fail-then-pass 測試鎖定。round 3 後全面掃描同類問題，修正 61 處 skill 與 design 文件的事實錯誤。未解：minor R5-1（archive 快照不含子資料表，`decisions.md:23` 與 design.md 第 7.5 節說法不精確），以 advisory 帶出。
- **Verify**: Grade A；task-completion、knowledge、tests 為 PASS（`make check` exit 0：kernel 333、example 367 passed，template-check 無漂移）；delta-spec-compliance WARN（T29 未執行）；constitution PASS；design not-applicable。
- **Quality Log**: new-story INVEST WARN 3 則；plan verifier WARN 2 輪與收斂規則 WARN；tasks verifier FAIL→WARN；review 各輪 WARN、fix-induced breaker 兩次並以使用者 break-glass 繼續；prospec-delegation WARN（round 3 ticket 因 `.prospec.yaml` 修改，經使用者同意以目前工作樹結束）；verify WARN 1 則（T29）。另有兩筆過早寫入的 review round-close 紀錄（round 3 merge 前、round 4 escalation 後），後續已以正確 merge 與 round 5 的 baseline 取代。

<!-- prospec:escalation-history -->
## Escalation History

Lifetime events: 2. Overrides: 2. Completeness: complete.

| Ordinal | Station | Trigger | Event | State |
|---|---|---|---|---|
| 1 | prospec-review | fix_induced_threshold_exceeded | review:3 | not pending |
| 2 | prospec-review | fix_induced_threshold_exceeded | review:4 | not pending |

| Event | Station | Reason | Usage |
|---|---|---|---|
| review:3 | prospec-review | 使用者指示「先掃描是否還有類似問題之後，再一起修正，然後進最後一輪 review」；所有 critical 已修正並有 regression pin，round 3 的 major／minor 與全面掃描找到的同類問題已一併修正 | consumed by prospec-review:748123a1feeb4df2195cfb05007ea399c5ebe6cf3c65f9e1421e708966f9ef6d |
| review:4 | prospec-review | 使用者確認 break-glass：所有 critical 與 major 已修正，只剩兩個 minor 文件錯誤（R4-1、R4-2），修正後跑最後一輪 review | consumed by prospec-review:ea872470fd1c46ad0a5b60a21540dcf1d64ae30b63196c9453a64a36b642e397 |
<!-- prospec:escalation-history-end -->

## Knowledge Update

- `prospec/ai-knowledge/modules/template/README.md`：`check_kernel_version.py`、`make kernel-version`、`make template-references`／`--sync-references`、`kernel_version` 不持久化、`check_template.py` 讀 example 檔案不列為 module 相依。
- `prospec/ai-knowledge/modules/example/README.md`：`make check` 先執行版本檢查；修改參考清單內的檔案後執行 `make template-references`。
- `prospec/ai-knowledge/_conventions.md`：服務 checks 的順序加入版本檢查。
