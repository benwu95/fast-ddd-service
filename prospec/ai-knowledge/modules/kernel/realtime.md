# Realtime Push
> 以 optional extra `fast-ddd-kernel[realtime]` 提供 commit 後推播、Socket.IO 連線認證與資源 room 權限。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `kernel/src/fast_ddd_adapter/realtime.py` | room 命名、`KernelAioPikaManager`、emitter 與 `push_after_commit` |
| `kernel/src/fast_ddd_port/realtime.py` | `mount_realtime`、連線認證、join／leave 與 `RealtimeServer` |
| `kernel/typings/socketio/*.pyi` | python-socketio 無 `py.typed`，kernel 只宣告用到的成員 |
| `kernel/tests/realtime_support.py` | uvicorn＋真 Socket.IO client 的測試 helper 與 listener 就緒探測 |

## Public API
- `push_after_commit(event_name, event_version, data, *, organization, users, resources)` — 登記 after-commit 推播；body 固定 `eventName`／`eventVersion`／`data`。
- `create_realtime_emitter(url, *, service)`、`configure_realtime(emitter)` — 每個程序的 write-only 發送端；關閉時 `await emitter.close()`，之後的推播失敗。
- `mount_realtime(app, *, verifier, resources, rabbitmq_url, service, ...)` → `RealtimeServer` — 掛載只開 WebSocket 的端點；關閉時 `await server.close()`。
- `organization_room()`／`user_room()`／`resource_room()` — room 命名的唯一 owner；資源 room 為 `org:{org}:{resource}:{id}`。
- `ensure_permission(principal, permission)`、`problem_json(problem)`（`fast_ddd_port`）— HTTP 與 realtime 共用的權限規則與 problem+json。

## Dependencies
**Depends on:** python-socketio（extra）、aio-pika；`SessionProvider.after_commit`、`JwtVerifier`、`kernel_problem`。
**Used by:** 採用即時推播 recipe 的服務（example／template 尚未接線）。

## Modification Guide
1. 改 room 規則 → 只改 adapter 的 room 函式；port 的 join 與推播都呼叫它們，並更新跨組織隔離測試。
2. 改連線或 join 行為 → `fast_ddd_port/realtime.py` 的 `_Handlers`；拒絕內容沿用 `problem_json`，不新增 `KERNEL_CODES`。
3. 升級 python-socketio → 先跑 `tests/test_socketio_stubs.py` 與 RabbitMQ 4 跨實例測試；extra 鎖在 `<5.19`。

## Pitfalls
- 空 room 清單在 socketio 等於廣播；`push_after_commit` 與 emitter 都在登記／送出前拒絕。
- 上游 `AsyncAioPikaManager` 的 transient queue 被 RabbitMQ 4 拒絕；kernel 的 manager 宣告 exclusive queue，不可換回。
- listener 在第一個連線才啟動，之前的推播沒有接收者；測試先以探測推播等待就緒。
- 不用 `aio_pika.connect_robust()`：逾時或取消後它的背景 factory 會無限重連；`_connect` 先建立 `RobustConnection` 再 `connect()`，失敗時在 shield 下關閉。
- 單次 publish 被取消不關閉共用連線；失敗時只丟棄該次嘗試自己的連線。
- 被拒絕的 client 連線會遺留 aiohttp session；測試以外部 `http_session` 自行關閉。
- `realtime` 兩個模組不得由套件 `__init__` import；未安裝 extra 時 import 會提示安裝。
- `cors_allowed_origins=None` 只允許同源，scheme 取自 `X-Forwarded-Proto`。
- `_KernelSocketServer` 結束被拒絕、或超過 `connect_timeout_seconds` 仍未認證的 Engine.IO session；每連線資源 room 上限為 `max_resource_rooms`。
- `RealtimeServer.close()` 可重複呼叫（engineio 的 `shutdown()` 本身不行）；之後新的 transport 一律被拒，manager 也主動關閉 listener 連線，不等 generator finalizer。
- exchange 依 `service` 命名（`realtime_channel()`）；emitter 與 `mount_realtime` 必須用同一個服務名稱，否則收不到。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
