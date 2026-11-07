# Team Playbook

經人工核准、由 lessons ledger 提升的團隊規則。各 station 以 `prospec learn playbook --station <name>` 載入對應條目；條目到期（TTL）時由 `prospec-learn` 重新審查。

### PB-001: 修改行為或宣稱前，先列出描述同一行為的所有位置並一次同步
- **Source**: ship-fast-ddd-init-plugin, render-utcdatetime-in-migrations, fail-on-missing-intermediate-init, add-batch-event-handlers · **Criteria**: freq=4, modules=4 (template, plugin, kernel, example) · **Kind**: convention · **Approved-by**: benwu95 · **Date**: 2026-11-07
- **Stations**: plan, implement, review
- **TTL**: review by 2027-05-07
- **Guidance**: 修改一項行為、規則或數字前，以識別字與關鍵詞 grep 列出所有描述它的位置：程式碼與測試、`docs/design.md` 各節、module README、`fast-ddd` skill references 的 template 與 example 兩份副本、Feature Spec，以及 change 的 proposal、delta-spec、plan、tasks。plan 把位置清單寫進 delta-spec 與 tasks；implement 與每次 review 修正都依清單一次同步。只改被指出的那一處，review 會逐輪重開另一處並觸發 fix-induced 或 oscillation circuit breaker。同一規則在多處重述時，優先改為一處完整敘述、其他位置引用。
