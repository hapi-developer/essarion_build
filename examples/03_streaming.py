"""Streaming: see the reasoning loop's phases land in real time.

Run with:
    OPENROUTER_API_KEY=... python examples/03_streaming.py
"""

from __future__ import annotations

from essarion_build import Context, stream_generate


def main() -> None:
    ctx = Context().with_skills(["python_idioms", "testing", "scope_discipline"])
    print("Generating … (events below)\n")

    for event in stream_generate(
        "write a small Python LRU cache class with type hints", context=ctx
    ):
        if event.kind == "phase_start":
            print(f"\n=== phase: {event.phase} ===")
        elif event.kind == "token":
            # OpenAI/OpenRouter providers send one big chunk per phase;
            # Anthropic providers send fine-grained deltas.
            print(event.text, end="", flush=True)
        elif event.kind == "phase_end":
            print(f"\n--- {event.phase} done ---")
        elif event.kind == "usage":
            print(f"# usage[{event.phase}]: {event.usage}")
        elif event.kind == "complete":
            print(f"\n# TOTAL usage: {event.usage}")


if __name__ == "__main__":
    main()
