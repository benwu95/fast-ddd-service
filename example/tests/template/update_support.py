import shutil
from pathlib import Path
from typing import Any, cast

import yaml
from copier import run_update

from tests.template.support import git, run

OLD_REVISION = "v0.1.0"
NEW_REVISION = "v0.2.0"
INITIALIZATION_FILES = (
    "pyproject.toml",
    "app/settings.py",
    "app/wiring.py",
    "app/adapter/resources.py",
    "app/adapter/repository/models.py",
    "tests/conftest.py",
    "tests/support.py",
)


def commit(repository: Path) -> None:
    git(repository, "add", ".")
    git(repository, "commit", "-m", "record update fixture")
    assert git(repository, "status", "--porcelain") == ""


def replace_once(path: Path, before: str, after: str) -> None:
    content = path.read_text()
    assert content.count(before) == 1, (str(path), before, content)
    path.write_text(content.replace(before, after))


def revision_service(
    template_repository: Path, generated_service: Path, directory: Path
) -> tuple[Path, Path]:
    directory = directory.resolve()
    source, service = directory / "source", directory / "service"
    git(directory, "clone", "--quiet", str(template_repository), str(source))
    answers = cast(
        dict[str, Any], yaml.safe_load((generated_service / ".copier-answers.yml").read_text())
    )
    shutil.copytree(
        generated_service,
        service,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".coverage",
            ".coverage.*",
            ".pytest_cache",
            ".ruff_cache",
            ".import_linter_cache",
        ),
    )
    assert git(source, "rev-parse", str(answers["_commit"])) == git(
        source, "rev-parse", OLD_REVISION
    )
    answers["_src_path"] = str(source)
    (service / ".copier-answers.yml").write_text(yaml.safe_dump(answers, sort_keys=False) + "\n")
    assert (service / "pyproject.toml").read_bytes() == (
        generated_service / "pyproject.toml"
    ).read_bytes()
    assert (service / ".coveragerc").read_bytes() == (
        generated_service / ".coveragerc"
    ).read_bytes()
    git(service, "init", "-b", "main")
    commit(service)
    assert git(service, "ls-files", "--error-unmatch", "uv.lock") == "uv.lock"
    return source, service


def publish_revision(source: Path) -> None:
    commit(source)
    git(source, "tag", NEW_REVISION)


def update_service(service: Path, **data: object) -> None:
    run_update(
        service,
        defaults=True,
        overwrite=True,
        quiet=True,
        conflict="inline",
        vcs_ref=NEW_REVISION,
        data=data,
    )
    assert git(service, "ls-files", "--unmerged") == ""
    result = run(service, "git", "diff", "--check", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
