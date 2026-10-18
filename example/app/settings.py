from fast_ddd_port.settings import KernelSettings
from pydantic import Field


class Settings(KernelSettings):
    notification_url: str
    notification_timeout_seconds: float = 5.0

    worker_health_host: str = "127.0.0.1"
    worker_health_port: int = Field(default=8081, ge=0, le=65535)
    worker_health_timeout_seconds: float = Field(default=5.0, gt=0)
    worker_shutdown_timeout_seconds: float = Field(default=30.0, gt=0)
