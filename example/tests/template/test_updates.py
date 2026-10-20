import tomllib
from pathlib import Path

import pytest
import yaml
from copier import run_copy

from tests.template.support import PYTHON_VERSION, git, run
from tests.template.update_support import (
    INITIALIZATION_FILES,
    NEW_REVISION,
    commit,
    publish_revision,
    replace_once,
    revision_service,
    update_service,
)

NONOVERLAPPING_CHANGES = (
    (
        "app/bootstrap.py",
        'application_name=f"{settings.service_name}:{role}",',
        'application_name=f"{settings.service_name}:{role}:orders",',
        "configure_logging(settings.log_level)",
        "configure_logging(settings.log_level.upper())",
    ),
    (
        "app/main.py",
        "JWKS_TIMEOUT_SECONDS = 5.0",
        "JWKS_TIMEOUT_SECONDS = 7.0",
        "title=runtime.settings.service_name,",
        'title=f"{runtime.settings.service_name} API",',
    ),
    (
        "app/consumer.py",
        "PING_TIMEOUT_SECONDS = 5.0",
        "PING_TIMEOUT_SECONDS = 7.0",
        'logger.exception("consumer lifecycle failed")',
        'logger.exception("consumer runtime lifecycle failed")',
    ),
    (
        "app/task_worker.py",
        "timeout_graceful_shutdown=math.ceil(settings.worker_shutdown_timeout_seconds),",
        "timeout_graceful_shutdown=math.ceil(settings.worker_shutdown_timeout_seconds) + 1,",
        'raise RuntimeError("worker component stopped unexpectedly")',
        'raise RuntimeError("worker or health component stopped unexpectedly")',
    ),
    (
        "ruff.toml",
        "line-length = 100",
        "line-length = 88",
        '"datetime.date.today".msg = "Use pendulum.today(\'UTC\')."',
        '"datetime.date.today".msg = "Use pendulum.today(\'UTC\') for UTC dates."',
    ),
    (
        "tests/runtime/test_entrypoints.py",
        'user:p%40ss@db:5432/example"\n'
        '    assert driver_dsn(url) == "postgresql://user:p%40ss@db:5432/example',
        'worker:p%40ss@db:5432/example"\n'
        '    assert driver_dsn(url) == "postgresql://worker:p%40ss@db:5432/example',
        '"SERVICE_NAME": "example",',
        '"SERVICE_NAME": "upstream-runtime-test",',
    ),
)


