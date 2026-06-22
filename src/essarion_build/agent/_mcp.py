"""MCP (Model Context Protocol) client — connect external tool servers.

Zero-dependency: a minimal JSON-RPC 2.0 client over the MCP **stdio**
transport (newline-delimited JSON messages on a child process's
stdin/stdout). That covers the overwhelming majority of real MCP servers
(`npx @modelcontextprotocol/server-*`, `uvx mcp-server-*`, local binaries)
without pulling in an SDK.

Servers are declared in `.essarion/config.toml` (per-project) or
`~/.config/essarion/config.toml` (user-scoped):

    [[mcp_servers]]
    name = "github"
    command = "npx -y @modelcontextprotocol/server-github"
    # env = { GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_..." }  # extra env (merged)
    # cwd = "/path/to/run/in"                              # default: project root

Each tool a connected server advertises is registered into the SDK tool
registry as `mcp__<server>__<tool>` so the autonomous loop can call it with
the normal `<tool_call>` protocol, and `/mcp` lists everything live.

Security posture: a server runs with YOUR credentials and its results are
UNTRUSTED external data (same trust level as `web_fetch`). Results are
size-capped before they're fed back to the model; env values are never
printed; servers only launch when *you* configured them.
"""

from __future__ import annotations

import atexit
import json
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import tools as sdk_tools


# Wire-format limits. A tool result larger than this is truncated before the
# model sees it (the executor windows it again on feedback).
_RESULT_CAP = 20_000
# Per-call timeout (seconds). Initialization gets a little longer because
# `npx`/`uvx` servers may download on first run.
_CALL_TIMEOUT = 30.0
_INIT_TIMEOUT = 45.0
_PROTOCOL_VERSION = "2025-03-26"


@dataclass
class McpServerConfig:
    """One `[[mcp_servers]]` entry, normalized."""

    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "McpServerConfig | None":
        name = str(raw.get("name", "")).strip()
        cmd = raw.get("command")
        if isinstance(cmd, str):
            command = shlex.split(cmd)
        elif isinstance(cmd, list):
            command = [str(c) for c in cmd]
        else:
            command = []
        if not name or not command:
            return None
        env = {str(k): str(v) for k, v in (raw.get("env") or {}).items()}
        return cls(name=name, command=command, env=env, cwd=str(raw.get("cwd", "") or ""))


class McpError(RuntimeError):
    """A server-side or transport-level MCP failure."""


