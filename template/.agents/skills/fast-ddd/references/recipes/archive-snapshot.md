# Recipe: archive snapshots

Placeholders as in `references/workflows/aggregate.md`. Archive is off by default (`archive_model_class = None`); turn it on only when the user asks for it on a specific aggregate.

## When to use

- The aggregate must answer "what was its complete state at time T", such as orders and payments, where a snapshot is direct evidence in disputes and reconciliation. See "When to enable archive snapshots" in `references/decisions.md` for why `domain_event` cannot replace it.
- Not for showing users a change log; that is `references/recipes/operation-history.md`.
- Not for every aggregate: each saved change and each delete writes one more row.

## Files to change

- `app/adapter/repository/<context>/<aggregate>_model.py`: `<Aggregate>ArchiveModel`.
- `app/adapter/repository/<context>/<aggregate>_repository.py`: `archive_model_class = <Aggregate>ArchiveModel`.
- `alembic/versions/`: `make migration name="add <aggregate> archive"`.
- `tests/adapter/test_<aggregate>_repository.py`, and the archive table in the truncate list of the `session_factory` fixture in `tests/conftest.py`.

`app/adapter/repository/models.py` needs no change when the archive model lives in the module that is already registered there.

## Rules to load

- `references/rules/security.md`: `organization_id` on every table, tenant filtering on custom queries.
- `references/rules/testing.md`: repository integration tests and the migration checks.
- `references/rules/time-and-serialization.md`: `archived_at` and the copied timestamps are UTC.

## Reference code

- `references/example/app/adapter/repository/billing/invoice_model.py`: the aggregate model whose columns the archive repeats.
- `references/example/app/adapter/repository/billing/invoice_repository.py`: where `archive_model_class` is set, beside `aggregate_class`, `model_class` and `tenant_scope`.
- `references/example/tests/adapter/test_invoice_repository.py`: repository test setup.

## Steps

1. Model: `class <Aggregate>ArchiveModel(ArchiveModel)` from `fast_ddd_adapter.repository`, `__tablename__ = "<context>_<aggregate>_archive"`. `ArchiveModel` adds `archive_id` (primary key), an indexed `id`, `archived_at`, `event_id` and `event_name`; never redeclare `id`.
2. Repeat, under the same names and types, every root column the snapshot must keep, always including `organization_id` (`Mapped[UUID | None]`, design §10.2) and `version`. Leave out unique constraints, foreign keys and server defaults: an archive holds many rows per aggregate and outlives a deleted one.
3. Repository: set `archive_model_class = <Aggregate>ArchiveModel`. `save_many` copies the columns whose names match when the aggregate actually changed or was deleted, and records the last event of that save in `event_id`/`event_name`. Creation writes no snapshot; the version-1 state is the creation event and the row itself.
4. Child tables are not copied: only columns of the root model reach the archive. When the snapshot must include child entities (such as invoice lines), say so to the user before changing the storage; keeping children as a JSON column on the root model instead of a child table is the only way the kernel copies them.
5. Migration: `make migration name="add <aggregate> archive"`, then review that the new table has `organization_id` and the index on `id`. Add the table to the truncate list of the `session_factory` fixture in `tests/conftest.py`, as `references/rules/testing.md` requires for every new table.
6. Reading snapshots back is a separate request. When it is asked for, query the archive model with an explicit `<Aggregate>ArchiveModel.organization_id == <organization>` condition (`tenant_conditions()` builds conditions on the aggregate model, not the archive), and test that another organization reads nothing.
7. Write the tests, then `make check`.

## Required tests

In `tests/adapter/test_<aggregate>_repository.py`, following the repository setup of `references/example/tests/adapter/test_invoice_repository.py`:

- Creating an aggregate writes no snapshot.
- An update that changes data writes one snapshot with the new `version`, the changed columns, `organization_id`, and `event_name`/`event_id` of the triggering event; the `event_id` matches a `domain_event` row (`DomainEventModel` from `fast_ddd_adapter.orm`).
- A save that changes nothing writes no snapshot.
- A delete writes a snapshot of the last state, and the snapshot remains after the aggregate row is gone.
- A batch (`save_many` over N aggregates) writes N snapshots in the same flush.
- `tests/runtime/test_migrations.py` already checks that the models have no pending migration.

## Pitfalls

- Do not snapshot from a domain method or an event handler; the repository does it inside the same flush.
- Do not store an operation-history array on the aggregate row; every snapshot would copy it and storage grows quadratically (design §7.5).
