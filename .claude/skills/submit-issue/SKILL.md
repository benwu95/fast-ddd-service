---
name: submit-issue
description: "建立 fast-ddd-service 專案的 GitHub issue，整理問題證據、方案與可驗證的驗收標準，使用英文 Conventional Commits 標題及繁體中文內文。Triggers: submit issue, open issue, create issue, file issue, 開 issue, 發 issue, 建 issue, 提 issue。僅討論需求或撰寫草稿時不發布。"
---

# Submit Issue

為 `benwu95/fast-ddd-service` 建立 GitHub issue。參考來源為 Prospec repo 的同名 skill；本版本依本專案的 DDD kernel、參考服務、copier template 與 plugin／skills 調整。

## 專案規則

- 標題使用英文 `<type>(<scope>): <summary>`，summary 使用小寫開頭的祈使句，不加句點。scope 依實際範圍選擇，例如 `kernel`、`persistence`、`http`、`mq`、`tasks`、`example`、`template`、`skills`、`docs`；不把規劃中的模組當成已存在的程式碼。
- 內文使用繁體中文（台灣），code、識別字、路徑與 technical terms 保留英文。不附加 AI attribution footer；未經使用者要求或現有 repo 規則支持，不自行指定 labels、assignees 或 milestones。
- 一個 issue 對應一個可獨立驗收的 change／PR。互不相依的修正拆開；相關系列註明執行順序與相依關係。
- 每個數字、行為與檔案位置都必須有實際證據。區分觀察到的行為、設計目標與待決選項；不將 `docs/design.md` 草案中的選擇直接認定為既定 contract。

## 1. 蒐集證據並界定範圍

閱讀專案入口規範。存在 Prospec 文件時，先讀 `prospec/index.md`，辨識模組後才載入相關 Knowledge 與 source；遵循 `prospec/CONSTITUTION.md`。缺少這些檔案時明確記錄限制，使用現有追蹤檔案與 `docs/design.md`，不補造規格。

以 `git ls-files` 確認路徑是否存在且受追蹤。查核問題相關的 source、測試、repro 或 review 紀錄；本機 `.tasks/` 與 `.prospec/` 可作研究材料，但 issue 必須重述必要證據，不把未發布的本機路徑當作讀者可存取的連結。跨服務 contract 以對方 repo 實際 pinned／deployed 版本查證。

需要查詢 GitHub 時，明確指定 `--repo benwu95/fast-ddd-service`，搜尋是否已有相同問題，並讀取相關 issue／PR。只有草稿需求時停在本機草稿。

## 2. 寫出可審閱的草稿

將完整內文存到 `.tasks/issue-<slug>.md` 或系統暫存檔，不將工作草稿加入 commit。依下列順序組織，省略不適用的選用段落：

```markdown
## 概述

描述具體觸發條件、目前結果與影響，附可追溯的證據。

## 背景與問題

說明根因或待驗證假設、相關檔案位置，以及預期與實際行為。

## 改善目標與方案

說明變更範圍、各位置負責的行為、選擇理由與不涵蓋的事項。
多個互斥方案需標明取捨與待決事項，不將它們寫成同時必須實作。

## 驗收標準

- [ ] **AC-1（行為）**：具體輸入／觸發條件與可觀察的預期結果。
- [ ] **AC-2（回歸驗證）**：列出本變更實際需要的檢查與測試範圍。

## 關聯項目

列出 issue／PR、受追蹤文件、證據連結與明確的相依關係。
```

涉及 kernel 公開 API、HTTP／MQ contract、migration 或 copier template 時，加入「相容性與升級」段落，交代既有服務的影響、版本相容策略與必要的升級步驟。涉及可安裝的 plugin／skills 時，依實際消費端說明路徑、設定與工具需求；不照搬 Prospec 模板的相容性禁令。

驗收門檻以該次 checkout 的 CI、Makefile、工具設定與專案規範為準。`docs/design.md` 第 13 節規劃以 `make check` 統一 ruff、pyright strict、import-linter／contract 涵蓋、pytest／coverage 等檢查；issue 若要求建立尚不存在的檢查，須明示為交付目標。不要加入 Prospec repo 的 `pnpm`、`counts:check` 等指令。

若使用者已授權發布且內容已足以完成，直接繼續；只有草稿需求或仍缺必要範圍決策時，先完成草稿，再提出具體缺口。不要重複索取已取得的授權。

## 3. 確認帳號並建立

GitHub 寫入前執行：

```bash
gh auth status
gh api user -q .login
```

本 repo 的 owner 為 `benwu95`；確認 active account 為 `benwu95`。若登入多個帳號且目前帳號不符，切換後重新確認；若該帳號不可用，保留草稿並報告登入缺口。

```bash
gh auth switch --hostname github.com --user benwu95
```

以完整草稿建立 issue：

```bash
gh issue create --repo benwu95/fast-ddd-service \
  --title '<type>(<scope>): <english summary>' \
  --body-file <draft-file>
```

必須明確傳入 `--repo`：本專案 origin 使用 SSH host alias，不能依賴 `gh` 自動推斷。

系列 issue 只在使用者授權的範圍內建立或更新。更新前先讀取每個 issue 的最新完整內文，保留既有內容後加入雙向關聯；`gh issue edit --body-file` 會取代整份內文，不得只傳關聯片段。

## 4. 驗證與交付

```bash
gh issue view <number> --repo benwu95/fast-ddd-service --json number,title,url,body
```

核對回傳的標題與完整內文和草稿一致，確認 AC checkbox 與關聯語法正確。若工具可查看渲染結果，再檢查實際顯示；只讀取 JSON 不宣稱完成視覺檢查。回報 issue URL 與尚待決定的事項。

若後續進入 Prospec story，由 `prospec-new-story` 使用已建立的 issue 登記 change；建立 issue 本身不啟動實作。

## 維護

這是本 repo 的維護工具，不是 `skills/` 內供下游服務安裝的產品 skill，也不由 `prospec agent sync` 產生。同時更新 `.agents/skills/submit-issue/SKILL.md` 與 `.claude/skills/submit-issue/SKILL.md`，兩份內容必須逐位元組一致。
