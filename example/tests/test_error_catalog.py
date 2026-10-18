import json
import re
from pathlib import Path
from typing import Any

from fast_ddd.errors import DomainError
from fast_ddd_devtools.error_catalog import main

from app.core.billing.domain import errors, invoice


def catalog(tmp_path: Path) -> dict[str, dict[str, Any]]:
    output = tmp_path / "errors.json"
    assert main([errors.__name__, invoice.__name__, "--output", str(output)]) == 0
    return {entry["code"]: entry for entry in json.loads(output.read_text())}


def test_service_codes_are_listed_with_status_and_params(tmp_path: Path) -> None:
    entries = catalog(tmp_path)

    assert {
        code: (entry["status"], entry["params"])
        for code, entry in entries.items()
        if code.startswith("billing.")
    } == {
        "billing.invoice.already_exists": (409, ["aggregateType", "aggregateId"]),
        "billing.invoice.already_voided": (409, ["invoiceId", "voidedAt"]),
        "billing.invoice.no_lines": (422, []),
        "billing.invoice.not_found": (404, ["aggregateType", "aggregateId"]),
        "billing.invoice.number_taken": (409, []),
    }


def test_message_placeholders_match_params(tmp_path: Path) -> None:
    for code, entry in catalog(tmp_path).items():
        if "message" in entry:
            placeholders = sorted(re.findall(r"{(\w+)}", entry["message"]))
            assert placeholders == sorted(entry["params"]), code


def test_every_service_error_is_in_the_catalog(tmp_path: Path) -> None:
    entries = catalog(tmp_path)
    service_errors = [
        error for error in DomainError.registry.values() if error.__module__.startswith("app.")
    ]

    assert service_errors
    assert all(error.code in entries for error in service_errors)
