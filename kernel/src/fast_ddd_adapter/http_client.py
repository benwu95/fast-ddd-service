import asyncio
import logging
import time
from collections.abc import Mapping

import httpx2
from opentelemetry import propagate
from opentelemetry.trace import SpanKind, Status, StatusCode

from fast_ddd_adapter.observability import meter, tracer

logger = logging.getLogger(__name__)

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_SENSITIVE_PARTS = ("auth", "token", "password", "secret", "key", "signature", "session")
REDACTED = "REDACTED"

_duration = meter.create_histogram(
    "http.client.request.duration", unit="s", description="Outbound HTTP calls by target service"
)


def redact_url(url: httpx2.URL) -> str:
    """The URL without credentials, and with sensitive-looking query values masked."""
    params = [
        (name, REDACTED if any(part in name.lower() for part in _SENSITIVE_PARTS) else value)
        for name, value in url.params.multi_items()
    ]
    return str(url.copy_with(username=None, password=None, params=params or None))


class _KernelTransport(httpx2.AsyncBaseTransport):
    def __init__(
        self, service: str, inner: httpx2.AsyncBaseTransport, *, retries: int, retry_delay: float
    ) -> None:
        self._service = service
        self._inner = inner
        self._retries = retries
        self._retry_delay = retry_delay

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        method = request.method
        url = redact_url(request.url)
        attributes: dict[str, str | int] = {
            "service.peer.name": self._service,
            "http.request.method": method,
        }
        started = time.perf_counter()
        with tracer.start_as_current_span(
            method, kind=SpanKind.CLIENT, attributes={**attributes, "url.full": url}
        ) as span:
            propagate.inject(request.headers)
            try:
                response = await self._send(request)
                attributes["http.response.status_code"] = response.status_code
            except httpx2.TransportError as error:
                attributes["error.type"] = type(error).__name__
                logger.warning("outbound request failed", extra={**attributes, "url.full": url})
                raise
            finally:
                _duration.record(time.perf_counter() - started, attributes)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
        logger.info(
            "outbound request",
            extra={
                **attributes,
                "url.full": url,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return response

    async def _send(self, request: httpx2.Request) -> httpx2.Response:
        attempt = 0
        while True:
            try:
                return await self._inner.handle_async_request(request)
            except (httpx2.NetworkError, httpx2.TimeoutException):
                if request.method not in IDEMPOTENT_METHODS or attempt >= self._retries:
                    raise
            attempt += 1
            await asyncio.sleep(self._retry_delay * 2 ** (attempt - 1))

    async def aclose(self) -> None:
        await self._inner.aclose()


def create_http_client(
    service: str,
    *,
    base_url: str,
    timeout: httpx2.Timeout | float,
    headers: Mapping[str, str] | None = None,
    retries: int = 2,
    retry_delay: float = 0.2,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> httpx2.AsyncClient:
    """One shared client per target service; close it at shutdown.

    ``timeout`` is required. Only idempotent methods are retried, and only on connection-level
    failures (network errors, timeouts); a received HTTP response is never retried.
    """
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        headers=headers,
        transport=_KernelTransport(
            service,
            transport or httpx2.AsyncHTTPTransport(),
            retries=retries,
            retry_delay=retry_delay,
        ),
    )
