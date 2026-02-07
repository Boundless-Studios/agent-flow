from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from sessionbus import schemas
from sessionbus.db import configure_database, create_tables, get_session
from sessionbus.models import InboxMessage, InputRequest, RequestStatus
from sessionbus.services import inbox as inbox_service
from sessionbus.services import requests as requests_service
from sessionbus.services import sessions as sessions_service
from sessionbus.services.events import event_bus

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
SESSIONS_PARTIAL_TEMPLATE = TEMPLATES.env.from_string(
    """
<div class="card-header">
  <h2>Sessions</h2>
</div>
{% if sessions %}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Session ID</th>
          <th>State</th>
          <th>Last Seen</th>
          <th>Pending</th>
        </tr>
      </thead>
      <tbody>
        {% for session in sessions %}
          <tr>
            <td>{{ session.display_name }}</td>
            <td><code>{{ session.session_id }}</code></td>
            <td><span class="state state-{{ session.state.value|lower }}">{{ session.state.value }}</span></td>
            <td>{{ session.last_seen_at.strftime('%Y-%m-%d %H:%M:%S %Z') }}</td>
            <td>{{ session.pending_request_count }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% else %}
  <p class="empty">No sessions registered yet.</p>
{% endif %}
"""
)
REQUESTS_PARTIAL_TEMPLATE = TEMPLATES.env.from_string(
    """
<div class="card-header">
  <h2>Pending Input Requests</h2>
</div>
{% if pending_requests %}
  <ul class="request-list">
    {% for request_obj in pending_requests %}
      <li>
        <a href="/requests/{{ request_obj.request_id }}">
          <span class="title">{{ request_obj.title }}</span>
          <span class="meta">
            <span class="priority priority-{{ request_obj.priority.value|lower }}">{{ request_obj.priority.value }}</span>
            <span><code>{{ request_obj.session_id }}</code></span>
          </span>
          <span class="question">{{ request_obj.question }}</span>
        </a>
      </li>
    {% endfor %}
  </ul>
{% else %}
  <p class="empty">No pending requests.</p>
{% endif %}
"""
)


def _request_to_view(request_obj: InputRequest) -> schemas.InputRequestView:
    return schemas.InputRequestView(
        request_id=request_obj.request_id,
        session_id=request_obj.session_id,
        title=request_obj.title,
        question=request_obj.question,
        context_json=request_obj.context_json,
        priority=request_obj.priority,
        tags=request_obj.tags_json,
        status=request_obj.status,
        response_text=request_obj.response_text,
        responder=request_obj.responder,
        created_at=request_obj.created_at,
        answered_at=request_obj.answered_at,
    )


def _message_to_view(message: InboxMessage) -> schemas.InboxMessageView:
    return schemas.InboxMessageView(
        message_id=message.message_id,
        type=message.message_type,
        payload=message.payload_json,
        status=message.status,
        created_at=message.created_at,
        delivered_at=message.delivered_at,
        acked_at=message.acked_at,
    )


def _render_sessions_partial(sessions: list[schemas.SessionSummary]) -> str:
    return SESSIONS_PARTIAL_TEMPLATE.render(sessions=sessions)


def _render_requests_partial(pending_requests: list[schemas.InputRequestView]) -> str:
    return REQUESTS_PARTIAL_TEMPLATE.render(pending_requests=pending_requests)


async def _get_session_summary_or_404(db: AsyncSession, session_id: str) -> schemas.SessionSummary:
    sessions = await sessions_service.list_sessions(db)
    for item in sessions:
        if item.session_id == session_id:
            return item
    raise HTTPException(status_code=404, detail="Session not found")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_tables()
    yield


