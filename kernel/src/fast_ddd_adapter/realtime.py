"""Realtime push over Socket.IO: room names, the RabbitMQ pub/sub backend and after-commit pushes.

Needs the ``realtime`` extra. Pushes always name their rooms; nothing is broadcast to every
connection.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from uuid import UUID

try:
    from socketio.async_pubsub_manager import AsyncPubSubManager
except ImportError as error:
    raise ImportError(
        "realtime push needs the socketio dependency: install fast-ddd-kernel[realtime]"
    ) from error

import aio_pika
from aio_pika import RobustConnection
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractRobustConnection
from aio_pika.connection import make_url

from fast_ddd.context import current_organization_id
from fast_ddd_adapter.infrastructure import NotConfiguredError
from fast_ddd_adapter.session import current_session_provider

logger = logging.getLogger(__name__)

_RESOURCE_NAME = re.compile(r"[a-z][a-z0-9_]*")
_SERVICE_NAME = re.compile(r"[a-z][a-z0-9_-]*")


class RealtimePushError(ValueError):
    """A push that cannot be delivered as requested: no room, no organization or non-JSON data."""


def organization_room(organization_id: UUID) -> str:
    return f"org:{organization_id}"


def user_room(user_id: str) -> str:
    if not user_id.strip():
        raise ValueError("user id must not be empty")
    return f"user:{user_id}"


def realtime_channel(service: str) -> str:
    """One fanout exchange per service: services sharing a broker never see each other's pushes."""
    if _SERVICE_NAME.fullmatch(service) is None:
        raise ValueError(
            f"service name must be lower case letters, digits, '_' or '-': {service!r}"
        )
    return f"fast_ddd.realtime.{service}"


def is_resource_name(name: str) -> bool:
    return _RESOURCE_NAME.fullmatch(name) is not None


def resource_room(organization_id: UUID, resource: str, resource_id: UUID) -> str:
    """The room of one resource, always inside its organization's namespace."""
    if not is_resource_name(resource):
        raise ValueError(f"resource name must be lower snake_case: {resource!r}")
    return f"org:{organization_id}:{resource}:{resource_id}"


async def _close_quietly(connection: AbstractRobustConnection) -> None:
    try:
        await connection.close()
    except Exception:
        logger.warning("closing the realtime RabbitMQ connection failed", exc_info=True)


class KernelAioPikaManager(AsyncPubSubManager):
    """Socket.IO pub/sub over a RabbitMQ fanout exchange, one exclusive queue per server.

    Replaces upstream ``AsyncAioPikaManager``: its transient non-exclusive queue is refused by
    RabbitMQ 4, an interrupted connect leaves its publisher unusable, and it has no close.
    """

    name = "fast_ddd_aiopika"

    def __init__(
        self,
        url: str,
        *,
        channel: str,
        write_only: bool = False,
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        super().__init__(channel=channel, write_only=write_only)
        self._url = url
        self._connect_timeout = connect_timeout_seconds
        self._publish_lock = asyncio.Lock()
        self._publisher: tuple[AbstractRobustConnection, AbstractExchange] | None = None
        self._closed = False
        self._listener_connection: AbstractRobustConnection | None = None
        # Cleared while the listener is inside connect_robust: cancelling it there leaks
        # aiormq tasks, so close() waits for this before cancelling the listener.
        self._listener_idle = asyncio.Event()
        self._listener_idle.set()

    async def _connect(self) -> AbstractRobustConnection:
        # connect_robust() would hide the connection while its background factory keeps
        # reconnecting after a timeout or cancellation; closing it is what stops that loop.
        connection = RobustConnection(make_url(self._url))
        try:
            await connection.connect(timeout=self._connect_timeout)
        except BaseException:
            await asyncio.shield(_close_quietly(connection))
            raise
        return connection

    async def _exchange(self, channel: AbstractChannel) -> AbstractExchange:
        return await channel.declare_exchange(self.channel, aio_pika.ExchangeType.FANOUT)

    async def _current_publisher(self) -> tuple[AbstractRobustConnection, AbstractExchange]:
        async with self._publish_lock:
            if self._closed:
                raise RuntimeError("the realtime manager is closed")
            if self._publisher is None:
                connection = await self._connect()
                try:
                    exchange = await self._exchange(await connection.channel())
                except BaseException:
                    await asyncio.shield(_close_quietly(connection))
                    raise
                self._publisher = (connection, exchange)
            return self._publisher

    async def _discard(self, publisher: tuple[AbstractRobustConnection, AbstractExchange]) -> None:
        # Only the attempt's own connection: another attempt may already have replaced it.
        if self._publisher is publisher:
            self._publisher = None
            await asyncio.shield(_close_quietly(publisher[0]))

    async def _reset_publisher(self) -> None:
        if self._publisher is not None:
            await self._discard(self._publisher)

    async def _publish(self, data: Any) -> None:
        message = aio_pika.Message(body=self.json.dumps(data).encode())
        for attempt in (1, 2):
            publisher = await self._current_publisher()
            try:
                await publisher[1].publish(message, routing_key="*")
                return
            except Exception:
                # A dropped broker connection fails the first publish; one fresh
                # connection keeps the push that happens to come right after. A cancelled
                # publish leaves the shared connection alone.
                await self._discard(publisher)
                if attempt == 2:
                    raise

    async def _listen(self) -> AsyncIterator[bytes]:
        retry_seconds = 1.0
        while True:
            try:
                self._listener_idle.clear()
                try:
                    connection = await self._connect()
                finally:
                    self._listener_idle.set()
                self._listener_connection = connection
                async with connection:
                    channel = await connection.channel()
                    await channel.set_qos(prefetch_count=1)
                    exchange = await self._exchange(channel)
                    queue = await channel.declare_queue(exclusive=True)
                    await queue.bind(exchange)
                    async with queue.iterator() as messages:
                        async for message in messages:
                            async with message.process():
                                yield message.body
                            retry_seconds = 1.0
            except Exception:
                logger.exception(
                    "realtime listener lost RabbitMQ; retrying in %s seconds", retry_seconds
                )
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, 60.0)

    async def close(self) -> None:
        """Stop the listener and close both RabbitMQ connections; later publishes fail."""
        self._closed = True
        thread: asyncio.Task[None] | None = getattr(self, "thread", None)
        if thread is not None and not thread.done():
            try:
                await asyncio.wait_for(self._listener_idle.wait(), self._connect_timeout + 1)
            except TimeoutError:
                logger.warning("realtime listener is still connecting; cancelling it anyway")
            thread.cancel()
            await asyncio.gather(thread, return_exceptions=True)
        # A listener cancelled while its generator is suspended at yield closes the connection
        # only when the generator is finalized later; close it now.
        listener, self._listener_connection = self._listener_connection, None
        if listener is not None:
            await asyncio.shield(_close_quietly(listener))
        async with self._publish_lock:  # waits for a publisher connection still being created
            await self._reset_publisher()


