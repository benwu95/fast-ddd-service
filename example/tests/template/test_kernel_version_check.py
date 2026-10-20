import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_versions import MARKDOWN_FIELD
from tests.template.support import ROOT

SCRIPT = ROOT / "template/.agents/skills/fast-ddd/scripts/check_kernel_version.py"
SKILL = ".agents/skills/fast-ddd/SKILL.md"
FAILURE = "fast-ddd kernel version check failed"


def fields(version: str, lock: str) -> str:
    return f"# fast-ddd\n\n- Kernel version: `{version}`\n- Kernel lock: `{lock}`\n"


def lock_text(version: str, name: str = "fast-ddd-kernel") -> str:
    return (
        'version = 1\nrequires-python = ">=3.13"\n\n'
        f'[[package]]\nname = "{name}"\nversion = "{version}"\n'
        'source = { git = "https://example.invalid/kernel?tag=v0#0" }\n'
    )


def service(root: Path, skill: str | None, lock: str | None, lock_name: str = "uv.lock") -> Path:
    root.mkdir(parents=True)
    if skill is not None:
        path = root / SKILL
        path.parent.mkdir(parents=True)
        path.write_text(skill)
    if lock is not None:
        (root / lock_name).write_text(lock)
    return root


def tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def check(root: Path) -> subprocess.CompletedProcess[str]:
    before = tree(root.parent)
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert tree(root.parent) == before
    return result


def test_matching_versions_pass(tmp_path: Path) -> None:
    root = service(tmp_path / "service", fields("0.1.0", "uv.lock"), lock_text("0.1.0"))

    result = check(root)

    assert result.returncode == 0, result.stderr
    assert "0.1.0" in result.stdout


@pytest.mark.parametrize(("skill", "locked"), [("0.2.0", "0.1.0"), ("0.1.0", "0.2.0")])
def test_mismatched_versions_fail_with_both_values(tmp_path: Path, skill: str, locked: str) -> None:
    root = service(tmp_path / "service", fields(skill, "uv.lock"), lock_text(locked))

    result = check(root)

    assert result.returncode == 1
    assert result.stderr.startswith(FAILURE)
    assert f"`{skill}`" in result.stderr
    assert f"`{locked}`" in result.stderr
    assert "docs/template-operations.md" in result.stderr


@pytest.mark.parametrize(
    ("lock", "reason"),
    [(None, "uv lock"), (lock_text("0.1.0", name="other-package"), "no fast-ddd-kernel")],
)
def test_missing_lock_or_kernel_package_fails(
    tmp_path: Path, lock: str | None, reason: str
) -> None:
    root = service(tmp_path / "service", fields("0.2.0", "uv.lock"), lock)

    result = check(root)

    assert result.returncode == 1
    assert result.stderr.startswith(FAILURE)
    assert reason in result.stderr
    assert "`0.2.0`" in result.stderr
    assert str(root) not in result.stderr


@pytest.mark.parametrize(
    "skill",
    [
        None,
        "# fast-ddd\n\n- Kernel lock: `uv.lock`\n",
        "# fast-ddd\n\n- Kernel version: `0.1.0`\n",
        fields("0.1.0", "uv.lock") + "- Kernel version: `0.2.0`\n",
    ],
    ids=["no-skill", "no-version", "no-lock", "duplicate-version"],
)
def test_unreadable_skill_fields_fail(tmp_path: Path, skill: str | None) -> None:
    root = service(tmp_path / "service", skill, lock_text("0.1.0"))

    result = check(root)

    assert result.returncode == 1
    assert result.stderr.startswith(FAILURE)


def test_workspace_lock_is_read_from_the_parent(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(lock_text("0.1.0"))
    root = service(tmp_path / "service", fields("0.1.0", "../uv.lock"), lock_text("9.9.9"))

    result = check(root)

    assert result.returncode == 0, result.stderr


def test_framework_example_matches_the_workspace_lock() -> None:
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--root", str(ROOT / "example")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_skill_fields_use_the_framework_version_field_format() -> None:
    rendered = fields("1.2.3", "../uv.lock")

    assert dict(MARKDOWN_FIELD.findall(rendered)) == {
        "Kernel version": "1.2.3",
        "Kernel lock": "../uv.lock",
    }
    template = (ROOT / "template/.agents/skills/fast-ddd/SKILL.md.jinja").read_text()
    assert [name for name, _ in MARKDOWN_FIELD.findall(template)] == [
        "Kernel version",
        "Kernel lock",
    ]


def test_make_target_surfaces_the_mismatch_message(tmp_path: Path) -> None:
    root = service(tmp_path / "service", fields("0.2.0", "uv.lock"), lock_text("0.1.0"))
    script = root / ".agents/skills/fast-ddd/scripts" / SCRIPT.name
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    (root / "Makefile").write_bytes((ROOT / "template/Makefile").read_bytes())

    result = subprocess.run(
        ["make", "kernel-version"], cwd=root, check=False, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "skill expects fast-ddd-kernel `0.2.0`; lock uv.lock has `0.1.0`" in result.stderr
    assert result.stderr.splitlines()[0].startswith(FAILURE)


BOTH_SIDES = re.compile(
    rf"^{FAILURE}: skill expects fast-ddd-kernel (`[^`]+`|unknown); lock \S+ has (`[^`]+`|unknown)"
)


@pytest.mark.parametrize(
    ("skill", "lock", "expected", "locked"),
    [
        (fields("0.2.0", "uv.lock"), lock_text("0.1.0"), "`0.2.0`", "`0.1.0`"),
        (fields("0.2.0", "uv.lock"), None, "`0.2.0`", "unknown"),
        (fields("0.2.0", "uv.lock"), lock_text("0.1.0", name="other"), "`0.2.0`", "unknown"),
        ("- Kernel lock: `uv.lock`\n", lock_text("0.1.0"), "unknown", "`0.1.0`"),
        (
            fields("0.2.0", "uv.lock") + "- Kernel version: `0.3.0`\n",
            lock_text("0.1.0"),
            "unknown",
            "`0.1.0`",
        ),
        ("- Kernel version: `0.2.0`\n", lock_text("0.1.0"), "`0.2.0`", "unknown"),
        (None, lock_text("0.1.0"), "unknown", "unknown"),
    ],
    ids=[
        "mismatch",
        "no-lock",
        "no-package",
        "no-version",
        "duplicate",
        "no-lock-field",
        "no-skill",
    ],
)
def test_every_failure_lists_both_sides(
    tmp_path: Path, skill: str | None, lock: str | None, expected: str, locked: str
) -> None:
    root = service(tmp_path / "service", skill, lock)

    result = check(root)

    assert result.returncode == 1
    match = BOTH_SIDES.match(result.stderr)
    assert match, result.stderr
    assert match.groups() == (expected, locked)
    assert str(root) not in result.stderr


def test_non_utf8_locale_reads_the_skill_as_utf8(tmp_path: Path) -> None:
    skill = (
        fields("0.1.0", "uv.lock") + '\nSee "可選的骨架更新" in `docs/template-operations.md`.\n'
    )
    root = service(tmp_path / "service", skill, lock_text("0.1.0"))
    environment = {**os.environ, "LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}

    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", str(SCRIPT), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )

    assert result.returncode == 0, result.stderr
