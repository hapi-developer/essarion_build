"""Tests for the lightweight tool-use surface."""

from __future__ import annotations

import json

import pytest

from essarion_build.tools import (
    list_tools,
    register_tool,
    run_tools_in_plan,
    tool_manifest,
    unregister_tool,
)


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """Snapshot and restore the registry around each test."""
    from essarion_build import tools as t

    snapshot_fns = dict(t._TOOLS)
    snapshot_descs = dict(t._TOOL_DESCRIPTIONS)
    t._TOOLS.clear()
    t._TOOL_DESCRIPTIONS.clear()
    yield
    t._TOOLS.clear()
    t._TOOLS.update(snapshot_fns)
    t._TOOL_DESCRIPTIONS.clear()
    t._TOOL_DESCRIPTIONS.update(snapshot_descs)


def test_register_and_call() -> None:
    @register_tool("add", description="add two numbers")
    def _add(a: int, b: int) -> int:
        return a + b

    text = '<tool_call name="add">{"a": 1, "b": 2}</tool_call>'
    out = run_tools_in_plan(text)
    assert "<tool_result" in out
    assert ">3<" in out


def test_no_args_call() -> None:
    @register_tool("now")
    def _now() -> str:
        return "2026-01-01"

    text = '<tool_call name="now"></tool_call>'
    out = run_tools_in_plan(text)
    assert "2026-01-01" in out


def test_unknown_tool_becomes_error_result() -> None:
    text = '<tool_call name="ghost">{}</tool_call>'
    out = run_tools_in_plan(text)
    assert 'name="ghost"' in out
    assert 'error="true"' in out
    assert "not registered" in out


def test_invalid_json_args_becomes_error() -> None:
    @register_tool("noop")
    def _noop() -> str:
        return "ok"

    text = '<tool_call name="noop">{bad}</tool_call>'
    out = run_tools_in_plan(text)
    assert 'error="true"' in out
    assert "JSON invalid" in out


def test_args_must_be_object_not_array() -> None:
    @register_tool("f")
    def _f(x: int = 0) -> int:
        return x

    text = '<tool_call name="f">[1, 2, 3]</tool_call>'
    out = run_tools_in_plan(text)
    assert 'error="true"' in out
    assert "must be a JSON object" in out


def test_tool_exception_becomes_error_result() -> None:
    @register_tool("explode")
    def _explode() -> str:
        raise ValueError("boom")

    text = '<tool_call name="explode">{}</tool_call>'
    out = run_tools_in_plan(text)
    assert 'error="true"' in out
    assert "ValueError" in out
    assert "boom" in out


def test_allow_list_restricts_callable_tools() -> None:
    @register_tool("dangerous")
    def _dangerous() -> str:
        return "did damage"

    @register_tool("safe")
    def _safe() -> str:
        return "fine"

    text = (
        '<tool_call name="dangerous">{}</tool_call>'
        '<tool_call name="safe">{}</tool_call>'
    )
    out = run_tools_in_plan(text, allow={"safe"})
    assert "did damage" not in out
    assert "fine" in out
    assert 'name="dangerous"' in out
    assert 'error="true"' in out


def test_multiple_tool_calls_in_one_text() -> None:
    @register_tool("echo")
    def _echo(s: str) -> str:
        return s.upper()

    text = (
        '<tool_call name="echo">{"s": "hi"}</tool_call>'
        ' and '
        '<tool_call name="echo">{"s": "bye"}</tool_call>'
    )
    out = run_tools_in_plan(text)
    assert "HI" in out
    assert "BYE" in out


def test_unregister_tool() -> None:
    @register_tool("temp")
    def _t() -> str:
        return "yes"

    assert any(t.name == "temp" for t in list_tools())
    unregister_tool("temp")
    assert all(t.name != "temp" for t in list_tools())


def test_tool_manifest_empty() -> None:
    assert "No tools" in tool_manifest()


def test_tool_manifest_lists_registered() -> None:
    @register_tool("read", description="read a file")
    def _r(path: str) -> str:
        return ""

    @register_tool("write")
    def _w(path: str, body: str) -> str:
        return ""

    m = tool_manifest()
    assert "read" in m
    assert "read a file" in m
    assert "write" in m


def test_list_tools_returns_sorted() -> None:
    @register_tool("zeta")
    def _z() -> str:
        return ""

    @register_tool("alpha")
    def _a() -> str:
        return ""

    names = [t.name for t in list_tools()]
    assert names == ["alpha", "zeta"]
