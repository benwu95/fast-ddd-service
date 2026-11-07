import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import cast

import yaml
from copier import run_copy
from copier.errors import CopierError

REFERENCE_COPY = PurePosixPath("template/.agents/skills/fast-ddd/references/example")
REFERENCE_SOURCES = (
    "app/core/billing",
    "app/adapter/controller/__init__.py",
    "app/adapter/controller/billing",
    "app/adapter/event_handler/__init__.py",
    "app/adapter/event_handler/billing",
    "app/adapter/repository/billing",
    "app/adapter/repository/models.py",
    "app/adapter/notification",
    "app/adapter/resources.py",
    "app/port/billing",
    "app/port/message_queue/__init__.py",
    "app/port/message_queue/customer",
    "app/port/restful/__init__.py",
    "app/port/restful/billing",
    "app/port/task/__init__.py",
    "app/port/task/billing",
    "app/settings.py",
    "app/wiring.py",
    "alembic/versions/2026_10_18_0000-3f6a1c2d9b10_create_billing_invoice.py",
    "tests/adapter",
    "tests/conftest.py",
    "tests/core/__init__.py",
    "tests/core/test_invoice.py",
    "tests/port",
    "tests/support.py",
    "tests/test_error_catalog.py",
)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Template Snapshot",
            "-c",
            "user.email=template@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            *arguments,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def snapshot_repository(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(strict=True), destination.resolve()
    if destination.is_relative_to(source):
        raise ValueError("snapshot destination must be outside the source repository")
    names = _git(source, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    destination.mkdir()
    links: list[Path] = []
    for name in names.split("\0"):
        if not name:
            continue
        original = source / name
        resolved = original.resolve()
        if not resolved.is_relative_to(source):
            raise ValueError(f"snapshot path leaves the source repository: {name}")
        if original.is_file() or original.is_symlink():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if original.is_symlink():
                relocated = destination / resolved.relative_to(source)
                target.symlink_to(
                    relocated.relative_to(target.parent.resolve(), walk_up=True),
                    target_is_directory=original.is_dir(),
                )
                links.append(target)
            else:
                shutil.copy2(original, target)
    for link in links:
        if not link.resolve().is_relative_to(destination):
            raise ValueError(f"snapshot link leaves the destination repository: {link}")
    _git(destination, "init", "-b", "main")
    _git(destination, "add", ".")
    _git(destination, "commit", "-m", "snapshot current template inputs")
    return destination


def _answers(path: Path) -> dict[str, object]:
    value: object = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Copier answers must be a mapping with string keys")
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueError("Copier answers must be a mapping with string keys")
    return {key: item for key, item in cast(dict[str, object], value).items() if key != "_commit"}


def _ownership_path(root: Path) -> Path:
    path = root / "scripts/template-ownership.json"
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("ownership file must be a regular path inside the repository")
    return path


def _owned_paths(root: Path, *, allow_missing: bool = False) -> set[str]:
    path = _ownership_path(root)
    if allow_missing and not path.exists():
        return set()
    value: object = json.loads(path.read_text())
    if not isinstance(value, list):
        raise ValueError("ownership must be a list of relative file paths")
    paths: set[str] = set()
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise ValueError("ownership paths must be strings")
        name = PurePosixPath(item)
        if (
            not item
            or not name.parts
            or name.is_absolute()
            or ".." in name.parts
            or "\\" in item
            or name.as_posix() != item
            or any(ord(character) < 32 for character in item)
            or item in paths
        ):
            raise ValueError(f"invalid or duplicate ownership path: {item!r}")
        paths.add(item)
    return paths


def _rendered_paths(
    root: Path, answers: dict[str, object], known: set[str]
) -> tuple[set[str], set[str]]:
    with tempfile.TemporaryDirectory(prefix="fast-ddd-render-") as directory:
        destination = Path(directory) / "service"
        worker = run_copy(
            str(root),
            destination,
            vcs_ref="HEAD",
            defaults=True,
            quiet=True,
            data={name: value for name, value in answers.items() if not name.startswith("_")},
        )
        paths = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if (path.is_file() or path.is_symlink())
            and not worker.match_skip(path.relative_to(destination))
        }
        preserved = {name for name in known if worker.match_skip(Path(name))}
    return paths, preserved


def _record_ownership(root: Path) -> int:
    known = _owned_paths(root, allow_missing=True)
    with tempfile.TemporaryDirectory(prefix="fast-ddd-ownership-") as directory:
        snapshot = snapshot_repository(root, Path(directory) / "repository")
        current, _ = _rendered_paths(
            snapshot, _answers(snapshot / "example/.copier-answers.yml"), known
        )
    path = _ownership_path(root)
    with tempfile.TemporaryDirectory(prefix=".ownership-", dir=path.parent) as directory:
        pending = Path(directory) / path.name
        pending.write_text(json.dumps(sorted(known | current), indent=2) + "\n")
        pending.replace(path)
    print(f"Recorded {len(known | current)} template paths; historical ownership retained")
    return 0


