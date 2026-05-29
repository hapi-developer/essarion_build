"""Telemetry: pipe SDK events into your observability stack.

Run with:
    OPENROUTER_API_KEY=... python examples/06_telemetry.py
"""

from __future__ import annotations

import json
import time

from essarion_build import Context, configure_telemetry, generate


def main() -> None:
    log = []

    def on_event(ev: dict) -> None:
        # In real code, send to your logger / OTLP exporter / etc.
        log.append(ev)

    configure_telemetry(on_event=on_event)

    g = generate(
        "write a Python function to validate an email address",
        context=Context().with_skills(["python_idioms", "secure_coding"]),
    )

    print("Event log:")
    for ev in log:
        print(" ", json.dumps({k: v for k, v in ev.items() if k != "ts"}))
    print(f"\nFinal code:\n{g.code}")


if __name__ == "__main__":
    main()
