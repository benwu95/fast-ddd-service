---
feature: service-template
status: active
last_updated: 2026-10-20
story_count: 6
req_count: 8
---

# service-template

## Who & Why

**Who it serves**: Python 後端開發者、服務維運者與框架維護者。

**Problem it solves**: 從依賴 workspace 的業務參考服務建立無範例業務、可獨立驗收的單服務 repo。

**Why it matters**: agent 與開發者可沿用已驗證的 DDD kernel，直接修改外層並自行選擇合併骨架更新。

## User Stories & Behavior Specifications

### US-1: 在 repo 外建立可驗收的空服務 [P0]

作為建立 DDD 後端服務的 Python 開發者，我要由已驗證的骨架建立獨立服務，以便開始業務開發前就能驗證環境與品質。

**Acceptance Scenarios:**
- WHEN 在 repo 外以本機 kernel 來源產生服務並依指引初始化環境，THEN 服務使用自己的 lock／venv，完整 `make check` 通過且不借用 repo workspace。
- WHEN 以固定 git tag 的 kernel 來源產生服務，THEN 不需 sibling kernel 目錄即可安裝、通過品質檢查，並能辨識實際使用的 kernel 版本。
- WHEN 檢視剛產生的服務，THEN 不含 Invoice／Customer／notification 範例業務，不需填寫 notification 設定即可完成初始化，且不新增假 bounded context。
- WHEN 檢視產生的開發設定與檔案，THEN 不含 agent host 的權限設定，`.gitignore` 排除機密檔案，沒有真實機密被寫入版本控制檔案，lock 可納入版本控制。

#### REQ-TEMPLATE-001: 可獨立驗收的空服務產生
Python 開發者可產生不含範例業務、具有自有環境且不含 agent host 設定的服務；example 保留 workspace 模式。
- WHEN 在 repo 外以 git 或 path kernel 來源建立服務，THEN 兩種產物各使用自己的 lock／venv 通過完整品質檢查；git 不依賴 sibling kernel，無效來源／版本明確失敗。
- WHEN 初始化與檢視服務，THEN 無 Invoice／Customer／notification 業務或假 bounded context，不需 notification 設定；必要 worker 設定與擴充入口可用，不含 agent host 設定，`.gitignore` 排除機密檔案，真實機密不寫入追蹤檔案，lock 可追蹤。
- WHEN example 重新產生骨架，THEN kernel 仍來自同 repo workspace，使用正確環境；版本 pin 使用明確版本，不取模板 commit 字串代替。

---

### US-2: 從空資料庫開始維護服務 schema [P0]

作為維護服務資料庫的 Python 開發者，我要在沒有範例業務表的狀態啟用 migrations，以便建立第一個業務 schema 並持續升級。

**Acceptance Scenarios:**
- WHEN 對新服務的空資料庫套用全部 migrations，THEN kernel 與 service 各有一個 head，沒有 billing tables，schema 檢查無未產生的變更。
- WHEN 新服務建立第一個業務 migration，THEN 文件記載的既有操作指令成功，並可升降版後再次通過 schema 檢查。
- WHEN example 套用或重新產生骨架，THEN 既有 service revision chain 保留，不增加第二個 service root，也不覆寫後續業務 migrations。

#### REQ-TEMPLATE-002: 空服務的 schema 生命週期
服務可從空資料庫接續業務 migrations，kernel 與 service branch 都有可驗證的歷史。
- WHEN 對空服務套用全部 migrations，THEN kernel／service 各有一 head、沒有 billing tables，schema check 無待產生差異。
- WHEN 建立第一個實際業務 migration 並升降版，THEN 操作指引中的指令成功，最後 schema check 通過；測試以正式 migrations 建 DB。
- WHEN 更新或 recopy 已有 service branch 的 example／服務，THEN 不新增第二個 service root、不覆寫既有 baseline 或後續 migrations，example revision chain 保留。

---

### US-3: 以分發產物操作三種執行角色 [P0]

