import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile


def test_wheel_contains_runtime_types_and_migrations_without_test_branch(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        environment.pop(key, None)

    def run(*command: str) -> str:
        result = subprocess.run(
            command, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    run("uv", "build", "--wheel", "--out-dir", str(tmp_path), str(root))
    (wheel,) = tmp_path.glob("*.whl")
    packages = ("fast_ddd", "fast_ddd_adapter", "fast_ddd_port", "fast_ddd_devtools")
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert {f"{package}/py.typed" for package in packages} <= names
    migrations = {
        path.name for path in (root / "src/fast_ddd_adapter/migrations/versions").glob("*.py")
    }
    assert {f"fast_ddd_adapter/migrations/versions/{name}" for name in migrations} <= names
    assert not any("tests/" in name or "test_" in name for name in names)
    run("uv", "venv", "--python", "3.13", str(tmp_path / ".venv"))
    python = str(tmp_path / ".venv/bin/python")
    run("uv", "pip", "install", "--python", python, "--no-deps", str(wheel))
    output = run(
        python,
        "-I",
        "-c",
        """
import json, sys
from importlib.resources import files
from importlib.metadata import distribution
packages = ('fast_ddd', 'fast_ddd_adapter', 'fast_ddd_port', 'fast_ddd_devtools')
assert all(files(package).joinpath('py.typed').is_file() for package in packages)
assert all(str(files(package)).startswith(sys.prefix) for package in packages)
resource = files('fast_ddd_adapter').joinpath('migrations/versions')
assert resource.joinpath('fastddd_0003_pgqueuer.py').is_file()
direct = json.loads(distribution('fast-ddd-kernel').read_text('direct_url.json'))
assert not direct.get('dir_info', {}).get('editable', False)
print(json.dumps(sorted(path.name for path in resource.iterdir() if path.name.endswith('.py'))))
""",
    )
    assert set(json.loads(output)) == migrations
