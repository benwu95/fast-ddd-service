import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import cast

SKILL = Path(".agents/skills/fast-ddd/SKILL.md")
# Same field format as the framework's scripts/check_versions.py, which services do not ship.
MARKDOWN_FIELD = re.compile(r"^- ([^:`]+): `([^`]*)`$", re.MULTILINE)
UPGRADE_GUIDE = "docs/template-operations.md"
FAILURE = "fast-ddd kernel version check failed"


class CheckError(Exception):
    pass


def skill_fields(skill: Path) -> dict[str, list[str]]:
    try:
        text = skill.read_text(encoding="utf-8")
    except OSError as error:
        raise CheckError(f"cannot read {SKILL}: {error.strerror}") from error
    fields: dict[str, list[str]] = {}
    for name, value in MARKDOWN_FIELD.findall(text):
        fields.setdefault(name, []).append(value)
    return fields


def skill_field(fields: dict[str, list[str]], name: str) -> str:
    found = fields.get(name, [])
    if len(found) != 1:
        raise CheckError(f"{SKILL} must contain exactly one `{name}` field")
    return found[0]


def locked_kernel(root: Path, lock_name: str) -> str:
    try:
        data = tomllib.loads((root / lock_name).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CheckError(f"{lock_name} does not exist; create it with `uv lock`") from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CheckError(f"cannot read {lock_name}: {error}") from error
    packages: object = data.get("package", [])
    versions: list[object] = []
    for package in cast(list[object], packages) if isinstance(packages, list) else []:
        if isinstance(package, dict):
            entry = cast(dict[str, object], package)
            if entry.get("name") == "fast-ddd-kernel":
                versions.append(entry.get("version"))
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise CheckError(f"{lock_name} has no fast-ddd-kernel package with a version")
    return versions[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the locked fast-ddd-kernel matches this skill"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    root = cast(Path, parser.parse_args(argv).root)
    problems: list[str] = []
    version = lock_name = locked = None
    try:
        fields = skill_fields(root / SKILL)
    except CheckError as error:
        problems.append(str(error))
        fields = {}
    if fields or not problems:
        try:
            version = skill_field(fields, "Kernel version")
        except CheckError as error:
            problems.append(str(error))
        try:
            lock_name = skill_field(fields, "Kernel lock")
        except CheckError as error:
            problems.append(str(error))
    if lock_name is not None:
        try:
            locked = locked_kernel(root, lock_name)
        except CheckError as error:
            problems.append(str(error))
    if not problems and locked == version:
        print(f"fast-ddd-kernel {version} matches {lock_name}")
        return 0
    expected = f"`{version}`" if version else "unknown"
    actual = f"`{locked}`" if locked else "unknown"
    details = "".join(f"; {problem}" for problem in problems)
    print(
        f"{FAILURE}: skill expects fast-ddd-kernel {expected}; lock {lock_name or 'unknown'} "
        f"has {actual}{details}. Update the template and the kernel together; "
        f"see {UPGRADE_GUIDE}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
