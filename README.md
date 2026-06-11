# essarion-build

A **BYOK reasoning amplification SDK + CLI coding agent**, by Essarion. Bring your own model provider; `essarion-build` provides the reasoning loop, the grounding context, the bundled software-development skills, and the structured outputs. The CLI agent gives you an interactive, **autonomous (agentic) coding experience by default** — like Claude Code or Codex, it plans internally and then creates/edits/deletes files and runs commands in a loop until the task is done — powered by the same SDK. A `/auto off` (plan-first) mode is one keystroke away when you want a checkpoint.

`essarion-build` is not a wrapper for any single LLM. It is a deliberate **plan → draft → self-check** pipeline that turns *whatever model you wire in* into a more thoughtful coder. The default is tuned to amplify **cheap** models — making a small, fast GPT reason about coding the way a senior engineer would, while spending a fraction of the tokens of a single-shot generation from a bigger model.

```text
                ┌──────────────────────────────────────────┐
                │      essarion-build SDK (this repo)      │
                │                                          │
   your task ─► │  ┌──────────┐  ┌──────────┐  ┌────────┐  │ ─► structured
                │  │   plan   │ →│  draft   │ →│selfcheck│ │    output
                │  └──────────┘  └──────────┘  └────────┘  │   (plan, code,
                │  + bundled skills + repo + docs + diffs  │    defense, …)
                │                                          │
                └──────────────────────────────────────────┘
                                  ▲
                       any LLM provider (BYOK)
                  OpenRouter · Anthropic · OpenAI · Gemini
                       Ollama (local) · custom
```

## The `essarion` CLI coding agent

Type `essarion` to launch the interactive coding agent. It uses the same SDK
under the hood — the agent IS the SDK, dressed in a TUI:

```bash
$ essarion

  essarion build · CLI coding agent
  by Essarion · amplifies any LLM with senior-engineer reasoning

  session   20260528-195838-5e4b
  cwd       /home/you/work/myproject
  model     openrouter/openai/gpt-4o-mini
  budget    $0.000 / $1.00
  skills    54 bundled, picker mode auto

  type your task to begin · /help for commands · /quit to exit
  ────────────────────────────────────────────────────────────

you: set up a codebase for a Next.js app with a todo API and tests

  skills  containers dx caching scope_discipline error_handling

  ✓ Created  package.json
  ✓ Created  tsconfig.json
  ✓ Created  app/page.tsx
  ✓ Created  app/api/todos/route.ts
  ✓ Created  tests/todos.test.ts
  ✓ Ran  npm install
  ✓ Ran  npm test
      Tests:  2 passed
  ✓ Next.js app scaffolded with a todo API and a passing test suite

  changes: 5 created  package.json, tsconfig.json, app/page.tsx, … · /diff to view
  turn usage 12,403 tokens · $0.0042
  ────────────────────────────────────────────────────────────
```

By **default the agent is autonomous** (like Claude Code / Codex): it plans
internally, then creates/edits/deletes files and runs commands in a loop until
the whole task is done — no "approve this plan" or "apply to which file?"
stops. Every change is captured in the change log, so `/undo` and `/diff` still
work. Prefer a checkpoint? `/auto off` (or `--plan-first`) switches to the
classic **plan → approve → hand-apply** flow:

```text
  approve plan? (Enter=approve, e=edit, s=skip-to-draft, c=cancel) _
```

### Why use the agent (over Claude Code / Codex / Aider / Cursor)

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
3. **MCP — plug in external tools.** Declare any MCP server in
   `.essarion/config.toml` (`[[mcp_servers]]`: GitHub, Postgres, Slack,
   your internal tools…) and its tools become first-class agent tools
   (`mcp__github__create_issue`), listed in the manifest and callable in
   the autonomous loop. Zero-dependency stdio JSON-RPC client built in —
   `/mcp` shows live servers + tools, `/mcp reconnect` retries.
3. **Code intelligence, not blind grep.** Every turn the agent gets an
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
3. **Collapsed, readable output + memory.** Each action is one compact,
   faded line (`Created index.html`, `Edited styles.css` + a small diff,
   `Ran npm test` + a short tail) — not a wall of file dumps. The agent
   also remembers the conversation, so "what did you just do?" or "how do I
   reach the server?" are answered from memory, and it can **ask you
   multiple-choice questions** mid-task when something's genuinely ambiguous.
