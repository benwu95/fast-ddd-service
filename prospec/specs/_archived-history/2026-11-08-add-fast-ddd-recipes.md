# add-fast-ddd-recipes — Archive Summary

- **Archived**: 2026-11-08
- **Original Created**: 2026-11-07T16:33:11.800Z
- **Quality Grade**: S
- **Issue**: https://github.com/benwu95/fast-ddd-service/issues/7

## User Story

As a 在 fast-ddd 產生的服務中工作的 coding agent（及審查其產出的開發者），
I want 從 `fast-ddd` 的 SKILL.md 找到七份 recipe，每份寫明採用時機、修改範圍與要補的測試，並只引用 kernel 實際提供的 API，
So that 使用者要求這些功能時，agent 依固定做法加入，不必從 kernel 原始碼推測，也不會在不需要時產生它們。

另含 US-2（CI 驗證 `app/lib` recipe 持續有效）與 US-3（repo 根目錄 README）。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| template | Medium | `references/recipes/` 七份 recipe（export、batch-operations、archive-snapshot、operation-history、batch-event-handler、realtime-push、app-lib）、SKILL.md 的 Recipes 表、既有 workflows／rules／decisions 改為指向 recipe；`test_service_skill_contract.py` 的 recipe 結構、kernel 名稱與參數、export 上限檢查；`test_app_lib_recipe.py` 在產生的服務套用 diff 後跑 `make check`；example skill 副本與 ownership |
| plugin | Low | repo（即 plugin）根目錄 `README.md` 與 `test_plugin_contract.py` 的連結與 make target 檢查；module-map 的 plugin paths 加入 `README.md` |
| example | Low | dev group 宣告 `fast-ddd-kernel[realtime]`，供 contract test 載入 realtime 模組 |

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-TEMPLATE-013 | ADDED | skill 的非預設功能 recipe：七份 recipe 由 Recipes 表索引、只在使用者要求時採用，只引用 kernel 實際的名稱與參數，export 有筆數上限且字串寫成文字 |
| REQ-TEMPLATE-014 | ADDED | app/lib recipe 的 CI 驗收：套用 diff 後服務的 `make check` 通過，未套用時 contract 涵蓋檢查失敗，template 改變使 diff 無法套用時 CI 失敗 |
| REQ-PLUGIN-004 | ADDED | repo 根目錄 README：介紹用途、結構、建立服務、skill 與 recipe、開發驗證與文件，CI 檢查連結與 make target |

## Completion

- **Tasks**: 15/15 (100%), 5/5 [V] (not counted)
- **Acceptance Criteria**: 9/9（issue #7 AC-1–AC-5 與 README 兩項情境）

## Review & Verify

- **Review**: 3 round(s), 1 critical / 5 major / 3 minor（共 9 項，全數 fixed）— R1-01 critical：export 的 xlsx writer 對含 `\x0b` 等 XML 不合法控制字元的字串會丟 `IllegalCharacterError`，整個匯出回 500；經獨立 verifier 確認後要求以 `ILLEGAL_CHARACTERS_RE` 清除並以 contract test 釘住。major：batch-create 的 id 改在 port 建立（R1-02）、`ensure_unique_ids` 的索引（R2-04）、app/lib 驗收擋下只套用部分 diff（R1-03）、realtime 寫法通過 pyright strict（R2-01）、realtime extra 在 example 明確宣告（R1-04）。第 2 輪 payload 因 repro 超過 600 字被 schema 拒收，依協定重派一次
- **Verify**: Grade S — task-completion PASS、knowledge PASS、tests PASS（root `make check` exit 0；example 399 passed、template-check 一致）、delta-spec-compliance PASS 3/3（fresh-subagent）、constitution PASS 7/7（fresh-subagent）、design not-applicable（fresh-subagent）
- **Quality Log**: plan verifier 第 1 輪 FAIL（README 的 US-3 沒有 REQ，補 REQ-PLUGIN-004 後第 2 輪 WARN）；tasks verifier WARN（建議均已納入）；review 3 輪皆 PASS；第一次 verify record 為 A（design 由實作 session 判定），fresh 重判後為 S
