"""Register the computer-use action tools into the SDK's `<tool_call>` registry.

Kept separate from registration of the file/shell tools so computer use is
strictly opt-in: nothing here runs unless `register_computer_tools()` is called
(by --computer-use, an explicit request, or an SDK user wiring their own loop).
"""

from __future__ import annotations

from .. import tools as sdk_tools
from ._actions import COMPUTER_TOOLS, DESKTOP_TOOLS

COMPUTER_TOOL_NAMES = set(COMPUTER_TOOLS)
DESKTOP_TOOL_NAMES = set(DESKTOP_TOOLS)


def register_computer_tools() -> None:
    """Make the browser_* tools callable via <tool_call>. Idempotent."""
    for name, (fn, desc) in COMPUTER_TOOLS.items():
        sdk_tools.register_tool(name, description=desc)(fn)


def unregister_computer_tools() -> None:
    for name in COMPUTER_TOOLS:
        sdk_tools.unregister_tool(name)


def register_desktop_tools() -> None:
    """Make the desktop_* tools callable via <tool_call>. Idempotent.

    Desktop control drives the real machine — registration is gated by the
    agent's explicit --desktop opt-in; this only wires the callables."""
    for name, (fn, desc) in DESKTOP_TOOLS.items():
        sdk_tools.register_tool(name, description=desc)(fn)


def unregister_desktop_tools() -> None:
    for name in DESKTOP_TOOLS:
        sdk_tools.unregister_tool(name)