3. **Token meter + a cap that actually holds.** Every turn shows tokens + cost
   (and cache hits); there's **no spending cap by default**. Set one with
   `/budget` (it'll prompt) or `--budget 5`. When a cap is set the autonomous
   loop **pre-estimates the next step and stops before crossing it** (not after
   the call is billed), and **finalizes with a grounded summary of findings so
   far** rather than stopping empty-handed. An **exploration budget**
   (`--read-cap`, default 25) stops the "reads forever, answers never" failure.
   `/cost <path>` estimates a hypothetical context before you send it.
3. **Guardrails + a live checklist.** Catastrophic commands (`rm -rf /`,
   `mkfs`, fork bombs) are always refused and risky ones (`sudo`, force-push,
   `curl | sh`) prompt for approval — tune it under `[permissions]` in
   `.essarion/config.toml`, or `/yolo` to wave it through. The agent keeps a
   visible todo checklist (`☐ ▶ ☑`) on multi-step tasks, and secrets are
   redacted from output and memory.
3. **Smart skill selection.** The 54 bundled skills aren't all loaded
   every turn — a fast keyword picker chooses the 3-5 most relevant
   ones. Big context savings on every call.
4. **Multi-model arbitrage (both directions).** Plan + selfcheck on a cheap
   model; `--escalate <bigger-model>` kicks in only if selfcheck rejects. And
   `--triage-model <cheap>` **de-escalates** the throwaway `effort=auto` routing
   call to a pennies model, so you can keep a *capable* default for the real
   reasoning at near-zero routing cost. Cheap by default, smart when it matters.
5. **Cross-model second opinion — no other coding agent ships this.** Turn on
   `/crosscheck <model>` (ideally a *different* family) and an INDEPENDENT model
   red-teams every change before it lands — seeing only the goal + the diff, so a
   review is a few hundred tokens. Different models have different blind spots, so
   **where they disagree is where bugs hide**: Essarion surfaces the specific
   concerns (file · symbol · why) and nudges you to `/fix` or `/undo`. Two pennies
   models — one building, a different one cross-examining — catch what a single
   model rubber-stamps. The cheap-ensemble take on "make cheap models reason like
   a better one." (On OpenRouter, write on `openai/…` and review on `anthropic/…`
   with one key.)
5. **Project-aware, with self-accumulating memory.** `essarion init` creates
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
6. **Inline tool execution during planning.** The model can emit
   `<tool_call name="read_file">…</tool_call>` inside its plan; the agent
   runs the read-only tool (read_file, grep, glob, list_dir, find_files,
   repo_map, outline, find_symbol), folds the result back as a note, and
   re-plans. Up to 3 rounds. No user friction. You can also steer it yourself
   with inline **`@path`** references — `@src/auth.py` attaches the file (and its
   sibling test), `@src/` a directory. Large files are **windowed** (head + tail,
   or around your search hits), so the end of a file is never silently dropped.
7. **Background tasks.** `/bg npm run dev` runs in parallel. The agent
   keeps working; completion notices fire between turns. /quit cleanly
   kills non-detached tasks via SIGTERM → SIGKILL on the process group.
8. **Drive a real browser (computer use).** Opt in with `/computer` (or
   `--computer-use`) and the agent drives a real headless browser to *test
   what it just built* — start a dev server in the background, then navigate,
   click, and type, reading back a reactive digest of console errors, network
   failures, and DOM changes (not just a screenshot). Each action can carry an
   `expect=` prediction the environment verifies deterministically. `/desktop`
   extends the same loop to the real mouse/keyboard/screen (explicit opt-in).
   On vision-capable models the agent can *see* the screenshots it takes.
9. **Streamed draft output.** `/stream on` shows code as it's written,
   token by token.
10. **Auto-verify + undo.** Configure `[verify].auto=true` and the agent
    runs your test suite after every applied change. If it fails, `/undo`
    reverts the last change.
11. **Reasoning-trace persistence.** Every session saved to
    `<project>/.essarion/sessions/` (or `~/.essarion/sessions/`). Replay
    with `essarion --resume <id>`.
12. **The whole SDK is yours.** Anything you can do in the agent, you can
    do in code — same `reason()`, `generate()`, `Conversation` calls.

### Quick commands

```bash
essarion                                  # interactive REPL
essarion --task "review src/auth.py"      # one-shot non-interactive
essarion --provider anthropic --model claude-sonnet-4-6
essarion --budget 5.00 --escalate claude-sonnet-4-6   # cheap+escalate
essarion --model anthropic/claude-sonnet-4-6 --triage-model openai/gpt-4o-mini  # capable+cheap routing
essarion --crosscheck-model anthropic/claude-haiku-4-5   # a 2nd model reviews every change
essarion --budget 1.00 --read-cap 15      # cap spend AND reading
essarion --resume 20260528-195838-5e4b    # continue a saved session
essarion --plan-first "harden the JWT check"  # opt out of autonomous mode
essarion --skills all                     # load every skill (vs auto)
essarion --effort deep                    # force deep reasoning every turn
essarion --effort quick                   # force minimal reasoning (cheapest)

# Subcommands fall through to the original CLI
essarion skills                           # list bundled skills
essarion providers
essarion reason "task" --json
essarion generate "task" --stream
```

### Project folders

Run `essarion init` inside a repo and you'll get a `.essarion/`
directory with:

- `config.toml` — per-project defaults (provider, model, budget, skills mode)
- `sessions/` — saved sessions live with the project instead of in `~`
- `.gitignore` — keeps sessions out of git

Once initialized, any time you launch `essarion` from anywhere inside
the project tree, the agent walks up to the project root, anchors the
sandbox there, and loads `.essarion/config.toml`. No `.essarion/`?
The agent still finds the project root via `.git/`, `pyproject.toml`,
`package.json`, `Cargo.toml`, `go.mod`, etc., and falls back to
`~/.essarion/sessions/` for storage.

