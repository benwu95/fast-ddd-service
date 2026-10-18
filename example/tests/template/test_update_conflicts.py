import sys
from pathlib import Path

import pytest
from copier import run_recopy

from tests.template.support import git, run
from tests.template.update_support import (
    NEW_REVISION,
    commit,
    publish_revision,
    replace_once,
    revision_service,
)

CONFLICTS = (
    (
        "app/bootstrap.py",
        "configure_logging(settings.log_level)",
        "configure_logging(settings.log_level.upper())",
        "configure_logging(settings.log_level.lower())",
    ),
    (
        "app/main.py",
        "JWKS_TIMEOUT_SECONDS = 5.0",
        "JWKS_TIMEOUT_SECONDS = 7.0",
        "JWKS_TIMEOUT_SECONDS = 9.0",
    ),
    ("ruff.toml", "line-length = 100", "line-length = 88", "line-length = 120"),
    (
        "tests/runtime/test_entrypoints.py",
        '"SERVICE_NAME": "example",',
        '"SERVICE_NAME": "orders",',
        '"SERVICE_NAME": "upstream",',
    ),
)


@pytest.mark.parametrize(
    ("filename", "before", "local", "upstream"), CONFLICTS, ids=[case[0] for case in CONFLICTS]
)
def test_update_conflicts_require_resolution_even_when_copier_returns_zero(
    template_repository: Path,
    generated_service: Path,
    tmp_path: Path,
    filename: str,
    before: str,
    local: str,
    upstream: str,
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    original = (service / filename).read_text()
    replace_once(service / filename, before, local)
    commit(service)
    replace_once(source / "template" / filename, before, upstream)
    publish_revision(source)
    result = run(
        service,
        sys.executable,
        "-m",
        "copier",
        "update",
        "--defaults",
        "--conflict",
        "inline",
        "--vcs-ref",
        NEW_REVISION,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    conflicted = (service / filename).read_text()
    assert local in conflicted
    assert upstream in conflicted
    assert all(marker in conflicted for marker in ("<<<<<<<", "=======", ">>>>>>>"))
    assert f"UU {filename}" in git(service, "status", "--porcelain")
    stages = git(service, "ls-files", "--unmerged", "--", filename).splitlines()
    assert {line.split()[2] for line in stages} == {"1", "2", "3"}
    for selection in (("--files", filename), ("--all-files",)):
        gate = run(
            service,
            sys.executable,
            "-m",
            "pre_commit",
            "run",
            "check-merge-conflict",
            *selection,
            check=False,
            timeout=240,
        )
        assert gate.returncode != 0
        assert filename in gate.stdout + gate.stderr
        assert "- hook id: check-merge-conflict" in gate.stdout
    (service / filename).write_text(original.replace(before, local))
    git(service, "add", filename)
    assert not git(service, "ls-files", "--unmerged")
    for selection in (("--files", filename), ("--all-files",)):
        gate = run(
            service,
            sys.executable,
            "-m",
            "pre_commit",
            "run",
            "check-merge-conflict",
            *selection,
            check=False,
        )
        assert gate.returncode == 0, gate.stdout + gate.stderr


def test_recopy_overwrites_tracked_customizations_in_an_isolated_fixture(
    template_repository: Path, generated_service: Path, tmp_path: Path
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    retained_names = ("app/wiring.py", "uv.lock", "alembic/versions/0000_service.py")
    wiring = service / "app/wiring.py"
    wiring.write_text(wiring.read_text() + "\nSERVICE_POLICY = 'orders'\n")
    retained = {name: (service / name).read_bytes() for name in retained_names}
    for filename, before, local, upstream in CONFLICTS:
        replace_once(service / filename, before, local)
        replace_once(source / "template" / filename, before, upstream)
    commit(service)
    publish_revision(source)
    run_recopy(service, defaults=True, overwrite=True, quiet=True, vcs_ref=NEW_REVISION)
    for filename, _before, local, upstream in CONFLICTS:
        assert (service / filename).read_bytes() == (source / "template" / filename).read_bytes()
        assert local not in (service / filename).read_text()
        assert upstream in (service / filename).read_text()
    for name, content in retained.items():
        assert (service / name).read_bytes() == content
