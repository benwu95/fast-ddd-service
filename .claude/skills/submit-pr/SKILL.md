---
name: submit-pr
description: "提交 fast-ddd-service 專案的 GitHub PR：確認分支範圍與驗證證據、push 已授權的變更，以英文 Conventional Commits 標題及繁體中文內文建立或更新 PR 並連結 issue。Triggers: submit pr, open pr, create pr, 開 PR, 送 PR, 發 PR, 提交 PR。僅審查或撰寫草稿時不發布。"
---

# Submit PR

為 `benwu95/fast-ddd-service` 提交完成的變更。先確認可審閱的 diff、驗證結果與完整內文，再 push 並建立或更新 PR；不執行 merge 或 release。

## 1. 確認分支、範圍與流程

閱讀專案入口規範，執行 `prospec status`，並檢查：

```bash
git status --short
git branch --show-current
git remote -v
git log --oneline main..HEAD
git diff --stat main...HEAD
git diff main...HEAD
```

預設 base 為 `main`；使用者指定其他 base 時，後續比較與 PR 指令全部一致替換。確認比較使用的 base ref 足夠新；需要更新遠端資訊時先 fetch，再以對應的遠端 base 比較。檢查 branch 上的所有 commit，不只最後一個。位於 base branch、沒有可提交的差異，或有應納入但尚未 commit 的變更時，先處理具體缺口；不將他人的未提交變更自動納入。

若本次變更有 Prospec change，讀取其 `.prospec/changes/<name>/metadata.yaml` 或對應 archive 中的紀錄，確認 review、verify、Knowledge sync 與 archive 的必要關卡已完成。進入任何站點前重新執行 `prospec status` 並讀取該站 skill，不以這份 skill 取代站點流程。一般文件或維護變更沒有登記 change 時，不補造 change、品質等級或 archive 紀錄。

Commit 遵循 Conventional Commits：英文標題、祈使句、小寫開頭、無句點；description 用英文 bullet list。不限定 commit 數量，也不搬用 Prospec repo 的固定 feature／archive 兩個 commit 規則。未 merge 分支的同一關注點修正依專案規範 fold 回原 commit；若需要改寫已發布歷史，先確認使用者已授權。使用明確路徑 staging，不提交 `.tasks/`；Prospec 本機狀態與報告的追蹤依 repo 政策核對。

## 2. 執行實際適用的驗證

先確認當次 checkout 的 CI workflow、Makefile、`pyproject.toml`、lockfile 與工具設定。`docs/design.md` 第 13 節規劃以 `make check` 統一品質檢查；設計中的指令不代表當前已存在。套件管理工具以實際設定為準，不能僅由 `.prospec.yaml` 的偵測值推斷。

- 程式碼變更：執行 CI 要求的 format、lint、型別、架構與測試檢查，涵蓋分支各 commit 的變更檔案。依 Makefile 的實際位置執行根目錄或 `kernel/`、`example/` 的 `make check`；kernel 變更需驗證參考服務的整合。若所需檢查尚不存在或無法執行，記錄阻礙，不宣稱通過，也不當成已完成的 PR 發布。
- Schema／template／plugin 變更：依實際變更與現有工具執行 migration、copier 產生／同步或 plugin 驗證。需要 DB／MQ 的測試缺少服務時不能以 skip 代替成功。
- 文件／維護 skill 變更：執行現有且適用的文件、格式與 skill 檢查；鏡像 skill 比對 `.agents`、`.claude` 的對應內容。未執行 runtime 測試時說明範圍與理由。

Formatter 與 linter 僅處理變更檔案；CI 若要求完整檢查，使用不改寫檔案的模式。保留完整 suite 的必要測試，不降低 coverage 或型別門檻來取得成功。記錄每個指令的結果、版本、測試通過／收集數及 skip／failure；只報告實際量測的 coverage、Prospec grade 與檢查結果。測試後若再修改、rebase 或解衝突，重新執行受影響的檢查。

## 3. 取得 issue 關聯並完成草稿

