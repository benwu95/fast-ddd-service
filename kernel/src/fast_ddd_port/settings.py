from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from fast_ddd_adapter.observability import TelemetryExporter


class JwtSettings(BaseModel):
    """JWT validation. Claim names have no defaults: they depend on the identity provider."""

    issuer: str
    audience: str
    jwks_url: str
    algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    user_id_claim: str
    organization_id_claim: str
    permissions_claim: str
    permissions_format: Literal["space_separated", "list"]
    leeway_seconds: int = 30
    jwks_cache_seconds: int = 300


class KernelSettings(BaseSettings):
    """Settings the kernel needs; a service's own settings class inherits from this.

    Nested values come from ``__``-delimited environment variables, e.g. ``JWT__ISSUER``.
    """

    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")

    service_name: str
    database_url: str
    rabbitmq_url: str | None = None
    jwt: JwtSettings
    cors_allow_origins: list[str] = Field(default_factory=list[str])
    public_paths: list[str] = Field(
        default_factory=lambda: ["/health/live", "/health/ready", "/docs", "/openapi.json"]
    )
    lock_timeout_ms: int = 5_000
    statement_timeout_ms: int = 30_000
    idle_in_transaction_session_timeout_ms: int = 60_000
    log_level: str = "INFO"
    telemetry_exporter: TelemetryExporter = "none"


def load_settings[S: BaseSettings](settings_class: type[S]) -> S:
    """Read settings from the environment; missing required values fail startup."""
    return settings_class()
