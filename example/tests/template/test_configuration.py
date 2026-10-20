from pathlib import Path

import pytest
import yaml
from copier import run_copy


@pytest.mark.parametrize("source", ["git", "path", "workspace"])
def test_source_and_baseline_answers_are_persistent(
    tmp_path: Path, source: str, template_repository: Path
) -> None:
    destination = tmp_path / "service"
    run_copy(
        str(template_repository),
        destination,
        vcs_ref="HEAD",
        defaults=True,
        data={
            "kernel_source": source,
            "initialize_service_baseline": False,
            "coverage_minimum": 90,
        },
    )
    answers = yaml.safe_load((destination / ".copier-answers.yml").read_text())
    assert answers["kernel_source"] == source
    assert answers["coverage_minimum"] == 90
    assert answers["initialize_service_baseline"] is False
    assert "kernel_version" not in answers
    assert not (destination / "uv.lock").exists()


@pytest.mark.parametrize(
    "data",
    [
        {"coverage_minimum": 79},
        {"coverage_minimum": 101},
        {"service_name": "../escape"},
        {"service_name": "Bad Name"},
        {"kernel_source": "unknown"},
        {"kernel_version": "1.0"},
    ],
)
def test_invalid_configuration_is_rejected(
    tmp_path: Path, data: dict[str, object], template_repository: Path
) -> None:
    with pytest.raises((ValueError, TypeError)):
        run_copy(
            str(template_repository), tmp_path / "service", vcs_ref="HEAD", defaults=True, data=data
        )


def test_kernel_version_override_renders_without_persisting(
    tmp_path: Path, template_repository: Path
) -> None:
    destination = tmp_path / "service"
    run_copy(
        str(template_repository),
        destination,
        vcs_ref="HEAD",
        defaults=True,
        data={"kernel_version": "9.8.7"},
    )
    answers = yaml.safe_load((destination / ".copier-answers.yml").read_text())
    assert "kernel_version" not in answers
    skill = (destination / ".agents/skills/fast-ddd/SKILL.md").read_text()
    assert "- Kernel version: `9.8.7`\n" in skill