作為部署服務的維運開發者，我要啟動、檢查與終止空服務的 API／consumer／worker，以便部署時具有與參考服務一致的操作保證。

**Acceptance Scenarios:**
- WHEN PostgreSQL／RabbitMQ 可用且必要設定完整，THEN 三個角色各自完成啟動與 health 檢查，consumer 沒有業務 subscriber、worker 沒有業務 task／cron 時也符合空服務啟動契約。
- WHEN 角色正常終止、啟動失敗或執行元件失敗，THEN health、錯誤回報、已取得資源的清理與有時限的停止行為符合既有角色規格，未完成工作不被誤報為已處理。
- WHEN 使用非 editable kernel 安裝執行服務，THEN 四個 package 的型別資訊與 kernel migrations 可用，不依賴 kernel source checkout。
- WHEN 使用產生的 Dockerfile 建置並操作服務，THEN 容器使用服務 lock、可分別啟動三個角色，且不需要 repo workspace 或主機既有 venv。

#### REQ-TEMPLATE-003: 可分發的三角色 runtime
非 editable 安裝與容器提供可操作的 API／consumer／worker，沿用既有角色規格與資源清理保證。
- WHEN 必要設定與 DB／MQ 可用，THEN 三角色各自啟動、通過角色 health 並可終止；零業務 subscriber／task／cron 仍可操作，不加入假業務 handler。
- WHEN 正常終止、startup 或執行元件失敗，THEN 已取得資源依既有 lifecycle 清理、停止有時限，未完成工作不誤報成功；實際程序 signal 與容器停止測試補充通用故障注入。
- WHEN 安裝 kernel 產物或以服務 lock 建容器，THEN 四個 package 的 py.typed／正式 migrations 可用，test-only branch 不進產物，三角色不依賴 host venv 或 kernel source checkout。

---

### US-4: 更新骨架並保留服務自主內容 [P0]

作為長期維護服務的 Python 開發者，我要直接客製化外層骨架並自行選擇採用更新，以便沿用共用改善而不遺失服務實作、相依與資料庫歷史。

**Acceptance Scenarios:**
- WHEN 已直接客製化外層 runtime、工具設定與通用測試後更新至下一個 template revision，THEN 可合併的本地修改與上游變更均保留，服務相依、設定、接線、業務測試、lock 與既有 migrations 的自主修改不被覆蓋；template 退役的追蹤檔案例外，依操作文件檢查並由 checkpoint 還原。
- WHEN 新 template 要求升級 kernel，THEN 可取得明確的相依／lock 升級及驗證指引，服務自行加入的相依保留，不將 template 更新成功誤報為 kernel 已升級。
- WHEN 將 coverage 設為合法的較高門檻後 update 或 recopy，THEN 設定與門檻保留；低於 80 或高於 100 的輸入被拒絕，預設門檻為 80。
- WHEN 產生或更新通用測試骨架，THEN 不需 billing／notification fixtures 即可收集及執行通用測試，服務可另外擴充業務測試並維持既定品質門檻。
- WHEN 本地客製化與上游變更無法合併，THEN 明確呈現衝突與雙方內容，由服務維護者處理並驗證，不將未解衝突視為更新完成；退役檔案的移除不產生衝突標記，由操作文件要求更新後以 Git 檢查。

