---
feature: plugin-distribution
status: active
last_updated: 2026-11-08
story_count: 3
req_count: 4
---

# plugin-distribution

## Who & Why

**Who it serves**: 使用 Claude Code、Codex 或 agy 建立 fast-ddd 服務的後端開發者，以及發布框架版本的維護者。

**Problem it solves**: 在服務 repo 存在之前，以使用者層級安裝的 plugin 提供建立服務的入口，並以對應版本的 git tag 產生服務。

**Why it matters**: 三家 host 用同一份 plugin 建立服務，產物記錄 git 來源而非 plugin 快取，之後可持續以 `copier update` 更新；發布時版本來源一致，三家都能收到更新。

## User Stories & Behavior Specifications

### US-1: 在三家 host 安裝 plugin 並手動建立服務 [P0]

作為使用 Claude Code、Codex 或 agy 的後端開發者，我要以使用者層級安裝 fast-ddd plugin 並手動呼叫 `fast-ddd-init`，以便從對應版本的 git tag 建立新服務，而不依賴 plugin 快取路徑。

**Acceptance Scenarios:**
- WHEN 驗證 repo 的 plugin（Claude、agy）或從本機 marketplace 安裝（Codex），THEN 全部成功，plugin 只提供 `fast-ddd-init`；警告只限框架 repo 根目錄開發指引不隨 plugin 載入。
- WHEN 在三家 host 提出建立服務的一般要求、未手動呼叫 skill，THEN 模型不會自動觸發 `fast-ddd-init`；使用者手動呼叫時可以執行。
- WHEN 使用者手動呼叫 `fast-ddd-init`，THEN 先確認服務名稱與目的地，以 `v<version>` tag 與 git 來源建立服務；產物 `_src_path` 是 git 來源，結束時提示機密保護設定。

#### REQ-PLUGIN-001: 三家 host 共用的 plugin 安裝
repo 本身就是 plugin，三家 host 以各自的 manifest 安裝同一份內容，只取得 `fast-ddd-init`。
- WHEN 以 Claude、agy 驗證 plugin 或以 Codex 從本機 marketplace 安裝，THEN 驗證與安裝成功，plugin id 為 `fast-ddd@fast-ddd`。
- WHEN 檢視安裝後的 plugin skill，THEN 只有 `fast-ddd-init`，repo 內的其他 skill 目錄不被當成 plugin skill。
- WHEN 開發者在新環境查閱服務操作文件，THEN 文件列出 Claude、Codex 與 agy 的使用者層級安裝指令。

---

#### REQ-PLUGIN-002: 只能手動呼叫的 fast-ddd-init
使用者手動呼叫 `fast-ddd-init`，以 plugin 版本對應的 git tag 建立服務。
- WHEN 模型處理一般要求，THEN 不自動觸發 `fast-ddd-init`；使用者以 host 的手動方式呼叫時可執行。
- WHEN 使用者呼叫 `fast-ddd-init`，THEN 先確認服務名稱與目的地，再以 SKILL.md 記載的 `v<version>` tag 與 git URL 建立服務，產物 answers 的 `_src_path` 為該 git URL；不依賴 host 提供 skill 目錄。
- WHEN tag 不存在、git 認證或 host sandbox 阻擋、copier 失敗或目的地非空，THEN 停止並回報原因與前置需求，不改用其他 ref、來源或覆寫檔案。
- WHEN 建立完成，THEN 提示在新服務中開啟 session，由服務內 `fast-ddd` 的機密保護工作流程設定 host。

---

### US-2: 發布時版本來源保持一致 [P0]

作為框架維護者，我要由 `make check` 強制 plugin manifests、`fast-ddd-init`、template 與 kernel 的版本一致，以便發布 tag 後三家 host 都能收到更新、`fast-ddd-init` 取得正確的 template。