@pytest.mark.parametrize(
    ("filename", "local_before", "local_after", "upstream_before", "upstream_after"),
    NONOVERLAPPING_CHANGES,
    ids=[change[0] for change in NONOVERLAPPING_CHANGES],
)
def test_nonoverlapping_runtime_tool_and_test_customizations_merge(
    template_repository: Path,
    generated_service: Path,
    tmp_path: Path,
    filename: str,
    local_before: str,
    local_after: str,
    upstream_before: str,
    upstream_after: str,
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    original = (service / filename).read_text()
    replace_once(service / filename, local_before, local_after)
    commit(service)
    replace_once(source / "template" / filename, upstream_before, upstream_after)
    publish_revision(source)

    update_service(service)

    expected = original.replace(local_before, local_after).replace(upstream_before, upstream_after)
    assert (service / filename).read_bytes() == expected.encode(), git(service, "diff")
    answers = yaml.safe_load((service / ".copier-answers.yml").read_text())
    assert answers["_commit"] == NEW_REVISION


def test_update_preserves_initialization_business_lock_and_migration_bytes(
    template_repository: Path, generated_service: Path, tmp_path: Path
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    configuration = yaml.safe_load((source / "copier.yml").read_text())
    assert set(configuration["_skip_if_exists"]) == {
        *INITIALIZATION_FILES,
        "alembic/versions/*",
    }
    replace_once(
        service / "pyproject.toml", '"fast-ddd-kernel",', '"fast-ddd-kernel",\n    "packaging>=25",'
    )
    run(service, "uv", "lock")
    run(service, "uv", "lock", "--check")
    for filename in INITIALIZATION_FILES[1:]:
        path = service / filename
        path.write_text(path.read_text() + '\nSERVICE_INITIALIZATION = "orders"\n')
    extra_files = {
        "app/core/orders.py": (
            "def total(quantity: int, price: int) -> int:\n    return quantity * price\n"
        ),
        "tests/test_orders.py": (
            "from app.core.orders import total\n\n"
            "def test_order_total():\n    assert total(3, 5) == 15\n"
        ),
        "alembic/versions/0001_orders.py": (
            "from alembic import op\nfrom sqlalchemy import Column, Integer\n"
            "revision = 'orders_0001'\ndown_revision = 'service_0000'\n"
            "branch_labels = None\ndepends_on = None\n"
            "def upgrade():\n"
            "    op.create_table('orders', Column('id', Integer, primary_key=True))\n"
            "def downgrade():\n    op.drop_table('orders')\n"
        ),
    }
    for filename, content in extra_files.items():
        path = service / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    baseline = service / "alembic/versions/0000_service.py"
    baseline.write_text(baseline.read_text() + '\nSERVICE_BASELINE_POLICY = "orders"\n')
    protected = (*INITIALIZATION_FILES, *extra_files, "uv.lock", "alembic/versions/0000_service.py")
    before = {filename: (service / filename).read_bytes() for filename in protected}
    commit(service)
    for filename in INITIALIZATION_FILES:
        upstream = source / "template" / filename
        if filename == "pyproject.toml":
            upstream = upstream.with_suffix(".toml.jinja")
            addition = "\n[tool.upstream]\nrevision = 2\n"
        else:
            addition = "\nUPSTREAM_INITIALIZATION = 2\n"
        upstream.write_text(upstream.read_text() + addition)
    upstream_baseline = next((source / "template/alembic/versions").glob("*.jinja"))
    upstream_baseline.write_text(upstream_baseline.read_text() + "\nUPSTREAM_BASELINE_POLICY = 2\n")
    replace_once(
        source / "template/app/main.py", "JWKS_TIMEOUT_SECONDS = 5.0", "JWKS_TIMEOUT_SECONDS = 6.0"
    )
    publish_revision(source)

    update_service(service)

    for filename, content in before.items():
        assert (service / filename).read_bytes() == content, filename
    assert "JWKS_TIMEOUT_SECONDS = 6.0" in (service / "app/main.py").read_text()
    assert sorted(path.name for path in baseline.parent.glob("*.py")) == [
        "0000_service.py",
        "0001_orders.py",
    ]
    run(service, "uv", "lock", "--check")


def test_missing_initialization_files_rebuild_from_new_defaults(
    template_repository: Path, generated_service: Path, tmp_path: Path
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    retained = (service / "uv.lock").read_bytes()
    baseline = (service / "alembic/versions/0000_service.py").read_bytes()
    for filename in INITIALIZATION_FILES:
        (service / filename).unlink()
        upstream = source / "template" / filename
        if filename == "pyproject.toml":
            upstream = upstream.with_suffix(".toml.jinja")
            addition = "\n[tool.upstream]\nrevision = 2\n"
        else:
            addition = "\nUPSTREAM_INITIALIZATION = 2\n"
        upstream.write_text(upstream.read_text() + addition)
    commit(service)
    publish_revision(source)
    answers = yaml.safe_load((generated_service / ".copier-answers.yml").read_text())
    expected = tmp_path / "new-defaults"
    run_copy(
        str(source),
        expected,
        defaults=True,
        quiet=True,
        vcs_ref=NEW_REVISION,
        data={name: value for name, value in answers.items() if not name.startswith("_")},
    )

    update_service(service)

    for filename in INITIALIZATION_FILES:
        assert (service / filename).read_bytes() == (expected / filename).read_bytes(), filename
    assert (service / "uv.lock").read_bytes() == retained
    assert (service / "alembic/versions/0000_service.py").read_bytes() == baseline
    assert len(list((service / "alembic/versions").glob("*.py"))) == 1


def test_intentionally_deleted_tracked_runtime_stays_deleted(
    template_repository: Path, generated_service: Path, tmp_path: Path
) -> None:
    source, service = revision_service(template_repository, generated_service, tmp_path)
    (service / "app/bootstrap.py").unlink()
    commit(service)
    replace_once(
        source / "template/app/main.py", "JWKS_TIMEOUT_SECONDS = 5.0", "JWKS_TIMEOUT_SECONDS = 6.0"
    )
    publish_revision(source)

    update_service(service)

    assert not (service / "app/bootstrap.py").exists()
    assert "JWKS_TIMEOUT_SECONDS = 6.0" in (service / "app/main.py").read_text()


def test_template_update_renders_the_new_kernel_version_without_upgrading_dependencies(
    template_repository: Path, tmp_path: Path
) -> None:
    source, service = tmp_path / "source", tmp_path / "service"
    git(tmp_path, "clone", "--quiet", str(template_repository), str(source))
    replace_once(source / "copier.yml", "  default: 0.1.0\n  when: false\n", "  default: 0.1.0\n")
    commit(source)
    git(source, "tag", "v0.0.9")
    run_copy(
        str(source),
        service,
        defaults=True,
        vcs_ref="v0.0.9",
        quiet=True,
        data={"kernel_source": "path", "kernel_path": str(source / "kernel")},
    )
    assert (
        yaml.safe_load((service / ".copier-answers.yml").read_text())["kernel_version"] == "0.1.0"
    )
    run(service, "uv", "lock", "--python", PYTHON_VERSION, timeout=240)
    git(service, "init", "-b", "main")
    commit(service)
    assert run(service, "make", "kernel-version", check=False).returncode == 0
    before = {name: (service / name).read_bytes() for name in ("pyproject.toml", "uv.lock")}
    replace_once(source / "copier.yml", "  default: 0.1.0\n", "  default: 0.2.0\n  when: false\n")
    publish_revision(source)

    update_service(service)

    answers = yaml.safe_load((service / ".copier-answers.yml").read_text())
    assert "kernel_version" not in answers
    assert answers["_commit"] == NEW_REVISION
    skill = (service / ".agents/skills/fast-ddd/SKILL.md").read_text()
    assert "- Kernel version: `0.2.0`\n" in skill
    for filename, content in before.items():
        assert (service / filename).read_bytes() == content, filename
    locked = tomllib.loads((service / "uv.lock").read_text())
    (kernel,) = [package for package in locked["package"] if package["name"] == "fast-ddd-kernel"]
    assert kernel["version"] == "0.1.0"
    run(service, "uv", "lock", "--check")
    mismatch = run(service, "make", "kernel-version", check=False)
    assert mismatch.returncode != 0
    assert "fast-ddd kernel version check failed" in mismatch.stderr
    assert "`0.2.0`" in mismatch.stderr
    assert "`0.1.0`" in mismatch.stderr
