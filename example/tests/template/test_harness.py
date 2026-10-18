import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.template.support import git, isolated_environment, run, snapshot_repository


def test_subprocess_failure_keeps_captured_diagnostics(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError) as failed:
        run(tmp_path, sys.executable, "-c", "import sys; print('fixture-error'); sys.exit(3)")
    assert failed.value.returncode == 3
    assert "fixture-error" in "\n".join(failed.value.__notes__)


def test_subprocess_environment_uses_its_own_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/wrong/project")
    monkeypatch.setenv("VIRTUAL_ENV", "/wrong/environment")
    environment = isolated_environment()
    assert "PYTHONPATH" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert environment["PATH"] == os.environ["PATH"]


def test_snapshot_includes_uncommitted_files_and_excludes_ignored(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    (source / ".gitignore").write_text("ignored.txt\n")
    (source / "tracked.txt").write_text("original\n")
    git(source, "add", ".gitignore", "tracked.txt")
    git(source, "commit", "-m", "initial")
    (source / "tracked.txt").write_text("updated\n")
    (source / "new.txt").write_text("new\n")
    (source / "ignored.txt").write_text("excluded\n")
    destination = snapshot_repository(source, tmp_path / "snapshot")
    assert (destination / "tracked.txt").read_text() == "updated\n"
    assert (destination / "new.txt").read_text() == "new\n"
    assert not (destination / "ignored.txt").exists()
    assert not git(destination, "status", "--porcelain")
    assert run(destination, "git", "rev-parse", "HEAD").returncode == 0


def test_http_git_fixture_serves_a_fixed_kernel_revision(
    kernel_git_url: str, tmp_path: Path, template_repository: Path
) -> None:
    run(tmp_path, "git", "clone", "--quiet", kernel_git_url, "clone")
    clone = tmp_path / "clone"
    assert git(clone, "rev-parse", "v0.1.0") == git(template_repository, "rev-parse", "v0.1.0")
    assert (clone / "kernel" / "pyproject.toml").is_file()


def test_snapshot_rejects_paths_outside_the_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside the snapshot scope\n")
    (source / "outside-link").symlink_to(outside)
    git(source, "add", "outside-link")
    git(source, "commit", "-m", "external symlink fixture")
    with pytest.raises(ValueError, match="leaves the source"):
        snapshot_repository(source, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot/outside-link").exists()
    with pytest.raises(ValueError, match="outside the source"):
        snapshot_repository(source, source / "nested-snapshot")
    assert not (source / "nested-snapshot").exists()


@pytest.mark.parametrize("target_kind", ["file", "directory"])
@pytest.mark.parametrize("link_kind", ["absolute", "relative", "chained", "backlink"])
def test_snapshot_relocates_internal_symlinks(
    tmp_path: Path, target_kind: str, link_kind: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    (source / "assets").mkdir()
    original = source / "assets/value.txt"
    original.write_text("preserve original content\n")
    target = original if target_kind == "file" else original.parent
    link_target = target
    if link_kind == "relative":
        link_target = target.relative_to(source)
    elif link_kind == "chained":
        (source / "alias").symlink_to(target, target_is_directory=target.is_dir())
        link_target = Path("alias")
    elif link_kind == "backlink":
        link_target = Path("..") / source.name / target.relative_to(source)
    (source / "link").symlink_to(link_target, target_is_directory=target.is_dir())
    git(source, "add", ".")
    git(source, "commit", "-m", "internal symlink fixture")

    snapshot = snapshot_repository(source, tmp_path / "snapshot")

    assert (snapshot / "link").resolve() == snapshot / target.relative_to(source)
    for path in snapshot.iterdir():
        if path.is_symlink():
            assert path.resolve().is_relative_to(snapshot)
    assert original.read_text() == "preserve original content\n"
