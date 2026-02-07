from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from sessionbus.models import IdempotencyKey, InputRequest, RequestPriority, RequestStatus, SessionState
from sessionbus.schemas import InputRequestCreateRequest, InputRequestResponseRequest
from sessionbus.services import inbox
from sessionbus.services.events import event_bus
from sessionbus.services.sessions import get_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_idempotency_record(db: AsyncSession, *, scope: str, key: str) -> IdempotencyKey | None:
    stmt = select(IdempotencyKey).where(
        IdempotencyKey.scope == scope,
        IdempotencyKey.key == key,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_request(db: AsyncSession, request_id: str) -> InputRequest | None:
    stmt = select(InputRequest).where(InputRequest.request_id == request_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_request(
    db: AsyncSession,
    *,
    session_id: str,
    payload: InputRequestCreateRequest,
    idempotency_key: str | None,
) -> tuple[InputRequest | None, bool]:
    session = await get_session(db, session_id)
    if session is None:
        return None, False

    scope = f"request.create:{session_id}"
    if idempotency_key:
        existing_key = await _get_idempotency_record(db, scope=scope, key=idempotency_key)
        if existing_key:
            existing_request = await get_request(db, existing_key.resource_id)
            if existing_request:
                return existing_request, True

    request_obj = InputRequest(
        request_id=str(uuid4()),
        session_id=session_id,
        title=payload.title,
        question=payload.question,
        context_json=payload.context_json,
        priority=payload.priority,
        tags_json=payload.tags,
        status=RequestStatus.PENDING,
    )
    session.state = SessionState.WAITING_FOR_INPUT
    session.last_seen_at = _now()

    db.add(request_obj)
    if idempotency_key:
        db.add(
            IdempotencyKey(
                scope=scope,
                key=idempotency_key,
                resource_type="input_request",
                resource_id=request_obj.request_id,
            )
        )

    await db.commit()
    await db.refresh(request_obj)

    await event_bus.publish(
        "request.created",
        {
            "request_id": request_obj.request_id,
            "session_id": request_obj.session_id,
            "priority": request_obj.priority.value,
        },
    )
    return request_obj, False


async def list_requests(
    db: AsyncSession,
    *,
    status: RequestStatus | None,
) -> list[InputRequest]:
    stmt = select(InputRequest)
    if status is not None:
        stmt = stmt.where(InputRequest.status == status)

    if status == RequestStatus.PENDING:
        priority_rank = case(
            (InputRequest.priority == RequestPriority.URGENT, 0),
            (InputRequest.priority == RequestPriority.HIGH, 1),
            (InputRequest.priority == RequestPriority.NORMAL, 2),
            (InputRequest.priority == RequestPriority.LOW, 3),
            else_=4,
        )
        stmt = stmt.order_by(priority_rank, InputRequest.created_at.asc())
    else:
        stmt = stmt.order_by(InputRequest.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def respond_to_request(
    db: AsyncSession,
    *,
    request_id: str,
    payload: InputRequestResponseRequest,
    idempotency_key: str | None,
) -> tuple[InputRequest | None, bool]:
    request_obj = await get_request(db, request_id)
    if request_obj is None:
        return None, False

    scope = f"request.respond:{request_id}"
    if idempotency_key:
        existing_key = await _get_idempotency_record(db, scope=scope, key=idempotency_key)
        if existing_key:
            existing_request = await get_request(db, existing_key.resource_id)
            if existing_request:
                return existing_request, True

    if request_obj.status == RequestStatus.ANSWERED:
        return request_obj, True

    request_obj.status = RequestStatus.ANSWERED
    request_obj.response_text = payload.response_text
    request_obj.responder = payload.responder
    request_obj.answered_at = _now()

    session = await get_session(db, request_obj.session_id)
    if session is not None:
        session.state = SessionState.WORKING
        session.last_seen_at = _now()

    await inbox.enqueue_message(
        db,
        session_id=request_obj.session_id,
        message_type="INPUT_RESPONSE",
        payload={
            "request_id": request_obj.request_id,
            "response_text": payload.response_text,
            "responder": payload.responder,
            "answered_at": request_obj.answered_at.isoformat() if request_obj.answered_at else None,
        },
        autocommit=False,
    )

    if idempotency_key:
        db.add(
            IdempotencyKey(
                scope=scope,
                key=idempotency_key,
                resource_type="input_request",
                resource_id=request_obj.request_id,
            )
        )

    await db.commit()
    await db.refresh(request_obj)

    await event_bus.publish(
        "request.answered",
        {
            "request_id": request_obj.request_id,
            "session_id": request_obj.session_id,
        },
    )
    return request_obj, False
