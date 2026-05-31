"""Register the computer-use action tools into the SDK's `<tool_call>` registry.

Kept separate from registration of the file/shell tools so computer use is
strictly opt-in: nothing here runs unless `register_computer_tools()` is called
(by --computer-use, an explicit request, or an SDK user wiring their own loop).
"""

from __future__ import annotations

from .. import tools as sdk_tools
from ._actions import COMPUTER_TOOLS

COMPUTER_TOOL_NAMES = set(COMPUTER_TOOLS)


def register_computer_tools() -> None:
    """Make the browser_* tools callable via <tool_call>. Idempotent."""
    for name, (fn, desc) in COMPUTER_TOOLS.items():
        sdk_tools.register_tool(name, description=desc)(fn)


def unregister_computer_tools() -> None:
    for name in COMPUTER_TOOLS:
        sdk_tools.unregister_tool(name)
