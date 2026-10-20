# Time and serialization rules

Source: design §7.1–7.4 and the Constitution rule "Python 命名與 wire contract".

## Time

- Get the current time with `pendulum.now("UTC")`, and the start of the current UTC day with `pendulum.today("UTC")`. It returns a `pendulum.DateTime` at 00:00 UTC, not a date; the kernel's `to_json` and `Timestamp` handle only datetimes. ruff `TID251` bans `datetime.datetime.now`, `utcnow`, `today` and `datetime.date.today` (`ruff.toml`), and the `DTZ` rules reject naive datetimes; `make lint` runs both.
- Annotate time fields in domain and value objects as `pendulum.DateTime`.
- Map ORM time columns as `Mapped[pendulum.DateTime]`. The kernel's declarative base maps that to a `timestamptz` `TypeDecorator` that reads UTC `pendulum.DateTime` and rejects naive datetimes on write.
- The application sets timestamps; never use `server_default` or `onupdate` for them. `AggregateRoot` sets `created_at` on construction; `save_many` sets `version` and `updated_at` on every real change and writes them back to the aggregate.
- On the wire, time is an RFC 3339 string in UTC with a `Z` suffix and millisecond precision, such as `"2026-10-17T02:00:00.123Z"`. Never use Unix timestamps. The database keeps microseconds.
- In port models, type time fields as `Timestamp` from `fast_ddd_port.models`. It accepts offset-carrying strings and aware datetimes, converts them to UTC, and rejects strings without an offset, naive datetimes and numbers with 422.
- Outside port models (task payloads, notification data), format with `format_datetime` from `fast_ddd.serialization`, as `enqueue_daily_summaries` does in `references/example/app/adapter/controller/billing/invoice_controller.py`.
- Time values in error `params` use the same format.

## Serialization

Naming per boundary:

| Boundary | Field names | Mechanism |
|---|---|---|
| Python attributes: domain, dataclasses, commands, Pydantic fields, handler attributes | snake_case | plain Python |
| HTTP request body and query parameters | camelCase only | `RequestModel`: camelCase aliases only, `extra="forbid"` |
| HTTP response | camelCase | `ResponseModel` built by a hand-written `from_domain()` |
| Inbound MQ payload | camelCase | `MessageModel`: camelCase aliases only, `extra="ignore"` |
| Outbound MQ envelope and `data` | camelCase | `integration_message()` in `fast_ddd_adapter.messaging` |
| Database columns and the `domain_event` body | snake_case | repository mapping; `save_many` writes events with `to_json` |
| Keys of a business map (a `dict` value) | kept exactly as given | `to_json` and Pydantic convert only fixed field names |

- Write every conversion by hand: `RequestModel` to command (`to_command()`), domain to `ResponseModel` (`from_domain()`), ORM model to aggregate and back (`model_to_entity`/`entity_to_model`). Never use `from_attributes`, `TypeAdapter` or generic dict conversion. See `references/example/app/port/restful/billing/invoice_schemas.py`.
- Value types on the wire: Enum as its lowercase value, UUID as a string, Decimal as a string through `DecimalStr` (JSON numbers, `NaN` and `Infinity` are rejected), time through `Timestamp`, the ETag through `etag_of(version)`.
- Never rename business map keys by hand in either direction; the kernel converts fixed fields only, at the serialization boundary.
- PATCH requests: declare fields as `T | MISSING = MISSING` (Optional fields `T | MISSING | None = MISSING`), importing `MISSING` from `pydantic`. Convert with `unset_if_missing()` or `convert_unless_missing()` into command fields typed `T | Unset` from `fast_ddd_adapter.commands`; the controller combines them with `merge()`. Nested value objects are replaced whole.
- When a new field is added to data stored as JSONB, give the domain dataclass field an explicit default; old rows lack it.
- Outbound messages: an adapter event handler builds them with `integration_message(event, exchange=...)` and stages them with `publish_after_commit()`; see `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`. The envelope is fixed:

  ```json
  {"eventId": "…", "eventName": "InvoiceVoided", "eventVersion": 1,
   "organizationId": "…", "occurredAt": "2026-10-17T02:00:00.000Z",
   "data": {"reason": "…"}}
  ```

  `data` holds the event's own fields in camelCase; `eventVersion` is the event class's `VERSION`; `organizationId` comes from the aggregate that raised the event (`null` for a `"global"` aggregate). Trace context travels in message headers, never in the body.
- Inbound messages: declare the payload as a `MessageModel` subclass; the kernel's `subscribe()` parses the envelope. Unknown fields are ignored, a message without `organizationId` goes to the DLQ, and a `null` `organizationId` reaches only subscribers registered with `accepts_global=True`. See `references/example/app/port/message_queue/customer/customer_subscriber.py`.
