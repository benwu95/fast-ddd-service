# Domain Core
> 提供不依賴框架的 domain primitive 與純資料規則。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `kernel/src/fast_ddd/aggregate.py` | Aggregate metadata 與事件收集 |
| `kernel/src/fast_ddd/events.py` | DomainEvent metadata |
| `kernel/src/fast_ddd/context.py` | ContextVar scope 與復原 |
| `kernel/src/fast_ddd/batch.py` | 集合載入與逐項 domain 結果 |
| `kernel/src/fast_ddd/repository.py` | Repository protocol |
| `kernel/src/fast_ddd/serialization.py` | JSON 值與 UTC 時間格式 |
| `kernel/src/fast_ddd/errors.py` | DomainError 與穩定錯誤代碼 |

## Public API
- `AggregateRoot.add_event()` — 補齊來源 aggregate metadata。
- `unit_of_work_context()`、`event_scope()` — 設定並復原呼叫脈絡。
- `apply_batch()`、`create_batch()` — 一次載入／儲存集合。
- `to_json(value, camel_case=False, exclude_fields=...)` — 遞迴序列化；排除只作用於根 dataclass。

## Dependencies
**Depends on:** 無內部 module；時間值使用 Pendulum。
**Used by:** kernel adapter／port 與 `example` core。

## Modification Guide
1. 新增 domain 規則 → aggregate 方法與 DomainError → `tests/core`。
2. 修改事件 metadata → events、aggregate、context → adapter 儲存與 MQ producer。
3. 修改 JSON 表達 → serialization → port models 與真實 producer contract；Mapping key 必須保留。

## Ripple Effects
- `Repository[Id, A]`／`BatchItem[Id, P]`／`BatchResult[Id, A]` 的 Id 沿 adapter、use case 到 port 傳遞。

## Pitfalls
- `pull_events()` 清空待存事件；repository 在 rollback 時以原順序與 identity 還原事件及持久化 metadata。
- `serialization.to_camel()` 是固定欄位、error params、aliases 與 catalog 的共同 owner；core 不依賴 Pydantic。
- naive datetime 無法序列化；金額以 Decimal，時間用 UTC。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
