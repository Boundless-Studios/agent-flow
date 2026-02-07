from __future__ import annotations

import argparse
import time

from sessionbus_client import SessionBusClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Example SessionBus agent loop")
    parser.add_argument("--base-url", default=None, help="SessionBus base URL (default: discover from ~/.sessionbus/runtime.json)")
    parser.add_argument("--display-name", default="Example Agent", help="Display name used for session registration")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with SessionBusClient(base_url=args.base_url) as client:
        session_id = client.register_session(
            display_name=args.display_name,
            metadata={"kind": "example", "script": "client/example_agent.py"},
        )
        print(f"Registered session: {session_id}")

        for step in range(1, 4):
            client.heartbeat(session_id, state="WORKING", metadata={"step": step, "phase": "pre-input"})
            print(f"Working step {step}/3")
            time.sleep(1)

        request_id = client.create_request(
            session_id,
            title="Need a human decision",
            question="Should I continue with strategy A or strategy B?",
            context_json={"options": ["A", "B"], "reason": "demo WAITING_FOR_INPUT flow"},
            priority="HIGH",
            tags=["demo", "human-input"],
        )
        print(f"Created input request: {request_id}")
        print("Open the SessionBus UI, answer this request, then return here.")

        waiting = True
        while waiting:
            client.heartbeat(session_id, state="WAITING_FOR_INPUT", metadata={"awaiting": request_id})
            messages = client.poll_inbox(session_id, timeout=30)
            if not messages:
                print("Still waiting for a response...")
                continue

            for message in messages:
                payload = message.get("payload", {})
                if message.get("type") != "INPUT_RESPONSE":
                    continue
                if payload.get("request_id") != request_id:
                    continue

                response_text = payload.get("response_text", "")
                print(f"Received human response: {response_text}")
                client.ack_message(session_id, message["message_id"])
                waiting = False

        client.set_state(session_id, "WORKING")
        print("Continuing work with human input...")
        time.sleep(1)
        client.set_state(session_id, "DONE")
        print("Session complete.")


if __name__ == "__main__":
    main()
