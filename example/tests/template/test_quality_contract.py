import configparser
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from copier import run_copy, run_recopy

from tests.template.support import isolated_environment, run
from tests.template.update_support import (
    NEW_REVISION,
    publish_revision,
    replace_once,
    revision_service,
    update_service,
)


@pytest.mark.parametrize(("source", "venv"), [("path", "."), ("git", "."), ("workspace", "..")])
def test_quality_settings_follow_the_environment_and_empty_package_contract(
    template_repository: Path, tmp_path: Path, source: str, venv: str
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        data={"kernel_source": source, "coverage_minimum": 90},
    )
    typing = json.loads((tmp_path / "pyrightconfig.json").read_text())
    assert typing["venvPath"] == venv
    assert typing["typeCheckingMode"] == "strict"
    config = configparser.ConfigParser()
    config.read(tmp_path / ".coveragerc")
    assert config.getint("report", "fail_under") == 90
    assert config.get("run", "source") == "app"
    assert not config.has_option("run", "omit")
    result = run(
        tmp_path,
        str(Path(sys.executable).with_name("lint-imports")),
        "--config",
        ".importlinter",
        "--no-cache",
    )
    assert "7 kept, 0 broken" in result.stdout
    assert not (tmp_path / ".claude/settings.json").exists()
    ignored = set((tmp_path / ".gitignore").read_text().splitlines())
    assert {".env*", "*.pem", "*.key", "*.crt", "*.cer", "*.p12", "*.pfx"} <= ignored


@pytest.mark.parametrize("minimum", [None, 80, 100])
def test_coverage_default_and_legal_boundaries(
    template_repository: Path, tmp_path: Path, minimum: int | None
) -> None:
    data = {} if minimum is None else {"coverage_minimum": minimum}
    run_copy(
        str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD", quiet=True, data=data
    )
    config = configparser.ConfigParser()
    config.read(tmp_path / ".coveragerc")
    assert config.getint("report", "fail_under") == (80 if minimum is None else minimum)


@pytest.mark.parametrize("minimum", [79, 101])
def test_coverage_rejects_values_outside_the_contract(
    template_repository: Path, tmp_path: Path, minimum: int
) -> None:
    with pytest.raises(ValueError, match="between 80 and 100"):
        run_copy(
            str(template_repository),
            tmp_path,
            defaults=True,
            vcs_ref="HEAD",
            quiet=True,
            data={"coverage_minimum": minimum},
        )


@pytest.mark.parametrize("minimum", [90, 100])
def test_raised_coverage_survives_update_and_isolated_recopy(
    template_repository: Path, generated_service: Path, tmp_path: Path, minimum: int
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    replace_once(
        source / "template/app/main.py", "JWKS_TIMEOUT_SECONDS = 5.0", "JWKS_TIMEOUT_SECONDS = 6.0"
    )
    publish_revision(source)
    update_service(service, coverage_minimum=minimum)
    before = (service / ".coveragerc").read_bytes()
    config = configparser.ConfigParser()
    config.read(service / ".coveragerc")
    assert config.getint("report", "fail_under") == minimum
    run_recopy(service, defaults=True, overwrite=True, quiet=True, vcs_ref=NEW_REVISION)
    assert (service / ".coveragerc").read_bytes() == before
    answers = yaml.safe_load((service / ".copier-answers.yml").read_text())
    assert answers["coverage_minimum"] == minimum


def test_standalone_full_quality_gate_covers_every_app_file_without_skips(
    generated_service: Path, tmp_path: Path
) -> None:
    service = generated_service
    assert not (service / "tests/template").exists()
    collected = run(
        service,
        str(service / ".venv/bin/python"),
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "tests/runtime",
    )
    nodes = {line for line in collected.stdout.splitlines() if "::" in line}
    baseline = json.loads((Path(__file__).parent / "runtime_cases.json").read_text())
    assert len(baseline) == 47
    assert len(set(baseline.values())) == 47
    assert set(baseline.values()) <= nodes
    report = tmp_path / "pytest.xml"
    checked = run(
        service,
        "make",
        "check",
        timeout=300,
        environment=isolated_environment(PYTEST_ADDOPTS=f"--junitxml={report}"),
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    suites = list(ET.parse(report).getroot().iter("testsuite"))
    assert sum(int(suite.attrib["tests"]) for suite in suites) == len(nodes)
    assert sum(int(suite.attrib["skipped"]) for suite in suites) == 0
    assert sum(int(suite.attrib["failures"]) + int(suite.attrib["errors"]) for suite in suites) == 0
    coverage = tmp_path / "coverage.json"
    run(service, str(service / ".venv/bin/coverage"), "json", "-o", str(coverage))
    measured = json.loads(coverage.read_text())
    expected = {str(path.relative_to(service)) for path in (service / "app").rglob("*.py")}
    assert set(measured["files"]) == expected
    assert measured["totals"]["excluded_lines"] == 0
    assert measured["totals"]["percent_covered"] >= 80
    answers = yaml.safe_load((service / ".copier-answers.yml").read_text())
    (tmp_path / "acceptance.json").write_text(
        json.dumps(
            {
                "source": answers["kernel_source"],
                "tests": len(nodes),
                "coverage": measured["totals"],
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {"service": str(service), "tests": len(nodes), "coverage": measured["totals"]},
            sort_keys=True,
        )
    )
