# render-utcdatetime-in-migrations — Archive Summary

- **Archived**: 2026-10-24
- **Original Created**: 2026-10-23
- **Quality Grade**: A
- **Issue**: https://github.com/benwu95/fast-ddd-service/issues/11

## User Story

As a 以 template 建立服務並新增 aggregate 的 Python 開發者（或代為操作的 coding agent），
I want `make migration name=...` 產生的 revision 把 `UtcDateTime` 欄位寫成資料庫層級的 `sa.DateTime(timezone=True)`，
So that 第一個業務 migration 不需手動修改就能升降版並通過 schema check。

## Affected Modules

| Module | Impact | Description |
|--------|--------|-------------|
| kernel | Medium | `fast_ddd_adapter.migrations.render_item`：`UtcDateTime` 以其 `impl` 與設定的 `sqlalchemy_module_prefix` 渲染，其他型別交回 alembic 預設；adapter 知識新增 hooks 與自訂型別 Pitfall |
| template | Medium | `alembic/env.py` 的 online 與 offline `context.configure` 傳入 `render_item` |
| example | Low | `alembic/env.py` 與 template 一致；產生服務的第一個業務 migration e2e 加入 `UtcDateTime` 欄位 |

## Requirements

| REQ ID | Status | Description |
|--------|--------|-------------|
| REQ-TEMPLATE-002 | MODIFIED | autogenerate 將 `UtcDateTime` 寫成 `sa.DateTime(timezone=True)`、不引用 kernel 模組，revision 不需手改即可升降版；其他型別維持 alembic 預設；template／example `env.py` 兩處 configure 套用同一 hook |

## Completion

- **Tasks**: 5/5 code tasks（100%）；4 個 `[V]` 驗證任務亦完成
- **Acceptance Criteria**: 4/4（acceptance revision 3）

## Review & Verify

- **Review**: 2 個 review loop 共 6 rounds（fresh-subagent），0 critical / 0 major，6 minor 全數修正——R-1 前綴行為補測試、R-2 變更產物與實作對齊、R-3 改由 `UtcDateTime.impl` 單一來源渲染、R-4／R-5 修正渲染成因與 `NameError` 時機措辭（第二次出現後整類掃除）、R-6 change description 改為繁體中文（經人工授權單行修改 metadata）
- **Verify**: Grade A；machine ledger task-completion／knowledge／tests 皆 PASS（`make check` exit 0：kernel 336 passed、coverage 95%；example 367 passed、coverage 99%；template／example 無漂移）；judgment ledger constitution PASS（7 條規則逐條陳述）、design not-applicable、delta-spec-compliance not-adjudicated——grader 逐條判 REQ-TEMPLATE-002 PASS，但 acceptance baseline 在 story 後修訂（late-capture），CLI 規則不給 PASS，S 不可達
- **Quality Log**: plan verifier WARN（10 項：offline autogenerate 不存在、Spec statement 過度宣稱、版本耦合、prefix 等，均已落實修正）；tasks verifier WARN（TDD 紅燈排序、TypeDecorator 邊界、offline 檢查、Summary 格式，均已修正）；implement WARN（移除不可觀察的 `type_ == "type"` 判斷）；review 3 筆 WARN 為各 round 帶出的 open minor，最終輪 PASS；另有一筆 review PASS 寫在被拒的 merge 之後，無對應 round；verify WARN：late-capture baseline

## Knowledge Update

- `prospec/ai-knowledge/modules/kernel/adapter.md`（Public API、Pitfalls）已更新；kernel／template／example 已以 `prospec knowledge verify` 戳記