class RealtimeEmitter:
    """Sends pushes through a write-only manager; every process emits the same way."""

    def __init__(self, manager: KernelAioPikaManager, *, emit_timeout_seconds: float) -> None:
        self._manager = manager
        self._timeout = emit_timeout_seconds

    async def emit(self, event: str, data: Mapping[str, Any], *, to: list[str]) -> None:
        if not to:
            raise RealtimePushError("a push needs at least one room; it is never broadcast")
        try:
            async with asyncio.timeout(self._timeout):
                await self._manager.emit(event, data, namespace="/", to=to)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            # A concurrent reset closed the shared channel; aiormq rejects pending
            # publishes with CancelledError, which would otherwise skip the other hooks.
            raise RealtimePushError("the realtime publish was interrupted by a reset") from None

    async def close(self) -> None:
        await self._manager.close()


def create_realtime_emitter(
    url: str,
    *,
    service: str,
    emit_timeout_seconds: float = 5.0,
    connect_timeout_seconds: float = 3.0,
) -> RealtimeEmitter:
    """The write-only emitter of ``service``; pair it with ``mount_realtime(service=...)``."""
    manager = KernelAioPikaManager(
        url,
        channel=realtime_channel(service),
        write_only=True,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    return RealtimeEmitter(manager, emit_timeout_seconds=emit_timeout_seconds)


_emitter: RealtimeEmitter | None = None


def configure_realtime(emitter: RealtimeEmitter) -> None:
    global _emitter
    _emitter = emitter


def realtime_emitter() -> RealtimeEmitter:
    if _emitter is None:
        raise NotConfiguredError("fast_ddd_adapter.realtime.configure_realtime() was not called")
    return _emitter


def _target_rooms(
    organization: bool, users: Sequence[str], resources: Sequence[tuple[str, UUID]]
) -> list[str]:
    if isinstance(users, str):
        raise RealtimePushError("users must be a sequence of user ids, not one string")
    rooms = [user_room(user_id) for user_id in users]
    if organization or resources:
        organization_id = current_organization_id()
        if organization_id is None:
            raise RealtimePushError("organization and resource rooms need an organization")
        if organization:
            rooms.append(organization_room(organization_id))
        rooms.extend(resource_room(organization_id, name, id_) for name, id_ in resources)
    if not rooms:
        raise RealtimePushError("a push needs at least one room; it is never broadcast")
    return list(dict.fromkeys(rooms))


def _snapshot(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(body, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as error:
        raise RealtimePushError(f"push data must be JSON: {error}") from error


def push_after_commit(
    event_name: str,
    event_version: int,
    data: Mapping[str, Any],
    *,
    organization: bool = False,
    users: Sequence[str] = (),
    resources: Sequence[tuple[str, UUID]] = (),
) -> None:
    """Stage a push for after the outermost commit; rollback discards it.

    ``data`` is sent as given (serialize it, e.g. with ``to_json(..., camel_case=True)``,
    before calling). Raises ``RealtimePushError`` now, inside the transaction, when the push
    has no room, needs an organization the unit of work lacks, or is not JSON.
    """
    rooms = _target_rooms(organization, users, resources)
    body = _snapshot({"eventName": event_name, "eventVersion": event_version, "data": dict(data)})
    emitter = realtime_emitter()
    current_session_provider().after_commit(lambda: emitter.emit(event_name, body, to=rooms))
