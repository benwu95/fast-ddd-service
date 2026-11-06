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


def test_intermediate_directory_without_init_is_reported(project: Path) -> None:
    _make_package(project, "app.core.billing.domain")
    (project / "app" / "core" / "billing" / "domain" / "entity.py").touch()

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert problems == [
        f"{project / 'app' / 'core' / 'billing'}: missing __init__.py, import-linter would skip it"
    ]


def test_each_missing_intermediate_directory_is_reported_in_path_order(project: Path) -> None:
    _make_package(project, "app.core.ctx.sub.inner", "app.core.ctx.sub.deep.leaf", "app.core.a.b")
    missing = ["a", "ctx", "ctx/sub", "ctx/sub/deep"]

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert problems == [
        f"{project / 'app' / 'core' / name}: missing __init__.py, import-linter would skip it"
        for name in missing
    ]


def test_directories_without_python_modules_are_not_reported(project: Path) -> None:
    static = project / "app" / "core" / "static" / "css"
    static.mkdir(parents=True)
    (static / "style.css").touch()
    for hidden in ("__pycache__", ".cache"):
        directory = project / "app" / "core" / "billing" / hidden
        directory.mkdir(parents=True)
        (directory / "module.py").touch()
    deep = project / "app" / ".hidden" / "deep"
    deep.mkdir(parents=True)
    (deep / "module.py").touch()

    assert find_problems(load_config(project / "pyproject.toml"), project) == []


def test_symlinked_directory_without_init_is_reported(project: Path, tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / "module.py").touch()
    (project / "app" / "core" / "linked").symlink_to(external, target_is_directory=True)

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert problems == [
        f"{project / 'app' / 'core' / 'linked'}: missing __init__.py, import-linter would skip it"
    ]


def test_symlink_cycle_is_walked_once(project: Path) -> None:
    _make_package(project, "app.core.billing.domain", "app.port.restful.billing")
    (project / "app" / "core" / "billing" / "domain" / "entity.py").touch()
    domain = project / "app" / "core" / "billing" / "domain"
    (domain / "loop").symlink_to(project / "app" / "core", target_is_directory=True)
    (domain / "root").symlink_to(project / "app", target_is_directory=True)

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert problems == [
        f"{project / 'app' / name}: missing __init__.py, import-linter would skip it"
        for name in ("core/billing", "port/restful")
    ]


def test_symlinks_to_one_directory_from_distinct_paths_are_each_walked(
    project: Path, tmp_path: Path
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "__init__.py").touch()
    (project / "app" / "core" / "a").symlink_to(shared, target_is_directory=True)
    (project / "app" / "core" / "zz").mkdir()
    (project / "app" / "core" / "zz" / "inner").symlink_to(shared, target_is_directory=True)

    problems = find_problems(load_config(project / "pyproject.toml"), project)

    assert problems == [
        f"{project / 'app' / 'core' / 'zz'}: missing __init__.py, import-linter would skip it"
    ]


def test_unreadable_directory_fails_instead_of_being_skipped(project: Path) -> None:
    locked = project / "app" / "core" / "locked"
    locked.mkdir()
    (locked / "__init__.py").touch()
    locked.chmod(0)
    try:
        with pytest.raises(PermissionError):
            find_problems(load_config(project / "pyproject.toml"), project)
    finally:
        locked.chmod(0o755)


def test_source_root_under_hidden_or_parent_path_is_still_checked(tmp_path: Path) -> None:
    service = tmp_path / ".checkout" / "svc"
    _make_package(service, "app", "app.port", "app.adapter", "app.core", "app.core.billing.domain")
    (service / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / ".checkout" / "other").mkdir()
    source_root = tmp_path / ".checkout" / "other" / ".." / "svc"

    problems = find_problems(load_config(service / "pyproject.toml"), source_root)

    assert problems == [
        f"{source_root / 'app' / 'core' / 'billing'}: missing __init__.py, "
        "import-linter would skip it"
    ]


def test_main_returns_non_zero_on_missing_intermediate_init(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(project, "app.port.restful.billing")

    exit_code = main(["--config", str(project / "pyproject.toml"), "--source-root", str(project)])

    assert exit_code == 1
    assert f"{project / 'app' / 'port' / 'restful'}: missing __init__.py" in capsys.readouterr().err


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
