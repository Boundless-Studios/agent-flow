from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sessionbus.models import InboxMessage, MessageStatus
from sessionbus.services.sessions import get_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue_message(
    db: AsyncSession,
    *,
    session_id: str,
    message_type: str,
    payload: dict,
    autocommit: bool = True,
) -> InboxMessage:
    message = InboxMessage(
        message_id=str(uuid4()),
        session_id=session_id,
        message_type=message_type,
        payload_json=payload,
        status=MessageStatus.PENDING,
    )
    db.add(message)
    if autocommit:
        await db.commit()
        await db.refresh(message)
    return message


async def _list_unacked_messages(db: AsyncSession, *, session_id: str) -> list[InboxMessage]:
    stmt = (
        select(InboxMessage)
        .where(InboxMessage.session_id == session_id, InboxMessage.status != MessageStatus.ACKED)
        .order_by(InboxMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def poll_messages(db: AsyncSession, *, session_id: str, timeout: int) -> tuple[list[InboxMessage] | None, bool]:
    session = await get_session(db, session_id)
    if session is None:
        return None, False

    timeout_s = max(0, min(timeout, 120))
    deadline = time.monotonic() + timeout_s

    while True:
        messages = await _list_unacked_messages(db, session_id=session_id)
        if messages:
            delivered_at = _now()
            for message in messages:
                if message.status == MessageStatus.PENDING:
                    message.status = MessageStatus.DELIVERED
                    message.delivered_at = delivered_at

            await db.commit()
            for message in messages:
                await db.refresh(message)
            return messages, True

        if time.monotonic() >= deadline:
            return [], True

        await asyncio.sleep(1)


async def ack_message(
    db: AsyncSession,
    *,
    session_id: str,
    message_id: str,
) -> tuple[InboxMessage | None, bool]:
    stmt = select(InboxMessage).where(
        InboxMessage.session_id == session_id,
        InboxMessage.message_id == message_id,
    )
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()
    if message is None:
        return None, False

    if message.status != MessageStatus.ACKED:
        message.status = MessageStatus.ACKED
        message.acked_at = _now()
        await db.commit()
        await db.refresh(message)
    return message, True
