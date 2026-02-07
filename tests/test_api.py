from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sessionbus.api import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "sessionbus-test.db"
    app = create_app(database_url=f"sqlite+aiosqlite:///{db_file}")
    with TestClient(app) as test_client:
        yield test_client


def test_request_response_inbox_flow(client: TestClient) -> None:
    register = client.post(
        "/api/sessions/register",
        json={"display_name": "Agent Alpha", "tenant_id": "tenant-a", "metadata": {"role": "worker"}},
    )
    assert register.status_code == 200
    session_id = register.json()["session_id"]

    create_request = client.post(
        f"/api/sessions/{session_id}/requests",
        json={
            "title": "Need input",
            "question": "Pick next action",
            "priority": "HIGH",
            "tags": ["test"],
        },
    )
    assert create_request.status_code == 200
    request_id = create_request.json()["request_id"]

    sessions = client.get("/api/sessions")
    assert sessions.status_code == 200
    [session] = [item for item in sessions.json() if item["session_id"] == session_id]
    assert session["state"] == "WAITING_FOR_INPUT"
    assert session["pending_request_count"] == 1

    respond = client.post(
        f"/api/requests/{request_id}/respond",
        json={"response_text": "Use action B", "responder": "human"},
    )
    assert respond.status_code == 200
    assert respond.json()["status"] == "ANSWERED"

    poll = client.get(f"/api/sessions/{session_id}/inbox", params={"timeout": 0})
    assert poll.status_code == 200
    messages = poll.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["type"] == "INPUT_RESPONSE"
    assert messages[0]["payload"]["request_id"] == request_id

    message_id = messages[0]["message_id"]
    ack = client.post(f"/api/sessions/{session_id}/inbox/{message_id}/ack")
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKED"

    poll_after_ack = client.get(f"/api/sessions/{session_id}/inbox", params={"timeout": 0})
    assert poll_after_ack.status_code == 200
    assert poll_after_ack.json()["messages"] == []


def test_idempotency_on_request_creation(client: TestClient) -> None:
    register = client.post("/api/sessions/register", json={"display_name": "Agent Beta"})
    session_id = register.json()["session_id"]

    headers = {"X-Idempotency-Key": "req-key-1"}
    first = client.post(
        f"/api/sessions/{session_id}/requests",
        headers=headers,
        json={"title": "Need approval", "question": "Continue?", "priority": "NORMAL"},
    )
    second = client.post(
        f"/api/sessions/{session_id}/requests",
        headers=headers,
        json={"title": "Need approval", "question": "Continue?", "priority": "NORMAL"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["request_id"] == second.json()["request_id"]
