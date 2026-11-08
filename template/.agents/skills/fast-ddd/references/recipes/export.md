# Recipe: export

Placeholders as in `references/workflows/aggregate.md`. Add this only when the user asks for an export; it is not generated with an aggregate.

## When to use

- The user asks to download a filtered list of one aggregate as a spreadsheet: `GET /<aggregates>/export` returns an `.xlsx` file of the same rows the list route would find with the same filters.
- The export is the search result plus a format conversion. It adds no domain behavior, so no use case, event or migration is involved.
- Every export has an upper bound on the number of rows (design §10, API4): `MAX_EXPORT_ROWS = 10_000`, the same bound as the list route's `offset`. A filter that matches more rows is rejected as a whole with 422; the file is never truncated. Larger exports need an asynchronous export job, which the framework does not provide.
- Not for a single resource (use get) or for feeding another service (publish integration messages instead).

## Files to change

- `pyproject.toml` and `uv.lock`: `uv add "openpyxl>=3.1,<4"` and `uv add --dev types-openpyxl`, in this service only; the stubs keep pyright strict passing.
- `app/core/<context>/domain/errors.py`: `<Aggregate>ExportTooLarge`.
- `app/adapter/controller/<context>/<aggregate>_controller.py`: `MAX_EXPORT_ROWS` and an `export` method.
- `app/port/export/__init__.py` and `app/port/export/xlsx.py`: the workbook writer, a port capability subpackage because openpyxl is a formatting dependency of the transport (see Shared code in `references/rules/layering.md`). Create the package marker, or `fast-ddd-check-packages` fails.
- `app/port/restful/<context>/<aggregate>_schemas.py`: `<Aggregate>ExportQuery` and the row mapping.
- `app/port/restful/<context>/<aggregate>_router.py`: `GET /<aggregates>/export`.
- `tests/support.py` (`ALL_PERMISSIONS`), `tests/port/test_<aggregate>_export.py`, `tests/test_error_catalog.py`.

## Rules to load

- `references/rules/api.md`: routes, 422, error code format, permissions.
- `references/rules/security.md`: tenant filtering, one permission per action, bounded resource use.
- `references/rules/time-and-serialization.md`: how timestamps and decimals are written.
- `references/rules/layering.md`: where openpyxl may be imported.

## Reference code

- `references/example/app/adapter/controller/billing/invoice_controller.py`: `search` calls `search_invoices` inside `execute`; `export` does the same with its own limit.
- `references/example/app/adapter/repository/billing/invoice_repository.py`: `search_invoices`, the filters and whitelists the export reuses.
- `references/example/app/port/restful/billing/invoice_schemas.py`: `InvoiceListQuery` and `to_query()`; the export query keeps its filter, search and sort fields and drops `offset` and `limit`.
- `references/example/app/port/restful/billing/invoice_router.py`: `list_invoices`.
- `references/example/app/core/billing/domain/errors.py`: how a `DomainError` declares `code`, `kind`, `message` and its params.

## Steps

