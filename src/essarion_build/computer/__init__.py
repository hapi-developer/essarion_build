"""Computer use for essarion — reactive, text-first, opt-in.

The principle: the environment observes and emits structured events; the model
acts on a compact *digest* only when something meaningful changes. The model is
never a continuous watcher. This package gives you, as importable building
blocks (the same way the reasoning loop is importable):

  * `ObservedEvent` / `reduce_events` / `Digest` — the event model and the
    reducer that turns a noisy firehose into a budget-sized digest (the heart).
  * `BufferedObserver` — the thread-safe sink backends push into.
  * `Backend`, `FakeBackend`, `PlaywrightBackend` — the action surface.
  * action tools (`browser_*`) + `bind_backend` + `register_computer_tools`.
  * `parse_expectation` / `check_expectation` — expectation-checked acting:
    declare a predicted post-condition in the same action call; the environment
    verifies it deterministically (deep reasoning, near-zero added latency).
  * `model_supports_vision` / `check_vision` — gate the screenshot tier.

Example (build your own reactive browser tool on top of the SDK):

    from essarion_build.computer import FakeBackend, bind_backend, browser_click
    bind_backend(FakeBackend(url="https://app.test"))
    print(browser_click(selector="#login", expect="navigates to /dashboard"))
"""

from __future__ import annotations

from . import tools as _tools  # noqa: F401  (registers nothing on import)
from ._actions import (
    COMPUTER_TOOLS,
    DESKTOP_TOOLS,
    bind_backend,
    bind_desktop,
    browser_click,
    browser_key,
    browser_navigate,
    browser_observe,
    browser_screenshot,
    browser_scroll,
    browser_snapshot,
    browser_type,
    current_backend,
    current_desktop,
    desktop_click,
    desktop_key,
    desktop_move,
    desktop_observe,
    desktop_screenshot,
    desktop_scroll,
    desktop_type,
)
from ._backend import Backend, FakeBackend, PlaywrightBackend
from ._desktop import DesktopBackend, FakeDesktopBackend
from ._events import ObservedEvent, severity_rank
from ._expectations import (
    Expectation,
    ExpectationResult,
    check_expectation,
    format_verdict,
    parse_expectation,
)
from ._observer import BufferedObserver
from ._reducer import Digest, reduce_events
from ._screen import ChangedRegion, ScreenDiffer
from ._vision import check_vision, model_supports_vision
from .tools import (
    COMPUTER_TOOL_NAMES,
    DESKTOP_TOOL_NAMES,
    register_computer_tools,
    register_desktop_tools,
)

__all__ = [
    "ObservedEvent",
    "severity_rank",
    "Digest",
    "reduce_events",
    "BufferedObserver",
    "Backend",
    "FakeBackend",
    "PlaywrightBackend",
    "bind_backend",
    "current_backend",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_key",
    "browser_scroll",
    "browser_observe",
    "browser_snapshot",
    "browser_screenshot",
    "COMPUTER_TOOLS",
    "COMPUTER_TOOL_NAMES",
    "register_computer_tools",
    # Desktop tier
    "DesktopBackend",
    "FakeDesktopBackend",
    "ScreenDiffer",
    "ChangedRegion",
    "bind_desktop",
    "current_desktop",
    "desktop_move",
    "desktop_click",
    "desktop_type",
    "desktop_key",
    "desktop_scroll",
    "desktop_observe",
    "desktop_screenshot",
    "DESKTOP_TOOLS",
    "DESKTOP_TOOL_NAMES",
    "register_desktop_tools",
    "Expectation",
    "ExpectationResult",
    "parse_expectation",
    "check_expectation",
    "format_verdict",
    "model_supports_vision",
    "check_vision",
]
