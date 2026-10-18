import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast

import pytest


class Position(TypedDict):
    line: int


class DiagnosticRange(TypedDict):
    start: Position


class Diagnostic(TypedDict):
    severity: str
    rule: str
    range: DiagnosticRange


class PyrightReport(TypedDict):
    generalDiagnostics: list[Diagnostic]


@pytest.mark.parametrize("fixture", ["positive", "negative"])
def test_invoice_id_typing_contract(fixture: str, tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    source = (project / "tests" / "typing_contracts" / f"{fixture}.py.txt").read_text()
    target = tmp_path / f"{fixture}.py"
    target.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(project / "pyrightconfig.json"),
            "--outputjson",
            str(target),
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    report = cast(PyrightReport, json.loads(result.stdout))
    diagnostics = report["generalDiagnostics"]
    if fixture == "positive":
        assert result.returncode == 0, result.stdout + result.stderr
        assert diagnostics == []
        return
    expected_lines = {
        node.lineno - 1 for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Await)
    }
    assert len(expected_lines) == 11
    assert result.returncode == 1, result.stdout + result.stderr
    assert {item["range"]["start"]["line"] for item in diagnostics} == expected_lines, result.stdout
    assert len(diagnostics) == len(expected_lines), result.stdout
    assert all(
        item["severity"] == "error" and item["rule"] == "reportArgumentType" for item in diagnostics
    ), result.stdout