def create_app(database_url: str | None = None) -> FastAPI:
    configure_database(database_url)

    app = FastAPI(title="Session I/O Bus", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    api_router = APIRouter(prefix="/api")
    ui_router = APIRouter()

    @api_router.post("/sessions/register", response_model=schemas.SessionRegisterResponse)
    async def register_session(
        payload: schemas.SessionRegisterRequest,
        db: AsyncSession = Depends(get_session),
    ) -> schemas.SessionRegisterResponse:
        session = await sessions_service.register_session(
            db,
            display_name=payload.display_name,
            tenant_id=payload.tenant_id,
            metadata=payload.metadata,
        )
        return schemas.SessionRegisterResponse(session_id=session.session_id)

    @api_router.post("/sessions/{session_id}/heartbeat", response_model=schemas.SessionSummary)
    async def heartbeat_session(
        session_id: str,
        payload: schemas.SessionHeartbeatRequest,
        db: AsyncSession = Depends(get_session),
    ) -> schemas.SessionSummary:
        session = await sessions_service.heartbeat(
            db,
            session_id=session_id,
            state=payload.state,
            metadata=payload.metadata,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return await _get_session_summary_or_404(db, session.session_id)

    @api_router.post("/sessions/{session_id}/state", response_model=schemas.SessionSummary)
    async def update_session_state(
        session_id: str,
        payload: schemas.SessionStateUpdateRequest,
        db: AsyncSession = Depends(get_session),
    ) -> schemas.SessionSummary:
        session = await sessions_service.set_state(db, session_id=session_id, state=payload.state)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return await _get_session_summary_or_404(db, session.session_id)

    @api_router.get("/sessions", response_model=list[schemas.SessionSummary])
    async def list_sessions(
        db: AsyncSession = Depends(get_session),
    ) -> list[schemas.SessionSummary]:
        return await sessions_service.list_sessions(db)

    @api_router.post("/sessions/{session_id}/requests", response_model=schemas.InputRequestCreateResponse)
    async def create_input_request(
        session_id: str,
        payload: schemas.InputRequestCreateRequest,
        db: AsyncSession = Depends(get_session),
        x_idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
    ) -> schemas.InputRequestCreateResponse:
        request_obj, _ = await requests_service.create_request(
            db,
            session_id=session_id,
            payload=payload,
            idempotency_key=x_idempotency_key,
        )
        if request_obj is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return schemas.InputRequestCreateResponse(request_id=request_obj.request_id)

    @api_router.get("/requests", response_model=list[schemas.InputRequestView])
    async def list_input_requests(
        status: RequestStatus | None = Query(default=None),
        db: AsyncSession = Depends(get_session),
    ) -> list[schemas.InputRequestView]:
        request_items = await requests_service.list_requests(db, status=status)
        return [_request_to_view(item) for item in request_items]

    @api_router.get("/requests/{request_id}", response_model=schemas.InputRequestView)
    async def get_input_request(
        request_id: str,
        db: AsyncSession = Depends(get_session),
    ) -> schemas.InputRequestView:
        request_obj = await requests_service.get_request(db, request_id)
        if request_obj is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return _request_to_view(request_obj)

    @api_router.post("/requests/{request_id}/respond", response_model=schemas.InputRequestResponseResponse)
    async def respond_to_request(
        request_id: str,
        payload: schemas.InputRequestResponseRequest,
        db: AsyncSession = Depends(get_session),
        x_idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
    ) -> schemas.InputRequestResponseResponse:
        request_obj, _ = await requests_service.respond_to_request(
            db,
            request_id=request_id,
            payload=payload,
            idempotency_key=x_idempotency_key,
        )
        if request_obj is None:
            raise HTTPException(status_code=404, detail="Request not found")

        return schemas.InputRequestResponseResponse(
            request_id=request_obj.request_id,
            status=request_obj.status,
        )

    @api_router.get("/sessions/{session_id}/inbox", response_model=schemas.InboxPollResponse)
    async def poll_inbox(
        session_id: str,
        timeout: int = Query(default=30, ge=0, le=120),
        db: AsyncSession = Depends(get_session),
    ) -> schemas.InboxPollResponse:
        messages, exists = await inbox_service.poll_messages(db, session_id=session_id, timeout=timeout)
        if not exists:
            raise HTTPException(status_code=404, detail="Session not found")
        assert messages is not None
        return schemas.InboxPollResponse(messages=[_message_to_view(message) for message in messages])

    @api_router.post("/sessions/{session_id}/inbox/{message_id}/ack", response_model=schemas.InboxAckResponse)
    async def ack_inbox_message(
        session_id: str,
        message_id: str,
        db: AsyncSession = Depends(get_session),
    ) -> schemas.InboxAckResponse:
        message, found = await inbox_service.ack_message(
            db,
            session_id=session_id,
            message_id=message_id,
        )
        if not found or message is None:
            raise HTTPException(status_code=404, detail="Message not found")

        return schemas.InboxAckResponse(message_id=message.message_id, status=message.status)

    @api_router.get("/events")
    async def sse_events(request: Request) -> StreamingResponse:
        async def event_stream():
            async with event_bus.subscribe() as queue:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield "event: ping\ndata: {}\n\n"

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

    @ui_router.get("/", response_class=HTMLResponse)
    async def home_page(request: Request, db: AsyncSession = Depends(get_session)) -> HTMLResponse:
        sessions = await sessions_service.list_sessions(db)
        pending_requests = await requests_service.list_requests(db, status=RequestStatus.PENDING)
        return TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "sessions": sessions,
                "pending_requests": [_request_to_view(item) for item in pending_requests],
            },
        )

    @ui_router.get("/partials/sessions", response_class=HTMLResponse)
    async def sessions_partial(db: AsyncSession = Depends(get_session)) -> HTMLResponse:
        sessions = await sessions_service.list_sessions(db)
        return HTMLResponse(_render_sessions_partial(sessions))

    @ui_router.get("/partials/requests", response_class=HTMLResponse)
    async def requests_partial(db: AsyncSession = Depends(get_session)) -> HTMLResponse:
        pending_requests = await requests_service.list_requests(db, status=RequestStatus.PENDING)
        request_views = [_request_to_view(item) for item in pending_requests]
        return HTMLResponse(_render_requests_partial(request_views))

    @ui_router.get("/requests/{request_id}", response_class=HTMLResponse)
    async def request_detail(
        request: Request,
        request_id: str,
        db: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        request_obj = await requests_service.get_request(db, request_id)
        if request_obj is None:
            raise HTTPException(status_code=404, detail="Request not found")

        return TEMPLATES.TemplateResponse(
            "request.html",
            {
                "request": request,
                "request_obj": _request_to_view(request_obj),
            },
        )

    @ui_router.post("/requests/{request_id}/respond", response_class=HTMLResponse)
    async def request_detail_respond(
        request_id: str,
        response_text: str = Form(...),
        responder: str = Form("human"),
        db: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        payload = schemas.InputRequestResponseRequest(response_text=response_text, responder=responder)
        request_obj, _ = await requests_service.respond_to_request(
            db,
            request_id=request_id,
            payload=payload,
            idempotency_key=None,
        )
        if request_obj is None:
            raise HTTPException(status_code=404, detail="Request not found")

        return RedirectResponse(url=f"/requests/{request_id}", status_code=303)

    app.include_router(api_router)
    app.include_router(ui_router)
    return app


app = create_app()
