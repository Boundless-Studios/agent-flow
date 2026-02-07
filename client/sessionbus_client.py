from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

RUNTIME_FILES = [
    Path.home() / ".agentflow" / "runtime.json",
    Path.home() / ".sessionbus" / "runtime.json",  # legacy fallback
]
DEFAULT_BASE_URL = "http://127.0.0.1:8765"


def discover_base_url() -> str:
    for runtime_file in RUNTIME_FILES:
        if not runtime_file.exists():
            continue

        try:
            content = json.loads(runtime_file.read_text(encoding="utf-8"))
            base_url = content.get("base_url")
            if isinstance(base_url, str) and base_url:
                return base_url.rstrip("/")
        except Exception:
            continue

    return DEFAULT_BASE_URL


class AgentFlowClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        resolved_base_url = (base_url or discover_base_url()).rstrip("/")
        self.base_url = resolved_base_url
        self._client = httpx.Client(base_url=resolved_base_url, timeout=timeout)

    def __enter__(self) -> AgentFlowClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def register_session(
        self,
        display_name: str,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "display_name": display_name,
            "tenant_id": tenant_id,
            "metadata": metadata,
        }
        response = self._client.post("/api/sessions/register", json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data["session_id"])

    def heartbeat(
        self,
        session_id: str,
        state: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {"state": state, "metadata": metadata}
        response = self._client.post(f"/api/sessions/{session_id}/heartbeat", json=payload)
        response.raise_for_status()
        return dict(response.json())

    def set_state(self, session_id: str, state: str) -> dict[str, Any]:
        response = self._client.post(f"/api/sessions/{session_id}/state", json={"state": state})
        response.raise_for_status()
        return dict(response.json())

    def list_sessions(self) -> list[dict[str, Any]]:
        response = self._client.get("/api/sessions")
        response.raise_for_status()
        return list(response.json())

    def create_request(
        self,
        session_id: str,
        *,
        title: str,
        question: str,
        context_json: Any | None = None,
        priority: str = "NORMAL",
        tags: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        headers = _idempotency_headers(idempotency_key)
        payload = {
            "title": title,
            "question": question,
            "context_json": context_json,
            "priority": priority,
            "tags": tags,
        }
        response = self._client.post(
            f"/api/sessions/{session_id}/requests",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["request_id"])

    def respond_to_request(
        self,
        request_id: str,
        *,
        response_text: str,
        responder: str = "human",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = _idempotency_headers(idempotency_key)
        payload = {
            "response_text": response_text,
            "responder": responder,
        }
        response = self._client.post(
            f"/api/requests/{request_id}/respond",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return dict(response.json())

    def poll_inbox(self, session_id: str, timeout: int = 30) -> list[dict[str, Any]]:
        response = self._client.get(f"/api/sessions/{session_id}/inbox", params={"timeout": timeout})
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("messages", []))

    def ack_message(self, session_id: str, message_id: str) -> dict[str, Any]:
        response = self._client.post(f"/api/sessions/{session_id}/inbox/{message_id}/ack")
        response.raise_for_status()
        return dict(response.json())


def _idempotency_headers(idempotency_key: str | None) -> dict[str, str]:
    if not idempotency_key:
        return {}
    return {"X-Idempotency-Key": idempotency_key}


# Backward-compatible alias.
SessionBusClient = AgentFlowClient
