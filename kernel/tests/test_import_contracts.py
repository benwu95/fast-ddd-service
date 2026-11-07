import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def lint_imports(tmp_path: Path, probe: str | None) -> subprocess.CompletedProcess[str]:
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    if probe is not None:
        (tmp_path / "src/fast_ddd/_probe.py").write_text(probe)
    environment = {**os.environ, "PYTHONPATH": str(tmp_path / "src")}
    return subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports"), "--config", "../pyproject.toml"],
        cwd=tmp_path / "src",
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(("probe", "broken"), [(None, False), ("import socketio\n", True)])
def test_core_may_not_import_socketio(tmp_path: Path, probe: str | None, broken: bool) -> None:
    result = lint_imports(tmp_path, probe)
    assert (result.returncode != 0) is broken, result.stdout + result.stderr
    assert ("Core has no framework dependencies BROKEN" in result.stdout) is broken
    if broken:
        assert "fast_ddd._probe -> socketio" in result.stdout
