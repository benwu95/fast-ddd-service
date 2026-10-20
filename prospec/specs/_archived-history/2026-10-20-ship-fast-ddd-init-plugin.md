# ship-fast-ddd-init-plugin — Archive Summary

- **Archived**: 2026-10-20
- **Original Created**: 2026-10-19
- **Quality Grade**: A
- **Issue**: #4

## User Story

使用 Claude Code、Codex 或 agy 的後端開發者以使用者層級安裝 fast-ddd plugin，手動呼叫 `fast-ddd-init`，以 plugin 版本對應的 git tag 建立服務，產物記錄 git 來源而非 plugin 快取。框架維護者由 `make check` 強制 plugin manifests、`fast-ddd-init`、template 與 kernel 的版本一致。template 產生 `.agents/skills` 與指向它的 `.claude/skills` symlink，並移除 agent host 設定。

## Affected Modules

| Module | Impact | Description |
|---|---|---|
| plugin | High | 新模組：三份 manifest、只能手動呼叫的 `skills/fast-ddd-init`（SKILL.md 記載版本與來源）與 Codex 的 `agents/openai.yaml` |
| template | High | `scripts/check_versions.py`（五個版本來源）、`_preserve_symlinks`、服務內 skill 目錄與 symlink、移除 `.claude/settings.json`、操作文件與 ownership |
| example | Medium | recopy 同步 skill 目錄與 symlink、移除 `.claude/settings.json`；承載版本、plugin contract 與 skill 目錄測試 |

## Requirements

| REQ ID | Status | Description |
|---|---|---|
| REQ-PLUGIN-001 | ADDED | 三家 host 共用的 plugin 安裝 |
| REQ-PLUGIN-002 | ADDED | 只能手動呼叫的 fast-ddd-init |
| REQ-PLUGIN-003 | ADDED | 版本一致性檢查 |
| REQ-TEMPLATE-008 | ADDED | 三家共用的 repo 層級 skill 目錄 |
| REQ-TEMPLATE-001 | MODIFIED | 空服務不含 agent host 設定，`.gitignore` 排除機密 |
| REQ-TEMPLATE-004 | MODIFIED | 新增 template 退役檔案的更新例外 |

## Completion

- **Tasks**: 11/11 code（100%）；2/2 verification、2/2 manual。
- **Acceptance Criteria**: fresh grader 核對 10/10 frozen scenarios（revision 3）、6/6 REQ PASS；CLI 因 acceptance 於 story 站後修訂（late-capture）將 spec 維度記為 not-adjudicated。

## Review & Verify

- **Review**: 14 個 merge round，19 個 finding（1 critical／2 major／16 minor）全部 fixed。critical R8-01 經獨立 verifier 確認：`fast-ddd-init` 以檔案條件定位 plugin 內 `copier.yml` 不唯一（repo checkout、fixture 與各 host 安裝目錄結構相同，agy 以 slash command 呼叫不提供 skill 目錄）；依使用者決定改為版本與來源寫在 SKILL.md，並以 regression pin（宣告值等於 `copier.yml` 預設值、body 引用的檔案限於 allowlist）與 mutation 驗證守住。major：產物 `.gitignore` 機密 pattern 無測試（R1-01）、design 15.2 的 CI 宣稱沒有執行者（R1-05）。
- **Verify**: Grade A、result PASS、status verified。task-completion／knowledge／tests machine PASS；Constitution fresh-context 6/6（2 PASS、4 not-applicable）；design not-applicable；delta-spec-compliance 由 grader 判 6/6 PASS，CLI 記 not-adjudicated（late-capture）。
- **Tests**: 最終 `make check` attempt ca1fc738-fdca-4097-b073-b3b6bc140493，exit 0：kernel 333 passed、example 315 passed、零 skip，template／example 無漂移，版本一致於 0.1.0。
- **Host 驗收**：Claude Code 2.1.303–2.1.304、Codex 0.163.0、agy 1.4.2 於隔離 home 驗證 plugin 安裝、不自動觸發、手動建立服務（`_src_path` 為 git URL）；三家產物完全相同。證據在 bundle 的 `evidence/host-e2e/`（不進版本控制，須摘要於 PR）。
- **Quality Log**: plan 第 1 輪 FLAWS（US-3.4 無 REQ 承接、退役檔案與 REQ-TEMPLATE-004 衝突）後修訂為 WARN；tasks 第 1 輪 FLAWS（前置實測順序、[M] 任務含 diff）後修訂為 WARN；ff 的 INVEST WARN（端到端需 host 登入、無法進 CI）；review R8-01 round 記 WARN；verify WARN 為 acceptance late-capture。無人工 override。

## Decisions

- 驗收修訂 revision 2：實際 repo 根目錄的 `AGENTS.md` 使 `agy plugin validate --strict` 失敗，改為非 strict 且限定唯一 warning（使用者 2026-10-19）。
- 驗收修訂 revision 3：`fast-ddd-init` 改為在 SKILL.md 記載版本與來源，版本來源由四個擴為五個；偏離 issue #4 的「以相對路徑讀 `../../copier.yml`」（使用者 2026-10-20）。
- 退役的 `.claude/settings.json` 接受 copier update 的刪除行為並修改 REQ-TEMPLATE-004，不用 `_exclude`。
- plugin 路徑自成 `plugin` 模組。
- prospec 2.8.0 不支援目錄 symlink 的快照，由 benwu95/prospec#400 修正後才能記錄證據。

## Knowledge Update

template／example／plugin 三個 README、module-map 與 index 已在最終 review／tests／verify 前同步；commit 後依 UTC 日期重新 stamp，該差異另經 review 與測試重新驗證。

## Limitations

Grade A 的 late-capture 是驗收基準修訂的歷史限制，不代表 REQ 失敗。端到端驗收使用本機 loopback git fixture 與測試 tag，未發布正式 `v0.1.0`；repo 為 private，實際使用需 git 的 HTTPS 認證。「不自動觸發」主要以各家 skill 清單為證據，一般要求下模型會以檔案搜尋找到 repo。五個版本來源以外的 `0.1.0` 字面值（操作文件範例、測試 fixture）不受版本檢查，升版時需一併處理。