### Background tasks

Long-running commands shouldn't block the agent. Start them in the
background and they run in parallel while you keep planning:

```text
you: /bg npm run dev
  started [a3f9c1] pid=14852 · npm run dev

you: /bg pytest -q
  started [b7e221] pid=14855 · pytest -q

you: /bg
                  background tasks
  ┏━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┓
  ┃ id     ┃ status  ┃ name        ┃ elapsed ┃ exit ┃
  ┡━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━┩
  │ a3f9c1 │ running │ npm run dev │   12.4s │      │
  │ b7e221 │ done    │ pytest -q   │    4.7s │    0 │
  └────────┴─────────┴─────────────┴─────────┴──────┘

you: review src/auth.py
  ── plan ──
  …(plan as normal while npm run dev keeps serving)…

  [bg] [b7e221] pytest -q → done (exit 0, 4.7s)   ← notice flushes here
```

- `/bg <cmd>` — start one
- `/bg detached <cmd>` — start one that survives `/quit`
- `/bg` — list every task with status
- `/bg show <id>` — recent stdout/stderr
- `/bg wait <id> [seconds]` — block until done
- `/bg kill <id>` — terminate
- `/bg clear` — forget finished tasks

The same tools are registered with the SDK's tool registry, so the
model can call `start_background` / `check_background` /
`wait_background` / `kill_background` / `list_background` itself
during reasoning. The footer always shows `bg N running` when tasks
are alive; completion notices print between turns; `/quit` cleanly
kills every non-detached task (SIGTERM → grace → SIGKILL via process
group, so dev-server children die too).

### Slash commands (inside the REPL)

Type `/help` inside the agent for the categorized view. The headline ones:

**session**

| Command | Description |
|---|---|
| `/whoami` | one-screen status: project + model + memory + budget + bg tasks |
| `/history` | list this session's turns |
| `/save` / `/load` | persist / list saved sessions |
| `/quit` | exit (saves; kills non-detached bg tasks) |

**code intelligence**

| Command | Description |
|---|---|
| `/map [paths]` | the ranked repo map the agent sees each turn (optionally biased toward `paths`) |
| `/outline <file>` | one file's symbols + signatures |
| `/symbol <name>` | where a symbol is defined and referenced (go-to-def + find-refs) |

**planning & workflows**

| Command | Description |
|---|---|
| `/ask <q>` | quick `reason()` only, no draft phase (Q&A) |
| `/review <target>` | shortcut: `workflows.review(<target>)` |
| `/fix <bug>` / `/tests <target>` / `/refactor <target>` | other workflows |
| `/security <target>` / `/perf <target>` | security / performance review |
| `/docs <target>` / `/pr <target>` / `/explain <target>` | docs, PR description, code explanation |

**models & cost**

