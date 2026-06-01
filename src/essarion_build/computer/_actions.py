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


def _observe(be, action_label: str, *, settle: float = 0.0, expect: str = "", min_severity: str = "info") -> str:
    """Settle, drain the observer (pumping any backend-side queue first), reduce
    to a digest, optionally check the expectation, and format the result. Shared
    by the browser and desktop tools — the whole act→observe→act spine."""
    if settle > 0:
        time.sleep(settle)
    pump = getattr(be, "pump", None)
    if callable(pump):
        pump()
    digest = reduce_events(be.observer().drain(), min_severity=min_severity)
    parts = [f"action: {action_label}", f"context: {be.url()}"]
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
    be = _require()
    be.navigate(url)
    return _observe(be, f"navigate → {url}", settle=_SETTLE_SECONDS, expect=expect)


def browser_click(selector: str = "", x: int | None = None, y: int | None = None, expect: str = "") -> str:
    """Click an element (CSS selector) or pixel coordinate, then report what changed."""
    be = _require()
    be.click(selector=selector or None, x=x, y=y)
    target = selector or f"({x},{y})"
    return _observe(be, f"click {target}", settle=_SETTLE_SECONDS, expect=expect)


def browser_type(text: str, selector: str = "", expect: str = "") -> str:
    """Type text (into `selector` if given, else the focused element)."""
    be = _require()
    be.type_text(text, selector=selector or None)
    return _observe(be, f"type {text!r}" + (f" into {selector}" if selector else ""), settle=_SETTLE_SECONDS, expect=expect)


def browser_key(key: str, expect: str = "") -> str:
    """Press a key or chord (e.g. 'Enter', 'Control+L')."""
    be = _require()
    be.press_key(key)
    return _observe(be, f"key {key}", settle=_SETTLE_SECONDS, expect=expect)


def browser_scroll(dy: int = 0, dx: int = 0, expect: str = "") -> str:
    """Scroll the page by (dx, dy) pixels."""
    be = _require()
    be.scroll(dy=dy, dx=dx)
    return _observe(be, f"scroll ({dx},{dy})", settle=_SETTLE_SECONDS, expect=expect)


def browser_observe() -> str:
    """Observe what changed WITHOUT acting — drains pending events into a digest.
    Use after triggering async work (a fetch, an animation) to see the result."""
    return _observe(_require(), "observe (no action)", settle=_SETTLE_SECONDS)


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


# ---------------------------------------------------------------------------
# Desktop tier — control the real machine's mouse/keyboard/screen.
# Bound separately from the browser so the two never collide, and so desktop
# control can carry its own (louder) safety settle and gating.
# ---------------------------------------------------------------------------

_DESKTOP = None
_DESKTOP_SETTLE: float = 0.0


def bind_desktop(backend, *, settle: float = 0.3, provider: str = "", model: str = "") -> None:
    """Bind the desktop backend for the desktop_* tools."""
    global _DESKTOP, _DESKTOP_SETTLE, _PROVIDER, _MODEL
    _DESKTOP = backend
    _DESKTOP_SETTLE = settle
    if provider:
        _PROVIDER = provider
    if model:
        _MODEL = model


def current_desktop():
    return _DESKTOP


def _require_desktop():
    if _DESKTOP is None:
        raise RuntimeError(
            "no desktop backend is bound. Enable desktop control with --desktop "
            "(it is off by default and controls the real machine)."
        )
    return _DESKTOP


def desktop_move(x: int, y: int, expect: str = "") -> str:
    """Move the mouse to absolute screen pixel (x, y)."""
    be = _require_desktop()
    be.move(x, y)
    return _observe(be, f"move → ({x},{y})", settle=_DESKTOP_SETTLE, expect=expect)


def desktop_click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1, expect: str = "") -> str:
    """Click at absolute screen pixel (x, y) — or the current pointer if omitted.
    `button` is left|middle|right; `clicks`=2 double-clicks."""
    be = _require_desktop()
    be.click(x=x, y=y, button=button, clicks=clicks)
    where = f"({x},{y})" if x is not None else "current pos"
    label = f"{'double-' if clicks >= 2 else ''}{button} click {where}"
    return _observe(be, label, settle=_DESKTOP_SETTLE, expect=expect)


def desktop_type(text: str, expect: str = "") -> str:
    """Type text into whatever currently has keyboard focus."""
    be = _require_desktop()
    be.type_text(text)
    return _observe(be, f"type {text!r}", settle=_DESKTOP_SETTLE, expect=expect)


def desktop_key(key: str, expect: str = "") -> str:
    """Press a key or chord, e.g. 'Return', 'ctrl+s', 'alt+Tab'."""
    be = _require_desktop()
    be.press_key(key)
    return _observe(be, f"key {key}", settle=_DESKTOP_SETTLE, expect=expect)


def desktop_scroll(amount: int = -3, expect: str = "") -> str:
    """Scroll the active window; positive = up, negative = down (in clicks)."""
    be = _require_desktop()
    be.scroll(amount)
    return _observe(be, f"scroll {amount}", settle=_DESKTOP_SETTLE, expect=expect)


def desktop_observe() -> str:
    """Observe what changed on screen WITHOUT acting (screen diff). Use after
    triggering async work to see the result."""
    return _observe(_require_desktop(), "observe (no action)", settle=_DESKTOP_SETTLE)


def desktop_screenshot() -> str:
    """Capture the screen. Requires a vision-capable model; otherwise returns a
    prompt to switch models rather than a blind call."""
    be = _require_desktop()
    ok, msg = check_vision(_PROVIDER, _MODEL)
    if not ok:
        return f"(screenshot skipped) {msg}"
    data = be.screenshot()
    w, h = be.screen_size()
    return (
        f"captured screen ({len(data)} bytes, {w}x{h}). "
        "[vision tier: attach to a multimodal message to inspect it]"
    )


DESKTOP_TOOLS: dict[str, tuple] = {
    "desktop_move": (desktop_move, "move the mouse to absolute screen pixel (x,y)"),
    "desktop_click": (desktop_click, "click at (x,y) on screen; button=left|middle|right, clicks=2 for double"),
    "desktop_type": (desktop_type, "type text into the focused window"),
    "desktop_key": (desktop_key, "press a key/chord, e.g. Return, ctrl+s, alt+Tab"),
    "desktop_scroll": (desktop_scroll, "scroll the active window (+up/-down)"),
    "desktop_observe": (desktop_observe, "observe screen changes without acting"),
    "desktop_screenshot": (desktop_screenshot, "screenshot the screen (needs a vision model)"),
}
