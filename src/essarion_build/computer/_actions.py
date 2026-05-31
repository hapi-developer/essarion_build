"""Computer-use action tools.

Each action embodies the reactive principle: it performs the input, lets the
environment settle, drains the observer, reduces the events to a digest, and
returns that digest as the tool result. So the existing `<tool_call>` loop
becomes act→observe→act with no new protocol — the model acts, reads a compact
digest of what changed, and acts again. It is never a continuous watcher.

Every action also takes an optional ``expect`` — a one-line predicted
post-condition. It's checked against the digest deterministically (no extra
model call) and a ✓/✗ verdict is prepended. That's the "reason deep, act fast"
mechanism: the model commits to a consequence in the same ~dozen tokens it uses
to act, and only gets pulled back in to reason when reality diverges.
"""

from __future__ import annotations

import time
from typing import Optional

from ._backend import Backend
from ._expectations import check_expectation, format_verdict, parse_expectation
from ._reducer import reduce_events
from ._vision import check_vision

# Bound per session, like agent._tools binds the sandbox cwd.
_BACKEND: Optional[Backend] = None
_SETTLE_SECONDS: float = 0.0
_PROVIDER: str = ""
_MODEL: str = ""


def bind_backend(backend: Optional[Backend], *, settle: float = 0.4, provider: str = "", model: str = "") -> None:
    """Bind the active backend for the action tools. `settle` is how long to
    wait for events to arrive after an action (0 for the synchronous FakeBackend
    in tests; ~0.4s for a real browser)."""
    global _BACKEND, _SETTLE_SECONDS, _PROVIDER, _MODEL
    _BACKEND = backend
    _SETTLE_SECONDS = settle
    _PROVIDER, _MODEL = provider, model


def current_backend() -> Optional[Backend]:
    return _BACKEND


def _require() -> Backend:
    if _BACKEND is None:
        raise RuntimeError(
            "no computer-use backend is bound. Start one with --computer-use "
            "(or ask the agent to 'use the computer')."
        )
    return _BACKEND


def _observe(action_label: str, *, expect: str = "", min_severity: str = "info") -> str:
    be = _require()
    if _SETTLE_SECONDS > 0:
        time.sleep(_SETTLE_SECONDS)
    # Pull page-side queued events (DOM mutations) into the observer first.
    pump = getattr(be, "pump", None)
    if callable(pump):
        pump()
    digest = reduce_events(be.observer().drain(), min_severity=min_severity)
    parts = [f"action: {action_label}", f"url: {be.url()}"]
    if expect.strip():
        text_fn = getattr(be, "text_content", None)
        page_text = text_fn() if callable(text_fn) else ""
        res = check_expectation(parse_expectation(expect), digest, url=be.url(), page_text=page_text)
        parts.append(format_verdict(res))
    parts.append("observed:")
    parts.append(digest.text)
    return "\n".join(parts)


def browser_navigate(url: str, expect: str = "") -> str:
    """Navigate the browser to a URL, then report what changed."""
    _require().navigate(url)
    return _observe(f"navigate → {url}", expect=expect)


def browser_click(selector: str = "", x: int | None = None, y: int | None = None, expect: str = "") -> str:
    """Click an element (CSS selector) or pixel coordinate, then report what changed."""
    _require().click(selector=selector or None, x=x, y=y)
    target = selector or f"({x},{y})"
    return _observe(f"click {target}", expect=expect)


def browser_type(text: str, selector: str = "", expect: str = "") -> str:
    """Type text (into `selector` if given, else the focused element)."""
    _require().type_text(text, selector=selector or None)
    return _observe(f"type {text!r}" + (f" into {selector}" if selector else ""), expect=expect)


def browser_key(key: str, expect: str = "") -> str:
    """Press a key or chord (e.g. 'Enter', 'Control+L')."""
    _require().press_key(key)
    return _observe(f"key {key}", expect=expect)


def browser_scroll(dy: int = 0, dx: int = 0, expect: str = "") -> str:
    """Scroll the page by (dx, dy) pixels."""
    _require().scroll(dy=dy, dx=dx)
    return _observe(f"scroll ({dx},{dy})", expect=expect)


def browser_observe() -> str:
    """Observe what changed WITHOUT acting — drains pending events into a digest.
    Use after triggering async work (a fetch, an animation) to see the result."""
    return _observe("observe (no action)", min_severity="info")


def browser_snapshot(max_chars: int = 2000) -> str:
    """A compact, vision-free text outline of the current page (accessibility
    tree). Use this to find elements to interact with."""
    be = _require()
    return f"url: {be.url()}\nsnapshot:\n{be.snapshot(max_chars=max_chars)}"


def browser_screenshot() -> str:
    """Capture a screenshot. Requires a vision-capable model; if the current
    model can't see images, returns a prompt to switch instead of a blind call."""
    be = _require()
    ok, msg = check_vision(_PROVIDER, _MODEL)
    if not ok:
        return f"(screenshot skipped) {msg}"
    data = be.screenshot()
    return (
        f"captured screenshot ({len(data)} bytes) at {be.url()}. "
        "[vision tier: attach to a multimodal message to inspect it]"
    )


# Tool name → (callable, description) for registration / allow-listing.
COMPUTER_TOOLS: dict[str, tuple] = {
    "browser_navigate": (browser_navigate, "navigate the browser to a URL; reports what changed"),
    "browser_click": (browser_click, "click a CSS selector or x/y; reports what changed"),
    "browser_type": (browser_type, "type text into a selector or the focused field"),
    "browser_key": (browser_key, "press a key or chord like Enter or Control+L"),
    "browser_scroll": (browser_scroll, "scroll the page by dx/dy pixels"),
    "browser_observe": (browser_observe, "observe what changed without acting"),
    "browser_snapshot": (browser_snapshot, "vision-free accessibility-tree outline of the page"),
    "browser_screenshot": (browser_screenshot, "screenshot (needs a vision-capable model)"),
}
