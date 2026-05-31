"""End-to-end computer-use loop with a scripted FakeBackend — no browser.

The FakeBackend reacts to actions exactly as a real page would (pushing
navigation/DOM/console events, changing the URL), so this exercises the whole
act→observe→reduce→expectation-check chain through the real action tools and the
real <tool_call> registry."""

from __future__ import annotations

import pytest

from essarion_build import tools as sdk_tools
from essarion_build.computer import (
    FakeBackend,
    bind_backend,
    browser_click,
    browser_navigate,
    browser_screenshot,
    register_computer_tools,
)
from essarion_build.computer.tools import unregister_computer_tools


def _login_app(be: FakeBackend, name: str, kw: dict) -> None:
    """A tiny scripted web app: navigating loads a login form; clicking #login
    with the right state navigates to /dashboard and renders a Logout button;
    clicking #broken raises a console error."""
    obs = be.observer()
    if name == "navigate":
        obs.push_event("navigation", f"navigated to {kw['url']}", severity="notice")
        obs.push_event("dom", "rendered login form", severity="info")
        be.outline = "form: Login\n  textbox: Username\n  button: Sign in"
    elif name == "click" and kw.get("selector") == "#login":
        be.current_url = "https://app.test/dashboard"
        obs.push_event("navigation", "navigated to https://app.test/dashboard", severity="notice")
        obs.push_event("dom", "added button: Logout", severity="notice")
    elif name == "click" and kw.get("selector") == "#broken":
        obs.push_event("console", "TypeError: handler is not a function", severity="error")


@pytest.fixture(autouse=True)
def _bound():
    be = FakeBackend(url="about:blank", on_action=_login_app)
    bind_backend(be, settle=0.0, provider="anthropic", model="claude-haiku-4-5")
    register_computer_tools()
    yield be
    unregister_computer_tools()
    bind_backend(None)


def test_navigate_then_click_reports_reactive_digest(_bound) -> None:
    out = browser_navigate("https://app.test/login")
    assert "navigated to https://app.test/login" in out
    assert "login form" in out

    out2 = browser_click(selector="#login")
    assert "url: https://app.test/dashboard" in out2
    assert "Logout" in out2


def test_expectation_met_is_marked(_bound) -> None:
    browser_navigate("https://app.test/login")
    out = browser_click(selector="#login", expect="navigates to /dashboard and a Logout button appears")
    assert "✓ expectation met" in out


def test_expectation_violation_is_flagged(_bound) -> None:
    browser_navigate("https://app.test/login")
    # We claim it stays on /login, but it actually goes to /dashboard.
    out = browser_click(selector="#login", expect="stays on /login page")
    assert "✗ EXPECTATION NOT MET" in out


def test_console_error_surfaces_and_fails_no_error_expectation(_bound) -> None:
    browser_navigate("https://app.test/login")
    out = browser_click(selector="#broken", expect="submits with no console errors")
    assert "[error]" in out and "TypeError" in out
    assert "✗ EXPECTATION NOT MET" in out


def test_tools_are_registered_for_tool_call_loop(_bound) -> None:
    # The reconstructed <tool_call> path the autonomous loop uses must work too.
    call = '<tool_call name="browser_navigate">{"url": "https://app.test/login"}</tool_call>'
    result = sdk_tools.run_tools_in_plan(call, allow={"browser_navigate"})
    assert "error=" not in result
    assert "login form" in result


def test_screenshot_blocked_without_vision_model() -> None:
    be = FakeBackend()
    bind_backend(be, settle=0.0, provider="openrouter", model="mistral-7b-instruct")
    try:
        out = browser_screenshot()
        assert "screenshot skipped" in out
        assert "vision-capable model" in out
    finally:
        bind_backend(None)


def test_screenshot_allowed_with_vision_model() -> None:
    be = FakeBackend(url="https://app.test")
    bind_backend(be, settle=0.0, provider="anthropic", model="claude-haiku-4-5")
    try:
        out = browser_screenshot()
        assert "captured screenshot" in out
    finally:
        bind_backend(None)
