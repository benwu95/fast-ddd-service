import logging
from contextlib import ExitStack

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fast_ddd.context import trace_scope, unit_of_work_context
from fast_ddd_adapter.observability import resolve_trace_id
from fast_ddd_adapter.session import SessionProvider, session_provider_scope
from fast_ddd_port.auth import JwtVerifier, principal_scope
from fast_ddd_port.problems import HttpProblem, kernel_problem, problem_response

logger = logging.getLogger(__name__)

TRACE_HEADER = "X-Trace-Id"
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def _has_body(headers: Headers) -> bool:
    length = headers.get("content-length")
    if length is not None:
        return length.strip() not in ("", "0")
    return "chunked" in headers.get("transfer-encoding", "").lower()


def _is_json(headers: Headers) -> bool:
    media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return media_type == "application/json"


def _bearer_token(headers: Headers) -> str:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HttpProblem("auth.unauthenticated", headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


class UnitOfWorkMiddleware:
    """Per request: trace id, 415 check, JWT, unit-of-work context, and the 500 fallback.

    Pure ASGI (not ``BaseHTTPMiddleware``) and placed inside CORS, so every response it
    produces, including 401 and 500, carries CORS headers and ``X-Trace-Id``.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        verifier: JwtVerifier,
        session_factory: async_sessionmaker[AsyncSession],
        public_paths: list[str],
    ) -> None:
        self.app = app
        self._verifier = verifier
        self._session_factory = session_factory
        self._public_paths = frozenset(public_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        trace_id = resolve_trace_id()
        started = False

        async def send_with_trace(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                MutableHeaders(scope=message)[TRACE_HEADER] = trace_id
            await send(message)

        with trace_scope(trace_id):
            try:
                await self._handle(scope, receive, send_with_trace, trace_id)
            except HttpProblem as problem:
                response = problem_response(
                    kernel_problem(problem.code, problem.detail), problem.headers
                )
                await response(scope, receive, send_with_trace)
            except Exception:
                logger.exception("unhandled error")
                if started:
                    raise
                response = problem_response(kernel_problem("server.internal_error"))
                await response(scope, receive, send_with_trace)

    async def _handle(self, scope: Scope, receive: Receive, send: Send, trace_id: str) -> None:
        headers = Headers(scope=scope)
        if scope["method"] in _BODY_METHODS and _has_body(headers) and not _is_json(headers):
            raise HttpProblem("request.unsupported_media_type")
        if scope["path"] in self._public_paths or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        principal = await self._verifier.verify(_bearer_token(headers))
        with ExitStack() as stack:
            stack.enter_context(principal_scope(principal))
            stack.enter_context(
                unit_of_work_context(
                    user=principal.user,
                    organization_id=principal.organization_id,
                    trace_id=trace_id,
                )
            )
            stack.enter_context(session_provider_scope(SessionProvider(self._session_factory)))
            await self.app(scope, receive, send)
