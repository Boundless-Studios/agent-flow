from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sessionbus.models import InboxMessage, InputRequest, MessageStatus, RequestStatus, Session, SessionState
from sessionbus.schemas import SessionPublicState, SessionSummary, StoredSessionState

OFFLINE_TIMEOUT_SECONDS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _compute_public_state(session: Session) -> SessionPublicState:
    age = (_now() - _ensure_aware(session.last_seen_at)).total_seconds()
    if age > OFFLINE_TIMEOUT_SECONDS:
        return SessionPublicState.OFFLINE
    return SessionPublicState(session.state.value)


async def register_session(
    db: AsyncSession,
    *,
    display_name: str,
    tenant_id: str | None,
    metadata: dict | None,
) -> Session:
    session = Session(
        session_id=str(uuid4()),
        display_name=display_name,
        tenant_id=tenant_id,
        state=SessionState.WORKING,
        session_metadata=metadata,
        last_seen_at=_now(),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: str) -> Session | None:
    stmt = select(Session).where(Session.session_id == session_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def heartbeat(
    db: AsyncSession,
    *,
    session_id: str,
    state: StoredSessionState | None,
    metadata: dict | None,
) -> Session | None:
    session = await get_session(db, session_id)
    if session is None:
        return None

    session.last_seen_at = _now()
    if state is not None:
        session.state = SessionState(state.value)
    if metadata is not None:
        session.session_metadata = metadata

    await db.commit()
    await db.refresh(session)
    return session


async def set_state(db: AsyncSession, *, session_id: str, state: StoredSessionState) -> Session | None:
    session = await get_session(db, session_id)
    if session is None:
        return None

    session.state = SessionState(state.value)
    session.last_seen_at = _now()
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession) -> list[SessionSummary]:
    sessions_stmt = select(Session).order_by(Session.last_seen_at.desc(), Session.created_at.desc())
    sessions_result = await db.execute(sessions_stmt)
    sessions = sessions_result.scalars().all()

    pending_stmt = (
        select(InputRequest.session_id, func.count(InputRequest.id))
        .where(InputRequest.status == RequestStatus.PENDING)
        .group_by(InputRequest.session_id)
    )
    pending_result = await db.execute(pending_stmt)
    pending_counts = {row[0]: int(row[1]) for row in pending_result.all()}

    latest_response_acked: dict[str, bool] = {}
    if sessions:
        session_ids = [session.session_id for session in sessions]
        latest_response_stmt = (
            select(
                InboxMessage.session_id,
                InboxMessage.status,
                InboxMessage.created_at,
                InboxMessage.id,
            )
            .where(
                InboxMessage.session_id.in_(session_ids),
                InboxMessage.message_type == "INPUT_RESPONSE",
            )
            .order_by(
                InboxMessage.session_id.asc(),
                InboxMessage.created_at.desc(),
                InboxMessage.id.desc(),
            )
        )
        latest_response_result = await db.execute(latest_response_stmt)
        for session_id, status, _created_at, _id in latest_response_result.all():
            if session_id in latest_response_acked:
                continue
            latest_response_acked[session_id] = status == MessageStatus.ACKED

    return [
        SessionSummary(
            session_id=session.session_id,
            display_name=session.display_name,
            state=_compute_public_state(session),
            last_seen_at=session.last_seen_at,
            pending_request_count=pending_counts.get(session.session_id, 0),
            response_acknowledged=(
                pending_counts.get(session.session_id, 0) == 0
                and latest_response_acked.get(session.session_id, False)
            ),
            tenant_id=session.tenant_id,
            metadata=session.session_metadata,
        )
        for session in sessions
    ]
