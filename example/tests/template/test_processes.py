import json
import signal
from http.client import RemoteDisconnected
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest

from tests.template import runtime_support
from tests.template.runtime_support import (
    ROLES,
    Role,
    RuntimeInfrastructure,
    assert_empty_wiring,
    assert_port_closed,
    assert_process_group_closed,
    assert_runtime_clean,
    prepare_runtime_database,
    role_command,
    runtime_environment,
    service_process,
    unused_port,
    wait_health,
)


@pytest.mark.parametrize(
    "failure", [RemoteDisconnected("starting"), ConnectionResetError("starting")]
)
def test_health_poll_waits_for_transport_and_all_role_probes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: ConnectionError
) -> None:
    responses = [MagicMock() for _ in range(6)]
    for response in responses:
        response.__enter__.return_value.status = 200
    request = Mock(side_effect=[failure, *responses])
    monkeypatch.setattr(runtime_support, "urlopen", request)
    process = Mock()
    process.poll.return_value = None
    log = tmp_path / "startup.log"
    log.write_text("starting\n")
    wait_health(8080, "worker", process, log, timeout=2)
    assert request.call_count == 7


def test_runtime_environment_overrides_defaults_and_isolates_inherited_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "JWT__ISSUER"):
        monkeypatch.setenv(key, "inherited")
    infrastructure = cast(
        RuntimeInfrastructure, Mock(database_url="original-database", amqp_url="original-broker")
    )
    environment = runtime_environment(
        infrastructure, 8080, DATABASE_URL="container-database", WORKER_HEALTH_HOST="0.0.0.0"
    )
    assert environment["DATABASE_URL"] == "container-database"
    assert environment["WORKER_HEALTH_HOST"] == "0.0.0.0"
    assert environment["WORKER_HEALTH_PORT"] == "8080"
    assert environment["RABBITMQ_URL"] == "original-broker"
    assert json.loads(environment["JWT"])["issuer"] == "smoke"
    assert not {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "JWT__ISSUER"} & (
        environment.keys()
    )


@pytest.mark.parametrize("role", ROLES)
def test_empty_service_roles_start_and_stop_with_real_infrastructure(
    generated_service: Path,
    runtime_infrastructure: RuntimeInfrastructure,
    tmp_path: Path,
    role: Role,
) -> None:
    infrastructure = runtime_infrastructure
    port = unused_port()
    environment = runtime_environment(infrastructure, port)
    sentinel = prepare_runtime_database(generated_service, infrastructure, environment)
    assert_empty_wiring(generated_service, environment)
    log = tmp_path / f"{role}.log"
    with service_process(
        generated_service, role_command(generated_service, role, port), environment, log
    ) as process:
        wait_health(port, role, process, log)
        assert infrastructure.consumers() == []
        assert infrastructure.queues() == []
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=12) == (0 if role == "worker" else -signal.SIGTERM), (
            log.read_text()
        )
    assert_port_closed(port)
    assert_process_group_closed(process.pid)
    assert_runtime_clean(infrastructure, sentinel)


def test_real_startup_failure_leaves_no_process_or_connections(
    generated_service: Path,
    runtime_infrastructure: RuntimeInfrastructure,
    tmp_path: Path,
) -> None:
    infrastructure = runtime_infrastructure
    port = unused_port()
    environment = runtime_environment(infrastructure, port)
    sentinel = prepare_runtime_database(generated_service, infrastructure, environment)
    environment["RABBITMQ_URL"] = f"amqp://smoke:smoke@127.0.0.1:{unused_port()}/smoke"
    log = tmp_path / "failed-startup.log"
    with service_process(
        generated_service, role_command(generated_service, "worker", port), environment, log
    ) as process:
        assert process.wait(timeout=15) != 0
    assert "AMQPConnectionError" in log.read_text()
    assert_port_closed(port)
    assert_process_group_closed(process.pid)
    assert_runtime_clean(infrastructure, sentinel)


def test_health_watchdog_cleans_up_a_running_service(
    generated_service: Path,
    runtime_infrastructure: RuntimeInfrastructure,
    tmp_path: Path,
) -> None:
    infrastructure = runtime_infrastructure
    port = unused_port()
    environment = runtime_environment(infrastructure, port)
    sentinel = prepare_runtime_database(generated_service, infrastructure, environment)
    log = tmp_path / "watchdog.log"
    with service_process(
        generated_service, role_command(generated_service, "api", port), environment, log
    ) as process:
        wait_health(port, "api", process, log)
        with pytest.raises(TimeoutError, match="health deadline"):
            wait_health(unused_port(), "api", process, log, timeout=0.2)
    assert process.returncode is not None
    assert_port_closed(port)
    assert_process_group_closed(process.pid)
    assert_runtime_clean(infrastructure, sentinel)
