import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from copier import run_copy

from scripts.check_template import main, snapshot_repository
from tests.template.support import ROOT, git, run


def _answers(repository: Path) -> dict[str, object]:
    return yaml.safe_load((repository / "example/.copier-answers.yml").read_text())


def _write_answers(repository: Path, answers: dict[str, object]) -> None:
    (repository / "example/.copier-answers.yml").write_text(
        yaml.safe_dump(answers, sort_keys=False)
    )


def _commit(repository: Path) -> None:
    git(repository, "add", ".")
    git(repository, "commit", "-m", "record drift fixture")
    assert git(repository, "status", "--porcelain") == ""


def _check(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return run(
        repository.parent,
        sys.executable,
        str(ROOT / "scripts/check_template.py"),
        "--root",
        str(repository),
        *arguments,
        check=False,
    )


def _tree_state(repository: Path) -> tuple[str, str, str, dict[str, bytes | None]]:
    names = git(repository, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    contents = {
        name: (repository / name).read_bytes() if (repository / name).is_file() else None
        for name in names.split("\0")
        if name
    }
    return (
        git(repository, "rev-parse", "HEAD"),
        git(repository, "ls-files", "--stage", "-z"),
        git(repository, "status", "--porcelain=v1", "--untracked-files=all", "-z"),
        contents,
    )


def _assert_revision_only(repository: Path, before: dict[str, object]) -> None:
    after = _answers(repository)
    assert after["_commit"] == git(repository, "describe", "--tags", "--always")
    assert after["_commit"] != before["_commit"]
    assert after["_src_path"] == ".."
    assert {key: value for key, value in after.items() if key != "_commit"} == {
        key: value for key, value in before.items() if key != "_commit"
    }
    assert git(repository, "diff", "--name-only") == "example/.copier-answers.yml"
    assert git(repository, "ls-files", "--others", "--exclude-standard") == ""


@pytest.fixture(scope="session")
def drift_seed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    repository = snapshot_repository(ROOT, tmp_path_factory.mktemp("drift-seed") / "framework")
    run_copy(
        str(repository),
        repository / "example",
        vcs_ref="HEAD",
        defaults=True,
        overwrite=True,
        data={
            "service_name": "example-service",
            "kernel_source": "workspace",
            "initialize_service_baseline": False,
        },
    )
    answers = _answers(repository)
    answers["_src_path"] = ".."
    _write_answers(repository, answers)
    _commit(repository)
    return repository


@pytest.fixture
def drift_repository(drift_seed: Path, tmp_path: Path) -> Path:
    repository = tmp_path / "framework"
    git(tmp_path, "clone", "--quiet", str(drift_seed), str(repository))
    return repository


def test_committed_example_recopy_ignores_only_revision(drift_repository: Path) -> None:
    before = _answers(drift_repository)

    result = _check(drift_repository)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_revision_only(drift_repository, before)


def test_public_main_resolves_source_from_example_cwd(
    drift_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _answers(drift_repository)
    monkeypatch.chdir(tmp_path)

    result = main(["--root", str(drift_repository)])

    assert result == 0
    _assert_revision_only(drift_repository, before)


def test_committed_bootstrap_modification_reports_actual_recopy_diff(
    drift_repository: Path,
) -> None:
    bootstrap = drift_repository / "example/app/bootstrap.py"
    original = bootstrap.read_text()
    bootstrap.write_text(original + '\nDRIFT_MARKER = "local-bootstrap-drift"\n')
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "example/app/bootstrap.py" in result.stdout
    assert '-DRIFT_MARKER = "local-bootstrap-drift"' in result.stdout
    assert bootstrap.read_text() == original


def test_committed_tracked_file_deletion_reports_restored_content(
    drift_repository: Path,
) -> None:
    bootstrap = drift_repository / "example/app/bootstrap.py"
    original = bootstrap.read_bytes()
    bootstrap.unlink()
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "example/app/bootstrap.py" in result.stdout
    assert "class Runtime:" in result.stdout
    assert bootstrap.read_bytes() == original
    assert git(drift_repository, "ls-files", "--others", "--exclude-standard") == (
        "example/app/bootstrap.py"
    )


def test_new_unsynchronized_template_file_reports_untracked_path_and_contents(
    drift_repository: Path,
) -> None:
    upstream = drift_repository / "template/app/new_template_component.py"
    upstream.write_text('NEW_TEMPLATE_COMPONENT = "unsynchronized-template-content"\n')
    _commit(drift_repository)
    generated = drift_repository / "example/app/new_template_component.py"
    assert not generated.exists()

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "example/app/new_template_component.py" in result.stdout
    assert "unsynchronized-template-content" in result.stdout
    assert generated.read_bytes() == upstream.read_bytes()
    assert git(drift_repository, "ls-files", "--others", "--exclude-standard") == (
        "example/app/new_template_component.py"
    )


def test_non_revision_answer_drift_is_not_discarded(drift_repository: Path) -> None:
    answers = _answers(drift_repository)
    answers["unexpected_answer"] = "non-revision-answer-drift"
    _write_answers(drift_repository, answers)
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "example/.copier-answers.yml" in result.stdout
    assert "unexpected_answer" in result.stdout
    assert "non-revision-answer-drift" in result.stdout
    assert "unexpected_answer" not in _answers(drift_repository)


def test_initialization_customization_survives_example_recopy(
    drift_repository: Path,
) -> None:
    project = drift_repository / "example/pyproject.toml"
    project.write_text(project.read_text() + "\n# preserve-initialization\n")
    _commit(drift_repository)
    before = _answers(drift_repository)
    customized = project.read_bytes()

    result = _check(drift_repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert project.read_bytes() == customized
    _assert_revision_only(drift_repository, before)


@pytest.mark.parametrize("checkout_name", ["other checkout", "nested/second checkout"])
def test_relative_source_is_portable_between_absolute_checkouts(
    drift_repository: Path, tmp_path: Path, checkout_name: str
) -> None:
    relocated = tmp_path / checkout_name
    relocated.parent.mkdir(parents=True, exist_ok=True)
    run(tmp_path, "git", "clone", "--quiet", str(drift_repository), str(relocated))
    before = _answers(relocated)
    assert relocated.resolve() != drift_repository.resolve()
    assert before["_src_path"] == ".."

    result = _check(relocated)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_revision_only(relocated, before)


@pytest.mark.parametrize("change", ["tracked", "untracked", "staged", "deleted"])
def test_dirty_tree_refusal_precedes_recopy_and_preserves_tree(
    drift_repository: Path, change: str
) -> None:
    bootstrap = drift_repository / "example/app/bootstrap.py"
    if change in {"tracked", "staged"}:
        bootstrap.write_text(bootstrap.read_text() + '\nDIRTY_TREE = "must-stay-dirty"\n')
        if change == "staged":
            git(drift_repository, "add", "example/app/bootstrap.py")
    elif change == "untracked":
        (drift_repository / "untracked-dirty.txt").write_text("untracked dirty oracle\n")
    else:
        bootstrap.unlink()
    before = _tree_state(drift_repository)
    assert before[2]

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "dirty" in (result.stdout + result.stderr).lower()
    assert _tree_state(drift_repository) == before


def test_snapshot_checks_uncommitted_template_content_without_touching_source(
    drift_repository: Path,
) -> None:
    bootstrap = drift_repository / "example/app/bootstrap.py"
    bootstrap.write_text(bootstrap.read_text() + '\nSNAPSHOT_DRIFT = "uncommitted-content"\n')
    (drift_repository / "local-untracked.txt").write_text("retain original untracked file\n")
    git(drift_repository, "add", "example/app/bootstrap.py")
    before = _tree_state(drift_repository)

    result = _check(drift_repository, "--snapshot")

    assert result.returncode != 0
    assert "example/app/bootstrap.py" in result.stdout
    assert '-SNAPSHOT_DRIFT = "uncommitted-content"' in result.stdout
    assert _tree_state(drift_repository) == before


def test_snapshot_repository_preserves_working_tree_contents_and_original_index(
    drift_repository: Path, tmp_path: Path
) -> None:
    bootstrap = drift_repository / "example/app/bootstrap.py"
    bootstrap.write_text(bootstrap.read_text() + '\nSNAPSHOT_VALUE = "staged-version"\n')
    git(drift_repository, "add", "example/app/bootstrap.py")
    bootstrap.write_text(bootstrap.read_text() + '\nWORKTREE_VALUE = "unstaged-version"\n')
    (drift_repository / "local-untracked.txt").write_text("snapshot includes untracked\n")
    (drift_repository / "example/app/main.py").unlink()
    before = _tree_state(drift_repository)

    snapshot = snapshot_repository(drift_repository, tmp_path / "snapshot")

    assert snapshot.resolve() != drift_repository.resolve()
    assert (snapshot / "example/app/bootstrap.py").read_bytes() == bootstrap.read_bytes()
    assert (snapshot / "local-untracked.txt").read_text() == "snapshot includes untracked\n"
    assert not (snapshot / "example/app/main.py").exists()
    assert git(snapshot, "status", "--porcelain") == ""
    assert _tree_state(drift_repository) == before


@pytest.mark.parametrize("linked_path", ["example", "example/app"])
def test_snapshot_recopy_preserves_source_behind_directory_symlink(
    drift_repository: Path, linked_path: str
) -> None:
    link = drift_repository / linked_path
    target = drift_repository / "service-files"
    shutil.move(str(link), target)
    link.symlink_to(target, target_is_directory=True)
    bootstrap = target / ("app/bootstrap.py" if linked_path == "example" else "bootstrap.py")
    bootstrap.write_text(bootstrap.read_text() + '\nSYMLINK_SOURCE = "keep-original"\n')
    _commit(drift_repository)
    before = _tree_state(drift_repository)

    _check(drift_repository, "--snapshot")

    assert _tree_state(drift_repository) == before


def test_external_example_link_is_refused_before_recopy(
    drift_repository: Path, tmp_path: Path
) -> None:
    example = drift_repository / "example"
    external = tmp_path / "external-service"
    example.rename(external)
    example.symlink_to(external, target_is_directory=True)
    _commit(drift_repository)
    before = _tree_state(drift_repository)
    contents = {
        str(path.relative_to(external)): path.read_bytes()
        for path in external.rglob("*")
        if path.is_file()
    }

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "example path leaves the repository" in result.stderr
    assert _tree_state(drift_repository) == before
    assert {
        str(path.relative_to(external)): path.read_bytes()
        for path in external.rglob("*")
        if path.is_file()
    } == contents


def test_upstream_deletion_reports_only_retired_skeleton_until_removed(
    drift_repository: Path,
) -> None:
    generated = drift_repository / "example/app/main.py"
    original = generated.read_bytes()
    business = drift_repository / "example/app/core/local_business.py"
    business.write_text('LOCAL_BUSINESS = "preserve"\n')
    project = drift_repository / "example/pyproject.toml"
    project.write_text(project.read_text() + "\n# preserve\n")
    protected = {path: path.read_bytes() for path in (business, project)}
    (drift_repository / "template/app/main.py").unlink()
    _commit(drift_repository)

    stale = _check(drift_repository)

    assert stale.returncode != 0, stale.stdout + stale.stderr
    assert "Retired template files remain" in stale.stdout
    assert "app/main.py" in stale.stdout
    assert generated.read_bytes() == original
    assert all(path.read_bytes() == content for path, content in protected.items())
    generated.unlink()
    _commit(drift_repository)

    synchronized = _check(drift_repository)

    assert synchronized.returncode == 0, synchronized.stdout + synchronized.stderr
    assert all(path.read_bytes() == content for path, content in protected.items())


def test_ownership_writer_adds_current_paths_without_forgetting_retired_paths(
    drift_repository: Path,
) -> None:
    ledger = drift_repository / "scripts/template-ownership.json"
    original = set(json.loads(ledger.read_text()))
    (drift_repository / "template/app/new_component.py").write_text("VALUE = 1\n")
    (drift_repository / "template/app/main.py").unlink()
    before = _tree_state(drift_repository)

    recorded = _check(drift_repository, "--update-ownership")

    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    assert set(json.loads(ledger.read_text())) == original | {"app/new_component.py"}
    assert "app/main.py" in json.loads(ledger.read_text())
    assert (drift_repository / "example/app/main.py").is_file()
    assert not (drift_repository / "example/app/new_component.py").exists()
    after = _tree_state(drift_repository)
    assert before[:2] == after[:2]
    assert {
        name: content
        for name, content in before[3].items()
        if name != "scripts/template-ownership.json"
    } == {
        name: content
        for name, content in after[3].items()
        if name != "scripts/template-ownership.json"
    }


@pytest.mark.parametrize(
    "entry",
    [
        None,
        "not-json",
        {},
        [1],
        ["."],
        ["../escape"],
        ["/absolute"],
        ["app//main.py"],
        ["app/main.py", "app/main.py"],
    ],
)
def test_invalid_ownership_is_refused_before_recopy(drift_repository: Path, entry: object) -> None:
    ledger = drift_repository / "scripts/template-ownership.json"
    if entry is None:
        ledger.unlink()
    elif entry == "not-json":
        ledger.write_text("not-json\n")
    else:
        ledger.write_text(json.dumps(entry))
    _commit(drift_repository)
    before = _tree_state(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert _tree_state(drift_repository) == before


def test_current_managed_path_missing_from_ownership_is_reported(
    drift_repository: Path,
) -> None:
    ledger = drift_repository / "scripts/template-ownership.json"
    paths = json.loads(ledger.read_text())
    paths.remove("app/main.py")
    ledger.write_text(json.dumps(paths))
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "Unrecorded template files" in result.stdout
    assert "app/main.py" in result.stdout


def test_historical_ownership_respects_current_initialization_rules(
    drift_repository: Path,
) -> None:
    ledger = drift_repository / "scripts/template-ownership.json"
    paths = json.loads(ledger.read_text())
    ledger.write_text(json.dumps([*paths, "pyproject.toml"]))
    project = drift_repository / "example/pyproject.toml"
    project.write_text(project.read_text() + "\n# preserve\n")
    original = project.read_bytes()
    (drift_repository / "template/pyproject.toml.jinja").unlink()
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert project.read_bytes() == original


@pytest.mark.parametrize("mode", [(), ("--update-ownership",)])
def test_ownership_link_outside_repository_is_refused(
    drift_repository: Path, tmp_path: Path, mode: tuple[str, ...]
) -> None:
    ledger = drift_repository / "scripts/template-ownership.json"
    ledger.unlink()
    outside = tmp_path / "outside-ownership.json"
    outside.write_text("[]\n")
    ledger.symlink_to(outside)
    _commit(drift_repository)
    before = _tree_state(drift_repository)

    result = _check(drift_repository, *mode)

    assert result.returncode != 0
    assert "ownership file must be a regular path inside" in result.stderr
    assert outside.read_text() == "[]\n"
    assert _tree_state(drift_repository) == before


def test_ownership_write_failure_preserves_original_inventory(
    drift_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = drift_repository / "scripts/template-ownership.json"
    before = _tree_state(drift_repository)
    attempted: list[Path] = []
    replace = Path.replace

    def fail_ledger_replace(path: Path, target: str | Path) -> Path:
        if Path(target) == ledger:
            attempted.append(path)
            raise OSError("ownership replace failed")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_ledger_replace)

    result = main(["--root", str(drift_repository), "--update-ownership"])

    assert result == 1
    assert len(attempted) == 1
    assert _tree_state(drift_repository) == before


def test_retired_file_replaced_by_generated_directory_is_synchronized(
    drift_repository: Path,
) -> None:
    relative = "docs/template-operations.md"
    source = drift_repository / "template" / relative
    source.unlink()
    source.mkdir()
    (source / "index.md").write_text("# New generated directory\n")
    generated = drift_repository / "example" / relative
    generated.unlink()
    recorded = _check(drift_repository, "--update-ownership")
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    _commit(drift_repository)

    first = _check(drift_repository)

    assert first.returncode != 0
    assert (generated / "index.md").read_text() == "# New generated directory\n"
    _commit(drift_repository)

    synchronized = _check(drift_repository)

    assert synchronized.returncode == 0, synchronized.stdout + synchronized.stderr


REFERENCE_COPY = "template/.agents/skills/fast-ddd/references/example"


def test_reference_copy_matches_example_sources(drift_repository: Path) -> None:
    copy = drift_repository / REFERENCE_COPY
    invoice = "app/core/billing/domain/invoice.py"
    assert (copy / invoice).read_bytes() == (drift_repository / "example" / invoice).read_bytes()
    assert (copy / "app/port/message_queue/customer/customer_subscriber.py").is_file()
    assert (copy / "app/port/restful/__init__.py").is_file()
    assert not (copy / ".agents").exists()
    assert not (copy / "app/main.py").exists()


def test_modified_reference_source_without_resync_is_reported(drift_repository: Path) -> None:
    invoice = drift_repository / "example/app/core/billing/domain/invoice.py"
    invoice.write_text(invoice.read_text() + '\nREFERENCE_DRIFT = "stale"\n')
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "stale: app/core/billing/domain/invoice.py" in result.stdout


def test_reference_copy_file_outside_the_list_is_reported(drift_repository: Path) -> None:
    (drift_repository / REFERENCE_COPY / "app/extra.py").write_text("EXTRA = 1\n")
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "extra: app/extra.py" in result.stdout


def test_reference_entry_without_files_is_refused(drift_repository: Path) -> None:
    shutil.rmtree(drift_repository / "example/app/adapter/notification")
    _commit(drift_repository)

    result = _check(drift_repository)

    assert result.returncode != 0
    assert "example/app/adapter/notification" in result.stderr


def test_deleted_reference_source_is_reported_until_resynchronized(
    drift_repository: Path,
) -> None:
    deleted = "tests/port/test_invoice_etag_limits.py"
    (drift_repository / "example" / deleted).unlink()
    _commit(drift_repository)

    stale = _check(drift_repository)

    assert stale.returncode != 0
    assert f"extra: {deleted}" in stale.stdout

    synchronized = _check(drift_repository, "--sync-references")

    assert synchronized.returncode == 0, synchronized.stdout + synchronized.stderr
    assert not (drift_repository / REFERENCE_COPY / deleted).exists()
    assert not (
        drift_repository / "example/.agents/skills/fast-ddd/references/example" / deleted
    ).exists()
    _commit(drift_repository)
    result = _check(drift_repository)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reference_sync_is_idempotent(drift_repository: Path) -> None:
    before = _tree_state(drift_repository)[3]

    result = _check(drift_repository, "--sync-references")

    assert result.returncode == 0, result.stdout + result.stderr
    after = _tree_state(drift_repository)[3]
    assert {name for name in after if name != "example/.copier-answers.yml"} == {
        name for name in before if name != "example/.copier-answers.yml"
    }
    assert all(
        after[name] == content
        for name, content in before.items()
        if name != "example/.copier-answers.yml"
    )
