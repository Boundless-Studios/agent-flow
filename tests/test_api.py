from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sessionbus.api import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENTFLOW_DESKTOP_NOTIFICATIONS", "0")
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
    assert session["response_acknowledged"] is False

    respond = client.post(
        f"/api/requests/{request_id}/respond",
        json={"response_text": "Use action B", "responder": "human"},
    )
    assert respond.status_code == 200
    assert respond.json()["status"] == "ANSWERED"

    sessions_after_response = client.get("/api/sessions")
    assert sessions_after_response.status_code == 200
    [session_after_response] = [
        item for item in sessions_after_response.json() if item["session_id"] == session_id
    ]
    assert session_after_response["state"] == "WORKING"
    assert session_after_response["pending_request_count"] == 0
    assert session_after_response["response_acknowledged"] is False

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

    sessions_after_ack = client.get("/api/sessions")
    assert sessions_after_ack.status_code == 200
    [session_after_ack] = [item for item in sessions_after_ack.json() if item["session_id"] == session_id]
    assert session_after_ack["response_acknowledged"] is True

    poll_after_ack = client.get(f"/api/sessions/{session_id}/inbox", params={"timeout": 0})
    assert poll_after_ack.status_code == 200
    assert poll_after_ack.json()["messages"] == []

    create_second_request = client.post(
        f"/api/sessions/{session_id}/requests",
        json={"title": "Need input again", "question": "Choose next step"},
    )
    assert create_second_request.status_code == 200

    sessions_after_second_request = client.get("/api/sessions")
    assert sessions_after_second_request.status_code == 200
    [session_after_second_request] = [
        item for item in sessions_after_second_request.json() if item["session_id"] == session_id
    ]
    assert session_after_second_request["state"] == "WAITING_FOR_INPUT"
    assert session_after_second_request["pending_request_count"] == 1
    assert session_after_second_request["response_acknowledged"] is False


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


def test_dismiss_request_flow(client: TestClient) -> None:
    register = client.post("/api/sessions/register", json={"display_name": "Agent Dismiss"})
    session_id = register.json()["session_id"]

    first_request = client.post(
        f"/api/sessions/{session_id}/requests",
        json={"title": "Old prompt", "question": "Already handled externally"},
    )
    second_request = client.post(
        f"/api/sessions/{session_id}/requests",
        json={"title": "Active prompt", "question": "Still pending"},
    )
    first_request_id = first_request.json()["request_id"]
    second_request_id = second_request.json()["request_id"]

    dismiss_first = client.post(f"/api/requests/{first_request_id}/dismiss")
    assert dismiss_first.status_code == 200
    assert dismiss_first.json()["status"] == "DISMISSED"

    sessions_after_first_dismiss = client.get("/api/sessions")
    [session_after_first_dismiss] = [
        item for item in sessions_after_first_dismiss.json() if item["session_id"] == session_id
    ]
    assert session_after_first_dismiss["state"] == "WAITING_FOR_INPUT"
    assert session_after_first_dismiss["pending_request_count"] == 1

    pending_requests = client.get("/api/requests", params={"status": "PENDING"}).json()
    pending_request_ids = {item["request_id"] for item in pending_requests}
    assert first_request_id not in pending_request_ids
    assert second_request_id in pending_request_ids

    dismiss_second = client.post(f"/api/requests/{second_request_id}/dismiss")
    assert dismiss_second.status_code == 200
    assert dismiss_second.json()["status"] == "DISMISSED"

    sessions_after_second_dismiss = client.get("/api/sessions")
    [session_after_second_dismiss] = [
        item for item in sessions_after_second_dismiss.json() if item["session_id"] == session_id
    ]
    assert session_after_second_dismiss["state"] == "WORKING"
    assert session_after_second_dismiss["pending_request_count"] == 0

    first_request_view = client.get(f"/api/requests/{first_request_id}")
    assert first_request_view.status_code == 200
    assert first_request_view.json()["status"] == "DISMISSED"


def test_requests_partial_preserves_multiline_format_and_context(client: TestClient) -> None:
    register = client.post("/api/sessions/register", json={"display_name": "Agent Gamma"})
    session_id = register.json()["session_id"]

    create_request = client.post(
        f"/api/sessions/{session_id}/requests",
        json={
            "title": "Formatted request",
            "question": "Line one\n\n- item A\n- item B",
            "context_json": {"source": "agent", "steps": ["one", "two"]},
        },
    )
    assert create_request.status_code == 200

    partial = client.get("/partials/requests")
    assert partial.status_code == 200
    body = partial.text
    assert "class=\"question\"" in body
    assert "Line one" in body
    assert "item A" in body
    assert "request-context" in body
    assert "Context" in body
    assert "inline-dismiss-button" in body
