"""Optional structured telemetry for the reasoning loop.

Off by default. Wire a callback (or a dict of callbacks) via
`configure_telemetry(...)` to receive events as the loop runs. Suitable for:
- piping events into your observability stack (logs, traces, spans)
- per-team usage accounting
- debugging without sprinkling print statements through the SDK

Events are simple dicts; the SDK never imports any logging or telemetry
library by default so adding telemetry costs zero deps in user code.

Usage:

    from essarion_build import configure_telemetry, reason, Context

    def on_event(ev: dict) -> None:
        print(f"[{ev['kind']}] {ev}")

    configure_telemetry(on_event=on_event)
    reason("task", context=Context())
    # → emits {"kind": "loop_start", ...}, {"kind": "phase_complete", ...},
    #         {"kind": "loop_complete", ...}
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator


TelemetryCallback = Callable[[dict[str, Any]], None]


class _TelemetryConfig:
    """Module-level telemetry state. Read-only outside `configure_telemetry`."""

    def __init__(self) -> None:
        self.on_event: TelemetryCallback | None = None
        self.enabled: bool = False


_TELEMETRY = _TelemetryConfig()


_UNSET = object()


def configure_telemetry(
    *,
    on_event: TelemetryCallback | None | object = _UNSET,
    enabled: bool | None = None,
) -> None:
    """Set or clear the global telemetry callback.

    - Pass `on_event=cb` to install a callback and enable telemetry.
    - Pass `on_event=None` to clear the callback (also disables).
    - Pass `enabled=False` to disable without clearing (lets you toggle).
    - Pass `enabled=True` to re-enable a previously installed callback.

    Omitting both is a no-op.
    """
    if on_event is not _UNSET:
        _TELEMETRY.on_event = on_event  # type: ignore[assignment]
        if on_event is None:
            _TELEMETRY.enabled = False
        elif enabled is None:
            _TELEMETRY.enabled = True
    if enabled is not None:
        _TELEMETRY.enabled = enabled


def emit(kind: str, **fields: Any) -> None:
    """Emit a telemetry event if telemetry is configured.

    No-op when no callback is set or `enabled=False`. Exceptions raised by
    the user callback are swallowed so telemetry can never break the loop.
    """
    if not _TELEMETRY.enabled or _TELEMETRY.on_event is None:
        return
    payload = {"kind": kind, "ts": time.time(), **fields}
    try:
        _TELEMETRY.on_event(payload)
    except Exception:  # noqa: BLE001 - telemetry must never break the loop
        pass


@contextmanager
def span(kind: str, **fields: Any) -> Iterator[None]:
    """Emit `{kind}_start` and `{kind}_end` around a block.

    The end event includes `elapsed_seconds`.
    """
    emit(f"{kind}_start", **fields)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        emit(f"{kind}_end", elapsed_seconds=time.perf_counter() - t0, **fields)


__all__ = ["configure_telemetry", "emit", "span", "TelemetryCallback"]
