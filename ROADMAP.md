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
- 🟡 **Memory** — project memory via `/remember` + `.essarion/`. A `CLAUDE.md`
  auto-read and self-accumulating memory are open.
- ⭕ **Subagents** · ⭕ **MCP** · ⭕ **Plugins / marketplaces**

## Automation & orchestration
- 🟡 **Headless / SDK** — `--task` one-shot + the Python SDK (`reason`/`generate`).
  A full programmatic agent SDK is open.
- ⭕ **Agent Teams** · ⭕ **Scheduled tasks (/loop, cron)** · ⭕ **GitHub/GitLab CI**
  · ⭕ **Automated code review**

## Computer & browser use
- ⭕ **Computer use** — open goal (intentionally deferred for now).
- ⭕ **Browser use** — open goal.

---

### Closed so far
- The agentic core: an autonomous execution loop (`_agent_exec.execute` +
  `run_turn_autonomous`), the `delete_file` tool, the `/auto` mode +
  `--autonomous` flag, and cloud auto-mode-by-default. The plan→approve gate is
  the single human checkpoint; everything after runs on disk and is undoable.
- Hooks: `pre_tool`/`post_tool`/`user_prompt`/`session_start`/`stop`, wired
  through the sandboxed tools and both turn paths, surfaced in the cloud worker.

### Suggested next open goal
**MCP** — connect external tools/services and let servers push events (CI,
alerts) into a session. After that, subagents or scheduled tasks. Say the word.
