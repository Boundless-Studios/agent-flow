from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sessionbus.models import MessageStatus, RequestPriority, RequestStatus


class StoredSessionState(str, Enum):
    WORKING = "WORKING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    DONE = "DONE"
    ERROR = "ERROR"


class SessionPublicState(str, Enum):
    WORKING = "WORKING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    DONE = "DONE"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class SessionRegisterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    tenant_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class SessionRegisterResponse(BaseModel):
    session_id: str


class SessionHeartbeatRequest(BaseModel):
    state: StoredSessionState | None = None
    metadata: dict[str, Any] | None = None


class SessionStateUpdateRequest(BaseModel):
    state: StoredSessionState


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    display_name: str
    state: SessionPublicState
    last_seen_at: datetime
    pending_request_count: int
    response_acknowledged: bool = False
    tenant_id: str | None = None
    metadata: dict[str, Any] | None = None


class InputRequestCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1)
    context_json: Any | None = None
    priority: RequestPriority = RequestPriority.NORMAL
    tags: list[str] | None = None


class InputRequestCreateResponse(BaseModel):
    request_id: str


class InputRequestResponseRequest(BaseModel):
    response_text: str = Field(min_length=1)
    responder: str = Field(default="human", min_length=1, max_length=255)


class InputRequestResponseResponse(BaseModel):
    request_id: str
    status: RequestStatus


class InputRequestDismissResponse(BaseModel):
    request_id: str
    status: RequestStatus


class InputRequestView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    session_id: str
    title: str
    question: str
    context_json: Any | None
    priority: RequestPriority
    tags: list[str] | None
    status: RequestStatus
    response_text: str | None
    responder: str | None
    created_at: datetime
    answered_at: datetime | None


class InboxMessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    type: str
    payload: dict[str, Any]
    status: MessageStatus
    created_at: datetime
    delivered_at: datetime | None
    acked_at: datetime | None


class InboxPollResponse(BaseModel):
    messages: list[InboxMessageView]


class InboxAckResponse(BaseModel):
    message_id: str
    status: MessageStatus
