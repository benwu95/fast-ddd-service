"""The local socketio stubs must describe the installed python-socketio (no py.typed upstream)."""

import ast
import importlib
import inspect
from pathlib import Path

import pytest

STUBS = Path(__file__).resolve().parents[1] / "typings/socketio"
_KINDS = inspect.Parameter


def _stub_parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    arguments = function.args
    parameters = [(a.arg, _KINDS.POSITIONAL_ONLY.name) for a in arguments.posonlyargs]
    parameters += [(a.arg, _KINDS.POSITIONAL_OR_KEYWORD.name) for a in arguments.args]
    if arguments.vararg:
        parameters.append((arguments.vararg.arg, _KINDS.VAR_POSITIONAL.name))
    parameters += [(a.arg, _KINDS.KEYWORD_ONLY.name) for a in arguments.kwonlyargs]
    if arguments.kwarg:
        parameters.append((arguments.kwarg.arg, _KINDS.VAR_KEYWORD.name))
    return parameters


def _stubbed_classes() -> list[tuple[str, ast.ClassDef]]:
    classes: list[tuple[str, ast.ClassDef]] = []
    for path in sorted(STUBS.glob("*.pyi")):
        module = "socketio" if path.stem == "__init__" else f"socketio.{path.stem}"
        tree = ast.parse(path.read_text())
        classes += [(module, node) for node in tree.body if isinstance(node, ast.ClassDef)]
    return classes


CLASSES = _stubbed_classes()


def test_stubs_cover_the_classes_the_kernel_uses() -> None:
    names = {f"{module}.{node.name}" for module, node in CLASSES}
    assert {
        "socketio.AsyncServer",
        "socketio.AsyncClient",
        "socketio.ASGIApp",
        "socketio.async_pubsub_manager.AsyncPubSubManager",
        "socketio.exceptions.ConnectionRefusedError",
    } <= names


@pytest.mark.parametrize(("module", "node"), CLASSES, ids=[f"{m}.{n.name}" for m, n in CLASSES])
def test_stub_signatures_match_the_installed_package(module: str, node: ast.ClassDef) -> None:
    runtime = getattr(importlib.import_module(module), node.name)
    for item in node.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            actual = [
                (name, parameter.kind.name)
                for name, parameter in inspect.signature(
                    getattr(runtime, item.name)
                ).parameters.items()
            ]
            assert actual == _stub_parameters(item), f"{node.name}.{item.name}"
            if item.name == "_listen":
                # The upstream base is a coroutine placeholder; the real contract is how
                # _thread consumes subclasses: as an async iterator.
                consumer = inspect.getsource(runtime._thread)
                assert "async for message in self._listen()" in consumer
            else:
                assert inspect.iscoroutinefunction(getattr(runtime, item.name)) is isinstance(
                    item, ast.AsyncFunctionDef
                ), f"{node.name}.{item.name} async-ness"
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            attribute = item.target.id
            source = "".join(inspect.getsource(cls) for cls in runtime.__mro__[:-1])
            assert f"self.{attribute} =" in source or hasattr(runtime, attribute), (
                f"{node.name}.{attribute}"
            )
