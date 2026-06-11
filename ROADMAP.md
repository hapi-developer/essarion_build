# essarion build — capability roadmap

Where essarion stands against the Claude-Code feature surface, and what's left.
Honest status — this is a map, not a marketing sheet. Scope is **CLI + cloud only**.

Legend: ✅ shipped · 🟡 partial · ⭕ open goal (not built yet)

## Agentic core
- ✅ **Agentic loop** — model chains tools autonomously until the goal is done
  (`agent/_agent_exec.py`). Enabled with `/auto` / `--autonomous`; the cloud
  defaults it on. Bounded by a step cap and the session budget.
- ✅ **Multi-file editing** — creates/edits across the workspace in one turn.
- ✅ **Write / edit / delete on disk** — `write_file`, `apply_diff`,
  `delete_file`, all sandboxed to the session cwd.
- ✅ **Running commands** — `run_shell` + background tasks (`/bg`).
- ✅ **Bug-fix / test-and-iterate** — the loop runs the tests, reads failures,
  fixes, and re-runs.
- ✅ **Checkpointing / undo / diff** — every mutation is recorded; `/undo`
  reverts, `/diff` shows the net change.
- ✅ **Permission modes** — supervised (plan → approve → hand-apply), auto
  (plan → approve → autonomous), read-only planning (`/ask`); `/auto`, `/yolo`.
- ✅ **Sandboxing** — tools are path-confined to the session cwd; in the cloud
  each session is its own container.
- 🟡 **Git workflows** — `/commit` commits the session's changes. Branch/PR
  automation is open.

## Surfaces
- ✅ Terminal CLI · ✅ Web (cloud) chat UI with one sandbox per session + `.zip` export
- ⭕ VS Code / JetBrains / Desktop / Mobile / Slack

## Codebase understanding
- ✅ Inline read tools during planning (`read_file`/`grep`/`glob`/`list_dir`/`find_files`),
  auto-attach of named files + their sibling tests.
- 🟡 Whole-repo semantic index — today it's heuristics + on-demand reads.

## Extensibility
- ✅ **Skills** — bundled, with an auto/all/none picker.
- ✅ **Hooks** — shell commands that fire on lifecycle events (`pre_tool`,
  `post_tool`, `user_prompt`, `session_start`, `stop`), configured as
  `[[hooks]]` in `.essarion/config.toml`. `pre_tool` exit-2 blocks a tool
  (Claude-Code parity); `post_tool` output folds into the tool result. Format
  on write, enforce command policy, notify on completion. `_hooks.py`, `/hooks`.
- ✅ **Memory** — project memory via `/remember` + `.essarion/`, auto-read of
  AGENTS.md / CLAUDE.md / `.cursorrules` (cross-tool conventions), and
  **self-accumulating memory**: the agent persists durable facts itself with
  the `remember` tool (deduplicated, secret-screened) and reads them back
  every turn. (`_memory.py`, `_conventions.py`)
- ✅ **Subagents** — `spawn_subagents` fans out up to 8 **parallel,
  context-isolated** workers; only their summaries return to the lead agent.
  Read-only option, non-interactive (ask → deny), no recursion, tighter
  budgets, usage rolls into the turn meter. (`_subagents.py`)
- ✅ **MCP** — `[[mcp_servers]]` in config connects any stdio MCP server; its
  tools become first-class `mcp__<server>__<tool>` tools in the autonomous
  loop. `/mcp` lists servers + tools, `/mcp reconnect` retries. Zero-dep
  JSON-RPC 2.0 client. (`_mcp.py`)
- ⭕ **Plugins / marketplaces**

## Automation & orchestration
- 🟡 **Headless / SDK** — `--task` one-shot + the Python SDK (`reason`/`generate`).
  A full programmatic agent SDK is open.
- ⭕ **Agent Teams** · ⭕ **Scheduled tasks (/loop, cron)** · ⭕ **GitHub/GitLab CI**
  · ⭕ **Automated code review**

## Computer & browser use
- ✅ **Browser use** — opt-in (`/computer`, `--computer-use`): the agent drives
  a real headless browser with a reactive digest (console errors, network
  failures, DOM changes), `expect=` predictions verified deterministically.
- ✅ **Desktop control** — explicit opt-in (`/desktop`, `--desktop`): real
  mouse/keyboard/screen with a screen-diff observer.

---

### Closed so far
- The agentic core: an autonomous execution loop (`_agent_exec.execute` +
  `run_turn_autonomous`), the `delete_file` tool, the `/auto` mode +
  `--autonomous` flag, and cloud auto-mode-by-default. The plan→approve gate is
  the single human checkpoint; everything after runs on disk and is undoable.
- Hooks: `pre_tool`/`post_tool`/`user_prompt`/`session_start`/`stop`, wired
  through the sandboxed tools and both turn paths, surfaced in the cloud worker.
- **v0.4.0 — the extensibility trio**: MCP (`_mcp.py`), parallel
  context-isolated subagents (`_subagents.py`), and self-accumulating memory
  (the `remember` tool). All zero-dependency, all in both turn paths.

### Suggested next open goal
**Scheduled tasks + automated code review** — a `/loop`-style recurring runner
and a CI surface (GitHub Action) that reviews PRs with the crosscheck ensemble.
After that: plugins/marketplaces, or the IDE surfaces. Say the word.
