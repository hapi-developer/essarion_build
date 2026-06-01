"""Desktop tier: the action tools over a FakeDesktopBackend, the gating/safety
policy, and (when a display + Xlib are available) a REAL X11 smoke test that
moves the pointer, captures the screen, and detects a drawn change via diff."""

from __future__ import annotations

import os

import pytest

from essarion_build import tools as sdk_tools
from essarion_build.agent import _computer
from essarion_build.computer import (
    DESKTOP_TOOL_NAMES,
    FakeDesktopBackend,
    bind_desktop,
    desktop_click,
    desktop_move,
    desktop_screenshot,
    desktop_type,
    register_desktop_tools,
)
from essarion_build.computer.tools import unregister_desktop_tools


# ---- gating / safety: desktop is explicit-opt-in only ----

def test_desktop_never_self_activates_from_phrasing() -> None:
    class S:
        desktop_control = False
    s = S()
    # Even very explicit phrasing must NOT auto-enable the real machine.
    assert _computer.desktop_active(s) is False
    assert _computer.suggests_desktop("control my mouse and keyboard") is True
    s.desktop_control = True
    assert _computer.desktop_active(s) is True


def test_no_backend_bound_is_a_clear_error() -> None:
    bind_desktop(None)
    with pytest.raises(RuntimeError) as e:
        desktop_move(10, 10)
    assert "--desktop" in str(e.value)


def test_input_driver_dispatch_by_platform(monkeypatch) -> None:
    """The right OS input driver is selected per platform (drivers stubbed so no
    real display/Quartz/SendInput is touched)."""
    from essarion_build.computer import _desktop

    monkeypatch.setattr(_desktop, "X11Input", lambda display=None: ("x11", display))
    monkeypatch.setattr(_desktop, "QuartzInput", lambda: ("quartz",))
    monkeypatch.setattr(_desktop, "WindowsInput", lambda: ("win",))
    monkeypatch.setattr(_desktop.sys, "platform", "darwin")
    assert _desktop.make_input_driver()[0] == "quartz"
    monkeypatch.setattr(_desktop.sys, "platform", "win32")
    assert _desktop.make_input_driver()[0] == "win"
    monkeypatch.setattr(_desktop.sys, "platform", "linux")
    assert _desktop.make_input_driver()[0] == "x11"


# ---- action tools over the fake backend ----

def _paint_app(be: FakeDesktopBackend, name: str, kw: dict) -> None:
    obs = be.observer()
    if name == "click" and kw.get("x") == 400:
        obs.push_event("screen", "screen changed: cols 6-9, rows 4-6 (~8% area)",
                       severity="notice", source="desktop")
        be.text = "Settings saved"
    elif name == "type_text":
        obs.push_event("screen", "screen changed: text field updated", severity="info", source="desktop")


@pytest.fixture
def fake():
    be = FakeDesktopBackend(width=1280, height=800, on_action=_paint_app)
    bind_desktop(be, settle=0.0, provider="anthropic", model="claude-haiku-4-5")
    register_desktop_tools()
    yield be
    unregister_desktop_tools()
    bind_desktop(None)


def test_move_and_click_report_screen_digest(fake) -> None:
    out = desktop_move(400, 500)
    assert "move → (400,500)" in out and fake.pointer == (400, 500)
    out2 = desktop_click(x=400, y=500, expect="'Settings saved' appears")
    assert "left click (400,500)" in out2
    assert "✓ expectation met" in out2          # text_content has "Settings saved"
    assert "screen changed" in out2


def test_desktop_tools_registered_for_tool_call_loop(fake) -> None:
    call = '<tool_call name="desktop_click">{"x": 400, "y": 500}</tool_call>'
    out = sdk_tools.run_tools_in_plan(call, allow=DESKTOP_TOOL_NAMES)
    assert "error=" not in out and "screen changed" in out


def test_screenshot_blocked_without_vision(fake) -> None:
    bind_desktop(fake, settle=0.0, provider="openrouter", model="mistral-7b-instruct")
    out = desktop_screenshot()
    assert "screenshot skipped" in out and "vision-capable model" in out


# ---- REAL X11 smoke test (skipped when no display/Xlib) ----

def _have_real_desktop() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        import mss  # noqa: F401
        from PIL import Image  # noqa: F401
        from Xlib import display
        # Verify the X server is actually reachable, not just that $DISPLAY is set.
        d = display.Display()
        d.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _have_ocr() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _have_real_desktop(), reason="no DISPLAY / desktop stack")
