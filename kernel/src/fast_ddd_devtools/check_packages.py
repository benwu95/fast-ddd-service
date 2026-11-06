import argparse
import configparser
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

_LIST_KEYS = ("source_modules", "forbidden_modules", "layers", "containers", "modules")
_SKIPPED_DIRS = {"__pycache__"}


@dataclass(frozen=True, slots=True)
class LinterConfig:
    root_packages: tuple[str, ...]
    referenced_modules: frozenset[str]


def _split_module_names(raw: str) -> list[str]:
    names: list[str] = []
    for token in re.split(r"[\s|:,]+", raw):
        name = token.strip().strip("()")
        if name:
            names.append(name)
    return names


def _as_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in cast(list[Any], value)]
    return []


def _load_toml(path: Path) -> LinterConfig:
    data = tomllib.loads(path.read_text())
    section = cast(dict[str, Any], data.get("tool", {}).get("importlinter", {}))
    roots = _as_strings(section.get("root_packages", section.get("root_package", [])))
    referenced: set[str] = set()
    for contract in cast(list[dict[str, Any]], section.get("contracts", [])):
        for key in _LIST_KEYS:
            for raw in _as_strings(contract.get(key, [])):
                referenced.update(_split_module_names(raw))
    return LinterConfig(tuple(roots), frozenset(referenced))


def _load_ini(path: Path) -> LinterConfig:
    parser = configparser.ConfigParser()
    parser.read(path)
    main = parser["importlinter"]
    roots = _split_module_names(main.get("root_packages", main.get("root_package", "")))
    referenced: set[str] = set()
    for name in parser.sections():
        if not name.startswith("importlinter:contract:"):
            continue
        for key in _LIST_KEYS:
            referenced.update(_split_module_names(parser[name].get(key, "")))
    return LinterConfig(tuple(roots), frozenset(referenced))


def load_config(path: Path) -> LinterConfig:
    if path.suffix == ".toml":
        return _load_toml(path)
    return _load_ini(path)


def _package_dir(source_root: Path, package: str) -> Path:
    return source_root.joinpath(*package.split("."))


def _raise(error: OSError) -> None:
    raise error


def _directories_requiring_init(package_dir: Path) -> list[Path]:
    # import-linter follows symlinked directories, so this walk does too; the chain of resolved
    # ancestors stops a symlink that points back up the tree from recursing forever.
    directories: set[Path] = set()
    real_ancestors = {package_dir: frozenset({package_dir.resolve()})}
    for directory, subdirectories, files in package_dir.walk(follow_symlinks=True, on_error=_raise):
        ancestors = real_ancestors.pop(directory)
        kept: list[str] = []
        for name in subdirectories:
            real = (directory / name).resolve()
            if name in _SKIPPED_DIRS or name.startswith(".") or real in ancestors:
                continue
            real_ancestors[directory / name] = ancestors | {real}
            kept.append(name)
        subdirectories[:] = kept
        if any(name.endswith(".py") for name in files):
            parts = directory.relative_to(package_dir).parts
            directories.update(
                package_dir.joinpath(*parts[:depth]) for depth in range(1, len(parts) + 1)
            )
    return sorted(directories)


def _immediate_children(package: str, package_dir: Path) -> list[str]:
    children: list[str] = []
    for child in sorted(package_dir.iterdir()):
        if child.name in _SKIPPED_DIRS or child.name.startswith("."):
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            children.append(f"{package}.{child.name}")
        elif child.suffix == ".py" and child.name != "__init__.py":
            children.append(f"{package}.{child.stem}")
    return children


def _is_covered(module: str, referenced: frozenset[str]) -> bool:
    return any(
        name == module or name.startswith(f"{module}.") or module.startswith(f"{name}.")
        for name in referenced
    )


def find_problems(config: LinterConfig, source_root: Path) -> list[str]:
    problems: list[str] = []
    for package in config.root_packages:
        package_dir = _package_dir(source_root, package)
        if not (package_dir / "__init__.py").exists():
            problems.append(f"{package}: root package not found at {package_dir}")
            continue
        for directory in _directories_requiring_init(package_dir):
            if not (directory / "__init__.py").exists():
                problems.append(f"{directory}: missing __init__.py, import-linter would skip it")
        for module in _immediate_children(package, package_dir):
            if not _is_covered(module, config.referenced_modules):
                problems.append(f"{module}: not covered by any import-linter contract")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when import-linter cannot see a module or no contract covers it."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--source-root", type=Path, default=Path())
    args = parser.parse_args(argv)
    config_path = cast(Path | None, args.config)
    if config_path is None:
        config_path = (
            Path(".importlinter") if Path(".importlinter").exists() else Path("pyproject.toml")
        )
    problems = find_problems(load_config(config_path), cast(Path, args.source_root))
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
