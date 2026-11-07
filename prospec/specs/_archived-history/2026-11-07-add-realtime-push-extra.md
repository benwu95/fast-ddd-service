# add-realtime-push-extra — Archive Summary

- **Archived**: 2026-11-07
- **Original Created**: 2026-11-06T16:39:20.840Z
- **Quality Grade**: A
- **Issue**: https://github.com/benwu95/fast-ddd-service/issues/5
- **Plan Decision**: hybrid (graded_by: in-session)

## User Story

As a 以 Socket.IO 接收即時更新的前端開發者，
I want 在連線時以 JWT 認證，並只能加入自己有權限的 room，
So that 即時推播與 HTTP API 遵守相同的認證、權限與 tenant 隔離。

另兩個 story：維護服務的 Python 開發者在 use case 中登記只在 commit 後送出、必有對象的推播（US-2）；未採用推播的服務不受 `realtime` extra 影響（US-3）。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| kernel | High | 新增 `fast_ddd_adapter/realtime.py`、`fast_ddd_port/realtime.py`、socketio stub；抽出 `ensure_permission`、`problem_json`；`realtime` optional extra 與 import contract |
| template | Low | root `uv.lock` 新增 realtime 與 dev 相依（example 不安裝 extra） |

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-KERNEL-011 | ADDED | 經 JWT 認證的即時推播連線 |
| REQ-KERNEL-012 | ADDED | 以權限與組織前綴保護的資源 room |
| REQ-KERNEL-013 | ADDED | commit 後才送出且必有對象的推播 |
| REQ-KERNEL-014 | ADDED | 以 optional extra 提供且只開放 WebSocket |

## Completion

- **Tasks**: 24/24 (100%), 1/1 [M]/[V] (not counted)
- **Acceptance Criteria**: 13/13 frozen scenarios（verify 2/5 無語意偏差）

## Review & Verify

- **Review**: 4 round(s), 1 critical / 8 major，全部修正並以 mutation 驗證的 regression 測試釘住；第 4 輪 review-clean。critical R1-1：publisher 連線逾時遺留無人持有、背景無限重連的 `RobustConnection`（獨立 verifier 實測 confirmed）。major 摘要：取消的 publish 關閉共用連線、close 殘留檢查的 oracle 恆真、被拒或未認證的 transport 佔用 server、資源 room 無上限、`Sequence[str]` 參數接受單一字串、`close()` 與建立中的連線競爭及關閉後重用、跨服務共用 fanout exchange、watcher 清理未被測試釘住。
- **Verify**: Grade A — 1/5 PASS、2/5 PASS（fresh-subagent，REQ 4/4）、3/5 PASS（7/7 rules）、4/5 WARN（既有 `plugin` 模組缺少目前版本的 `source_digest`，非本 change 範圍）、5/5 PASS、6 not-applicable；root `make check` exit 0。
- **Quality Log**: plan 第 1 輪 FAIL（上游 `AsyncAioPikaManager` 的 transient queue 被 RabbitMQ 4 拒絕），第 2、3 輪 WARN 收斂為 kernel 自有的 `KernelAioPikaManager`；tasks WARN（AC 對應與測試檔位置）已修正；review 4 輪皆 PASS；verify A。

## Knowledge Update

- `prospec/ai-knowledge/modules/kernel/README.md`、`prospec/ai-knowledge/modules/kernel/realtime.md`（新增子模組）
- `prospec/ai-knowledge/_conventions.md`、`prospec/ai-knowledge/module-map.yaml`、`prospec/index.md`