def test_real_desktop_end_to_end() -> None:
    """One real display, one backend: verify the primitives (move/capture/diff)
    AND that the autonomous executor drives them end-to-end with a real
    screen-diff flowing back as a digest. (One backend avoids cross-test X
    connection churn.)"""
    import io
    import json

    from rich.console import Console

    from essarion_build import Context, ProviderResponse, Usage
    from essarion_build._runtime import LiteRuntime
    from essarion_build.agent import _agent_exec
    from essarion_build.agent._computer import DESKTOP_PROTOCOL
    from essarion_build.agent._session import Session, TaskTurn, new_session_id
    from essarion_build.agent._theme import ESSARION_THEME
    from essarion_build.computer import DESKTOP_TOOL_NAMES, DesktopBackend, bind_desktop, register_desktop_tools
    from essarion_build.computer.tools import unregister_desktop_tools

    be = DesktopBackend.launch()
    try:
        # --- primitives ---
        w, h = be.screen_size()
        assert w > 0 and h > 0
        be.move(321, 222)
        p = be.input.display.screen().root.query_pointer()
        assert (p.root_x, p.root_y) == (321, 222)        # real absolute move
        png = be.screenshot()
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000  # real capture

        # --- OCR: with the engine present, on-screen text is readable, so text
        #     expectations resolve. Feed a known frame, then restore real grab. ---
        if _have_ocr():
            from PIL import Image, ImageDraw, ImageFont
            from essarion_build.computer import check_expectation, parse_expectation, reduce_events

            real_grab = be._grab
            img = Image.new("RGB", (640, 200), "white")
            ImageDraw.Draw(img).text((30, 80), "Welcome back, user", fill="black",
                                     font=ImageFont.load_default(size=36))
            be._grab = lambda: img  # type: ignore
            try:
                assert "Welcome back" in be.text_content()
                res = check_expectation(parse_expectation("a 'Welcome back' message appears"),
                                        reduce_events([]), page_text=be.text_content())
                assert res.met
            finally:
                be._grab = real_grab  # type: ignore

        root = be.input.display.screen().root
        gc = root.create_gc(foreground=be.input.display.screen().white_pixel)

        # --- full agent loop: scripted provider moves + clicks; the click draws
        #     a real rectangle, and the screen-diff must report it. ---
        orig_click = be.click
        def click_and_paint(*a, **k):
            orig_click(*a, **k)
            root.fill_rectangle(gc, 150, 120, 500, 360)
            be.input.display.sync()
        be.click = click_and_paint  # type: ignore

        bind_desktop(be, settle=0.1, provider="anthropic", model="claude-haiku-4-5")
        register_desktop_tools()

        def _call(name, **kw):
            return f'<tool_call name="{name}">{json.dumps(kw)}</tool_call>'

        responses = [
            _call("desktop_move", x=400, y=300),
            _call("desktop_click", x=400, y=300, expect="the screen changes"),
            "<done>moved and clicked; the screen updated</done>",
        ]
        idx = {"i": 0}

        class P:
            model = "m"
            def complete(self, *, system, messages, max_tokens):
                assert "DESKTOP CONTROL IS ENABLED" in system
                t = responses[idx["i"]]; idx["i"] += 1
                return ProviderResponse(text=t, usage=Usage(total_tokens=10))

        console = Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)
        session = Session(id=new_session_id(), cwd="/tmp", provider="stub", model="m",
                          budget_usd=1.0, autonomous=True, desktop_control=True)
        result = _agent_exec.execute(
            console, session, "move and click and confirm the screen changed", Context(),
            make_runtime=lambda pr, m: LiteRuntime(P()),
            turn=TaskTurn(task="t"), allow=set(DESKTOP_TOOL_NAMES), extra_system=DESKTOP_PROTOCOL,
            max_steps=8,
        )
        out = console.file.getvalue()
        assert result.stopped_reason == "done"
        assert "desktop_move" in out and "desktop_click" in out
        assert "screen changed" in out          # real screen-diff fed back
        assert "✓ expectation met" in out       # the diff satisfied "the screen changes"
    finally:
        try:
            unregister_desktop_tools()
            bind_desktop(None)
        finally:
            be.close()
