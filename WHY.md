# Why essarion-build instead of Claude Code / Codex / Aider / Cursor

The one-sentence version lives in the [README](./README.md): adaptive
reasoning effort makes cheap models reason like expensive ones, spending
tokens only where a task's stakes call for it. Everything below is the
full point-by-point case.

1. **Adaptive reasoning depth.** Defaults to `effort="auto"` — a tiny
   triage call sizes every task and routes trivial work to a 1-call plan
   while reserving the deep critique→revise loop for tasks with real
   stakes. You see the depth it chose. Override live with `/effort deep`.
   This is the whole bet: better reasoning, paid for only where it counts.
2. **Autonomous by default, with an optional plan checkpoint.** Out of the
   box the agent works like Claude Code / Codex: it plans internally, then
   writes/edits/deletes files and runs commands in a loop until the task is
   done — no approval stops. When you *want* a checkpoint, `/auto off` (or
   `--plan-first`) gives you the plan + verdict BEFORE any code is paid for,
   so you can edit, reject, or send it back. Most agents force one mode; this
   gives you both.
3. **Parallel subagents with context isolation.** On a big task the agent
   fans out up to 8 scoped workers (`spawn_subagents`) that run
   *concurrently* — sweep these modules, audit that area, build this piece —
   each in its **own fresh context**. Only their final summaries return to
   the lead agent, so a wide exploration costs the parent a paragraph
   instead of a context window. Subagents can be marked `read_only`, can't
   prompt you, can't spawn further subagents, and inherit your permission
   policy (anything that would *ask* is denied instead). Their token spend
   rolls into the same turn meter and budget cap.
4. **MCP — plug in external tools.** Declare any MCP server in
   `.essarion/config.toml` (`[[mcp_servers]]`: GitHub, Postgres, Slack,
   your internal tools…) and its tools become first-class agent tools
   (`mcp__github__create_issue`), listed in the manifest and callable in
   the autonomous loop. Zero-dependency stdio JSON-RPC client built in —
   `/mcp` shows live servers + tools, `/mcp reconnect` retries.
5. **Code intelligence, not blind grep.** Every turn the agent gets an
   Aider-style *repo map* — a ranked, token-budgeted skeleton of the codebase's
   key classes/functions — and tools to navigate it: `repo_map`,
   `outline <file>`, and `find_symbol <name>` (go-to-definition +
   find-references). It can edit by *symbol* — `edit_symbol` rewrites a whole
   function/class located via the AST and refuses to write code that won't
   parse — and every edit comes back with objective feedback: a `⚠` for a
   syntax error you just introduced, a real-linter diagnostic when one is
   installed (`ruff`/`pyflakes`/`ruby -c`/`php -l`/`shellcheck`, auto-detected,
   zero-config), and a `↔` *blast-radius* note listing the callers of a symbol
   you changed or removed. All standard library — no tree-sitter, no embeddings,
   no vector DB.
6. **Collapsed, readable output + memory.** Each action is one compact,
   faded line (`Created index.html`, `Edited styles.css` + a small diff,
   `Ran npm test` + a short tail) — not a wall of file dumps. The agent
   also remembers the conversation, so "what did you just do?" or "how do I
   reach the server?" are answered from memory, and it can **ask you
   multiple-choice questions** mid-task when something's genuinely ambiguous.
