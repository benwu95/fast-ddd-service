import re
import shutil
from pathlib import Path

import pytest

from tests.template.support import ROOT, git, isolated_environment, run

RECIPE = ROOT / "template/.agents/skills/fast-ddd/references/recipes/app-lib.md"
LIB_MODULE = """def slug(text: str) -> str:
    return "-".join(text.lower().split())
"""
LIB_TEST = """from app.lib.text import slug


def test_slug_joins_lowercase_words() -> None:
    assert slug("Monthly  Invoice Run") == "monthly-invoice-run"
"""

# One import per contract the recipe adds app.lib to; a partial patch leaves one of them kept.
LEAKING_MODULE = """import pgqueuer
import pydantic

import app.core
import app.wiring

__all__ = ["app", "pgqueuer", "pydantic"]
"""
LIB_CONTRACTS = (
    "Layers: port > adapter > core",
    "Core has no framework, kernel adapter/port, or settings dependencies",
    "Only entry points import the composition root",
    "PgQueuer stays behind the kernel's TaskQueue",
)


def recipe_patch() -> str:
    blocks = re.findall(r"^```diff\n(.*?)^```$", RECIPE.read_text(), re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1
    return blocks[0]


def service_copy(generated_service: Path, destination: Path) -> Path:
    shutil.copytree(
        generated_service,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".coverage",
            ".coverage.*",
            ".pytest_cache",
            ".ruff_cache",
            ".import_linter_cache",
        ),
    )
    (destination / ".venv").symlink_to(generated_service / ".venv", target_is_directory=True)
    git(destination, "init", "-b", "main")
    return destination


def add_lib_module(service: Path) -> None:
    (service / "app/lib").mkdir()
    (service / "app/lib/__init__.py").write_text("")
    (service / "app/lib/text.py").write_text(LIB_MODULE)
    (service / "tests/lib").mkdir()
    (service / "tests/lib/__init__.py").write_text("")
    (service / "tests/lib/test_text.py").write_text(LIB_TEST)


def venv_entries(service: Path) -> set[str]:
    packages = next((service / ".venv/lib").glob("python*/site-packages"))
    return {path.name for path in packages.iterdir() if path.name != "__pycache__"}


@pytest.mark.parametrize("generated_service", ["path"], indirect=True)
def test_app_lib_recipe_contracts_pass_the_service_quality_gate(
    generated_service: Path, tmp_path: Path
) -> None:
    before = venv_entries(generated_service)
    service = service_copy(generated_service, tmp_path / "service")
    patch = tmp_path / "app-lib.diff"
    patch.write_text(recipe_patch())

    run(service, "git", "apply", str(patch))
    assert "    app.lib\n" in (service / ".importlinter").read_text()
    add_lib_module(service)
    checked = run(
        service, "make", "check", check=False, timeout=300, environment=isolated_environment()
    )

    assert checked.returncode == 0, checked.stdout + checked.stderr
    (service / "app/lib/leak.py").write_text(LEAKING_MODULE)
    leaked = run(service, "make", "imports", check=False, environment=isolated_environment())
    assert leaked.returncode != 0
    broken = {line.removesuffix(" BROKEN") for line in leaked.stdout.splitlines()}
    assert set(LIB_CONTRACTS) <= broken, leaked.stdout
    assert venv_entries(generated_service) == before


@pytest.mark.parametrize("generated_service", ["path"], indirect=True)
def test_app_lib_without_the_recipe_contracts_fails_contract_coverage(
    generated_service: Path, tmp_path: Path
) -> None:
    service = service_copy(generated_service, tmp_path / "service")
    add_lib_module(service)

    checked = run(service, "make", "imports", check=False, environment=isolated_environment())

    assert checked.returncode != 0
    output = checked.stdout + checked.stderr
    assert "app.lib" in output
    assert "not covered by any import-linter contract" in output
