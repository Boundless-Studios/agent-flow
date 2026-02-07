from __future__ import annotations

from sessionbus.hub import start_hub_in_background


def run() -> None:
    runtime = start_hub_in_background()
    base_url = str(runtime["base_url"])

    try:
        import webview
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pywebview is not installed. Install desktop extras with `pip install -e \".[desktop]\"`."
        ) from exc

    webview.create_window(
        title="Session I/O Bus",
        url=base_url,
        width=1180,
        height=820,
        text_select=True,
    )
    webview.start()


def cli() -> None:
    run()


if __name__ == "__main__":
    cli()