#### REQ-TEMPLATE-004: 骨架更新與服務內容保護
外層程式、工具與測試是服務可直接修改的起點，開發者可自行選擇更新並保留客製化，明確處理衝突、退役檔案與 kernel 升級。
- WHEN 直接修改外層 runtime、工具設定及通用測試後更新至下一個 revision，THEN 本地可合併修改與上游變更均保留；服務相依、設定、接線、業務測試、lock 與既有 migrations 不被覆蓋，客製化不限定於 answers／hooks。
- WHEN 本地與上游變更衝突，THEN 雙方內容及未解狀態明確呈現，由服務維護者處理並驗證；未解衝突不能通過更新驗證，不以正常返回碼宣稱完成。
- WHEN template 退役某個追蹤檔案，THEN 操作文件列出該檔案、說明更新會移除它（包含服務修改過的情況），並要求更新後以 Git 檢查刪除、由更新前 checkpoint 還原要保留的檔案；退役行為由兩版更新測試驗證。
- WHEN 新 template 需要升級 kernel，THEN 指引明訂相依、lock 與品質驗證操作；不覆蓋服務新增相依，不將 template 更新視為 kernel 已升級。
- WHEN 初始化檔刪除後重新產生，THEN 按明訂重建規則處理，不因此建立第二個 migration root；更新失敗可由事前 Git checkpoint 檢視／撤回，生成流程不執行 DB migration。
- WHEN 依操作指引升級客製化服務，THEN 使用合併更新；覆寫重新產生只用於框架 example 同步與隔離驗收，明訂可能覆掉客製化，不作為下游一般升級流程。

---

#### REQ-TEMPLATE-005: 可持續更新的品質基準
空服務具有獨立通用測試與可擴充業務測試入口，品質設定可提高且可重現。
- WHEN 生成服務並執行通用 tests，THEN 不需 billing／notification fixtures 即可收集／執行，服務可擴充自己的業務 tests，runtime 公開行為有測試。
- WHEN 未指定 coverage 或選擇 80–100，THEN 預設 80，較高值於 update／recopy 後保留；79／101 等範圍外拒絕，不以略過測試／排除 runtime 達門檻。
- WHEN 執行 standalone hooks 或 CI，THEN hooks 跑服務根的靜態／lock，CI 跑完整 make check，含 strict typing、分層、schema、tests、coverage；必要工具缺失失敗。

---

### US-5: 在 CI 偵測骨架漂移並保留 Phase 1 保證 [P0]

作為維護架構與後續 skill 的專案擁有者，我要由 CI 偵測 template／example 不一致及既有行為退步，以便使用可追溯的參考架構建立新服務。

**Acceptance Scenarios:**
- WHEN 乾淨 checkout 以目前 template 重新產生 example，THEN 骨架的 tracked／untracked 檔案集合與內容一致，answers 只容許 template commit 改變，workspace 來源保持有效。
- WHEN 在框架 repo 刻意修改 example 的 template 追蹤檔案、加入未同步的骨架檔案或改變其他答案，THEN CI 偵測漂移且保留初始化檔案的修改；此一致性要求不套用至下游客製化服務。
- WHEN 執行 Phase 2 交付驗收，THEN 產生／更新／分發／三角色／migration 驗收與 repo 完整 `make check` 均通過，kernel 與 example 各自 coverage 至少 80%，必要測試零 skip，既有 wire、交易與 lifecycle 保證保留。

#### REQ-TEMPLATE-006: 參考服務的骨架漂移偵測
框架 repo 的 CI 以目前 revision 驗 template／example 追蹤檔案與 answers 的一致性，提供可重現差異證據；不要求下游客製化服務與範本一致。
- WHEN 乾淨 checkout 以 HEAD recopy example，THEN tracked／untracked 集合與內容一致，answers 只容許 _commit 改變，workspace 來源有效。
- WHEN 在框架 example 刻意修改／刪除追蹤檔、新增未同步骨架檔或改非 commit 答案，THEN 偵測差異並失敗退出；初始化修改保留，下游外層修改由更新／衝突測試驗證，不施加此 drift gate。
- WHEN template 移除曾受管檔案，THEN 框架專用歷史 ownership 清單使 example 殘留副本被回報；副本同步移除後可通過。清單更新不遺忘歷史路徑，未登錄新受管路徑失敗；初始化與業務內容保留，check／CI 不自動刪檔或更新清單。

---

#### REQ-TEMPLATE-007: 完整產物驗收與既有行為保留
產生、更新、分發與 regression 由 required CI 驗證，不將局部成功等同交付。
- WHEN 執行交付驗收，THEN git／path 獨立服務、兩版更新、recopy 正負向、migration、非 editable 產物、三角色／容器全部通過，必要案例零 skip。
- WHEN 執行 repo 完整 make check，THEN kernel／example 各 coverage 至少 80%，既有 wire、分層、交易、migration／lifecycle 測試保留；搬移／刪改 tests 有需求與 node ID 對照，不以產物成功取代既有 regression。