| Command | Description |
|---|---|
| `/model <p>/<m>` | switch provider/model mid-session (warns if the key isn't set) |
| `/escalate <m>` | set escalation model (cheap → strong on reject) |
| `/triage <m>` | cheap model for `effort=auto` routing only (de-escalation) |
| `/crosscheck <m>` | a **different** model independently reviews every change (second opinion) |
| `/budget [N]` | show or set USD budget |
| `/cost` | session cost ledger (per turn + total) |
| `/cost <path>` | estimate the cost of a turn against a path/dir |
| `/stream [on\|off]` | toggle streamed draft output (token-by-token) |
| `/reload` | hot-reload `.env` / config without restarting |
| `/keys` | show which provider API keys are set |
| `/keys set <p> [key]` | capture a provider key (hidden prompt); optionally save to `.env` |

**skills & memory**

| Command | Description |
|---|---|
| `/skills [auto\|all\|none]` | switch picker mode |
| `/remember <fact>` | append to `.essarion/memory.md` (per-project) |
| `/forget <pattern>` | remove facts matching a substring |

**extensibility (MCP)**

| Command | Description |
|---|---|
| `/mcp` | list connected MCP servers + the tools they expose |
| `/mcp reconnect` | retry failed/dead servers after fixing config |

**project & files**

| Command | Description |
|---|---|
| `/cd <path>` | change sandbox directory |
| `/pwd` | print sandbox cwd |

**changes & verify**

| Command | Description |
|---|---|
| `/diff` | unified diff of every change this session |
| `/undo` | revert the most recent agent-applied change |
| `/commit [msg]` | git-commit the session's touched files |
| `/verify [cmd]` | run the project's check command (tests/lint) |

**background**

| Command | Description |
|---|---|
| `/bg <cmd>` | start a background shell command |
| `/bg [show\|wait\|kill\|clear] <id>` | manage tasks |

**safety**

| Command | Description |
|---|---|
| `/auto [on\|off]` | toggle autonomous mode (off = plan → approve → apply checkpoint) |
| `/yolo` | toggle auto-approval of side-effect tools |
| `/computer [on\|off]` | let the agent drive a real browser to test what it builds (opt-in) |
| `/desktop [on\|off]` | let the agent control the real mouse/keyboard/screen (explicit opt-in) |

## Install

```bash
pip install essarion-build
```

Set your provider key. The default is OpenRouter, which gives you access to ~any model through one API:

```bash
export OPENROUTER_API_KEY=sk-or-...
```

Or pick another:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GEMINI_API_KEY=...
# Ollama needs no key; runs locally
```

**Prefer a `.env`?** Drop the key in a `.env` at your project root and it's
**auto-loaded at startup** — no `export`, no restart (a shell-exported var still
wins). Added a key while the REPL is open? `/reload` picks it up live, or
`/keys set openrouter` captures one with a hidden prompt and offers to save it to
`.env`. (Add `.env` to your `.gitignore`.)

## Quick start

```python
from essarion_build import Context, reason, generate

ctx = (
    Context()
      .with_all_skills()                 # 54 bundled coding-practice skills
      .add_repo("./")                    # ground in your codebase
      .add_docs("https://datatracker.ietf.org/doc/html/rfc7519")
)

# Pure reasoning — returns a plan, no code yet
r = reason("harden JWT signature check", context=ctx)
print(r.plan)                  # the numbered reasoning trace
print(r.tradeoffs)             # what was considered and rejected
print(r.verdict)               # "ship" or "do not ship without X"
print(r.usage.total_tokens)    # token cost across the whole loop

# Reason + produce code — returns reasoning AND a snippet
g = generate("harden JWT signature check", context=ctx)
print(g.code)                  # the proposed change
print(g.reasoning)             # the underlying Reasoning object
print(g.defense)               # one-paragraph "why this is safe to ship"
print(g.usage.total_tokens)    # token cost across plan + draft + selfcheck
```

## Adaptive reasoning effort — deep when it matters, cheap when it doesn't

The headline feature. A one-line rename shouldn't cost the same as hardening a JWT validator. The `effort` parameter spends tokens **proportional to task difficulty**:

| effort | reason() calls | what it does |
|---|---|---|
| `quick` | 1 | plan only — trivial tasks |
| `standard` | 2 | plan + adversarial self-check (default) |
| `deep` | 4 | plan → **critique** the plan → **revise** it → self-check |
| `max` | 6 | + explore an **alternative** plan → **synthesize** the best of both |
| `auto` | 1 triage + above | a tiny triage call sizes the task 1–5, then routes to quick/standard/deep automatically |

```python
from essarion_build import reason, Context

ctx = Context().with_all_skills().add_repo("./")

# Let Essarion size the task. Trivial → 1-2 calls; security-critical → 4.
r = reason("harden JWT signature check", context=ctx, effort="auto")
print(r.effort)        # e.g. "deep" — triage decided this one was worth it

# Or pin the depth yourself.
r = reason("rename `cfg` to `config`", context=ctx, effort="quick")    # 1 call
r = reason("design the migration", context=ctx, effort="max")          # 6 calls
```

**Why this is cheap AND deep:** the extra calls in `deep`/`max` refine the *plan* — which is short — before any code is written. You pay a few hundred tokens to catch a design flaw, not thousands to regenerate a bad draft. The `auto` triage call caps its own output, so sizing a task costs almost nothing.

Set a global default or seed from the environment:

```python
import essarion_build
essarion_build.configure(effort="auto")        # every call sizes itself
# or: export ESSARION_EFFORT=auto
```

The `essarion` CLI agent defaults to `effort="auto"` — it sizes every task you give it and tells you the depth it chose. Change it live with `/effort deep`.

## Bundled software-dev skills

A core idea: cheap models cost less but reason worse. `essarion_build` closes the gap by **injecting senior-engineer skills into the context** — short, focused markdown briefs the model reads alongside the task.

```python
from essarion_build import Context, list_skills, load_skill

list_skills()
# [  # 54 bundled, alphabetical
#   'accessibility', 'agile_practice', 'api_design', 'auth_security',
#   'build_systems', 'caching', 'cli_design', 'cloud_infra',
#   'code_organization', 'code_review', 'code_review_practice', 'code_search',
#   'code_smells', 'code_style', 'code_with_llms', 'concurrency', 'containers',
#   'data_modeling', 'database_design', 'debugging', 'dependency_injection',
#   'dependency_management', 'distributed_systems', 'documentation', 'dx',
#   'error_handling', 'event_driven', 'feature_flags', 'git_workflow',
#   'go_idioms', 'incident_response', 'internationalization', 'kubernetes',
#   'llm_integration', 'logging', 'microservices', 'migrations',
#   'ml_engineering', 'networking', 'observability', 'observability_practice',
#   'performance', 'python_idioms', 'react_patterns', 'refactoring',
#   'release_engineering', 'rust_idioms', 'scope_discipline', 'secure_coding',
#   'sql_idioms', 'state_management', 'testing', 'typescript_idioms',
#   'web_security'
# ]

# Pick the ones relevant to your task...
ctx = Context().with_skills(["secure_coding", "auth_security", "error_handling"])

# ...or load them all (recommended default for coding tasks)
ctx = Context().with_all_skills()

# Or read one inline
print(load_skill("secure_coding"))
```

Each skill is a short, actionable brief. `secure_coding` covers input validation, output encoding, secret handling, and crypto defaults. `scope_discipline` covers staying within scope. `testing` covers what to test and how. The full set is bundled with the package; no network calls.

### Custom skills

Need project-specific guidance? Inject your own:

```python
ctx = (
    Context()
      .with_all_skills()
      .with_custom_skill("house_style", open("./docs/style.md").read())
      .with_skills_dir("./team_skills")    # every *.md file in the dir
)
```

## High-level workflows

For the common cases, skip the prompt engineering — call a workflow.

```python
from essarion_build import workflows, Context

# Review a target with the review-default skill set
r = workflows.review("src/auth.py", repo="./")

# Fix a bug end-to-end (plan → patch → defense)
g = workflows.fix_bug("payment endpoint hangs on null email", repo="./")

# Generate tests for a public surface
g = workflows.write_tests("class JWTValidator", repo="./")

# Refactor with behavior-preserving guarantees
g = workflows.refactor("UserService.god_method", repo="./")

# Write docs in the existing house style
g = workflows.docs("public Context API", repo="./")
```

Each workflow picks a sensible default skill set, frames the task, and runs the loop. They're thin on purpose — drop down to `reason()` / `generate()` when you need full control.

## Recipes

For the most common asks, skip prompt engineering — pull a recipe:

```python
from essarion_build import Context, recipes, reason

task, skills = recipes.audit_for_race_conditions("the booking flow")
ctx = Context().with_skills(skills).add_repo("./src/booking")
r = reason(task, context=ctx)
```

Recipes ship for: race conditions, N+1 queries, type-annotation passes,
runbooks, API design, data migrations, hot-path optimization, endpoint
hardening, schema design. See `essarion_build.recipes.list_recipes()`.

## Streaming

See progress in real time. Yields a `phase_start`/`token`/`phase_end`/`usage`/`complete` event sequence:

```python
from essarion_build import stream_generate, Context

for event in stream_generate("write a JWT validator", context=Context().with_all_skills()):
    if event.kind == "token":
        print(event.text, end="", flush=True)
    elif event.kind == "phase_end":
        print(f"\n--- {event.phase} done ---")
    elif event.kind == "complete":
        print(f"\nFinal usage: {event.usage}")
```

Providers with native token streams (Anthropic) emit fine-grained tokens; buffered providers emit one chunk per phase. The UI surface is the same either way.

## Async API

`areason()` / `agenerate()` mirror the sync API:

```python
import asyncio
from essarion_build import Context, agenerate

async def main():
    g = await agenerate("write a JWT validator", context=Context().with_all_skills())
    print(g.code)

asyncio.run(main())
```

### Parallel batches

For independent tasks, run them concurrently:

```python
from essarion_build import batch_generate, run_batch, Context

tasks = [
    "review src/auth.py",
    "review src/billing.py",
    "review src/notifications.py",
]
results = run_batch(batch_generate(tasks, context=Context().with_all_skills(),
                                   max_concurrency=4))
print(f"{len(results.ok)} succeeded, {len(results.errors)} failed")
```

One task's failure doesn't fail the rest — failures are returned as `Exception` instances in the result list.

## Multi-turn conversations

When tasks build on each other, use `Conversation`. Each turn's plan + verdict is auto-summarized into the context so the next call can refer back:

```python
from essarion_build import Conversation, Context

conv = Conversation(context=Context().with_all_skills().add_repo("./"))

# Turn 1: agree on the schema
r1 = conv.reason("design a users-and-orgs schema with row-level multitenancy")

# Turn 2: write the migration — the prior plan + verdict are in the context
g2 = conv.generate("write the SQL migration for the schema above")

# Turn 3: tests — same context, plus turns 1+2
g3 = conv.generate("write integration tests for the migration")

print(conv.usage.total_tokens)   # aggregated across all 3 turns
print(len(conv.history))         # 3
forked = conv.fork()              # branch for what-if scenarios
```

## Diff-focused context

Reviewing a change? Don't load the whole repo; load the diff:

```python
import subprocess
from essarion_build import workflows, Context

diff = subprocess.check_output(["git", "diff", "main"]).decode()

ctx = Context().with_all_skills().add_diff(diff, title="main..HEAD")
r = workflows.review("the change above", context=ctx)
```

## Token budgeting and usage tracking

Every `reason()` and `generate()` result carries a `usage` field with prompt, completion, total, and provider-reported cached token counts:

```python
r = reason("...", context=ctx)
print(r.usage)
# Usage(prompt_tokens=2618, completion_tokens=373, total_tokens=2991, cached_tokens=0)
```

Cap the per-call budget without changing the module default:

```python
g = generate("...", context=ctx, max_tokens=1500)
```

Pre-flight estimate before sending:

```python
print(ctx.estimate_tokens())     # ~1.2k? send it. ~120k? trim.
print(ctx.total_chars())         # raw character count
```

Or set the budget globally:

```python
import essarion_build
essarion_build.configure(max_tokens=2000)
```

The runtime divides the budget across the 2 calls (`reason`) or 3 calls (`generate`) in the loop, plus any one-shot tag-repair retries (see below). Usage from those retries is included in the total.

## Response cache

For dev iteration, skip duplicate provider calls:

```python
from essarion_build import LiteRuntime, ResponseCache, CachingProvider, build_provider

provider = build_provider(name="anthropic", api_key=None, model="claude-sonnet-4-6")
cache = ResponseCache("./.essarion-cache")
cached_provider = CachingProvider(provider, cache, provider_name="anthropic")

# Use it as you would any provider:
rt = LiteRuntime(cached_provider)
```

Identical `(system, messages, max_tokens)` tuples are served from disk; cache misses populate it.

## Post-generation validators

Cheap, deterministic checks on generated code (no model calls):

```python
from essarion_build.validators import validate

g = generate("write a Python function …", context=ctx)
issues = validate(g.code, kind="python")
for i in issues:
    print(f"{i.severity}: {i.message} (line {i.line})")
```

Built-in validators: `python` (syntax, bare except, mutable defaults, dangerous calls, TODO markers), `json` (RFC 8259 strictness), `diff` (unified-diff header check). Register your own with `register_validator(kind, fn)`.

## Cheap-model survival kit

Small models drop XML tags. When the model returns a selfcheck without the `<defense>` tag, the runtime asks once for just the missing tag(s) and merges the result. If even the repair pass fails, you get a typed `ReasoningFormatError` — not a silently empty `defense` field.

You don't have to opt in; this happens automatically inside `LiteRuntime`.

## The `@reasoned` decorator

Mark functions you want the `essarion-build` CLI to enumerate. In normal Python execution the original body runs unchanged — the decorator just records the function in a module-level registry.

```python
from essarion_build import reasoned

@reasoned(context=ctx)
def parse_jwt(token: str) -> Claims:
    """Parse a JWT and return validated claims."""
    ...  # body is yours; the CLI uses this entry for future reason+generate runs
```

## BYOK and providers

The Provider seam keeps `essarion_build` model-agnostic. v0.3 ships six concrete providers; the model you run is your choice:

| Provider | Env var | Default model | Notes |
|---|---|---|---|
| `openrouter` (default) | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` | Routes to ~any model behind one OpenAI-compatible API. The cheap-default story. |
| `anthropic` | `ANTHROPIC_API_KEY` | (provide one, e.g. `claude-sonnet-4-6`) | Direct to the Claude API. Uses prompt caching on the system block. Streaming supported. |
| `openai` | `OPENAI_API_KEY` | (provide one, e.g. `gpt-4o-mini`) | Direct to OpenAI. |
| `gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | (provide one, e.g. `gemini-2.0-flash`) | Direct to Google Gemini. |
| `ollama` | (none) | (provide one, e.g. `llama3.2`) | Local OSS models. Set `OLLAMA_BASE_URL` if not on `localhost:11434`. |
| `stub` | (none) | n/a | In-memory scripted responses for tests. |

Switch globally or per-call:

```python
import essarion_build

# Stay on OpenRouter but use a stronger model
essarion_build.configure(model="anthropic/claude-sonnet-4.6")  # OpenRouter slug

# Or switch provider entirely
essarion_build.configure(provider="anthropic", model="claude-sonnet-4-6")

# Per-call override
generate("...", provider="openai", model="gpt-4o-mini", max_tokens=1500)
```

### Register a custom provider

```python
from essarion_build import register_provider

class _MyProvider:
    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model
    def complete(self, *, system, messages, max_tokens):
        ...  # return ProviderResponse(text=..., usage=Usage(...))

register_provider("my-llm", lambda *, api_key, model: _MyProvider(api_key=api_key, model=model))

# Now usable just like a built-in:
generate("...", provider="my-llm", model="my-model-v1")
```

Async siblings (`register_async_provider`, `build_async_provider`, `AsyncProvider` protocol) follow the same shape.

## Structured output (JSON-schema mode)

When you want a typed payload instead of free text, use `generate_json`:

```python
from pydantic import BaseModel
from essarion_build import Context, generate_json

class ReviewFinding(BaseModel):
    file: str
    line: int
    severity: str  # "info" | "warning" | "error"
    description: str
    suggested_fix: str

parsed, gen = generate_json(
    "review src/auth.py for a single finding",
    schema=ReviewFinding,
    context=Context().with_skill("code_review"),
)
finding = ReviewFinding(**parsed)
print(finding.severity, finding.suggested_fix)
```

If the model emits invalid JSON (or fails Pydantic validation), the
runtime automatically reframes the task with the validation error and
asks once more. After the second failure, `SchemaValidationError` is
raised with the last output for inspection.

Pass a raw JSON schema dict if you don't want Pydantic in the mix:

```python
parsed, gen = generate_json("…", schema={"type": "object", "required": ["a", "b"]}, …)
```

Async sibling: `agenerate_json(...)`.

## Compaction

When your Context exceeds the token budget:

```python
from essarion_build import Context, compact, truncate_files, keep_only_files

ctx = Context().with_all_skills().add_repo("./src")
print(ctx.estimate_tokens())              # e.g. 380_000

# Drop low-signal sections (repo files first, then docs) to fit a budget.
ctx = compact(ctx, max_tokens=40_000)

# Or cap each file body individually with a truncation marker.
ctx = truncate_files(ctx, max_chars_per_file=4_000)

# Or filter the file set by glob.
ctx = keep_only_files(ctx, patterns=["src/auth/*", "src/billing/*"])
```

`compact()` never drops skills, notes, or diffs — they are the
high-signal content.

## Telemetry

Off by default, zero-dependency. Wire a callback to receive structured events
as the reasoning loop runs — pipe them into your logs/traces, do per-team
usage accounting, or debug without sprinkling `print`s through the SDK:

```python
from essarion_build import configure_telemetry, reason, Context

def on_event(ev: dict) -> None:
    print(f"[{ev['kind']}] {ev}")   # loop_start, phase_complete, loop_complete, …

configure_telemetry(on_event=on_event)
reason("harden the JWT check", context=Context().with_all_skills())

# Toggle without losing the callback, or clear it entirely:
configure_telemetry(enabled=False)
configure_telemetry(on_event=None)
```

Events are plain dicts (`{"kind": ..., "ts": ..., ...}`); a callback that
raises can never break the loop. See `examples/06_telemetry.py`.

## Evals

A model-driven SDK without evals is a benchmark waiting to regress.
`essarion_build.evals` is a thin harness for running a labeled benchmark
against any callable runner:

```python
from essarion_build.evals import EvalCase, contains_all, run_eval
from essarion_build import Context, reason

CASES = [
    EvalCase(task="audit JWT alg=none confusion", expected="whitelist, alg=none"),
    EvalCase(task="audit a SQL injection",        expected="parameterized, prepared"),
]

def runner(task: str):
    r = reason(task, context=Context().with_skill("secure_coding"))
    return r.plan, r.usage    # tuple → usage flows into the report

report = run_eval(CASES, runner, contains_all, name="security-v1")
print(report.summary())       # → "security-v1: 2/2 passed (100%, mean 1.00). Tokens: …"

# Compare against a baseline for CI gating
delta = report.delta(baseline_report)
if delta["regressed"]:
    raise SystemExit(f"Regressions: {delta['regressed']}")
```

Built-in scorers: `exact_match`, `contains_all`, `keyword_overlap`.
Roll your own — it's just a function returning `Score`.

## Tools (model-side)

`essarion_build` ships a small, opt-in tool surface that works on every
provider (no native tool-use required):

```python
from essarion_build import register_tool, run_tools_in_plan, Context, tool_manifest

@register_tool("read_file", description="read a file from disk")
def _read(path: str) -> str:
    return open(path).read()

ctx = Context().with_all_skills().add_note(tool_manifest())

# The model emits <tool_call name='read_file'>{"path": "…"}</tool_call>;
# you evaluate them before the next turn:
plan_with_results = run_tools_in_plan(plan_text, allow={"read_file"})
```

The `allow` set is a security boundary — unknown or disallowed tools
become inline `<tool_result error="true">…</tool_result>` instead of
running. Use this for the small-tool case (look up the schema, fetch a
URL); for full agent loops, build directly on `Provider.complete()`.

## Vision — let the model see

A message's content can be a plain string (as always) or a list of neutral
blocks, so you can send a screenshot or a diagram alongside text. Each provider
(OpenAI/OpenRouter, Anthropic, Gemini) renders the blocks into its own native
multimodal shape; text-only providers (Ollama) fall back to the text parts, and
a plain string flows through untouched:

```python
from essarion_build import build_provider, image_block, text_block

provider = build_provider(name="anthropic", api_key=None, model="claude-sonnet-4-6")
resp = provider.complete(
    system="You are a meticulous UI reviewer.",
    messages=[{
        "role": "user",
        "content": [
            text_block("What's broken in this screenshot?"),
            image_block(open("screenshot.png", "rb").read()),   # bytes or base64
        ],
    }],
    max_tokens=500,
)
print(resp.text)
```

This is the same seam the computer-use tools use to show the model a screenshot
of the page or screen — on vision-capable models only (otherwise the capture is
noted, never sent blind).

## Computer use (browser + desktop)

The `essarion` agent can drive a **real browser** to test what it builds, and —
explicitly opt-in — the **real desktop** (mouse/keyboard/screen). It's built on
one principle: the environment observes and emits structured events, and the
model acts on a compact *digest* only when something meaningful changes — never
a continuous watcher.

In the CLI agent it's off by default; turn it on with `/computer` (browser) or
`/desktop` (machine), or launch with `--computer-use`:

```bash
essarion --computer-use "open the dev server and check the login flow works"
```

- **Reactive, text-first.** Every action returns a budget-sized digest of
  console errors, network failures, navigations, dialogs, and DOM mutations —
  catching the transient changes a screenshot-only agent misses.
- **Expectation-checked acting** ("reason deep, act fast"). Each action takes an
  optional `expect=` one-line prediction; the environment verifies it against
  the digest + page text deterministically (no extra model call) and prepends
  a ✓/✗.
- **Vision when the model has it.** `browser_screenshot` / `desktop_screenshot`
  attach the image to the next message on vision-capable models, and note the
  capture (never send blind) otherwise.
- **Desktop is explicit-opt-in only.** `/desktop` requires a typed
  acknowledgement and treats on-screen text as untrusted (prompt-injection);
  run it on a contained display/VM.

The whole toolkit is importable — build your own reactive browser automation on
top of the SDK, the same way the reasoning loop is importable:

```python
from essarion_build.computer import FakeBackend, bind_backend, browser_click

bind_backend(FakeBackend(url="https://app.test"))
result = browser_click(selector="#login", expect="navigates to /dashboard")
print(result)        # the action's digest, prefixed with a ✓/✗ on the expectation
```

The reducer, observer, and expectation engine are pure-Python and
dependency-free; only the live backends need extras — `pip install
'essarion-build[computer]'` (Playwright, browser tier) or
`'essarion-build[desktop]'` (python-xlib/mss/Pillow, desktop tier).

## CLI

The package installs an `essarion-build` console command. Useful for one-off coding tasks, CI scripts, and editor integrations:

```bash
# List bundled skills
essarion-build skills

# Print a skill's body
essarion-build skills --show secure_coding

# List recognized providers
essarion-build providers

# List bundled workflows
essarion-build workflows

# Estimate token cost of a context before sending
essarion-build estimate --repo ./ --json

# Run a reason() loop
essarion-build reason "review the auth flow" --repo ./src --json

# Stream a generate() loop's output
essarion-build generate "write a JWT validator" --repo ./src --stream

# Pipe a task from stdin
git diff main | essarion-build reason "review this change" -
```

## Testing your essarion-build code

For a zero-setup, no-network smoke test, just select the `stub` provider — it
auto-answers every reasoning phase, so `reason()`, `generate()`, and
`Conversation` work with no scripting and no API key:

```python
from essarion_build import configure, reason

configure(provider="stub", model="test")   # or pass provider="stub" per call
r = reason("add a retry decorator")          # works out of the box
assert r.verdict                              # canned, well-formed output
```

When you want **deterministic** output to assert on, script the responses with
an explicit `StubProvider` (strict: each call pops the next response, and
running out raises so a miscount can't pass silently):

```python
from essarion_build import Context, LiteRuntime, StubProvider, reason

def test_my_workflow():
    stub = StubProvider(responses=[
        "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
        "<verdict>ship</verdict>",
    ])
    r = reason("anything", context=Context(), _runtime=LiteRuntime(stub))
    assert "ship" in r.verdict
    assert stub.call_count == 2
```

The `run_with_stub` helper wires the runtime for you and works with the
top-level functions *and* `Conversation`:

```python
from essarion_build import Conversation
from essarion_build.testing import StubProvider, run_with_stub

conv = Conversation()
r = run_with_stub(stub, conv.reason, "design the schema")
```

Async sibling: `AsyncStubProvider` + `AsyncLiteRuntime` (and `arun_with_stub`).
See `essarion_build.testing` for helpers.

## Error handling

Provider failures map to typed exceptions all rooted at `EssarionError`:

| Exception | When |
|---|---|
| `ProviderAuthError` | HTTP 401/403 (bad or missing key) |
| `ProviderRateLimitError` | HTTP 429 after exhausting retries |
| `ProviderHTTPError` | Other non-2xx, or network errors after retries |
| `ProviderResponseError` | Provider returned 2xx but the body was unparseable |
| `ReasoningFormatError` | Model output still missing required tags after one repair pass |
| `CloudRuntimeNotAvailable` | `runtime="cloud"` requested (not yet shipped) |
| `ProviderNotAvailable` | Unknown provider name |
| `ContextError` | Bad input to a `Context` method |

Transient HTTP errors (429, 5xx, connection errors) get up to 2 retries with exponential backoff before surfacing.

## Lite vs Cloud

Both runtimes implement the same protocol:

| Runtime | What it does | Status in v0.3 |
|---|---|---|
| `LiteRuntime` (default) | Drives the 3-step reasoning loop locally via your provider key. Fast to set up. | **Available** |
| `CloudRuntime` | Sends the task to `build.essarion.com` for a heavier reasoning loop, longer context, and real Sourcipedia grounding. | **Stub** — raises `CloudRuntimeNotAvailable` |

```python
generate("...", runtime="cloud")           # raises in v0
essarion_build.configure(runtime="cloud")  # configure now, callable when Cloud ships
```

## Interop hooks (stubs in v0.3)

These exist on `Context` so the API surface is right; implementations land when upstream APIs are exposed.

```python
ctx.add_sourcipedia_topic("jwt")     # placeholder source entry
ctx.add_agent_skill("auth_review")   # Anthropic Agents skill manifest reference
```

```python
from essarion_build.auth import from_platform_api   # raises NotImplementedError in v0
```

## Out of scope for v0.3

No plugin loader (custom providers + custom skills cover the same surface) and no embeddings/RAG (use the `Context.add_repo(include=...)` filter). The `CloudRuntime` is still a stub (raises `CloudRuntimeNotAvailable`), and the Sourcipedia / Agent-skill interop hooks are placeholder seams (see above).

## License

Apache-2.0.
