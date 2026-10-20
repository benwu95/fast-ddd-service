from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.check_versions import SOURCES, main, read_versions
from tests.template.support import ROOT

CONTENT: dict[str, Callable[[str], str]] = {
    ".claude-plugin/plugin.json": lambda version: f'{{"name": "fast-ddd", "version": "{version}"}}',
    "plugin.json": lambda version: f'{{"name": "fast-ddd", "version": "{version}"}}',
    "copier.yml": lambda version: f"kernel_version:\n  type: str\n  default: {version}\n",
    "kernel/pyproject.toml": lambda version: f'[project]\nname = "kernel"\nversion = "{version}"\n',
    "skills/fast-ddd-init/SKILL.md": lambda version: f"# Init\n\n- Template version: `{version}`\n",
}
MISSING_FIELD = {
    ".claude-plugin/plugin.json": '{"name": "fast-ddd"}',
    "plugin.json": '{"name": "fast-ddd"}',
    "copier.yml": "kernel_version:\n  type: str\n",
    "kernel/pyproject.toml": '[project]\nname = "kernel"\n',
    "skills/fast-ddd-init/SKILL.md": "# Init\n\n- Template source: `https://example.invalid`\n",
}
NON_STRING = {
    ".claude-plugin/plugin.json": '{"name": "fast-ddd", "version": 1}',
    "plugin.json": '{"name": "fast-ddd", "version": 1}',
    "copier.yml": "kernel_version:\n  type: str\n  default: 1.0\n",
    "kernel/pyproject.toml": '[project]\nname = "kernel"\nversion = 1\n',
}
NOT_MAPPING = {
    ".claude-plugin/plugin.json": '["version"]',
    "plugin.json": '["version"]',
    "copier.yml": "kernel_version: default\n",
    "kernel/pyproject.toml": 'project = "version"\n',
}
EMPTY = {
    ".claude-plugin/plugin.json": '{"name": "fast-ddd", "version": ""}',
    "plugin.json": '{"name": "fast-ddd", "version": ""}',
    "copier.yml": "kernel_version:\n  type: str\n  default: ''\n",
    "kernel/pyproject.toml": '[project]\nname = "kernel"\nversion = ""\n',
    "skills/fast-ddd-init/SKILL.md": "# Init\n\n- Template version: ``\n",
}
UNPARSEABLE = {
    ".claude-plugin/plugin.json": '{"version": ',
    "plugin.json": '{"version": ',
    "copier.yml": "kernel_version: [\n",
    "kernel/pyproject.toml": "[project\n",
    "skills/fast-ddd-init/SKILL.md": "- Template version: `1.2.3`\n- Template version: `1.2.4`\n",
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name, content in CONTENT.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content("1.2.3"))
    return tmp_path


def test_matching_sources_pass(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert read_versions(root) == (dict.fromkeys(SOURCES, "1.2.3"), {})
    assert main(["--root", str(root)]) == 0
    assert "1.2.3" in capsys.readouterr().out


BROKEN: dict[str, dict[str, str]] = {
    "missing-field": MISSING_FIELD,
    "not-mapping": NOT_MAPPING,
    "non-string": NON_STRING,
    "empty": EMPTY,
    "unparseable": UNPARSEABLE,
}
CASES = [(source, "mismatch") for source in CONTENT] + [
    (source, breakage)
    for breakage in ("missing-file", *BROKEN)
    for source in CONTENT
    if breakage == "missing-file" or source in BROKEN[breakage]
]


@pytest.mark.parametrize(("source", "breakage"), CASES)
def test_any_inconsistent_source_fails_and_reports_every_source(
    root: Path, capsys: pytest.CaptureFixture[str], source: str, breakage: str
) -> None:
    path = root / source
    match breakage:
        case "mismatch":
            path.write_text(CONTENT[source]("1.2.4"))
        case "missing-file":
            path.unlink()
        case _:
            path.write_text(BROKEN[breakage][source])
    versions, errors = read_versions(root)
    if breakage == "mismatch":
        assert versions[source] == "1.2.4"
        assert errors == {}
    else:
        assert source not in versions
        assert list(errors) == [source]
    assert main(["--root", str(root)]) == 1
    report = capsys.readouterr().err.splitlines()
    assert [line.split(" ", 1)[0] for line in report] == list(SOURCES)
    assert report[list(SOURCES).index(source)].endswith(
        "1.2.4" if breakage == "mismatch" else errors[source]
    )


def test_repository_versions_match() -> None:
    versions, errors = read_versions(ROOT)
    assert errors == {}
    assert len(set(versions.values())) == 1
    assert main([]) == 0
