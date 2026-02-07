from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from sessionbus.hub import ensure_hub_running

RUNTIME_DIR = Path.home() / ".agentflow"
MCP_PID_FILE = RUNTIME_DIR / "mcp.pid"
MCP_LOG_FILE = RUNTIME_DIR / "mcp.log"


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _start_mcp_background() -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    existing_pid = _read_pid(MCP_PID_FILE)
    if existing_pid and _pid_is_running(existing_pid):
        return {"pid": existing_pid, "already_running": True}

    log_handle = MCP_LOG_FILE.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "sessionbus.mcp_service"],
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    MCP_PID_FILE.write_text(str(process.pid), encoding="utf-8")
    return {"pid": process.pid, "already_running": False}


def _cleanup_mcp() -> None:
    pid = _read_pid(MCP_PID_FILE)
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    try:
        MCP_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def run() -> None:
    runtime = ensure_hub_running(autostart=True)
    base_url = str(runtime["base_url"])

    mcp_info = _start_mcp_background()
    _ = mcp_info

    try:
        import webview
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pywebview is not installed. Install desktop extras with `pip install -e \".[desktop]\"`."
        ) from exc

    try:
        webview.create_window(
            title="AgentFlow",
            url=base_url,
            width=1180,
            height=820,
            text_select=True,
        )
        webview.start()
    finally:
        _cleanup_mcp()


def cli() -> None:
    run()


if __name__ == "__main__":
    cli()
