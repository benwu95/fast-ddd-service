import os
from pathlib import Path

from copier import run_copy

from tests.template.support import git
from tests.template.update_support import (
    OLD_REVISION,
    commit,
    publish_revision,
    replace_once,
    update_service,
)

SKILL = ".agents/skills/fast-ddd/SKILL.md"
RETIRED_SETTINGS_REVISION = "v0.1.1"


def clone(template_repository: Path, directory: Path) -> Path:
    source = directory.resolve() / "source"
    git(directory, "clone", "--quiet", str(template_repository), str(source))
    return source


def copy_service(source: Path, service: Path, revision: str) -> None:
    run_copy(str(source), service, defaults=True, vcs_ref=revision, quiet=True)
    git(service, "init", "-b", "main")
    commit(service)


def assert_claude_link(service: Path) -> None:
    link = service / ".claude/skills"
    assert link.is_symlink()
    assert os.readlink(link) == "../.agents/skills"
    assert (link / "fast-ddd/SKILL.md").read_text() == (service / SKILL).read_text()


def test_copy_renders_the_service_skill_behind_a_claude_link(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        quiet=True,
        data={"kernel_version": "9.8.7"},
    )
    skill = (tmp_path / SKILL).read_text()
    assert "`9.8.7`" in skill
    assert "kernel_version" not in (tmp_path / ".copier-answers.yml").read_text()
    assert "{{" not in skill
    assert_claude_link(tmp_path)
    assert not (tmp_path / ".claude/settings.json").exists()


def test_update_keeps_the_link_and_merges_the_skill(
    template_repository: Path, tmp_path: Path
) -> None:
    source = clone(template_repository, tmp_path)
    service = tmp_path / "service"
    copy_service(source, service, OLD_REVISION)
    skill = service / SKILL
    skill.write_text(skill.read_text() + "\nLocal service note.\n")
    commit(service)
    replace_once(
        source / "template/.agents/skills/fast-ddd/SKILL.md.jinja",
        "# fast-ddd\n",
        "# fast-ddd\n\nUpstream template note.\n",
    )
    publish_revision(source)
    update_service(service)
    content = skill.read_text()
    assert "Upstream template note." in content
    assert "Local service note." in content
    assert_claude_link(service)


def test_phase_two_service_update_adds_the_skill_link_and_removes_customized_settings(
    template_repository: Path, tmp_path: Path
) -> None:
    source = clone(template_repository, tmp_path)
    current = git(source, "rev-parse", "HEAD")
    phase_two = ("copier.yml", "template/.agents", "template/.claude/skills")
    git(source, "rm", "-r", "--quiet", "template/.agents", "template/.claude/skills")
    replace_once(source / "copier.yml", "_preserve_symlinks: true\n", "")
    settings = source / "template/.claude/settings.json"
    settings.parent.mkdir()
    settings.write_text('{"permissions": {"deny": ["Read(**/.env*)"]}}\n')
    commit(source)
    git(source, "tag", RETIRED_SETTINGS_REVISION)
    service = tmp_path / "service"
    copy_service(source, service, RETIRED_SETTINGS_REVISION)
    assert sorted(path.name for path in (service / ".claude").iterdir()) == ["settings.json"]
    assert not (service / ".agents").exists()
    (service / ".claude/settings.json").write_text('{"permissions": {"deny": []}}\n')
    commit(service)
    git(source, "checkout", current, "--", *phase_two)
    settings.unlink()
    publish_revision(source)
    update_service(service)
    assert not (service / ".claude/settings.json").exists()
    assert git(service, "ls-files", "--deleted") == ".claude/settings.json"
    assert_claude_link(service)
