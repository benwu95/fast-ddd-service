from dataclasses import dataclass

from fast_ddd_adapter.infrastructure import NotConfiguredError


@dataclass(frozen=True, slots=True)
class Resources:
    """Service-owned infrastructure, built once at startup by ``wire_resources``."""


_resources: Resources | None = None


def configure_resources(resources: Resources) -> None:
    global _resources
    _resources = resources


def resources() -> Resources:
    if _resources is None:
        raise NotConfiguredError("app.adapter.resources was not configured at startup")
    return _resources
