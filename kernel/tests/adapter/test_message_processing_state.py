from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd_adapter.messaging import claim_message, is_processed


async def test_processed_message_lookup_follows_claim_and_rollback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    event_id = uuid4()
    async with session_factory() as session:
        assert not await is_processed(session, "consumer", event_id)
        assert await claim_message(session, "consumer", event_id)
        assert await is_processed(session, "consumer", event_id)
        assert not await is_processed(session, "other-consumer", event_id)
        assert not await is_processed(session, "consumer", uuid4())
        await session.rollback()
        assert not await is_processed(session, "consumer", event_id)
    async with session_factory() as session:
        assert not await is_processed(session, "consumer", event_id)
