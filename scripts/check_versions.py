import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import cast

import yaml

SOURCES: dict[str, tuple[str, ...]] = {
    ".claude-plugin/plugin.json": ("version",),
    "plugin.json": ("version",),
    "copier.yml": ("kernel_version", "default"),
    "kernel/pyproject.toml": ("project", "version"),
    "skills/fast-ddd-init/SKILL.md": ("Template version",),
}
MARKDOWN_FIELD = re.compile(r"^- ([^:`]+): `([^`]*)`$", re.MULTILINE)


def _markdown_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for name, value in MARKDOWN_FIELD.findall(text):
        if name in fields:
            raise ValueError(f"duplicate {name}")
        fields[name] = value
    return fields


def _load(path: Path) -> object:
    text = path.read_text()
    match path.suffix:
        case ".json":
            return json.loads(text)
        case ".yml":
            return yaml.safe_load(text)
        case ".md":
            return _markdown_fields(text)
        case _:
            return tomllib.loads(text)


def _version(path: Path, keys: tuple[str, ...]) -> str:
    value = _load(path)
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"missing {'.'.join(keys)}")
        value = cast(dict[object, object], value)[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{'.'.join(keys)} must be a non-empty string")
    return value


def read_versions(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    versions: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name, keys in SOURCES.items():
        try:
            versions[name] = _version(root / name, keys)
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors[name] = f"error: {error}".replace("\n", " ")
    return versions, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the plugin manifests, template and kernel share one version"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    versions, errors = read_versions(cast(Path, args.root))
    if errors or len(set(versions.values())) != 1:
        for name, keys in SOURCES.items():
            print(f"{name} {'.'.join(keys)}: {versions.get(name) or errors[name]}", file=sys.stderr)
        return 1
    print(f"Plugin, template and kernel versions match: {next(iter(versions.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
