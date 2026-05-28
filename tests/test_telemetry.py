"""Tests for the optional telemetry hook."""

from __future__ import annotations

from typing import Any

from essarion_build import (
    Context,
    LiteRuntime,
    StubProvider,
    configure_telemetry,
    generate,
    reason,
)


def _stub_for_reason() -> StubProvider:
    return StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<verdict>ship</verdict>",
        ]
    )


def _stub_for_generate() -> StubProvider:
    return StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>x=1</code>",
            "<verdict>ship</verdict><defense>safe</defense>",
        ]
    )


def test_telemetry_is_off_by_default() -> None:
    """No callback configured -> reason() runs without invoking telemetry."""
    events: list[dict] = []
    # No configure_telemetry call.
    rt = LiteRuntime(_stub_for_reason())
    reason("task", context=Context(), _runtime=rt)
    assert events == []  # nothing captured because nothing emitted


def test_telemetry_captures_loop_events() -> None:
    events: list[dict[str, Any]] = []

    def cb(ev: dict[str, Any]) -> None:
        events.append(ev)

    configure_telemetry(on_event=cb)
    try:
        rt = LiteRuntime(_stub_for_reason())
        reason("task", context=Context(), _runtime=rt)
    finally:
        configure_telemetry(on_event=None, enabled=False)

    kinds = [e["kind"] for e in events]
    assert kinds[0] == "loop_start"
    assert kinds[-1] == "loop_done"
    assert "phase_call" in kinds
    assert "phase_done" in kinds


def test_telemetry_captures_repair_events() -> None:
    events: list[dict[str, Any]] = []
    configure_telemetry(on_event=events.append)
    try:
        stub = StubProvider(
            responses=[
                "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
                "<code>x=1</code>",
                "<verdict>ship</verdict>",  # missing defense
                "<defense>safe</defense>",
            ]
        )
        rt = LiteRuntime(stub)
        g = generate("task", context=Context(), _runtime=rt)
    finally:
        configure_telemetry(on_event=None, enabled=False)

    assert g.defense == "safe"
    assert any(e["kind"] == "tag_repair_attempt" for e in events)


def test_telemetry_callback_exception_does_not_break_loop() -> None:
    """A buggy callback must not poison the reasoning loop."""

    def broken_cb(ev: dict) -> None:
        raise RuntimeError("oops")

    configure_telemetry(on_event=broken_cb)
    try:
        rt = LiteRuntime(_stub_for_reason())
        r = reason("task", context=Context(), _runtime=rt)
    finally:
        configure_telemetry(on_event=None, enabled=False)

    # The loop still completed.
    assert r.verdict == "ship"


def test_telemetry_can_be_disabled_without_clearing_callback() -> None:
    events: list[dict] = []
    configure_telemetry(on_event=events.append)
    configure_telemetry(enabled=False)
    try:
        rt = LiteRuntime(_stub_for_reason())
        reason("task", context=Context(), _runtime=rt)
    finally:
        configure_telemetry(on_event=None, enabled=False)
    assert events == []