7. **Token meter + a cap that actually holds.** Every turn shows tokens + cost
   (and cache hits); there's **no spending cap by default**. Set one with
   `/budget` (it'll prompt) or `--budget 5`. When a cap is set the autonomous
   loop **pre-estimates the next step and stops before crossing it** (not after
   the call is billed), and **finalizes with a grounded summary of findings so
   far** rather than stopping empty-handed. An **exploration budget**
   (`--read-cap`, default 25) stops the "reads forever, answers never" failure.
   `/cost <path>` estimates a hypothetical context before you send it.
8. **Guardrails + a live checklist.** Catastrophic commands (`rm -rf /`,
   `mkfs`, fork bombs) are always refused and risky ones (`sudo`, force-push,
   `curl | sh`) prompt for approval — tune it under `[permissions]` in
   `.essarion/config.toml`, or `/yolo` to wave it through. The agent keeps a
   visible todo checklist (`☐ ▶ ☑`) on multi-step tasks, and secrets are
   redacted from output and memory.
9. **Smart skill selection.** The 54 bundled skills aren't all loaded
   every turn — a fast keyword picker chooses the 3-5 most relevant
   ones. Big context savings on every call.
10. **Multi-model arbitrage (both directions).** Plan + selfcheck on a cheap
    model; `--escalate <bigger-model>` kicks in only if selfcheck rejects. And
    `--triage-model <cheap>` **de-escalates** the throwaway `effort=auto` routing
    call to a pennies model, so you can keep a *capable* default for the real
    reasoning at near-zero routing cost. Cheap by default, smart when it matters.
11. **Cross-model second opinion — no other coding agent ships this.** Turn on
    `/crosscheck <model>` (ideally a *different* family) and an INDEPENDENT model
    red-teams every change before it lands — seeing only the goal + the diff, so a
    review is a few hundred tokens. Different models have different blind spots, so
    **where they disagree is where bugs hide**: Essarion surfaces the specific
    concerns (file · symbol · why) and nudges you to `/fix` or `/undo`. Two pennies
    models — one building, a different one cross-examining — catch what a single
    model rubber-stamps. The cheap-ensemble take on "make cheap models reason like
    a better one." (On OpenRouter, write on `openai/…` and review on `anthropic/…`
    with one key.)
12. **Project-aware, with self-accumulating memory.** `essarion init` creates
    `.essarion/{config.toml, sessions/, memory.md}` per repo. The agent
    auto-detects the project root from `.essarion/`, `.git/`, `pyproject.toml`,
    etc. Per-project memory and config flow into every turn — and the agent
    **maintains its own memory**: when it learns a durable fact mid-run (a
    convention, a gotcha, where something lives) it saves it with the
    `remember` tool, deduplicated and secret-screened, so the next session
    starts already knowing it. Curate by hand with `/remember` / `/forget`.
    It also reads **AGENTS.md** (monorepo-nested, nearest-wins) plus
    `CLAUDE.md` / `.cursorrules` / `.github/copilot-instructions.md`, so a repo
    already set up for another agent steers this one too.
13. **Inline tool execution during planning.** The model can emit
    `<tool_call name="read_file">…</tool_call>` inside its plan; the agent
    runs the read-only tool (read_file, grep, glob, list_dir, find_files,
    repo_map, outline, find_symbol), folds the result back as a note, and
    re-plans. Up to 3 rounds. No user friction. You can also steer it yourself
    with inline **`@path`** references — `@src/auth.py` attaches the file (and its
    sibling test), `@src/` a directory. Large files are **windowed** (head + tail,
    or around your search hits), so the end of a file is never silently dropped.
14. **Background tasks.** `/bg npm run dev` runs in parallel. The agent
    keeps working; completion notices fire between turns. /quit cleanly
    kills non-detached tasks via SIGTERM → SIGKILL on the process group.
15. **Drive a real browser (computer use).** Opt in with `/computer` (or
    `--computer-use`) and the agent drives a real headless browser to *test
    what it just built* — start a dev server in the background, then navigate,
    click, and type, reading back a reactive digest of console errors, network
    failures, and DOM changes (not just a screenshot). Each action can carry an
    `expect=` prediction the environment verifies deterministically. `/desktop`
    extends the same loop to the real mouse/keyboard/screen (explicit opt-in).
    On vision-capable models the agent can *see* the screenshots it takes.
16. **Streamed draft output.** `/stream on` shows code as it's written,
    token by token.
17. **Auto-verify + undo.** Configure `[verify].auto=true` and the agent
    runs your test suite after every applied change. If it fails, `/undo`
    reverts the last change.
18. **Reasoning-trace persistence.** Every session saved to
    `<project>/.essarion/sessions/` (or `~/.essarion/sessions/`). Replay
    with `essarion --resume <id>`.
19. **The whole SDK is yours.** Anything you can do in the agent, you can
    do in code — same `reason()`, `generate()`, `Conversation` calls.
