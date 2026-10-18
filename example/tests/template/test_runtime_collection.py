import sys
from pathlib import Path

from copier import run_copy

from tests.template.support import run


def test_runtime_fixtures_do_not_import_business_helpers(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    (tmp_path / "tests/support.py").write_text("raise AssertionError('business helper imported')\n")
    probe = tmp_path / "tests/runtime/test_fixture_probe.py"
    probe.parent.mkdir(exist_ok=True)
    probe.write_text(
        "from sqlalchemy import text\n"
        "async def test_fixtures(session_factory, tokens):\n"
        "    async with session_factory() as session:\n"
        "        assert await session.scalar(text('SELECT count(*) FROM alembic_version')) == 2\n"
        "    assert isinstance(tokens.token(organization_id=None), str)\n"
    )
    result = run(
        tmp_path, sys.executable, "-m", "pytest", "-q", "tests/runtime", check=False, timeout=180
    )
    assert result.returncode == 0, result.stdout + result.stderr
