from __future__ import annotations

import os
import platform
import shutil
import subprocess

_DISABLED_VALUES = {"0", "false", "no", "off"}


def _notifications_enabled() -> bool:
    value = os.getenv("AGENTFLOW_DESKTOP_NOTIFICATIONS", "1").strip().lower()
    return value not in _DISABLED_VALUES


def _compact_text(value: str) -> str:
    return " ".join(value.strip().split())


def _truncate_text(value: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value
    if max_length <= 3:
        return value[:max_length]
    return f"{value[: max_length - 3]}..."


def _apple_script_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _notify_macos(*, title: str, subtitle: str, body: str) -> None:
    script = (
        f'display notification "{_apple_script_quote(body)}" '
        f'with title "{_apple_script_quote(title)}" '
        f'subtitle "{_apple_script_quote(subtitle)}"'
    )
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _notify_linux(*, title: str, body: str) -> None:
    if shutil.which("notify-send") is None:
        return
    subprocess.Popen(
        ["notify-send", title, body],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def notify_pending_input_request(
    *,
    request_id: str,
    session_id: str,
    title: str,
    question: str,
    priority: str,
) -> None:
    if not _notifications_enabled():
        return

    normalized_title = _truncate_text(_compact_text(title) or "Input Request", 80)
    normalized_question = _truncate_text(_compact_text(question), 220)
    subtitle = _truncate_text(f"{priority} | {session_id}", 120)
    short_request_id = _truncate_text(request_id, 40)
    body = normalized_question or "A request is waiting for your response."
    notification_body = f"{subtitle}\n{body}\nRequest: {short_request_id}"
    os_name = platform.system()

    try:
        if os_name == "Darwin":
            _notify_macos(title="AgentFlow", subtitle=normalized_title, body=notification_body)
        elif os_name == "Linux":
            _notify_linux(title=f"AgentFlow: {normalized_title}", body=notification_body)
    except Exception:
        # Notifications are best-effort and must never break request creation flow.
        return
