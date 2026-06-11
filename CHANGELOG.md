# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **`web_fetch` is now SSRF-guarded.** The tool fetches URLs the *model*
  chooses, and that choice can be steered by untrusted content the agent just
  read — so a fetch could be aimed at the cloud metadata endpoint
  (`169.254.169.254`), `localhost`, or a private-range host (in the cloud
  product each session is a container with internal sidecars). `web_fetch` now
  refuses any URL whose host resolves to a non-public address — private,
  loopback, link-local, multicast, reserved, IPv4-mapped — and re-validates
  every redirect hop, so a public URL that 302s inward is caught too.
  Still standard-library only (`agent/_ssrf.py`).

## [0.4.0] - 2026-06-11

The extensibility release — the three biggest items on the roadmap land at
once, closing the gap to (and past) the mainstream agents: **MCP** (plug in
any external tool server), **parallel subagents with context isolation**
(fan out wide work without burning the lead agent's context), and
**self-accumulating memory** (the agent persists what it learns). Plus the
full cost-and-quality line: an exploration cap so the agent stops reading and
starts answering, a spending cap that holds *before* the bill, cross-model
second opinions, and `.env` that just works. All still zero-dependency
(standard library only).

### Added

- **MCP support (`[[mcp_servers]]`, `/mcp`) — connect any Model Context
  Protocol server.** A zero-dependency JSON-RPC 2.0 client over the MCP stdio
  transport (the transport virtually every real server speaks: `npx
  @modelcontextprotocol/server-*`, `uvx mcp-server-*`, local binaries).
  Declare servers in `.essarion/config.toml` or `~/.config/essarion/
  config.toml`; each tool a server advertises becomes a first-class agent
  tool (`mcp__<server>__<tool>`) — in the manifest with its real argument
  names, callable in the autonomous loop, rendered as a compact `MCP
  github · create_issue` action line. `/mcp` shows live servers + tools;
  `/mcp reconnect` retries after a config fix; servers shut down cleanly with
  the session. Server results are treated as untrusted external data and
  size-capped before the model sees them; env values are never printed.
- **Parallel subagents with context isolation (`spawn_subagents`).** The lead
  agent can fan out up to 8 scoped workers that run *concurrently*, each in
  its own fresh executor with its own context (project memory + conventions +
  repo map — not the parent's conversation). Only each worker's final summary
  returns to the parent, so a wide sweep costs the lead agent a paragraph
  instead of a context window. Guardrails built in: subagents are
  non-interactive (`ask_user` is answered with "decide yourself"; permission
  decisions that would *ask* are **denied** instead — never a hung prompt in a
  worker thread), can be `read_only`, can never spawn further subagents
  (depth cap 1), get tighter step/read budgets, and their mutations flow
  through the same change log (`/undo`, `/diff`) and usage/cost meter as the
  parent's.
- **Self-accumulating memory (`remember` tool).** The agent now *maintains its
  own* project memory: when it learns a durable fact mid-run (a convention, a
  gotcha, where something lives, a decision you made) it persists it to
  `.essarion/memory.md` — deduplicated, whitespace-normalized, length-capped,
  and **secret-screened** (anything key/token-shaped is refused). Facts come
  back in every future turn's context. `/remember` and `/forget` still curate
  by hand. This closes the "memory" roadmap item end to end: auto-read was
  already in (AGENTS.md / CLAUDE.md / `.cursorrules` conventions), and now
  the write side is automatic too.
- **Cross-model second opinion (`/crosscheck`, `--crosscheck-model`) — a feature
  no mainstream coding agent ships.** A *different* model independently red-teams
  every change before it lands, seeing only the goal and the diff (never the
  repo, so it's cheap — a review is a few hundred tokens). Different model
  families have different blind spots, so where the writer and the reviewer
  **disagree is exactly where bugs hide** — Essarion surfaces the specific
  concerns (file·symbol·why) and, in autonomous mode, nudges you to `/fix` or
  `/undo`. This is the cheap-ensemble reading of the whole thesis: two *pennies*
  models, one building and a different one cross-examining, catch what one model
  rubber-stamps. Pairs naturally with cheap-triage routing and the budget cap.
  Best with a different family on the same provider (e.g. write on `openai/...`,
  review on `anthropic/...` — one OpenRouter key).
- **`.env` just works.** A `.env` at the project root or cwd is now **auto-loaded
  at startup** (non-overriding, so a shell-exported var still wins) — no
  `export`, no restart. `/keys set <provider> [key]` captures a key for the
  session (hidden prompt if you omit it) and can persist it to `.env` (with a
  warning if `.env` isn't git-ignored). `/reload` re-reads it live. Key *names*
  are reported, values never printed.
- **Semantic windowing for large files (`_windowing.py`).** Truncation no longer
  drops the *tail* of a file — the end (a `__main__` guard, a class's later
  methods) is often where the load-bearing logic lives. `read_file` now accepts
  a `pattern` to window around the matching lines *and the enclosing
  function/class*; without one it keeps both the head and the tail. The same
  head+tail windowing replaces the old head-only byte-slice everywhere a big
  blob gets capped (auto-attached files, inline tool results, autonomous
  tool-result feedback). Every elision is marked, so nothing is *silently* lost.
- **Exploration budget for the autonomous loop.** After `read_cap` read-only
  tool calls in a turn (default 25; set `--read-cap`, `[agent] read_cap`, or
  `session.read_cap`), the agent is pushed to stop gathering context and produce
  its answer/edits. This is the guard against the "reads forever, answers never"
  failure where a strong model exhausts the budget on context-gathering alone.
- **Cheap-triage de-escalation (tiered models).** The throwaway "how hard is
  this task, 1-5?" routing call made for `effort=auto` can now run on a separate
  cheap model while the real reasoning stays on your capable one — keep a strong
  default at near-zero routing cost. Set it with `/triage <model>`,
  `--triage-model`, `[defaults] triage_model`, `ESSARION_TRIAGE_MODEL`, or
  `configure(triage_model=...)`.
- **`/reload` — hot-reload credentials/config.** Re-reads `.env` (project root +
  cwd) and `essarion.toml` without restarting, so a key you just added takes
  effect on the next task. Removes the one rough edge where a missing API key
  meant killing and relaunching the REPL. Key *names* are reported, never values.
- **Inline `@path` file references.** `@src/auth.py` / `@src/` at the prompt
  attach a file (and its sibling test) or a directory — an explicit, Gemini-style
  way to steer exploration that also works for extension-less files (`@Makefile`)
  the bare-path detector skips. E-mail addresses are not mistaken for paths.
- **`/triage`, `/commands`.** `/triage` shows/sets the cheap routing model;
  `/commands` lists every command (alias of `/help`).

### Changed

- **Budget enforcement now pre-estimates the next step and stops *before* it
  crosses the cap**, instead of detecting the overage after an in-flight call is
  already billed. It reserves headroom for a wrap-up: when the cap is reached the
  autonomous run **finalizes with a short, grounded summary of findings so far**
  (or a synthesized recap when there isn't even budget for that) rather than
  stopping silently with nothing written. A cap is only useful if you still get
  value when it's hit.
- **Sharper analysis prompts.** The reasoning system prompt now applies three
  structural lenses to non-trivial code — shared mutable state & concurrency,
  trust boundaries (shell/subprocess/untrusted input), and resource lifecycle —
  and the autonomous executor, on analysis/review tasks, deliberately sweeps the
  security- and concurrency-sensitive files (tool execution, subprocess/shell,
  shared global state, background/threaded code, raw-input paths), not just the
  entrypoints. Every claim must cite a file and, where possible, a symbol or
  line; output is kept dense and grounded rather than restating context.
- **`/model` validates credentials on switch.** Switching to a provider whose key
  isn't set warns *which* env var the route needs (and points at `/reload`),
  instead of failing cryptically on the next task. `/keys` uses the same map.
- **Footer surfaces more context** — reasoning effort and the git branch, next to
  model and cost.

## [0.3.6] - 2026-06-01

Code-intelligence release: give the model structural understanding of the
codebase (so it stops blind-grepping), robust structural edits, objective
edit-time feedback, and cross-tool conventions — plus a calmer, more honest
autonomous run. All zero-dependency (standard library only).

### Added

- **Repo map (Aider-style, zero-dep).** A ranked, token-budgeted skeleton of the
  codebase's most important symbols (classes/functions + signatures) is built
  with the stdlib `ast` (Python) / a regex def-table (JS·TS·Go·Rust·Ruby·Java·
  C/C++·PHP·Swift) and ranked with a pure-Python PageRank over the symbol
  def/ref graph. It's injected into the model's context each turn so it orients
  without reading every file. Honours the project's `.gitignore` automatically
  (via `git check-ignore`, with a graceful fallback when git is absent) so
  generated/vendored files don't pollute the map. Toggle with `[agent] repo_map`
  / `repo_map_chars` in `.essarion/config.toml`.
- **Code-intelligence tools.** `repo_map` (ranked overview), `outline <file>`
  (a file's symbols + signatures), and `find_symbol <name>` (go-to-definition +
  find-references across the repo) — far cheaper and more precise than grep.
  Also surfaced as slash commands for humans: `/map`, `/outline <file>`,
  `/symbol <name>`.
- **`edit_symbol` — AST-anchored edits.** Replace a whole function or class *by
  name* (`Class.method` supported), located via `ast` rather than fuzzy text
  matching. Refuses to write if the result wouldn't parse, so a structural edit
  can never leave the file broken.
- **Post-edit feedback (objective signals only).** After an edit, the tool
  result carries a `⚠` syntax/JSON/TOML parse error you just introduced (the
  cheapest reliability gate there is) and a `↔` *blast-radius* note listing the
  callers of any symbol you changed or removed — so you fix it now and check the
  dependents, instead of finding out later.
- **Zero-config diagnostics on edit.** When a fast, standalone checker is
  installed — `ruff`/`pyflakes` (Python), `ruby -c`, `php -l`, `shellcheck`,
  `luacheck` — its real diagnostics (undefined names, unused imports, lint) are
  auto-detected and folded into the edit result. On by default, no setup; silent
  when nothing's installed. Turn off with `[verify] lint_on_edit = false` or
  `ESSARION_NO_LINT_ON_EDIT=1`.
- **AGENTS.md & convention files.** The agent reads `AGENTS.md`
  (monorepo-nested, nearest-wins), plus `CLAUDE.md`, `.cursorrules`,
  `.windsurfrules`, and `.github/copilot-instructions.md`, and injects them as
  project conventions — instant interop with repos already set up for other
  agents.
- **`web_fetch`.** Fetch a URL and get its text (HTML reduced to readable text)
  for reading docs/changelogs/error pages — stdlib `urllib`, governed by the
  environment's network policy.

### Changed

- **Quieter todo checklist.** The live checklist now renders only when it
  actually advances: the full plan prints once, then each step shows just the
  line(s) that changed (a `☑` done + the next `▶` doing), and a re-sent
  identical list prints nothing. (The model is also told to call `update_todos`
  only when starting/finishing a step, not after every action.)
- **Edits show a diffstat, not the code.** A successful `apply_diff` now renders
  a compact `+added −removed` line-count summary instead of dumping the changed
  code; use `/diff` to view the actual change.
- **Quieter reasoning narration.** On a step that also takes an action, the
  model's "I'll now…" prose is shown as a single dim, truncated lead-in instead
  of a bright multi-line block, so the action lines dominate. A prose-only step
  (a direct answer) is still shown in full.

### Fixed

- **Resilient `apply_diff`.** When the snippet doesn't match verbatim, the edit
  now falls back to a whitespace/indentation-tolerant match (re-indenting the
  replacement to align with the matched block) instead of failing with "old
  text not found" and burning a step.
- **Failed commands no longer show a green ✓.** A shell command that runs but
  exits nonzero is now marked ✗ and recorded as failed.
- **`open <file>` works on Linux** — it's translated to `xdg-open` (a macOS-ism
  models reach for) when that's available.

## [0.3.5] - 2026-06-01

The Claude-Code-parity release. The autonomous agent gains **conversation
memory** (it remembers what it built and what's running), an interactive
**`ask_user`** tool, a **live todo checklist**, **permission guardrails** with a
dangerous-command denylist, **prompt caching** across multi-step turns, a live
**"Thinking…"** spinner, **collapsed** Claude-Code-style output, **secret
redaction**, and **no spending cap** by default.

### Added

- **Interactive `ask_user` tool.** Mid-task the agent can ask you multiple-choice
  questions (Claude-Code style): up to 4 options plus an auto-added "Other (type
  your own)", and several questions in a row. Answer by number or type your own.
  Non-blocking in pipes/CI — with no TTY it proceeds with sensible defaults.
- **Conversation memory in the autonomous loop.** Every turn now carries a recap
  of prior turns and live background-process state, so follow-ups are answered
  precisely from memory instead of groping the filesystem:
  - the **concrete actions** of the most recent turn ("Created index.html",
    "Ran ls -l", "Started Simple HTTP Server") — for "what did you just do?";
  - **running background processes** with an inferred reachable URL
    (`http://localhost:8000`) — for "what's running?" / "how do I reach it?";
  - recently-finished background tasks with their exit status.
- **Live "Thinking…" spinner** (the rotating `|/-\` bar) during every model
  call, so a step never looks frozen while the model works.
- **Permission policy + guardrails.** The autonomous executor now screens every
  action: reads are free, writes/edits are allowed (undoable), and shell
  commands are checked against a built-in dangerous-command list — catastrophic
  ones (`rm -rf /`, `mkfs`, fork bombs, `dd of=/dev/…`) are **always refused**,
  risky ones (`sudo`, `git push --force`, `rm -rf …`, `curl … | sh`) prompt for
  approval (and are denied when there's no interactive user). Configure via
  `[permissions]` in `.essarion/config.toml` (`shell`/`write`/`delete` =
  `allow|ask|deny`, plus `allow`/`ask`/`deny` regex lists). `/yolo` downgrades
  "ask" to "allow" — but never the catastrophic list.
- **Live todo checklist.** The agent maintains a task list via an `update_todos`
  tool and renders it with state glyphs (`☐` todo, `▶` doing, `☑` done) as it
  works, so long autonomous runs stay legible. Stored on the turn for memory.
- **Secret redaction in output + memory.** API keys / tokens / private keys are
  stripped from rendered tool output and from the conversation memory that rides
  along in the prompt.

### Performance

- **Prompt caching across multi-step turns.** The executor's system prompt is
  reordered so the stable prefix (protocol + tool manifest) comes first for
  cross-turn cache reuse, and the Anthropic provider now also caches the
  *growing message history* (an ephemeral breakpoint on the latest message), so
  each step reuses prior steps' cached tokens instead of re-billing them. Cache
  hits are now shown in the usage line and footer (`385 tokens (210 cached)`).

### Changed

- **No spending cap by default.** The budget is off (`0`) unless you set one —
  the status line just meters tokens + cost (no "`/ $1.00`"). `/budget` shows
  spend and (interactively) prompts for a cap; `/budget <amount>` or `--budget`
  sets one; `/budget off` clears it.
- **Collapsed, Claude-Code-style output.** Each action is one compact, faded line
  — `Created index.html`, `Edited styles.css` (+ a small diff), `Ran npm test`
  (+ a short output tail) — instead of dumping full file contents and a result
  panel per call. The end-of-turn full diff is replaced by a one-line change
  summary (`/diff` for the detail).
- **Planning is silent in autonomous mode** — computed internally and fed to the
  executor, with no plan/tradeoffs/verdict wall and no "build" header. A question
  (as opposed to a build task) is answered directly in prose, without running
  tools. Long answers are shown in full (no 400-char clip).
- Refreshed the banner tagline/tips to reflect autonomous-by-default.

### Fixed

- The agent no longer invents placeholder targets (e.g. running `curl`/`ping`
  against `example.com`) to answer a question — it answers from context, or asks.

## [0.3.4] - 2026-06-01

The autonomous release. The CLI agent is now **agentic by default** — like
Claude Code or Codex, it plans internally and then creates/edits/deletes files
and runs shell commands in a loop until the whole task is done, with **no
plan-approval gate** and **no single-file "apply" step**. Multi-file scaffolds,
"run the tests and fix failures", and full end-to-end tasks now just work from a
plain prompt. The classic plan → approve → hand-apply flow is one keystroke
away (`/auto off` or `--plan-first`).

### Changed

- **Autonomous mode is now the DEFAULT.** A bare task (in the REPL, one-shot
  `--task`, or a custom slash command) now runs the Claude-Code / Codex-style
  agentic loop: the agent plans *internally*, then creates/edits/deletes files
  and runs commands directly on disk, looping until the whole task is done —
  no "approve this plan?" gate and no "apply to which file?" prompt. Previously
  the default was the plan-first flow that emitted a single code blob to apply
  by hand, which made the agent feel like it "did one file and stopped".
- **Removed the plan-approval gate from the autonomous turn.** Planning is now
  internal; execution proceeds straight through. The classic
  plan → approve → hand-apply flow is still available via `/auto off` or the
  new `--plan-first` (`--no-auto`) flag.

### Added

- **`--plan-first` / `--no-auto`** CLI flag to opt out of autonomous mode.
- **`run_task()`** — a single mode-aware dispatcher the REPL, the one-shot CLI,
  and custom slash commands all funnel through, so the autonomous/plan-first
  choice is honored everywhere.

### Improved

- The autonomous executor's system prompt now explicitly tells the agent to
  build the **complete** solution (all files, configs, entry points, tests),
  run/verify its work, and not stop after a single file.
- The loop **nudges** the model to keep going (up to twice) when a step
  produces neither a tool call nor `<done>`, instead of ending the task on a
  transient prose-only step.
- Running narration strips structural reasoning tags so it reads like clean
  prose rather than raw XML.

## [0.3.3] - 2026-06-01

### Added

- python -m essarion_build now launches the agent as a PATH-independent
  fallback, calling the same entry point as the essarion /
  essarion-build console scripts.

## [0.3.2] - 2026-06-01

The agentic release — everything since the published 0.3.1. Autonomous "auto"
mode, lifecycle hooks, a Claude-Code-style CLI, real-model tool-call robustness,
the `/goal` no-stop command, and **computer use** (browser + desktop, reactive
and expectation-checked, with the model able to *see* the screen).

- **`/goal <task>`** — pursue a goal autonomously until it's accomplished:
  pre-approves the plan and keeps working across step caps, round after round,
  until the agent emits `<done>` or the budget runs out. No stopping to ask.
  e.g. `/goal run all tests and fix any failures`.

### Computer use — vision, cross-platform, OCR, cloud
- **Vision seam (the model SEES).** Message content can be a list of neutral
  blocks (`text_block` / `image_block`); each provider renders them to its
  native multimodal shape (OpenAI/OpenRouter, Anthropic, Gemini), and a plain
  string still flows through unchanged. `browser_screenshot` / `desktop_screenshot`
  now capture the image and the autonomous loop attaches it to the next message —
  but only on vision-capable models (otherwise it notes the capture, never sends
  blind). Verified live: a real model read text straight from image pixels.
- **Cross-platform desktop input.** Input lives behind a per-OS `InputDriver`:
  `X11Input` (Linux/XTEST, the CI-tested reference), `QuartzInput` (macOS,
  CoreGraphics), `WindowsInput` (Windows, ctypes SendInput). Capture (mss) and
  the screen-diff were already cross-platform. (macOS/Windows drivers are
  written from the documented APIs but not exercised by this Linux CI.)
- **Desktop OCR.** With `pytesseract` + a `tesseract` binary, the desktop tier
  reads on-screen text, so text expectations ("'Welcome back' appears") resolve
  instead of being "unclear".

### Cloud (essarion_build_cloud)
- The worker can drive the headless-browser tier via `ESSARION_COMPUTER_USE=1`
  (desktop control is intentionally not offered in a remote container).

### Verified
- 579 passing; real X11 under Xvfb (move/capture/diff + OCR + full agent loop);
  live vision read-through; cloud worker driving a real headless browser.

### Computer use — desktop tier (control the real machine)

Computer use extends from the browser to
the *real machine*: the agent can move the mouse, type, press keys, scroll, and
screenshot the actual screen, observing changes via screen diffing. Same
reactive spine (observe→digest→act), same expectation-checked acting.

### Added
- **`DesktopBackend`** — real X11 control: input via the XTEST extension (the
  mechanism xdotool uses), screen capture via mss, structured so macOS (Quartz)
  and Windows (SendInput) backends slot in behind the same interface.
- **Screen-diff observer (`ScreenDiffer`)** — the universal floor: downsample
  each frame to a coarse colour grid, diff consecutive frames, and report the
  changed regions (with pixel centres) as events. Pure grid math — no display
  needed to test it — works on any app/OS including canvas/Electron.
- **`desktop_*` tools** — `desktop_move/click/type/key/scroll/observe/`
  `screenshot`, each act→observe→digest→`expect=` like the browser tools.
  Expectations now also understand "the screen changes" (useful where there's
  no text to match).
- **`FakeDesktopBackend`** and the screen-diff core are dependency-free and
  importable for building your own desktop automation on the SDK.

### Safety
- Desktop control is **explicit-opt-in only** (`--desktop` / `/desktop`) — never
  activated from phrasing, because it can do anything you can. `/desktop`
  requires typing an acknowledgement. The protocol treats on-screen text as
  **untrusted** (prompt-injection) and forbids destructive/credential/purchase
  actions unless unambiguously requested. Run it on a contained display/VM.

### Verified
- Real X11 under Xvfb: absolute pointer move reflected by the server, real
  screenshot, and the autonomous executor driving a real interactive app — the
  agent's click flipped a real button from "Submit" to "CLICKED!", confirmed by
  the screen-diff and the expectation check. 568 passed (12 new).

### Notes
- Desktop deps live in the new `[desktop]` extra (python-xlib, mss, Pillow).
- The vision tier (model *sees* screenshots) still needs the multimodal seam —
  it's the next additive layer; the text/screen-diff tier works on any model.

### Computer use — browser tier (reactive, text-first, opt-in)

The agent can drive a real
browser to test apps, pages, and flows (start a dev server in the background,
then navigate and interact). Built on one principle: the environment observes
and emits structured events; the model acts on a compact *digest* only when
something meaningful changes — it is never a continuous watcher.

### Added
- **`essarion_build.computer`** — an importable toolkit (like the reasoning
  loop): `reduce_events`/`Digest` (the reducer — the heart), `BufferedObserver`,
  `Backend`/`FakeBackend`/`PlaywrightBackend`, the `browser_*` action tools,
  and `parse_expectation`/`check_expectation`. Build your own reactive browser
  tools on top of it.
- **Reactive browser tier** — a CDP/Playwright tap (console, network failures,
  navigation, dialogs, DOM mutations via a page-side queue) normalized and
  reduced into a budget-sized digest returned by every action. Catches the
  transient changes a screenshot-only agent misses.
- **Expectation-checked acting** ("reason deep, act fast") — every action takes
  an optional `expect=` one-line prediction; the environment verifies it against
  the digest + page text deterministically (no extra model call) and prepends
  ✓/✗. Forces the model to reason about consequences in the same tokens it acts
  with, and only re-engages it when reality diverges.
- **Opt-in gating** — off by default. Enable via `--computer-use`, `/computer`,
  or an unambiguous request ("use the computer", "open a browser and …"). The
  `[computer]` extra installs Playwright; the reducer/observer/expectations are
  pure-Python and dependency-free.
- **Vision check** — `browser_screenshot` (and `/computer`) detect when the
  model can't see images and prompt you to switch instead of sending blind.

### Changed
- `tool_manifest()` already exposes exact signatures (0.3.2) — the computer
  tools rely on it so the model uses `selector=`/`url=` correctly.

### CLI, autonomy & robustness

A coding-agent UX pass: a persistent Claude-Code-style chat input, a friendlier
launch story, and verified end-to-end autonomous execution. (Also in this
release: autonomous "auto" mode + the agentic executor + `delete_file`, and
real-model tool-call parsing — XML-child args + manifest signatures — so live
models reliably write multi-line files and call tools.)

### Added
- **Persistent chat REPL input (`prompt_toolkit`).** A fresh input line returns
  after every turn — no need to re-invoke `essarion` or pass `--task`. Includes
  command history that survives across turns and sessions (↑/↓), history-based
  autosuggestions, slash-command completion, a placeholder, and a hint toolbar.
  Falls back to a plain Rich prompt for pipes/CI or if prompt_toolkit is absent.
- **Lifecycle hooks** (`pre_tool`/`post_tool`/`user_prompt`/`session_start`/
  `stop`) configured in `.essarion/config.toml`; `/hooks` lists them.
- **Redesigned welcome screen**: block wordmark with a `>` prompt and a
  "Tips for getting started" box.

### Changed
- **Bare `essarion` *and* `essarion-build` now launch the REPL.** Both console
  scripts share one dispatcher; subcommands still work, free text / `--task`
  runs one-shot.

### Fixed
- **Multi-word tasks no longer truncate to the first word.** `--task please
  code a website` (unquoted) and bare `essarion fix the failing test` are
  joined into the full task instead of erroring on "unrecognized arguments".

### Verified
- The autonomous loop genuinely **writes code, runs the tests, observes the real
  failure, fixes it, re-runs, and finishes** — proven by a reactive test that
  branches on live subprocess output (`tests/test_agent_exec_verify.py`).

## [0.3.1] - 2026-05-29

Usability fixes for the built-in test stub, from a v0.3.0 field report. No
breaking changes: explicitly constructed stubs keep their strict, scripted
behavior; only stubs selected *by name* gain auto-respond.

### Fixed
- **`configure(provider="stub")` / `--provider stub` now work out of the
  box.** Previously the first call raised
  `ProviderResponseError: StubProvider exhausted: no more scripted responses`,
  because the registry-built stub had an empty queue and a reasoning loop
  makes several provider calls (plan, self-check, draft, …). A stub selected
  by name is now created with `auto_respond=True` and synthesizes a
  well-formed response for whichever reasoning phase is asking — across every
  effort level (`quick`/`standard`/`deep`/`max`/`auto`) and for the sync,
  async, and CLI surfaces. No scripting, no API key, no network.
- **`Conversation.reason()` / `.generate()` accept the `_runtime` test seam.**
  `essarion_build.testing` documents that `run_with_stub(stub, conv.reason,
  task)` works, but it raised `TypeError: unexpected keyword argument
  '_runtime'`. The kwarg is now threaded through (mirroring the top-level
  `reason()` / `generate()`), restoring the documented contract.
- The `StubProvider` / `AsyncStubProvider` "exhausted" error is now
  actionable: it explains that a loop makes several calls and points at
  `responses=[...]` / `push(...)` and `auto_respond=True`.

### Added
- `StubProvider(auto_respond=True)` / `AsyncStubProvider(auto_respond=True)`:
  serve scripted responses first, then auto-answer once the queue is empty.
  Auto replies are phase-aware (read from the prompt's requested tags) and
  carry a deterministic, non-zero usage estimate.

## [0.3.0] - 2026-05-29

The big "SDK + CLI coding agent" release. v0.2 was a focused
`reason()`/`generate()` primitive; v0.3 turns essarion-build into a
full toolkit AND ships a `essarion` CLI coding agent on top — all via
`pip install essarion-build`.

### Added — adaptive reasoning effort (headline)
- New `effort` parameter on `reason()` / `generate()` / `areason()` /
  `agenerate()` / `generate_json()` / `agenerate_json()`: `quick` (1
  call), `standard` (2, default), `deep` (4 — adds a critique→revise
  round on the plan), `max` (6 — adds an alternative-plan→synthesis
  round), and `auto` (a tiny triage call sizes the task 1–5 and routes
  to quick/standard/deep).
- The refinement steps operate on the *plan* (short), so deeper effort
  stays cheap relative to drafting code. Triage caps its own output.
- Output-gated escalation: in `auto`, when the model's own self-check
  flags "do not ship", one bounded critique→revise round is spent
  rather than returning a flagged plan (adaptive on the output).
- `Reasoning.effort` / `Generation.reasoning.effort` report the depth
  actually used (matters for `auto`).
- `configure(effort=...)` global default; `ESSARION_EFFORT` env seed.
- `approx_reason_calls()` / `approx_generate_calls()` helpers and
  `EFFORT_LEVELS` / `VALID_EFFORTS` exported.
- Strengthened the system prompt with an explicit reasoning method
  (work backward from failure modes; find the load-bearing decision;
  distrust the first idea; smallest correct change; never invent APIs).
- The `essarion` agent defaults to `effort="auto"`, announces the
  resolved depth per turn, and exposes `/effort`, `--effort`, and the
  `[agent].effort` project-config key.

### Added — agent: planning UX

- **Pre-flight cost prediction.** Each turn prints a projected USD cost
  before the plan call so the user sees the spend before paying.
- **`/cost`** session ledger (per-turn + total), or `/cost <path>` to
  estimate against a hypothetical context loading that path.
- **`/whoami`** one-screen status: project + sessions dir + model +
  skills mode + budget + memory facts + bg tasks running.
- **`/stream [on|off]`** toggles streamed draft output (token-by-token
  via `stream_generate`). Buffered phases stay buffered; the draft
  shows code as it's written.
- **`/ask <question>`** runs `reason()` only — quick Q&A without paying
  for a draft.
- **Categorized `/help`.** Commands grouped by area (session, planning,
  workflows, models & cost, skills & memory, project & files, changes
  & verify, background, safety). `/help <substring>` filters.

### Added — agent: project memory

- `<project>/.essarion/memory.md` auto-injected into every turn as a
  `memory` custom skill.
- `/remember <fact>` appends; `/remember` alone prints current memory.
- `/forget <pattern>` removes matching facts; `/forget all` wipes.
- Per-project; falls back to `~/.essarion/memory.md` outside a project.

### Added — agent: verification + change tracking

- `/verify [cmd]` runs the project's check command (auto-detects pytest /
  npm test / cargo test / go test / make test, or reads
  `[verify].check_cmd` from project config).
- `[verify].auto = true` in `.essarion/config.toml` makes the agent
  auto-run the check after every applied change. Failures surface PASS
  / FAIL inline with the output panel.
- `/diff` shows a unified diff of every file the agent changed this
  session (multiple edits to the same file collapse into the net diff).
- `/undo` reverts the most recent change (create → delete, modify →
  restore prior content).
- `/commit [msg]` git-adds touched files and creates a commit.

### Added — agent: inline tool execution during the plan phase

- The model can emit `<tool_call name="...">...</tool_call>` inside its
  plan. The agent runs read-only tools (read_file, grep, glob,
  list_dir, find_files), folds the results back as context notes, and
  re-plans. Up to 3 rounds.
- Side-effect tools (write_file, run_shell, apply_diff, start_background,
  kill_background) are blocked from inline execution — those keep going
  through the user-approved apply step.
- A short manifest is injected into every turn so the model knows what
  syntax to use.

### Added — agent: workflow shortcuts

- `/review`, `/fix`, `/tests`, `/refactor`, `/docs`, `/security`,
  `/perf`, `/explain`, `/pr` route to the matching `workflows.*`
  function.
- Custom commands: drop `<name>.md` in `<project>/.essarion/commands/`
  to create `/<name>` with `{args}` substitution.

### Added — agent: project folders
- `essarion init [<path>]` creates `<path>/.essarion/` with starter
  `config.toml`, per-project `sessions/` directory, and a `.gitignore`
  that ignores stored sessions.
- `essarion` now auto-detects the project root by walking up looking
  for `.essarion/`, then `.git/`, then `pyproject.toml` / `package.json`
  / `Cargo.toml` / `go.mod` / `pom.xml` / `build.gradle` / `Gemfile`.
  The sandbox CWD anchors to the project root unless `--cwd` overrides.
- Per-project `<root>/.essarion/config.toml` is loaded at startup;
  `[defaults]` overrides the SDK defaults and `[agent]` sets
  `budget` / `skills_mode` / `escalate_model`.
- Sessions persist to `<root>/.essarion/sessions/{id}.json` when a
  `.essarion/` directory is present; otherwise they go in the global
  `~/.essarion/sessions/` like before. `--resume <id>` looks in both.
- New banner row "project … (detected by .essarion/)" identifies what
  triggered the project anchor.

### Added — background tasks
- `essarion_build.agent._background` ships a `TaskManager` that runs
  shell commands via `subprocess.Popen` with non-blocking
  stdout/stderr drained into bounded ring buffers (500 lines per
  stream per task). Tasks run in parallel and can be polled, tailed,
  waited on, or killed.
- New slash command `/bg`:
  - `/bg <cmd>`              start a task
  - `/bg detached <cmd>`     start one that survives REPL exit
  - `/bg`                    list every task with status table
  - `/bg show <id>`          status + recent output of one task
  - `/bg wait <id> [secs]`   block until done
  - `/bg kill <id>`          terminate
  - `/bg clear`              forget finished tasks
- New tools (registered with the SDK's `tools.register_tool` surface,
  so the model can also call them):
  `start_background(cmd, name=, detached=)`,
  `check_background(id, tail=)`,
  `wait_background(id, timeout_seconds=)`,
  `kill_background(id)`,
  `list_background()`.
- Completion notices: when a task finishes between turns, the next
  REPL prompt prints a single `[bg] [abc123] cmd → done (exit 0, 1.2s)`
  notice so the user never has to ask.
- Footer status line gains a `bg N running` indicator when any tasks
  are alive.
- On `/quit`, the manager terminates every non-detached task using
  SIGTERM → grace → SIGKILL via the child's process group, so e.g.
  a `npm run dev` and its spawned `node` child both die cleanly.

### Added — discovery tools
- `find_files(pattern, path=".")` — fnmatch on file name, skips VCS
  and node_modules / build dirs.
- `glob(pattern)` — path-shaped glob from the sandbox root, supports
  `**`.

### Tests
- Suite grew from 284 to 318 cases. New files:
  `test_agent_project.py`, `test_agent_background.py`,
  `test_agent_tools_discovery.py`.

### Added — `essarion` CLI coding agent

A new module, `essarion_build.agent`, ships an interactive coding agent
on top of the SDK. Bare `essarion` launches the REPL; `essarion
<subcmd>` falls through to the existing CLI subcommands.

Differentiators vs Claude Code / Codex / Aider / Cursor:

- **Plan-first interactivity.** The SDK's `reason()` runs first; the
  user sees the plan in a panel and can approve / edit / cancel
  *before* any code-generation call is paid for.
- **Live token-budget meter.** Per-session USD budget; live cost
  readout in the footer; per-turn cost line. Makes the
  amplification-savings story visible.
- **Smart skill selection.** A tiny keyword-based picker chooses 3-5
  relevant skills out of 54 instead of loading them all. Big context
  savings.
- **Multi-model arbitrage.** `--escalate <bigger-model>` makes the
  agent retry with a stronger model only when the cheap-model
  selfcheck rejects the draft.
- **Reasoning-trace persistence.** Sessions saved to
  `~/.essarion/sessions/{id}.json`. Replay with `essarion --resume <id>`.
- **Workflow-prefixed shortcuts.** `review: src/auth.py`,
  `fix-bug: payment hangs`, `tests: parse_jwt`, `refactor: …`, `docs:
  …`, `security-review: …`, `perf-review: …`, `pr-description: …`,
  `explain: …` route to the matching `workflows.*` function.

Visual polish via `rich`: panels, syntax-highlighted code, live status
spinners, color-coded phase headers (plan = magenta, draft = cyan,
selfcheck = yellow), persistent footer with model + budget + token +
turn counts.

Slash commands inside the REPL: `/help`, `/quit`, `/clear`,
`/budget [N]`, `/model <p>/<m>`, `/escalate <m>`, `/skills
[auto|all|none]`, `/cd <path>`, `/pwd`, `/history`, `/save`, `/load`,
`/export`, `/yolo`, `/version`.

CLI flags: `--task`, `--cwd`, `--budget`, `--provider`, `--model`,
`--escalate`, `--skills {auto,all,none}`, `--resume <id>`,
`--max-tokens`.

### Added — agent sub-modules

- `essarion_build.agent._loop` — the plan-first turn loop (uses
  `reason()` + `generate()` + `workflows.*` from the SDK)
- `essarion_build.agent._session` — Session state, TaskTurn,
  `estimate_cost_usd()`, persistence to `~/.essarion/sessions/`
- `essarion_build.agent._skill_picker` — keyword-based skill selection
- `essarion_build.agent._tools` — sandboxed file/grep/shell tools
  (read_file, list_dir, grep, write_file, apply_diff, run_shell)
- `essarion_build.agent._ui` — rich-based panels, prompts, footer
- `essarion_build.agent._commands` — slash-command dispatcher
- `essarion_build.agent._theme` — color theme + ASCII banner
- `essarion_build.agent.main` — entry point + top-level dispatcher

### Added — `essarion` console script

A new entry point in `pyproject.toml`: `essarion =
essarion_build.agent.main:main_or_subcommand`. Bare `essarion` runs
the agent REPL; `essarion <subcmd>` (skills / providers / workflows /
version / estimate / reason / generate) passes through to the existing
`essarion-build` CLI.

The `essarion-build` console script is preserved unchanged.

### Added — dependencies
- `rich>=13.7` (TUI, syntax highlighting, panels, progress)

### Tests
- Suite grew from 229 to 284 cases. New files: `test_agent_skill_picker.py`,
  `test_agent_tools.py`, `test_agent_session.py`, `test_agent_loop.py`,
  `test_agent_commands.py`, `test_agent_main.py`.

### Added — SDK expansion (foundation for the agent)

### Added — providers
- **OpenAI** (`provider="openai"`) — direct, no OpenRouter hop. Reads `OPENAI_API_KEY`.
- **Gemini** (`provider="gemini"`) — Google Gemini direct via REST. Reads `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
- **Ollama** (`provider="ollama"`) — local OSS models. No key required. Reads `OLLAMA_BASE_URL` (default `http://localhost:11434`).
- **Stub** (`provider="stub"`, also `StubProvider` / `AsyncStubProvider`) — in-memory scripted responses for users' own tests. Re-exported under `essarion_build.testing`.
- `register_provider(name, factory)` / `unregister_provider(name)` for user-defined providers.
- `list_providers()` enumerates built-in plus custom providers.

### Added — async API
- `areason()` / `agenerate()` mirror the sync entrypoints; awaitable.
- `AsyncLiteRuntime`, `AsyncProvider` protocol, `AsyncRuntime` protocol.
- Async transports for every built-in provider.
- `select_async_runtime()`, `build_async_provider()`, `register_async_provider()`, `unregister_async_provider()`.

### Added — streaming
- `stream_reason()` / `stream_generate()` yield `ReasoningEvent` objects: `phase_start`, `token`, `phase_end`, `usage`, `complete`.
- `StreamingProvider` protocol; the Anthropic provider implements native token streaming via the SDK's `messages.stream`. Buffered providers emit one `token` event per phase, so the UI shape is identical either way.
- `StreamChunk` carries the partial text and (on the final chunk) the usage for the call.

### Added — multi-turn
- `Conversation` class with persistent `Context`, ordered `history` of `ConversationTurn`, `usage` aggregation, and `fork()` for branching.
- Each turn's plan + verdict is auto-summarized into the context's `notes` so subsequent turns can refer back without restating.

### Added — high-level workflows
- `essarion_build.workflows.review()` / `fix_bug()` / `write_tests()` / `refactor()` / `docs()`.
- Each workflow auto-picks a sensible default skill set, frames the task, and runs the loop.
- Accept `context=`, `repo=`, `diff=` kwargs plus any `reason()`/`generate()` kwargs.

### Added — batching
- `batch_reason()` / `batch_generate()` run many `areason()` / `agenerate()` calls concurrently with a configurable `max_concurrency` semaphore.
- `BatchResult` exposes `.ok` and `.errors`. One task's failure doesn't fail the rest.
- `run_batch(coro)` helper to call a batch from sync code.

### Added — Context upgrades
- `add_repo()` now accepts `include=` / `exclude=` (gitignore-style globs) and `max_files=`.
- `add_file(path)` for loading a single focused file.
- `with_custom_skill(name, body)` injects a project-specific skill.
- `with_skills_dir(path)` loads every `*.md` under a directory as a custom skill.
- `add_diff(body, title=...)` attaches a focused diff (rendered as `<diffs>` in the prompt block).
- `add_note(text)` pins a one-sentence reminder (rendered as `<notes>`).
- `total_chars()` and `estimate_tokens()` for pre-flight budgeting.
- New `Diff` model class.

### Added — response cache
- `ResponseCache(root)` — on-disk, content-addressed (SHA-256 of provider, model, system, messages, max_tokens).
- `CachingProvider(inner, cache, provider_name=...)` wraps any provider; identical calls are served from disk.
- Cache exposes `.hits`, `.misses`, `.clear()`.

### Added — CLI
- `essarion-build` console entry point.
- Subcommands: `skills`, `providers`, `version`, `estimate`, `reason`, `generate`.
- Flags: `--repo`, `--doc`, `--skill`, `--no-skills`, `--diff`, `--provider`, `--model`, `--max-tokens`, `--json`, `--stream`.
- Reads tasks from stdin when the positional argument is `-`.

### Added — validators
- `essarion_build.validators` module: cheap, deterministic post-generation checks (no model calls).
- `validate_python()` flags syntax errors, bare `except`, `eval`/`exec`, mutable defaults, TODO/FIXME markers.
- `validate_json()` enforces RFC 8259.
- `validate_unified_diff()` sanity-checks unified diff headers.
- `register_validator(kind, fn)` for user-defined checks. `list_validators()` enumerates.

### Added — skills (+16)
- `rust_idioms`, `go_idioms`, `sql_idioms`
- `react_patterns`, `state_management`
- `accessibility`, `internationalization`
- `caching`, `microservices`, `event_driven`
- `feature_flags`, `migrations`, `release_engineering`, `incident_response`
- `llm_integration`, `dx`

### Added — testing helpers
- `essarion_build.testing` re-exports `StubProvider`, `AsyncStubProvider`, plus `run_with_stub()` and `arun_with_stub()` convenience helpers.

### Added — runtime exposure
- `LiteRuntime`, `AsyncLiteRuntime`, `Runtime`, `AsyncRuntime`, `select_runtime`, `select_async_runtime`, `build_provider`, `build_async_provider` are now re-exported from the package root.

### Changed
- Default classifier bumped to `Development Status :: 4 - Beta`.
- README rewritten end to end. Architecture diagram up top; provider table covers all six; workflows / streaming / async / batching / conversation / cache / CLI / validators all documented with runnable examples.
- `pyproject.toml` adds `[project.scripts]` for the `essarion-build` CLI, adds `pytest-asyncio` to the test extras, sets `asyncio_mode = "auto"`.

### Added — structured output
- `generate_json(task, schema=...)` / `agenerate_json(...)` — generate a JSON object that validates against a Pydantic model or a raw JSON schema dict. One automatic repair pass on validation failure. `SchemaValidationError` if even the repair pass fails.
- Re-exported `SchemaValidationError` from the package root.

### Added — evaluation harness
- `essarion_build.evals.EvalCase`, `Score`, `CaseResult`, `Report`.
- `run_eval(cases, runner, scorer)` runs every case, scores, aggregates token usage.
- Built-in scorers: `exact_match`, `contains_all`, `keyword_overlap`.
- `Report.delta(baseline)` returns regressed/improved lists for CI gates.
- Re-exported as `essarion_build.evals`.

### Added — context compaction
- `compact(ctx, max_tokens=N)` trims repo files then docs until the context fits.
- `truncate_files(ctx, max_chars_per_file=N)` caps individual file bodies with a `(truncated)` marker.
- `keep_only_files(ctx, patterns=[...])` filters repo files by fnmatch glob.
- All return a new Context — the input is untouched.
- `Context.merge(other)` unions every section; repo files de-dup by path with newest-wins.

### Added — telemetry
- `configure_telemetry(on_event=, enabled=)` wires a user callback for SDK events.
- Events: `loop_start`, `phase_call`, `phase_done`, `tag_repair_attempt`, `tag_repair_failed`, `loop_done`.
- Buggy user callbacks are swallowed so they can never break the loop.

### Added — prompt overrides
- `configure_prompts(system=, plan=, draft=, selfcheck_reason=, selfcheck_generate=)` for teams that want their own house voice.
- `reset_prompts()` restores defaults.

### Added — tools (model-side)
- `register_tool(name, description=)` decorator.
- `run_tools_in_plan(text, allow=)` evaluates `<tool_call>` tags in arbitrary text, replacing them with `<tool_result>` (or `<tool_result error="true">`).
- `tool_manifest()` prints a one-line summary for injection into Context.
- Provider-agnostic by design — works on every backend.

### Added — pytest plugin
- `essarion_build.pytest_plugin` provides fixtures: `essarion_stub`, `essarion_async_stub`, `essarion_runtime`, `essarion_async_runtime`, `essarion_context`, `essarion_skills`, `isolated_prompts`, `isolated_telemetry`, `isolated_providers`.

### Added — auth
- `essarion_build.auth.from_env(*providers)` reads provider env vars and returns a `Credential` for `configure()`.
- `from_platform_api(token)` still NotImplementedError, but now rejects empty/whitespace tokens with ValueError so typos are distinguishable from "not shipped yet".

### Added — workflows (+4)
- `security_review()` — threat-model-shaped review with CWE/OWASP refs.
- `performance_review()` — hot-path analysis with expected-payoff estimates.
- `write_pr_description()` — generates a PR body (summary, why, what, test plan, risk).
- `explain_code()` — 3-layer explanation (1 sentence / 5 sentences / full walkthrough).

### Added — skills (+21 total, 42 in v0.3)
- `rust_idioms`, `go_idioms`, `sql_idioms`
- `react_patterns`, `state_management`
- `accessibility`, `internationalization`
- `caching`, `microservices`, `event_driven`
- `feature_flags`, `migrations`, `release_engineering`, `incident_response`
- `llm_integration`, `dx`
- `dependency_injection`, `cloud_infra`, `kubernetes`, `code_style`, `code_smells`

### Added — CLI subcommands
- `essarion-build workflows` lists bundled workflows with their docstrings.

### Added — docs and examples
- `examples/` — 8 runnable scripts (quick start, workflows, streaming, async batch, conversation, telemetry, custom provider, cache).
- `docs/COOKBOOK.md` — 20 runnable recipes covering every public surface.
- `docs/ARCHITECTURE.md` — two-page internal-structure tour.

### Added — CI
- `.github/workflows/ci.yml` matrix over 3.11/3.12/3.13 + CLI smoke job + build+twine check.

### Tests
- Suite grew from 42 to 192 cases. New files: `test_async_api.py`, `test_streaming.py`, `test_context_extras.py`, `test_conversation.py`, `test_cache.py`, `test_workflows.py`, `test_cli.py`, `test_validators.py`, `test_batch.py`, `test_telemetry.py`, `test_prompts.py`, `test_tools.py`, `test_pytest_plugin.py`, `test_auth.py`, `test_evals.py`, `test_compaction.py`, `test_schemas.py`.

## [0.2.0] - 2026-05-28

### Added
- Tag-repair pass: if a required `<plan>`/`<tradeoffs>`/`<verdict>`/`<code>`/`<defense>` tag is missing from a model response, the runtime asks once for just the missing tag(s) before raising.
- Typed provider exceptions: `ProviderAuthError` (HTTP 401/403), `ProviderRateLimitError` (HTTP 429), `ProviderHTTPError` (other non-2xx and network failures), `ProviderResponseError` (unparseable 2xx), and `ReasoningFormatError` (required tags still missing after the repair pass).
- Usage tracking: `Reasoning` and `Generation` carry a `Usage(prompt_tokens, completion_tokens, total_tokens, cached_tokens)` field aggregated across every provider call in the loop, including any repair retries.
- Per-call `max_tokens` kwarg on `reason()` and `generate()` (was previously global-only via `configure()`).
- Exponential-backoff retry (up to 2 retries) on HTTP 429, 5xx, and connection errors before surfacing the typed exception.

### Fixed
- `_OpenRouterProvider` no longer leaks `httpx.Client` instances — the client is now created per-call inside a context manager.

### Changed
- README rewritten to document usage tracking, per-call `max_tokens`, tag-repair behavior, and the typed-exception table.
- **Breaking:** `Provider.complete()` now returns `ProviderResponse(text, usage)` instead of `str`. Only affects users who wrote a custom `Provider`.

### Tests
- Suite grew from 26 to 42 cases. Added coverage for tag repair (happy path, failed repair, no-repair-needed), usage arithmetic and aggregation, per-call `max_tokens` override, and HTTP error mapping / retry behavior via `httpx.MockTransport`.

[Unreleased]: https://github.com/hapi-developer/essarion_build/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/hapi-developer/essarion_build/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.3.0
[0.2.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.2.0