1. Error: `@dataclass class <Aggregate>ExportTooLarge(DomainError)` with fields `total: int` and `limit: int`, `code = "<context>.<aggregate>.export_too_large"`, `kind = ErrorKind.INVALID` (422), and a message such as `"The export matches {total} rows; narrow the filters to at most {limit}"`.
2. Controller: define `MAX_EXPORT_ROWS = 10_000` next to the controller, then `async def export(self, query: Search<Aggregates>Query) -> list[<Aggregate>]`. Inside one `execute` (from `fast_ddd_adapter.controller`), first call `self._repository.search_<aggregates>(..., offset=0, limit=1)` with the query's filters only to read `total`, and raise `<Aggregate>ExportTooLarge(total=page.total, limit=MAX_EXPORT_ROWS)` when `total > MAX_EXPORT_ROWS`, so a rejected export loads at most one row. Otherwise call it again with `limit=MAX_EXPORT_ROWS`, check the new `total` the same way (rows may have been added in between), and return its `items`. The repository applies the tenant filter, the whitelists and the stable `id` order, exactly as for the list route.
3. Query model: `<Aggregate>ExportQuery(RequestModel)` repeats the list query's filter, `searchKeyField`/`searchKey` and `sortBy` fields with the same patterns and bounds, and has no `offset` or `limit`. Its `to_query()` builds the same `Search<Aggregates>Query` with `limit=MAX_EXPORT_ROWS` (import the constant from the controller).
4. Rows: a hand-written `export_row(<aggregate>) -> list[str | int | Decimal | None]` and a fixed header list beside the response models, the same way `from_domain()` is written. Format timestamps with `format_datetime` from `fast_ddd.serialization` (RFC 3339 UTC) and enum values as their lowercase value; never export fields the response model does not expose.
5. Writer: `app/port/export/xlsx.py` defines `def write_xlsx(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes` with `Workbook(write_only=True)`. Wrap every `str` value in a `WriteOnlyCell` and set `cell.data_type = "s"`: openpyxl otherwise stores a string that starts with `=` as a formula, which runs when the file is opened (formula injection). Before that, remove the control characters XML forbids with `ILLEGAL_CHARACTERS_RE.sub("", value)` from `openpyxl.cell.cell`: openpyxl raises `IllegalCharacterError` for them (a soft line break `\x0b` pasted from a word processor is enough), and the request schemas do not reject them, so one such row would fail the whole export with 500. Save into a `BytesIO` and return its bytes.
6. Route: `@router.get("/export", response_class=Response, responses={200: {"content": {XLSX: {}}}}, dependencies=[require("<aggregate>:export")])` with `require` from `fast_ddd_port.auth` where `XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`, function `export_<aggregates>(query: Annotated[<Aggregate>ExportQuery, Query()]) -> Response`. Call the controller, then build the file with `await asyncio.to_thread(write_xlsx, headers, rows)` so the event loop is not blocked, and return `Response(content, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="<aggregates>.xlsx"'})`. Route order does not matter: the `{<aggregate>_id:uuid}` convertor keeps `/export` from matching the get route.
7. Permission: `<aggregate>:export` is its own action because a bulk download exposes far more data than one read; add it to `ALL_PERMISSIONS` in `tests/support.py`.
8. Run `make error-catalog` if the service tracks the catalog, write the tests, then `make check`.

## Required tests

- `tests/port/test_<aggregate>_export.py`, following the API test setup of `references/example/tests/port/test_invoice_api.py`:
  - 200 with the xlsx media type and `Content-Disposition`; `openpyxl.load_workbook(BytesIO(response.content))` shows the header row and one row per matching aggregate, in the list route's order for the same filters.
  - Another organization's aggregates are absent (tenant filtering).
  - A text field that starts with `=` is read back as a string cell (`cell.data_type == "s"`), not a formula.
  - A text field that contains `\x0b` still exports with 200, and the cell reads back without it.
  - Over the limit: monkeypatch `MAX_EXPORT_ROWS` in the controller module to a small number, create one more aggregate than it, and assert 422 with code `<context>.<aggregate>.export_too_large` and params `total` and `limit`; exactly the limit still returns 200.
  - 401 without a token and 403 with a token that lacks `<aggregate>:export`, even when it holds `<aggregate>:read`.
  - 422 for an unknown query parameter or a sort field outside the whitelist, as for the list route.
- The error catalog test includes the new code (`references/example/tests/test_error_catalog.py`).

## Pitfalls

- Never page through the whole table in a loop to bypass the limit, and never accept a client-supplied limit above `MAX_EXPORT_ROWS`.
- Do not build the workbook in the controller or the domain: openpyxl stays in `app/port/`.
- Keep the export's filters identical to the list route's; a filter that exists only on the export is a second, untested search API.
