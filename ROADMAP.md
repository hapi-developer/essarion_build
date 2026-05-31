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
- 🟡 **Memory** — project memory via `/remember` + `.essarion/`. A `CLAUDE.md`
  auto-read and self-accumulating memory are open.
- ⭕ **Subagents** · ⭕ **Hooks** · ⭕ **MCP** · ⭕ **Plugins / marketplaces**

## Automation & orchestration
- 🟡 **Headless / SDK** — `--task` one-shot + the Python SDK (`reason`/`generate`).
  A full programmatic agent SDK is open.
- ⭕ **Agent Teams** · ⭕ **Scheduled tasks (/loop, cron)** · ⭕ **GitHub/GitLab CI**
  · ⭕ **Automated code review**

## Computer & browser use
- ⭕ **Computer use** — open goal (intentionally deferred for now).
- ⭕ **Browser use** — open goal.

---

### Closed in this pass
The agentic core: an autonomous execution loop (`_agent_exec.execute` +
`run_turn_autonomous`), the `delete_file` tool, the `/auto` mode + `--autonomous`
flag, and cloud auto-mode-by-default. The plan→approve gate is kept as the single
human checkpoint; everything after it runs on disk and is fully undoable.

### Suggested next open goal
**Hooks** or **MCP** give the most leverage next (they unlock CI events, custom
commands, and external tools). Say which and it's the next pass.
