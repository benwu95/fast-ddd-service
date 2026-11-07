import asyncio
from collections.abc import AsyncIterator
from typing import Any

from socketio.async_manager import AsyncManager

class AsyncPubSubManager(AsyncManager):
    name: str
    channel: str
    write_only: bool
    host_id: str
    thread: asyncio.Task[None]
    def __init__(
        self,
        channel: str = "socketio",
        write_only: bool = False,
        logger: Any = None,
        json: Any = None,
    ) -> None: ...
    async def emit(
        self,
        event: str,
        data: Any,
        namespace: str | None = None,
        room: str | list[str] | None = None,
        skip_sid: str | None = None,
        callback: Any = None,
        to: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None: ...
    async def _publish(self, data: Any) -> None: ...
    def _listen(self) -> AsyncIterator[Any]: ...
    async def _thread(self) -> None: ...
