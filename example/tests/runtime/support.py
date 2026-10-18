from typing import Any
from unittest.mock import AsyncMock, Mock

from fast_ddd_port.settings import JwtSettings

from app.bootstrap import Runtime
from app.settings import Settings

JWT_SETTINGS = JwtSettings(
    issuer="https://issuer.test",
    audience="runtime-tests",
    jwks_url="https://issuer.test/jwks",
    user_id_claim="sub",
    organization_id_claim="org",
    permissions_claim="scope",
    permissions_format="space_separated",
)


def settings(**values: Any) -> Settings:
    configured: dict[str, Any] = {
        "service_name": "runtime-test",
        "database_url": "postgresql+asyncpg://u:p@localhost/test",
        "rabbitmq_url": "amqp://guest:guest@localhost/",
        "jwt": JWT_SETTINGS,
        **values,
    }
    return Settings(**configured)


def runtime() -> Mock:
    result = Mock(spec=Runtime)
    result.settings = settings(worker_shutdown_timeout_seconds=0.05)
    result.close = AsyncMock()
    result.broker = Mock()
    result.broker.connect = AsyncMock()
    result.broker.stop = AsyncMock()
    return result
