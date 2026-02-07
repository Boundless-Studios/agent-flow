# Session I/O Bus

Local-first standalone hub for coordinating many AI agent sessions that may need human input.

- FastAPI async backend
- SQLite persistence via SQLAlchemy 2.0
- Server-rendered UI (Jinja2 + minimal JS)
- SSE live updates for dashboard refresh
- Desktop window wrapper via pywebview
- MCP service mode (stdio)
- Python client library + example agent loop

## Requirements

- Python 3.11+
- `make` (recommended)

## Quick Start (Recommended)

```bash
make setup
make launch
make status
```

Then open the desktop UI (optional):

```bash
make launch-ui
```

Run tests:

```bash
make test
```

Shutdown background hub:

```bash
make shutdown
```

## Install Modes

- Core only:

```bash
pip install -e .
```

- Development + tests:

```bash
pip install -e ".[dev]"
```

- Desktop UI support:

```bash
pip install -e ".[desktop]"
```

- MCP support:

```bash
pip install -e ".[mcp]"
```

- Everything:

```bash
pip install -e ".[all]"
```

## Makefile Targets

```bash
make help
make setup
make setup-core
make setup-dev
make setup-desktop
make setup-mcp
make setup-all
make readme
make test
make launch
make launch-ui
make mcp
make status
make logs
make shutdown
make clean
```

## Run (Desktop App)

```bash
agent-flow
```

This starts the hub server on `127.0.0.1` with a free local port, writes runtime metadata to `~/.sessionbus/runtime.json`, and opens a desktop window.

Equivalent command:

```bash
python -m sessionbus.main
```

## Run (Headless Hub Only)

```bash
sessionbus-hub
```

This runs only the local FastAPI hub on `127.0.0.1` (no desktop window).

## Run as MCP Service

```bash
sessionbus-mcp
```

Behavior:
- Starts/attaches to the local SessionBus hub automatically.
- Serves MCP over stdio.
- Exposes tools for session registration, heartbeat/state, request create/respond, and inbox poll/ack.

Disable hub autostart (require an already-running hub):

```bash
SESSIONBUS_MCP_AUTOSTART=0 sessionbus-mcp
```

### MCP Client Config Example (Claude Desktop-style)

```json
{
  "mcpServers": {
    "sessionbus": {
      "command": "sessionbus-mcp"
    }
  }
}
```

## Run the Example Agent

In a second terminal:

```bash
python client/example_agent.py
```

The script:
1. Registers a session
2. Performs work
3. Creates an input request (session becomes `WAITING_FOR_INPUT`)
4. Polls inbox until human response arrives
5. ACKs inbox message and continues to `DONE`

## API Highlights

- `POST /api/sessions/register`
- `POST /api/sessions/{session_id}/heartbeat`
- `POST /api/sessions/{session_id}/state`
- `GET /api/sessions`
- `POST /api/sessions/{session_id}/requests`
- `GET /api/requests?status=PENDING`
- `GET /api/requests/{request_id}`
- `POST /api/requests/{request_id}/respond`
- `GET /api/sessions/{session_id}/inbox?timeout=30`
- `POST /api/sessions/{session_id}/inbox/{message_id}/ack`
- `GET /api/events` (SSE)

Idempotency is supported on request/response creation via `X-Idempotency-Key`.

## Integrating Your Agents

Use `client/sessionbus_client.py` or call APIs directly.

```python
from client.sessionbus_client import SessionBusClient

client = SessionBusClient()  # auto-discovers base_url from ~/.sessionbus/runtime.json
session_id = client.register_session("Cloud Agent")

request_id = client.create_request(
    session_id,
    title="Need approval",
    question="Proceed with migration?",
    priority="URGENT",
)

while True:
    messages = client.poll_inbox(session_id, timeout=30)
    if not messages:
        client.heartbeat(session_id, state="WAITING_FOR_INPUT")
        continue

    for msg in messages:
        if msg["type"] == "INPUT_RESPONSE" and msg["payload"]["request_id"] == request_id:
            human_answer = msg["payload"]["response_text"]
            client.ack_message(session_id, msg["message_id"])
            # continue your agent loop using human_answer
            break
```

## Major Dependencies

Core runtime:
- `fastapi`: API + server-side routes
- `sqlalchemy` + `aiosqlite`: async persistence and data model
- `uvicorn`: ASGI server runtime
- `jinja2`: UI templates
- `httpx`: client integration
- `pydantic`: request/response validation

Optional:
- `pywebview` (`[desktop]`): desktop app window wrapper
- `mcp` (`[mcp]`): MCP server transport/tooling
- `pytest` (`[dev]`): tests

## License

MIT. See `LICENSE`.