def _listed_files(root: Path, pathspec: str) -> list[str]:
    names = _git(
        root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", pathspec
    )
    return [name for name in names.split("\0") if name and (root / name).is_file()]


def _reference_sources(root: Path) -> list[str]:
    files: set[str] = set()
    for entry in REFERENCE_SOURCES:
        found = _listed_files(root, f"example/{entry}")
        if not found:
            raise ValueError(f"reference source has no files: example/{entry}")
        for name in found:
            if (root / name).is_symlink():
                raise ValueError(f"reference source must be a regular file: {name}")
            files.add(PurePosixPath(name).relative_to("example").as_posix())
    return sorted(files)


def _reference_drift(root: Path) -> list[str]:
    sources = _reference_sources(root)
    copy = root / REFERENCE_COPY
    copied = {
        PurePosixPath(name).relative_to(REFERENCE_COPY).as_posix()
        for name in _listed_files(root, REFERENCE_COPY.as_posix())
    }
    problems: list[str] = []
    for name in sources:
        if name not in copied:
            problems.append(f"missing: {name}")
        elif (copy / name).read_bytes() != (root / "example" / name).read_bytes():
            problems.append(f"stale: {name}")
    problems += [f"extra: {name}" for name in sorted(copied - set(sources))]
    return problems


def _recopy_example(example: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "copier",
            "recopy",
            "--overwrite",
            "--defaults",
            "--vcs-ref",
            "HEAD",
        ],
        cwd=example,
        check=True,
        capture_output=True,
        text=True,
    )


def _sync_references(root: Path) -> int:
    sources = _reference_sources(root)
    target = root / REFERENCE_COPY
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".references-", dir=target.parent) as directory:
        staged = Path(directory) / "example"
        for name in sources:
            copied = staged / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / "example" / name, copied)
        previous = Path(directory) / "previous"
        if target.exists():
            target.rename(previous)
        staged.rename(target)
    example = root / "example"
    shutil.rmtree(example / REFERENCE_COPY.relative_to("template"), ignore_errors=True)
    _recopy_example(example)
    return _record_ownership(root)


def _check(root: Path) -> int:
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("dirty tree: commit changes or use --snapshot before checking")
    example = root / "example"
    if not example.resolve(strict=True).is_relative_to(root):
        raise ValueError("example path leaves the repository")
    answers_file = example / ".copier-answers.yml"
    before = _answers(answers_file)
    if before.get("_src_path") != "..":
        raise ValueError("example/.copier-answers.yml must use _src_path: ..")
    known = _owned_paths(root)
    current, preserved = _rendered_paths(root, before, known)
    unrecorded = sorted(current - known)
    retired = sorted(
        name
        for name in known - current - preserved
        if (example / name).is_symlink() or (example / name).is_file()
    )
    references = _reference_drift(root)
    _recopy_example(example)
    diff = _git(root, "diff", "--", "example", ":(exclude)example/.copier-answers.yml")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", "example")
    after = _answers(answers_file)
    if unrecorded:
        print("Unrecorded template files:")
        print("\n".join(unrecorded))
    if retired:
        print("Retired template files remain in example:")
        print("\n".join(retired))
    if diff:
        print(diff)
    if untracked:
        print("Untracked generated files:")
        for name in untracked.splitlines():
            delta = subprocess.run(
                ["git", "diff", "--no-index", "--", "/dev/null", name],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            print(delta.stdout)
    if before != after:
        print("Answers changed: example/.copier-answers.yml")
        print(yaml.safe_dump({"before": before, "after": after}, sort_keys=True))
    if references:
        print("Skill reference copy differs from example (run make template-references):")
        print("\n".join(references))
    if diff or untracked or before != after or unrecorded or retired or references:
        return 1
    print("Template and example match; only _commit may change")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the framework template/example pair")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--snapshot", action="store_true")
    mode.add_argument("--update-ownership", action="store_true")
    mode.add_argument("--sync-references", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = cast(Path, args.root).resolve(strict=True)
        if args.update_ownership:
            return _record_ownership(root)
        if args.sync_references:
            return _sync_references(root)
        if args.snapshot:
            with tempfile.TemporaryDirectory(prefix="fast-ddd-template-") as directory:
                return _check(snapshot_repository(root, Path(directory) / "repository"))
        return _check(root)
    except (OSError, ValueError, subprocess.CalledProcessError, CopierError) as error:
        print(str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
