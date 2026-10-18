import os
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from scripts.check_template import snapshot_repository as snapshot_repository

ROOT = Path(__file__).resolve().parents[3]
PYTHON_VERSION = "3.13.12"


def isolated_environment(**values: str) -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        environment.pop(name, None)
    environment.update(values)
    return environment


def run(
    cwd: Path,
    *command: str,
    check: bool = True,
    timeout: float = 180,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=isolated_environment() if environment is None else environment,
            text=True,
            capture_output=True,
            check=check,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as error:
        error.add_note(f"stdout:\n{error.stdout}\nstderr:\n{error.stderr}")
        raise


def git(cwd: Path, *arguments: str) -> str:
    return run(
        cwd,
        "git",
        "-c",
        "user.name=Template Tests",
        "-c",
        "user.email=template@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        *arguments,
    ).stdout.strip()


class QuietGitHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve_git(repository: Path, directory: Path) -> Generator[str]:
    directory.mkdir()
    git(directory, "clone", "--bare", str(repository), "kernel.git")
    git(directory / "kernel.git", "repack", "-ad")
    git(directory / "kernel.git", "update-server-info")
    handler = partial(QuietGitHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    resolver = {
        "GIT_CONFIG_COUNT": str(count + 1),
        f"GIT_CONFIG_KEY_{count}": "http.curloptResolve",
        f"GIT_CONFIG_VALUE_{count}": f"host.docker.internal:{server.server_port}:127.0.0.1",
    }
    try:
        with patch.dict(os.environ, resolver):
            yield f"http://host.docker.internal:{server.server_port}/kernel.git"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
