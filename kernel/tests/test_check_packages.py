from pathlib import Path

import pytest

from fast_ddd_devtools.check_packages import find_problems, load_config, main

PYPROJECT = """
[tool.importlinter]
root_packages = ["app"]

[[tool.importlinter.contracts]]
name = "layers"
type = "layers"
layers = ["app.port", "app.adapter", "app.core"]

[[tool.importlinter.contracts]]
name = "settings"
type = "forbidden"
source_modules = ["app.core"]
forbidden_modules = ["app.settings", "pydantic"]
"""

INI = """
[importlinter]
root_package = app

[importlinter:contract:layers]
name = layers
type = layers
layers =
    app.port
    app.adapter | app.worker
    (app.core)
"""


def _make_package(root: Path, *modules: str) -> None:
    for module in modules:
        parts = module.split(".")
        directory = root.joinpath(*parts[:-1]) if module.endswith(".py") else root.joinpath(*parts)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").touch()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _make_package(tmp_path, "app", "app.port", "app.adapter", "app.core")
    (tmp_path / "app" / "settings.py").touch()
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    return tmp_path


def test_fully_covered_project_has_no_problems(project: Path) -> None:
    config = load_config(project / "pyproject.toml")

    assert find_problems(config, project) == []


def test_directory_without_init_is_reported(project: Path) -> None:
    hidden = project / "app" / "core" / "invoice"
    hidden.mkdir()
    (hidden / "entity.py").touch()

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert any("missing __init__.py" in problem for problem in problems)


def test_top_level_module_outside_contracts_is_reported(project: Path) -> None:
    (project / "app" / "bootstrap.py").touch()

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert problems == ["app.bootstrap: not covered by any import-linter contract"]


def test_ini_config_parses_layer_separators(tmp_path: Path) -> None:
    (tmp_path / ".importlinter").write_text(INI)

    config = load_config(tmp_path / ".importlinter")

    assert config.root_packages == ("app",)
    assert {"app.port", "app.adapter", "app.worker", "app.core"} <= config.referenced_modules


def test_main_returns_non_zero_on_problems(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "app" / "bootstrap.py").touch()

    exit_code = main(["--config", str(project / "pyproject.toml"), "--source-root", str(project)])

    assert exit_code == 1
    assert "app.bootstrap" in capsys.readouterr().err
