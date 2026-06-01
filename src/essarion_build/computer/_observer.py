"""Observer — the buffered event sink every backend pushes into.

A backend's native event taps (CDP listeners, accessibility callbacks, a
screen-diff poller) run on their own threads and `push()` normalized
ObservedEvents here. The agent loop `drain()`s the buffer after each action and
hands it to the reducer. The observer itself is dumb and thread-safe by design;
all the intelligence lives in the reducer.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from ._events import ObservedEvent


class BufferedObserver:
    """Thread-safe FIFO buffer of ObservedEvents."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, cap: int = 5000) -> None:
        self._buf: list[ObservedEvent] = []
        self._lock = threading.Lock()
        self._clock = clock
        self._cap = cap

    def push(self, ev: ObservedEvent) -> None:
        if ev.ts == 0.0:
            ev.ts = self._clock()
        with self._lock:
            self._buf.append(ev)
            if len(self._buf) > self._cap:
                # Keep the most recent; old noise is the first to go.
                del self._buf[: len(self._buf) - self._cap]

    def push_event(
        self, kind: str, summary: str, *, severity: str = "info", source: str = "browser", **detail
    ) -> None:
        self.push(ObservedEvent(kind=kind, summary=summary, severity=severity, source=source, detail=detail))

    def drain(self) -> list[ObservedEvent]:
        """Return and clear all buffered events."""
        with self._lock:
            evs = self._buf
            self._buf = []
        return evs

    def pending(self) -> int:
        with self._lock:
            return len(self._buf)
