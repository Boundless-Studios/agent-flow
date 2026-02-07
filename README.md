# AgentFlow — Local-first hub for coordinating agent sessions.

Local-first hub for coordinating AI agent sessions that need human input. Connect multiple agents (Claude Code, Codex, custom scripts) to a single dashboard where you can monitor sessions and respond to requests.

## Setup

```bash
git clone <repo-url> && cd agent-overflow
make setup    # Creates venv, installs all dependencies
make launch   # Starts the hub in background
```

Verify it's running:

```bash
make status
```

## Testing the Flow

Run the example agent to see the full human-in-the-loop cycle:

```bash
# Terminal 1: Start the hub (if not already running)
make launch

# Terminal 2: Run example agent
./.venv/bin/python client/example_agent.py
```

The agent will create a request and wait. Open the dashboard to respond:

```bash
make launch-ui
```

Submit a response in the UI, then watch Terminal 2 receive it and continue.

## Integrating with Agents

### Claude Code / Codex (via MCP)

Add to your MCP config (`~/.config/claude/mcp.json` or similar):

```json
{
  "mcpServers": {
    "agentflow": {
      "command": "/path/to/agent-overflow/.venv/bin/agentflow-mcp"
    }
  }
}
```

The MCP server auto-starts the hub if needed. Your agent can then use these tools:

| Tool | Description |
|------|-------------|
| `register_session` | Register a new agent session |
| `create_input_request` | Ask for human input (moves session to WAITING_FOR_INPUT) |
| `poll_inbox` | Check for responses |
| `ack_inbox_message` | Acknowledge received message |
| `heartbeat_session` | Update session state/metadata |
| `list_sessions` | View all sessions |
| `hub_status` | Check hub connection |

### Python Client

```python
from client.sessionbus_client import AgentFlowClient

with AgentFlowClient() as client:
    session_id = client.register_session("My Agent")

    # Do work...
    client.heartbeat(session_id, state="WORKING")

    # Need human input
    request_id = client.create_request(
        session_id,
        title="Approval needed",
        question="Proceed with deployment?",
        priority="URGENT",
    )

    # Wait for response
    while True:
        messages = client.poll_inbox(session_id, timeout=30)
        for msg in messages:
            if msg["type"] == "INPUT_RESPONSE":
                answer = msg["payload"]["response_text"]
                client.ack_message(session_id, msg["message_id"])
                break
```

The client auto-discovers the hub URL from `~/.agentflow/runtime.json` (falls back to legacy `~/.sessionbus/runtime.json`).

---

## MCP Server Reference

The MCP server (`agentflow-mcp`) provides Model Context Protocol access to AgentFlow.

### Running the MCP Server

```bash
# Auto-starts hub if not running
./.venv/bin/agentflow-mcp

# Require existing hub (no autostart)
SESSIONBUS_MCP_AUTOSTART=0 agentflow-mcp
```

### Available MCP Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `hub_status` | — | Hub connection info and session count |
| `register_session` | `display_name`, `tenant_id?`, `metadata?` | Register new session |
| `heartbeat_session` | `session_id`, `state?`, `metadata?` | Update session heartbeat |
| `set_session_state` | `session_id`, `state` | Set state (WORKING, WAITING_FOR_INPUT, DONE, ERROR) |
| `list_sessions` | — | List all sessions with state and request counts |
| `create_input_request` | `session_id`, `title`, `question`, `priority?`, `tags?` | Create human input request |
| `list_requests` | `status?` | List requests (default: PENDING) |
| `get_request` | `request_id` | Get request details |
| `respond_to_request` | `request_id`, `response_text`, `responder?` | Answer a request |
| `poll_inbox` | `session_id`, `timeout?` | Long-poll for messages |
| `ack_inbox_message` | `session_id`, `message_id` | Acknowledge message |

### MCP Resource

- `agentflow://runtime` — Hub connection info (base_url)

---

## Running Modes

### Desktop + MCP (Combined)

```bash
./.venv/bin/agentflow-launch
# or
make launch-all
```

Starts the hub, opens the desktop window, and runs MCP as a background sidecar for local notification/chat workflows.

### Desktop App (Hub + UI)

```bash
./.venv/bin/agent-flow
# or
make launch-ui
```

Starts the hub and opens a desktop window (requires `pywebview`).

### Headless Hub Only

```bash
./.venv/bin/agentflow-hub
# or
make launch
```

Runs the API server without UI. Access the web dashboard at the URL shown in `~/.agentflow/runtime.json`.

### MCP Service

```bash
./.venv/bin/agentflow-mcp
# or
make mcp
```

Runs the MCP server over stdio for agent integration.

---

## Commands Reference

```bash
# Setup
make setup          # Full install (all extras)
make setup-core     # Core runtime only
make setup-dev      # Core + pytest
make setup-desktop  # Add pywebview
make setup-mcp      # Add MCP support

# Operations
make launch         # Start headless hub (background)
make launch-ui      # Start desktop app
make launch-all     # Start desktop app + MCP sidecar
make mcp            # Run MCP server
make status         # Check hub status
make logs           # Tail hub logs
make shutdown       # Stop background hub
make test           # Run tests
make clean          # Remove runtime files
```

## Install Modes

```bash
pip install -e .            # Core only
pip install -e ".[dev]"     # + pytest
pip install -e ".[desktop]" # + pywebview
pip install -e ".[mcp]"     # + mcp
pip install -e ".[all]"     # Everything
```

---

## API Reference

All endpoints are served from the hub's base URL (default `127.0.0.1`, port in runtime.json).

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sessions/register` | Register new session |
| POST | `/api/sessions/{id}/heartbeat` | Send heartbeat |
| POST | `/api/sessions/{id}/state` | Set session state |
| GET | `/api/sessions` | List all sessions |

### Requests

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sessions/{id}/requests` | Create input request |
| GET | `/api/requests` | List requests (filter by `?status=`) |
| GET | `/api/requests/{id}` | Get request details |
| POST | `/api/requests/{id}/respond` | Submit response |

### Inbox

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions/{id}/inbox` | Poll inbox (`?timeout=30`) |
| POST | `/api/sessions/{id}/inbox/{msg_id}/ack` | Acknowledge message |

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events` | SSE stream for live updates |

**Idempotency:** Use `X-Idempotency-Key` header on request/response creation.

---

## Architecture

- **FastAPI** async backend
- **SQLite** persistence (SQLAlchemy 2.0 + aiosqlite)
- **Jinja2** server-rendered UI with minimal JS
- **SSE** live dashboard updates
- **pywebview** desktop wrapper (optional)
- **MCP** stdio transport for agent integration

## License

MIT. See `LICENSE`.
