import argparse
import dataclasses
import importlib
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.errors import DomainError, humanize_class_name
from fast_ddd.serialization import to_camel
from fast_ddd_port.problems import KERNEL_CODES, KIND_STATUS


def _all_subclasses[T](cls: type[T]) -> Iterator[type[T]]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _all_subclasses(subclass)


def build_catalog() -> list[dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for code, (status, title) in KERNEL_CODES.items():
        entries[code] = {"code": code, "status": status, "title": title, "params": []}
    for code, error_class in DomainError.registry.items():
        entries[code] = {
            "code": code,
            "status": KIND_STATUS[error_class.kind],
            "title": humanize_class_name(error_class.__name__),
            "params": [to_camel(f.name) for f in dataclasses.fields(error_class)],
            "message": error_class.message,
        }
    for aggregate in _all_subclasses(AggregateRoot):
        if not hasattr(aggregate, "bounded_context"):
            continue
        namespace = aggregate.error_namespace()
        for suffix, status in (("not_found", 404), ("already_exists", 409)):
            code = f"{namespace}.{suffix}"
            entries[code] = {
                "code": code,
                "status": status,
                "title": f"{aggregate.aggregate_type()} {suffix.replace('_', ' ')}",
                "params": ["aggregateType", "aggregateId"],
            }
    return sorted(entries.values(), key=lambda entry: str(entry["code"]))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write every error code as JSON.")
    parser.add_argument("modules", nargs="*", help="modules that define DomainErrors/aggregates")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    for module in args.modules:
        importlib.import_module(module)
    document = json.dumps(build_catalog(), indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(document)
    else:
        args.output.write_text(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
