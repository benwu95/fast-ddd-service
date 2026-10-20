import sys
from pathlib import Path

import yaml
from copier import run_copy

from tests.template.support import ROOT, run

KERNEL_VERSION_SCRIPT = "template/.agents/skills/fast-ddd/scripts/check_kernel_version.py"


def test_framework_check_runs_template_tools_and_drift() -> None:
    for target in ("tooling", "template-check", "template-ownership", "template-references"):
        result = run(ROOT, "make", "-n", target, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    commands = run(ROOT, "make", "-n", "check").stdout.splitlines()
    assert [
        line.rsplit("python ", 1)[1]
        for line in commands
        if "python scripts/check_template.py" in line
    ] == ["scripts/check_template.py --snapshot"]
    gates = (
        f"ruff format --check scripts template {KERNEL_VERSION_SCRIPT}",
        f"ruff check scripts template {KERNEL_VERSION_SCRIPT}",
        f"pyright --project example/pyrightconfig.json scripts {KERNEL_VERSION_SCRIPT}",
        "pre-commit run check-merge-conflict --all-files",
        "python scripts/check_versions.py",
        "coverage run -m pytest",
        "python scripts/check_template.py --snapshot",
    )
    positions = [
        [index for index, line in enumerate(commands) if line.endswith(gate)] for gate in gates
    ]
    assert [len(found) for found in positions] == [1, 1, 1, 1, 1, 2, 1]
    assert [index for found in positions for index in found] == sorted(
        index for found in positions for index in found
    )
    (kernel_version,) = [
        index
        for index, line in enumerate(commands)
        if line.endswith("python -I .agents/skills/fast-ddd/scripts/check_kernel_version.py")
    ]
    kernel_tests, example_tests = positions[5]
    assert kernel_tests < kernel_version < example_tests
    workflow = yaml.safe_load((ROOT / ".github/workflows/check.yml").read_text())
    commands = [step["run"] for step in workflow["jobs"]["quality"]["steps"] if "run" in step]
    assert commands == ["uv sync --frozen --all-packages --all-groups", "make check"]


def test_standalone_tools_run_from_the_service_root(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    result = run(tmp_path, "make", "-n", "check", check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].endswith(
        "uv run --no-project --python 3.13 python -I "
        ".agents/skills/fast-ddd/scripts/check_kernel_version.py"
    )
    assert "make -C kernel" not in result.stdout
    assert "make -C example" not in result.stdout
    assert "coverage run -m pytest" in result.stdout
    hooks = yaml.safe_load((tmp_path / ".pre-commit-config.yaml").read_text())
    all_hooks = [hook for repo in hooks["repos"] for hook in repo["hooks"]]
    merge = next(hook for hook in all_hooks if hook["id"] == "check-merge-conflict")
    assert merge["args"] == ["--assume-in-merge"]
    workflow = yaml.safe_load((tmp_path / ".github/workflows/check.yml").read_text())
    commands = [step.get("run", "") for step in workflow["jobs"]["quality"]["steps"]]
    assert "make check" in commands
    assert any("check-merge-conflict --all-files" in command for command in commands)
    migration = run(tmp_path, "make", "-n", "migration", "name=add a field").stdout
    assert "--head service@head" in migration
    assert "--version-path alembic/versions" in migration


def test_standalone_ruff_skips_the_skill_reference_copy(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    unformatted = "import os\nx=1\n"
    reference = tmp_path / ".agents/skills/fast-ddd/references/example/app/sample.py"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text(unformatted)
    for command in (("check", "."), ("format", "--check", ".")):
        result = run(tmp_path, sys.executable, "-m", "ruff", *command, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    (tmp_path / "app/sample.py").write_text(unformatted)
    for command in (("check", "."), ("format", "--check", ".")):
        result = run(tmp_path, sys.executable, "-m", "ruff", *command, check=False)
        assert result.returncode == 1, result.stdout + result.stderr
