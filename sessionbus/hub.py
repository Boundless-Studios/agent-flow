from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import uvicorn

from sessionbus.api import create_app

RUNTIME_DIR = Path.home() / ".agentflow"
RUNTIME_FILE = RUNTIME_DIR / "runtime.json"
LEGACY_RUNTIME_FILE = Path.home() / ".sessionbus" / "runtime.json"


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=1.0):
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"Server did not become ready in {timeout_seconds:.1f}s: {url}")


def runtime_db_url() -> str:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    db_path = RUNTIME_DIR / "agentflow.db"
    return f"sqlite+aiosqlite:///{db_path}"


def write_runtime_info(port: int) -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "port": port,
        "base_url": f"http://127.0.0.1:{port}",
        "updated_at": int(time.time()),
    }
    RUNTIME_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def read_runtime_info() -> dict[str, Any] | None:
    for runtime_file in (RUNTIME_FILE, LEGACY_RUNTIME_FILE):
        if not runtime_file.exists():
            continue

        try:
            content = json.loads(runtime_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(content, dict):
            continue

        base_url = content.get("base_url")
        port = content.get("port")
        if isinstance(base_url, str) and isinstance(port, int):
            return content

    return None


def is_hub_reachable(base_url: str, timeout_seconds: float = 1.0) -> bool:
    try:
        req = Request(f"{base_url.rstrip('/')}/api/sessions", method="GET")
        with urlopen(req, timeout=timeout_seconds) as resp:
            return int(resp.status) == 200
    except URLError:
        return False
    except Exception:
        return False


def run_server_blocking(port: int) -> None:
    app = create_app(database_url=runtime_db_url())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def start_hub_in_background(*, port: int | None = None, timeout_seconds: float = 10.0) -> dict[str, Any]:
    chosen_port = port or pick_free_port()
    base_url = f"http://127.0.0.1:{chosen_port}"

    server_thread = threading.Thread(target=run_server_blocking, args=(chosen_port,), daemon=True)
    server_thread.start()
    wait_for_http(base_url, timeout_seconds=timeout_seconds)

    runtime = write_runtime_info(chosen_port)
    runtime["started_new"] = True
    return runtime


def ensure_hub_running(*, autostart: bool = True) -> dict[str, Any]:
    runtime = read_runtime_info()
    if runtime:
        base_url = str(runtime["base_url"])
        if is_hub_reachable(base_url):
            runtime["started_new"] = False
            return runtime

    if not autostart:
        raise RuntimeError(
            "AgentFlow hub is not running. Start it with `agent-flow` or `agentflow-hub` "
            "or allow MCP autostart."
        )

    return start_hub_in_background()


def run_hub_forever(port: int | None = None) -> None:
    chosen_port = port or pick_free_port()
    write_runtime_info(chosen_port)
    run_server_blocking(chosen_port)


def cli() -> None:
    run_hub_forever()
