from collections.abc import Callable, Mapping, Sequence
from typing import Any

from socketio.async_manager import AsyncManager as AsyncManager

class AsyncServer:
    manager: AsyncManager
    eio: Any
    def __init__(
        self,
        client_manager: AsyncManager | None = None,
        logger: bool = False,
        json: Any = None,
        async_handlers: bool = True,
        namespaces: Any = None,
        **kwargs: Any,
    ) -> None: ...
    def on(
        self,
        event: str,
        handler: Callable[..., Any] | None = None,
        namespace: str | None = None,
    ) -> Any: ...
    async def emit(
        self,
        event: str,
        data: Any = None,
        to: str | list[str] | None = None,
        room: str | list[str] | None = None,
        skip_sid: str | None = None,
        namespace: str | None = None,
        callback: Callable[..., Any] | None = None,
        ignore_queue: bool = False,
    ) -> None: ...
    async def enter_room(self, sid: str, room: str, namespace: str | None = None) -> None: ...
    async def leave_room(self, sid: str, room: str, namespace: str | None = None) -> None: ...
    async def get_session(self, sid: str, namespace: str | None = None) -> dict[str, Any]: ...
    async def save_session(
        self, sid: str, session: dict[str, Any], namespace: str | None = None
    ) -> None: ...
    async def shutdown(self) -> None: ...
    async def _handle_connect(self, eio_sid: str, namespace: str | None, data: Any) -> None: ...
    async def _handle_eio_connect(self, eio_sid: str, environ: Any) -> bool | None: ...
    async def _handle_eio_disconnect(self, eio_sid: str, reason: Any) -> None: ...

class AsyncClient:
    connected: bool
    def __init__(
        self,
        reconnection: bool = True,
        reconnection_attempts: int = 0,
        reconnection_delay: float = 1,
        reconnection_delay_max: float = 5,
        randomization_factor: float = 0.5,
        logger: bool = False,
        serializer: str = "default",
        json: Any = None,
        handle_sigint: bool = True,
        **kwargs: Any,
    ) -> None: ...
    def on(
        self,
        event: str,
        handler: Callable[..., Any] | None = None,
        namespace: str | None = None,
    ) -> Any: ...
    async def connect(
        self,
        url: str,
        headers: Mapping[str, str] = {},
        auth: Any = None,
        transports: Sequence[str] | None = None,
        namespaces: Any = None,
        socketio_path: str = "socket.io",
        wait: bool = True,
        wait_timeout: float = 1,
        retry: bool = False,
    ) -> None: ...
    async def emit(
        self,
        event: str,
        data: Any = None,
        namespace: str | None = None,
        callback: Callable[..., Any] | None = None,
    ) -> None: ...
    async def call(
        self, event: str, data: Any = None, namespace: str | None = None, timeout: float = 60
    ) -> Any: ...
    async def disconnect(self) -> None: ...

class ASGIApp:
    def __init__(
        self,
        socketio_server: AsyncServer,
        other_asgi_app: Any = None,
        static_files: Any = None,
        socketio_path: str = "socket.io",
        on_startup: Any = None,
        on_shutdown: Any = None,
    ) -> None: ...
    async def __call__(self, scope: Any, receive: Any, send: Any) -> None: ...
