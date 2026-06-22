"""MCP client: a zero-dep JSON-RPC stdio client driven against a real child
process (a tiny fake MCP server written to tmp_path) — no network, no SDK."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from essarion_build import tools as sdk_tools
from essarion_build.agent._mcp import (
    McpClient,
    McpError,
    McpManager,
    McpServerConfig,
)


FAKE_SERVER = textwrap.dedent(
    """
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            out = {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1"}}}
        elif method == "tools/list":
            out = {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": "echo", "description": "echo text back",
                 "inputSchema": {"type": "object",
                                 "properties": {"text": {"type": "string"}}}},
                {"name": "fail", "description": "always errors",
                 "inputSchema": {"type": "object", "properties": {}}},
            ]}}
        elif method == "tools/call":
            params = msg.get("params") or {}
            args = params.get("arguments") or {}
            if params.get("name") == "echo":
                out = {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text",
                                 "text": "echo: " + str(args.get("text", ""))}]}}
            else:
                out = {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "boom"}],
                    "isError": True}}
        elif mid is None:
            continue
        else:
            out = {"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": "unknown method"}}
        sys.stdout.write(json.dumps(out) + "\\n")
        sys.stdout.flush()
    """
)


@pytest.fixture
def server_cmd(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return [sys.executable, str(script)]


@pytest.fixture
def client(server_cmd: list[str]):
    c = McpClient(McpServerConfig(name="fake", command=server_cmd))
    c.start()
    yield c
    c.stop()


# ---------- config parsing ----------

def test_config_from_dict_string_command() -> None:
    cfg = McpServerConfig.from_dict({"name": "gh", "command": "npx -y server-github"})
    assert cfg is not None
    assert cfg.command == ["npx", "-y", "server-github"]


def test_config_from_dict_list_command_and_env() -> None:
    cfg = McpServerConfig.from_dict(
        {"name": "x", "command": ["python", "-m", "srv"], "env": {"TOKEN": "t"}}
    )
    assert cfg is not None
    assert cfg.command == ["python", "-m", "srv"]
    assert cfg.env == {"TOKEN": "t"}


def test_config_from_dict_rejects_incomplete() -> None:
    assert McpServerConfig.from_dict({"name": "x"}) is None
    assert McpServerConfig.from_dict({"command": "y"}) is None


def test_configs_from_first_definition_wins() -> None:
    mgr = McpManager()
    project = {"mcp_servers": [{"name": "a", "command": "proj-a"}]}
    user = {"mcp_servers": [{"name": "a", "command": "user-a"},
                            {"name": "b", "command": "user-b"}]}
    configs = mgr.configs_from(project, user)
    assert [c.name for c in configs] == ["a", "b"]
    assert configs[0].command == ["proj-a"]  # project config shadows user config


# ---------- live client against the fake server ----------

def test_handshake_lists_tools(client: McpClient) -> None:
    assert client.alive
    assert [t["name"] for t in client.tools] == ["echo", "fail"]


def test_call_tool_returns_text(client: McpClient) -> None:
    assert client.call_tool("echo", {"text": "hi"}) == "echo: hi"


def test_call_tool_surfaces_server_error(client: McpClient) -> None:
    with pytest.raises(McpError, match="boom"):
        client.call_tool("fail", {})


def test_unknown_method_is_an_error(client: McpClient) -> None:
    with pytest.raises(McpError, match="unknown method"):
        client._request("nope/nope", {})


def test_launch_failure_is_a_clean_error() -> None:
    c = McpClient(McpServerConfig(name="x", command=["definitely-not-a-binary-xyz"]))
    with pytest.raises(McpError, match="could not launch"):
        c.start()


def test_call_after_server_death_errors(client: McpClient) -> None:
    client.stop()
    with pytest.raises(McpError):
        client.call_tool("echo", {"text": "hi"})


# ---------- manager: registry integration ----------

def test_manager_registers_namespaced_proxy_tools(server_cmd: list[str]) -> None:
    mgr = McpManager()
    try:
        mgr.connect(McpServerConfig(name="fake", command=server_cmd))
        assert {"mcp__fake__echo", "mcp__fake__fail"} <= mgr.tool_names()
        # Callable through the normal <tool_call> protocol.
        out = sdk_tools.run_tools_in_plan(
            '<tool_call name="mcp__fake__echo">{"text": "via registry"}</tool_call>',
            allow={"mcp__fake__echo"},
        )
        assert "echo: via registry" in out
        # The manifest advertises the schema's arg names.
        assert "(args: text)" in sdk_tools.tool_manifest()
    finally:
        mgr.shutdown()
    # Shutdown unregisters everything it added.
    assert "mcp__fake__echo" not in {t.name for t in sdk_tools.list_tools()}
    assert mgr.tool_names() == set()


def test_manager_reports_failed_server_without_raising() -> None:
    mgr = McpManager()
    lines = mgr.connect_all(
        [McpServerConfig(name="bad", command=["definitely-not-a-binary-xyz"])]
    )
    assert len(lines) == 1 and "failed" in lines[0]
    assert "bad" in mgr.errors
    mgr.shutdown()
