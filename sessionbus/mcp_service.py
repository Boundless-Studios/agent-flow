from __future__ import annotations

import inspect
import json
import os
from typing import Any

import httpx

from sessionbus.hub import ensure_hub_running

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover - import error path depends on environment
    raise RuntimeError(
        "The `mcp` package is required for SessionBus MCP mode. Install with `pip install -e \".[mcp]\"`."
    ) from exc

mcp = FastMCP("SessionBus")
_BASE_URL: str | None = None


def _autostart_enabled() -> bool:
    value = os.getenv("SESSIONBUS_MCP_AUTOSTART", "1").strip().lower()
    return value not in {"0", "false", "no"}


def _get_base_url() -> str:
    global _BASE_URL
    if _BASE_URL:
        return _BASE_URL

    runtime = ensure_hub_running(autostart=_autostart_enabled())
    _BASE_URL = str(runtime["base_url"]).rstrip("/")
    return _BASE_URL


def _request(
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    base_url = _get_base_url()
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        response = client.request(method, path, json=json_payload, params=params, headers=headers)

    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


@mcp.tool()
def hub_status() -> dict[str, Any]:
    """Return SessionBus hub connection information for this MCP process."""
    base_url = _get_base_url()
    sessions = _request("GET", "/api/sessions")
    return {
        "base_url": base_url,
        "session_count": len(sessions),
    }


@mcp.tool()
def register_session(
    display_name: str,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register a new Cloud/agent session in SessionBus."""
    payload = {
        "display_name": display_name,
        "tenant_id": tenant_id,
        "metadata": metadata,
    }
    return _request("POST", "/api/sessions/register", json_payload=payload)


@mcp.tool()
def heartbeat_session(
    session_id: str,
    state: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send heartbeat and optional state/metadata update for a session."""
    payload = {
        "state": state,
        "metadata": metadata,
    }
    return _request("POST", f"/api/sessions/{session_id}/heartbeat", json_payload=payload)


@mcp.tool()
def set_session_state(session_id: str, state: str) -> dict[str, Any]:
    """Set stored state for a session (WORKING, WAITING_FOR_INPUT, DONE, ERROR)."""
    return _request("POST", f"/api/sessions/{session_id}/state", json_payload={"state": state})


@mcp.tool()
def list_sessions() -> list[dict[str, Any]]:
    """List sessions with computed state and pending request counts."""
    result = _request("GET", "/api/sessions")
    return list(result)


@mcp.tool()
def create_input_request(
    session_id: str,
    title: str,
    question: str,
    context_json: Any | None = None,
    priority: str = "NORMAL",
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create an input request for a session and move it to WAITING_FOR_INPUT."""
    payload = {
        "title": title,
        "question": question,
        "context_json": context_json,
        "priority": priority,
        "tags": tags,
    }
    headers = {"X-Idempotency-Key": idempotency_key} if idempotency_key else None
    return _request(
        "POST",
        f"/api/sessions/{session_id}/requests",
        json_payload=payload,
        headers=headers,
    )


@mcp.tool()
def list_requests(status: str = "PENDING") -> list[dict[str, Any]]:
    """List input requests by status (default PENDING)."""
    result = _request("GET", "/api/requests", params={"status": status})
    return list(result)


@mcp.tool()
def get_request(request_id: str) -> dict[str, Any]:
    """Get detailed request record by request_id."""
    return _request("GET", f"/api/requests/{request_id}")


@mcp.tool()
def respond_to_request(
    request_id: str,
    response_text: str,
    responder: str = "human",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Answer a pending request and enqueue INPUT_RESPONSE into the session inbox."""
    payload = {
        "response_text": response_text,
        "responder": responder,
    }
    headers = {"X-Idempotency-Key": idempotency_key} if idempotency_key else None
    return _request(
        "POST",
        f"/api/requests/{request_id}/respond",
        json_payload=payload,
        headers=headers,
    )


@mcp.tool()
def poll_inbox(session_id: str, timeout: int = 30) -> dict[str, Any]:
    """Long-poll session inbox and return unacked messages."""
    return _request("GET", f"/api/sessions/{session_id}/inbox", params={"timeout": timeout})


@mcp.tool()
def ack_inbox_message(session_id: str, message_id: str) -> dict[str, Any]:
    """ACK one inbox message so it no longer appears in poll results."""
    return _request("POST", f"/api/sessions/{session_id}/inbox/{message_id}/ack")


@mcp.resource("sessionbus://runtime")
def runtime_resource() -> str:
    """Expose hub runtime connection info as an MCP resource."""
    return json.dumps({"base_url": _get_base_url()}, indent=2)


def run() -> None:
    _get_base_url()
    run_method = getattr(mcp, "run")
    try:
        signature = inspect.signature(run_method)
    except Exception:
        signature = None

    if signature and "transport" in signature.parameters:
        run_method(transport="stdio")
    else:
        run_method()


def cli() -> None:
    run()


if __name__ == "__main__":
    cli()