**Acceptance Scenarios:**
- WHEN 兩份 plugin manifest、`copier.yml` 的 `kernel_version`、`kernel/pyproject.toml` 的 `version` 與 `fast-ddd-init` SKILL.md 的 Template version 相同，THEN 檢查通過。
- WHEN 任一來源不同、缺少或無法解析，THEN 檢查失敗並列出每個來源與其值；每種不一致都有測試證明。
- WHEN 執行 repo 根目錄的 `make check`，THEN 版本一致性檢查與其測試都會執行。

#### REQ-PLUGIN-003: 版本一致性檢查
框架 repo 的品質檢查保證 plugin manifest、`fast-ddd-init`、template 與 kernel 使用同一版本。
- WHEN 五個版本來源相同，THEN 檢查通過。
- WHEN 任一來源不同、檔案不存在、缺少欄位或無法解析，THEN 檢查失敗並列出每個來源與其值或錯誤。
- WHEN 執行 repo 根目錄 `make check`，THEN 包含此檢查。

---

### US-3: 從 repo 根目錄 README 了解框架 [P1]

作為第一次接觸 fast-ddd-service repo 的開發者，我要在根目錄 README 讀到用途、repo 結構、建立服務的入口、服務內 skill 與 recipe、開發驗證指令與文件連結，以便不必先讀完設計文件就能開始使用或參與開發。

**Acceptance Scenarios:**
- WHEN 開啟 repo 根目錄，THEN README.md 涵蓋上述六個主題，安裝與建立服務的指令連到服務操作指引而不另行複製。
- WHEN README 的相對連結目標或提到的 make target 不存在，THEN 框架 CI 失敗。

#### REQ-PLUGIN-004: repo 根目錄 README
repo 根目錄的 README 介紹框架並指向權威文件。

- WHEN 開啟 repo 根目錄，THEN README.md 說明用途、repo 結構、建立服務的入口、服務內 skill 與 recipe、開發驗證指令與文件連結。
- WHEN README 的相對連結目標或提到的 make target 不存在，THEN 框架 CI 失敗。

---

## Edge Cases

- `v<version>` tag 不存在、private repo 缺少 git 認證，或 host sandbox 拒絕網路、uv cache／tools 與 Copier git cache 的寫入：停止並回報，不改用其他 ref、來源或 plugin 安裝目錄。
- 目的地已存在且非空、服務名稱不符合 validator：停止並請使用者修正，不覆寫既有檔案。
- host 以 slash command 呼叫時可能不提供 skill 目錄：`fast-ddd-init` 不讀 plugin 內任何檔案，版本與來源記載於 SKILL.md。
- repo 內其他 skill 目錄（`.claude/skills`、`.agents/skills`）不被當成 plugin skill。

## Success Criteria

- Claude 與 agy 的 plugin validate 成功，Codex 從本機 marketplace 安裝成功，安裝後只有 `fast-ddd-init`。
- 三家各自不自動觸發 `fast-ddd-init`、手動呼叫可建立服務，產物 `_src_path` 為 git 來源。
- 版本一致性檢查涵蓋五個來源的一致與各種不一致，並納入 `make check`。

## Maintenance Rules

1. **Replace-in-Place**：MODIFIED Story 與 REQ 直接取代原版本。
2. **Functional Grouping**：需求置於對應的 User Story。
3. **No Inline Provenance**：變更歸屬只記錄於 Change History。
4. **Deprecation over Deletion**：移除需求保留於 Deprecated Requirements。

## Deprecated Requirements

無。

## Change History

| Date | Change | Impact | Stories/REQs |
|------|--------|--------|-------------|
| 2026-11-08 | add-fast-ddd-recipes | ADDED REQ-PLUGIN-004 | REQ-PLUGIN-004 |
| 2026-10-20 | add-fast-ddd-service-skill | MODIFIED REQ-PLUGIN-002 | REQ-PLUGIN-002 |
| 2026-10-20 | ship-fast-ddd-init-plugin | 新增三家共用 plugin 交付與版本一致性規格 | REQ-PLUGIN-001, REQ-PLUGIN-002, REQ-PLUGIN-003 |