---

### US-6: 三家 host 讀取同一份服務內 skill [P0]

作為以 template 建立服務的開發者，我要讓服務以 `.agents/skills` 提供 repo 層級 skill、`.claude/skills` 以 symlink 指向它，以便 Claude Code、Codex 與 agy 讀到同一份隨 template 更新的 skill。

**Acceptance Scenarios:**
- WHEN 以 template 產生服務，THEN 產物含已渲染 `kernel_version` 的 `.agents/skills/fast-ddd/SKILL.md`，`.claude/skills` 是指向 `../.agents/skills` 的 symlink。
- WHEN 對已產生的服務執行 `copier update`，THEN `.claude/skills` 仍是 symlink，skill 內容合併上游與本地修改；Phase 2 產生的服務更新後新增 symlink。
- WHEN 框架 repo 執行 example recopy 與 ownership 檢查，THEN 新路徑已登記，example 含 skill 目錄與 symlink，無漂移。

#### REQ-TEMPLATE-008: 三家共用的 repo 層級 skill 目錄
服務以單一 skill 目錄供 Claude、Codex 與 agy 讀取，版本隨 template 更新。
- WHEN 以 template 產生服務，THEN `.agents/skills/fast-ddd/SKILL.md` 含產生時的 `kernel_version`，`.claude/skills` 是指向 `../.agents/skills` 的 symlink。
- WHEN 服務以 `copier update` 更新，THEN `.claude/skills` 維持 symlink，skill 內容合併上游與本地修改。
- WHEN 框架 example recopy，THEN skill 目錄與 symlink 和 template 一致，新路徑已登記於歷史 ownership。

---

## Edge Cases

- 無效 kernel path／tag、缺少必要設定或 Docker／品質工具時明確失敗，不回退來源、不 skip 必要驗收。
- 初始化檔刪除後依持久化答案重建；既有 service migration chain 不新增第二個 root。
- 下游外層可直接修改；更新衝突保留雙方內容與未解狀態，維護者處理後重新驗證。
- 框架歷史 ownership 永久保留退役路徑；CI 只回報殘留，不自動刪檔或寫清單。
- snapshot 內部 symlink 重定位到副本；外部路徑在寫入前拒絕。
- template 退役的追蹤檔案（`.claude/settings.json`）在 update 時被刪除，即使服務修改過也無衝突；服務已有實體 `.claude/skills` 目錄時 update 失敗，需先把 skill 移到 `.agents/skills/`。

## Success Criteria

- git／path 服務各自以 lock／venv 通過完整 make check，coverage 至少80%、必要測試零 skip。
- 空服務 migrations、第一個業務 migration 升降版、三角色程序與容器操作均可驗收。
- 兩版更新保留可合併客製化與初始化內容，衝突與 framework example 漂移有負向驗收。
- kernel／example 的 wire、分層、交易與 lifecycle regression 保留，搬移測試具 node ID 對照。
- 產物的 `.claude/skills` 在 copy 與 update 後皆為指向 `../.agents/skills` 的 symlink，不含 agent host 設定。

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
| 2026-10-20 | ship-fast-ddd-init-plugin | ADDED REQ-TEMPLATE-008; MODIFIED REQ-TEMPLATE-001; MODIFIED REQ-TEMPLATE-004 | REQ-TEMPLATE-008, REQ-TEMPLATE-001, REQ-TEMPLATE-004 |
| 2026-10-18 | extract-service-template | 新增服務骨架與完整驗收規格 | REQ-TEMPLATE-001, REQ-TEMPLATE-002, REQ-TEMPLATE-003, REQ-TEMPLATE-004, REQ-TEMPLATE-005, REQ-TEMPLATE-006, REQ-TEMPLATE-007 |
