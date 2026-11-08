# Recipe: shared core code in `app/lib`

Add this only when the user asks for code shared by the core of several bounded contexts, or a workflow reaches that case. Neither the template nor the reference service creates `app/lib` (design §6.4).

## When to use

- Code that the core of two or more bounded contexts of this service needs, using nothing beyond the standard library and pendulum: a value object such as `Money`, a date-range helper, a checksum.
- Not for code one context uses (keep it in that context), not for code that depends on SQLAlchemy, an HTTP client or another SDK (a capability subpackage of the layer that owns the dependency), and not for code other services need (the kernel or a separate distribution). The full table is Shared code in `references/rules/layering.md`; the reasons are in "Where shared code lives" in `references/decisions.md`.
- Never under `app/core/`: the `bounded-contexts` independence contract treats every `app.core.*` package as a context, so no other context could import it.

## Files to change

- `.importlinter`: the four changes below, all in the same change.
- `app/lib/__init__.py` and one module per topic, such as `app/lib/money.py`.
- `tests/lib/__init__.py` and `tests/lib/test_<module>.py`.
- The bounded contexts' domain modules that import from `app.lib`.

## Rules to load

- `references/rules/layering.md`: layers, contracts and `fast-ddd-check-packages`.
- `references/rules/time-and-serialization.md`: value objects and time handling.
- `references/rules/testing.md`: unit tests and coverage.

## Reference code

- `references/example/app/core/billing/domain/invoice.py`: frozen value objects (`Customer`, `InvoiceLine`) and `Decimal` amounts, the style of code that belongs in `app/lib` once two contexts share it.
- `references/example/tests/core/test_invoice.py`: plain unit tests without a database.

## Steps

1. Apply the contract change. `app.lib` becomes the lowest layer, and it gets the same limits as `app.core` in the `core`, `composition` and `task-queue` contracts. From the service root, save the block below as a file and run `git apply <file>`; if `.importlinter` was customized and the patch does not apply, make the same four edits by hand.

```diff
--- a/.importlinter
+++ b/.importlinter
@@ -11,12 +11,14 @@
     app.port
     app.adapter
     app.core
+    app.lib
 
 [importlinter:contract:core]
 name = Core has no framework, kernel adapter/port, or settings dependencies
 type = forbidden
 source_modules =
     app.core
+    app.lib
 forbidden_modules =
     fast_ddd_adapter
     fast_ddd_port
@@ -58,6 +60,7 @@
     app.core
     app.adapter
     app.port
+    app.lib
 forbidden_modules =
     app.bootstrap
     app.wiring
@@ -72,5 +75,6 @@
     app.core
     app.adapter
     app.port
+    app.lib
 forbidden_modules =
     pgqueuer
```

2. Create `app/lib/__init__.py` and the module. `fast-ddd-check-packages` fails while `app.lib` appears in no contract, but it cannot see a partial change: with only the `layers` entry, `app.lib` could still import Pydantic or `app.settings`. Apply all four edits.
3. Write the shared code like domain code: frozen dataclasses, no I/O, no framework imports, no reads from context. `app.lib` must not import `app.core`, `app.adapter` or `app.port`; the `layers` contract enforces it.
4. Move the duplicated code out of the bounded contexts and import it from `app.lib` in each of them.
5. Write the tests, then `make check`. `make imports` runs both `fast-ddd-check-packages` and `lint-imports`.

## Required tests

- `tests/lib/test_<module>.py`: unit tests for every public function and value object, including the invariants it rejects. Coverage counts `app/lib` like the rest of `app`.
- The existing domain tests of each context that now imports from `app.lib` keep passing.
- The framework's CI applies this recipe's patch to a generated service and runs `make check`, so the patch matches the template's `.importlinter`.