有 Prospec change 時以該 change 的 `metadata.yaml` 中 `issue` 為優先來源，並核對使用者指定的 issue。沒有 metadata 時可使用使用者明確提供的 issue 或已驗證的現有 PR 關聯；不從 branch 名稱或模糊的 commit 文字猜測。若工作明確對應 issue 卻缺少號碼，完成草稿與其他驗證後再詢問；未綁定 issue 的獨立維護變更不強制建立 issue。

完整內文存到 `.tasks/<branch>/pr-body.md` 或系統暫存檔。標題使用英文 Conventional Commits，依最終變更範圍撰寫；單一主題可沿用其 feature／fix commit subject。內文使用繁體中文（台灣），technical terms、code 與路徑保留英文，不附加 AI attribution footer，也不加入 AI co-authorship trailers。

```markdown
## 問題與結果

先寫具體問題與變更後的可觀察行為，附必要證據。

## 變更內容

依主題說明行為、責任位置與 reviewer 需要知道的設計取捨。

## 驗證

列出實際執行的指令、版本、範圍、通過／總數與結果。
有 Prospec change 時列出實際 verify 結果與 archive 狀態。

## 限制與後續

有未執行的檢查、相容性影響或未解事項才保留此節，說明影響與後續。
```

PR 完整解決 issue 時最後一行使用 `Closes #NN`；僅推進 issue 時使用 `Refs #NN`。無關聯 issue 時省略，不使用 placeholder。涉及公開 kernel API、HTTP／MQ contract、migration 或 template 時交代既有服務的相容性與升級步驟；區分設計草案與已落實行為。

若使用者已授權提交 PR，直接完成後續步驟；只有草稿／review 需求時停在本機草稿。需要額外授權時先備妥完整 diff、驗證與內文，再提出具體待授權動作，不重複詢問已有授權。

## 4. 確認帳號、push 與建立／更新

GitHub 寫入前執行 `gh auth status` 與 `gh api user -q .login`，確認 active account 為本 repo owner `benwu95`。若帳號不符且已登入 `benwu95`，執行 `gh auth switch --hostname github.com --user benwu95` 後重新確認；不可用時保留本機成果並報告登入缺口。SSH push 成功不能證明 `gh` 帳號正確。

先查詢此分支是否已有 PR：

```bash
gh pr list --repo benwu95/fast-ddd-service --head <branch> --state open \
  --json number,title,url,body,baseRefName,headRefName
```

確認 diff 與內文完成後 push：

```bash
git push -u origin HEAD
```

若已授權推送改寫後的歷史，只使用 `--force-with-lease`。Push 失敗時查明原因，不自動 force push。

沒有現有 PR 時建立：

```bash
gh pr create --repo benwu95/fast-ddd-service --base main --head <branch> \
  --title '<type>(<scope>): <english summary>' \
  --body-file <draft-file>
```

`--repo` 與 `--head` 都明確指定，避免 origin 的 SSH host alias 造成推斷錯誤。有現有 PR 時先讀取最新內文，保留仍適用的人工補充，以 `gh pr edit <number> --repo benwu95/fast-ddd-service --title '<title>' --body-file <draft-file>` 更新完整內容。Push 後同步描述；數字或結論改變時回報舊值、新值與原因。未經要求不改 labels、reviewers、assignees 或 milestones。

## 5. 驗證與交付

```bash
gh pr view <number> --repo benwu95/fast-ddd-service \
  --json number,title,url,body,baseRefName,headRefName,commits
gh pr checks <number> --repo benwu95/fast-ddd-service
```

核對 base／head、遠端 commit、標題、完整內文與 issue 關聯。CI 尚在執行時以短間隔追蹤並提供進度；失敗時讀取 log，修正本變更引入的問題並重新驗證。沒有 CI 時明確說明，不宣稱 CI green。若外部阻礙無法排除，回報具體檢查及影響，不要求 merge。

交付 PR URL、變更結果、實際驗證範圍與尚存阻礙。不手動關閉 issue；完整解決的 issue 由 merge 時的 closing reference 處理。

## 維護

這是本 repo 的維護工具，不是 `skills/` 內供下游服務安裝的產品 skill，也不由 `prospec agent sync` 產生。同時更新 `.agents/skills/submit-pr/SKILL.md` 與 `.claude/skills/submit-pr/SKILL.md`，兩份內容必須逐位元組一致。
