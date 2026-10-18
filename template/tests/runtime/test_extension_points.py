from dataclasses import fields
from typing import Any, cast
from unittest.mock import Mock

import asyncpg
import pytest
from fast_ddd_adapter.infrastructure import NotConfiguredError
from fast_ddd_port.tasks import TaskRegistry
from pgqueuer import PgQueuer
from pydantic import ValidationError

from app import task_worker, wiring
from app.adapter import resources
from app.bootstrap import Runtime
from tests.runtime.support import runtime, settings


def test_service_resources_require_explicit_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "_resources", None)
    with pytest.raises(NotConfiguredError):
        resources.resources()
    values: dict[str, Any] = {field.name: Mock() for field in fields(resources.Resources)}
    configured = resources.Resources(**values)
    resources.configure_resources(configured)
    assert resources.resources() is configured


def test_service_task_registry_reaches_the_kernel_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = TaskRegistry()
    wiring.wire_tasks(expected)
    hook = Mock(wraps=task_worker.wire_tasks)
    monkeypatch.setattr(task_worker, "wire_tasks", hook)
    worker = Mock(spec=PgQueuer)
    build = Mock(return_value=worker)
    monkeypatch.setattr(task_worker, "build_worker", build)
    configured = runtime()
    connection = cast(asyncpg.Connection, Mock())
    assert task_worker.build_task_worker(cast(Runtime, configured), connection) is worker
    hook.assert_called_once()
    build.assert_called_once_with(connection, hook.call_args.args[0], configured.session_factory)
    registry = cast(TaskRegistry, build.call_args.args[1])
    assert registry.tasks.keys() == expected.tasks.keys()
    assert registry.schedules.keys() == expected.schedules.keys()


def test_worker_settings_validate_probe_and_drain_limits() -> None:
    configured = settings()
    assert configured.worker_health_port == 8081
    assert configured.worker_health_timeout_seconds == 5
    assert configured.worker_shutdown_timeout_seconds == 30
    for values in (
        {"worker_health_port": 65536},
        {"worker_health_timeout_seconds": 0},
        {"worker_shutdown_timeout_seconds": 0},
    ):
        with pytest.raises(ValidationError):
            settings(**values)