class McpClient:
    """One live MCP server connection over stdio.

    Thread-safe for calls: a single background reader thread routes responses
    by request id; callers block on a condition until their id resolves.
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self.tools: list[dict[str, Any]] = []  # [{name, description, inputSchema}]
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._responses: dict[int, dict[str, Any]] = {}
        self._next_id = 0
        self._dead_reason = ""

    # ---------- lifecycle ----------

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def dead_reason(self) -> str:
        return self._dead_reason

    def start(self) -> None:
        """Spawn the server process and run the MCP initialize handshake."""
        import os

        env = dict(os.environ)
        env.update(self.config.env)
        try:
            self._proc = subprocess.Popen(
                self.config.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.config.cwd or None,
                env=env,
                text=True,
                bufsize=1,  # line-buffered — the transport is newline-delimited
            )
        except OSError as e:
            self._dead_reason = f"could not launch {self.config.command[0]!r}: {e}"
            raise McpError(self._dead_reason) from None
        threading.Thread(
            target=self._read_loop, name=f"mcp-{self.config.name}", daemon=True
        ).start()
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "essarion-build", "version": _sdk_version()},
                },
                timeout=_INIT_TIMEOUT,
            )
            self._notify("notifications/initialized")
            listed = self._request("tools/list", {}, timeout=_INIT_TIMEOUT)
            self.tools = [t for t in (listed.get("tools") or []) if t.get("name")]
        except McpError:
            self.stop()
            raise

    def stop(self) -> None:
        """Terminate the server process (TERM → KILL)."""
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass

    # ---------- JSON-RPC plumbing ----------

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol output (some servers log to stdout)
            if not isinstance(msg, dict):
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                with self._cond:
                    self._responses[msg["id"]] = msg
                    self._cond.notify_all()
            elif msg.get("method") == "ping" and "id" in msg:
                # Server-initiated ping — answer so the server doesn't drop us.
                self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            elif "id" in msg and "method" in msg:
                # Any other server→client request (sampling, roots): politely decline.
                self._send({
                    "jsonrpc": "2.0", "id": msg["id"],
                    "error": {"code": -32601, "message": "not supported by this client"},
                })
            # Notifications from the server are ignored.
        # EOF — server exited.
        with self._cond:
            if not self._dead_reason:
                self._dead_reason = "server process exited"
            self._cond.notify_all()

    def _send(self, msg: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise McpError(self._dead_reason or "server is not running")
        try:
            proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as e:
            self._dead_reason = f"write failed: {e}"
            raise McpError(self._dead_reason) from None

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._send(msg)

    def _request(
        self, method: str, params: dict[str, Any], *, timeout: float = _CALL_TIMEOUT
    ) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        with self._cond:
            while req_id not in self._responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpError(f"{method} timed out after {timeout:.0f}s")
                if self._proc is None or self._proc.poll() is not None:
                    raise McpError(self._dead_reason or "server exited mid-call")
                self._cond.wait(timeout=min(remaining, 0.5))
            msg = self._responses.pop(req_id)
        if "error" in msg:
            err = msg["error"] or {}
            raise McpError(str(err.get("message") or err))
        result = msg.get("result")
        return result if isinstance(result, dict) else {}

    # ---------- the one call that matters ----------

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> str:
        """Invoke `tool` and flatten its content blocks to text."""
        result = self._request(
            "tools/call", {"name": tool, "arguments": arguments or {}}
        )
        parts: list[str] = []
        for block in result.get("content") or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind == "resource":
                res = block.get("resource") or {}
                parts.append(str(res.get("text", "")) or f"(resource: {res.get('uri', '?')})")
            else:
                parts.append(f"({kind} content omitted)")
        body = "\n".join(p for p in parts if p).strip() or "(empty result)"
        if len(body) > _RESULT_CAP:
            body = body[:_RESULT_CAP].rstrip() + "\n… (truncated)"
        if result.get("isError"):
            raise McpError(body)
        return body


def _sdk_version() -> str:
    try:
        from .. import __version__

        return __version__
    except Exception:  # noqa: BLE001 - version string is cosmetic here
        return "0"


# ---------- manager (module-level, like _background) ----------


class McpManager:
    """All configured servers for the current session."""

    def __init__(self) -> None:
        self.clients: dict[str, McpClient] = {}
        self.errors: dict[str, str] = {}  # server name → why it failed to connect
        self._registered: set[str] = set()  # full tool names we put in the registry

    def configs_from(self, *config_dicts: dict[str, Any]) -> list[McpServerConfig]:
        """Collect `[[mcp_servers]]` entries; first definition of a name wins
        (project config is passed before the user-scoped one)."""
        out: list[McpServerConfig] = []
        seen: set[str] = set()
        for data in config_dicts:
            for raw in (data or {}).get("mcp_servers") or []:
                cfg = McpServerConfig.from_dict(raw) if isinstance(raw, dict) else None
                if cfg is not None and cfg.name not in seen:
                    seen.add(cfg.name)
                    out.append(cfg)
        return out

    def connect(self, config: McpServerConfig) -> McpClient:
        """Start one server, register its tools. Raises McpError on failure."""
        client = McpClient(config)
        client.start()
        self.clients[config.name] = client
        self.errors.pop(config.name, None)
        for tool in client.tools:
            self._register_proxy(client, tool)
        return client

    def connect_all(self, configs: list[McpServerConfig]) -> list[str]:
        """Connect every configured server. Returns human-readable status lines.
        A failing server is reported, never fatal."""
        lines: list[str] = []
        for cfg in configs:
            if cfg.name in self.clients and self.clients[cfg.name].alive:
                continue
            try:
                client = self.connect(cfg)
                lines.append(f"{cfg.name}: connected ({len(client.tools)} tool(s))")
            except McpError as e:
                self.errors[cfg.name] = str(e)
                lines.append(f"{cfg.name}: failed — {e}")
        return lines

    def _register_proxy(self, client: McpClient, tool: dict[str, Any]) -> None:
        tool_name = str(tool["name"])
        full = f"mcp__{client.config.name}__{tool_name}"
        desc = " ".join(str(tool.get("description", "")).split())[:160]
        # Surface the schema's parameter names in the manifest, because the
        # proxy's own signature is just **kwargs.
        props = ((tool.get("inputSchema") or {}).get("properties") or {})
        if props:
            desc = (desc + " " if desc else "") + f"(args: {', '.join(sorted(props))})"

        def _proxy(**kwargs: Any) -> str:
            if not client.alive:
                raise McpError(
                    f"MCP server {client.config.name!r} is not running "
                    f"({client.dead_reason or 'stopped'}); try /mcp reconnect"
                )
            return client.call_tool(tool_name, kwargs)

        sdk_tools.register_tool(full, description=desc)(_proxy)
        self._registered.add(full)

    def tool_names(self) -> set[str]:
        """Every registered MCP tool's full `mcp__server__tool` name."""
        return set(self._registered)

    def shutdown(self) -> None:
        for client in self.clients.values():
            client.stop()
        for name in self._registered:
            sdk_tools.unregister_tool(name)
        self.clients.clear()
        self._registered.clear()


_MANAGER = McpManager()

# Even on a crash path that skips the REPL's clean shutdown, child server
# processes must not be orphaned.
atexit.register(lambda: _MANAGER.shutdown())


def current_manager() -> McpManager:
    return _MANAGER


def active_tool_names() -> set[str]:
    """The full names of every connected MCP tool — folded into the autonomous
    loop's allow-list so the model can call them."""
    return _MANAGER.tool_names()


def startup_from_config(console, cwd: str | Path) -> None:
    """Read `[[mcp_servers]]` from project + user config and connect them.

    Called once at REPL/one-shot start. Quiet when nothing is configured;
    one status line per server otherwise.
    """
    from ._project import find_project_root, load_project_config

    try:
        project_cfg = load_project_config(find_project_root(cwd))
    except Exception:  # noqa: BLE001 - a broken config file must not block startup
        project_cfg = {}
    user_cfg: dict[str, Any] = {}
    user_path = Path.home() / ".config" / "essarion" / "config.toml"
    if user_path.is_file():
        import tomllib

        try:
            user_cfg = tomllib.loads(user_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            user_cfg = {}
    configs = _MANAGER.configs_from(project_cfg, user_cfg)
    if not configs:
        return
    for line in _MANAGER.connect_all(configs):
        style = "ok" if "connected" in line else "warn"
        console.print(f"[meta]mcp:[/meta] [{style}]{line}[/{style}]")


def shutdown_all() -> None:
    _MANAGER.shutdown()


__all__ = [
    "McpClient",
    "McpError",
    "McpManager",
    "McpServerConfig",
    "active_tool_names",
    "current_manager",
    "shutdown_all",
    "startup_from_config",
]
