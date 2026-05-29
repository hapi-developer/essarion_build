# essarion-build Cookbook

Recipes for the things you'll actually want to do. Every recipe is a
complete, runnable Python snippet. See [`examples/`](../examples) for
self-contained scripts.

## Table of contents

1. [Smallest possible plan](#smallest-possible-plan)
2. [Generate code from a plan](#generate-code-from-a-plan)
3. [Ground in your codebase](#ground-in-your-codebase)
4. [Review a PR diff](#review-a-pr-diff)
5. [Run the same plan against multiple models](#run-the-same-plan-against-multiple-models)
6. [Cap your token budget](#cap-your-token-budget)
7. [Cache responses during dev iteration](#cache-responses-during-dev-iteration)
8. [Stream tokens to a terminal](#stream-tokens-to-a-terminal)
9. [Stream to a web client](#stream-to-a-web-client)
10. [Run many tasks concurrently](#run-many-tasks-concurrently)
11. [Carry context across multiple turns](#carry-context-across-multiple-turns)
12. [Inject team-specific guidance](#inject-team-specific-guidance)
13. [Wire telemetry into your observability stack](#wire-telemetry-into-your-observability-stack)
14. [Set up an eval suite](#set-up-an-eval-suite)
15. [Use a local Ollama model](#use-a-local-ollama-model)
16. [Plug in a private model gateway](#plug-in-a-private-model-gateway)
17. [Write tests against `generate()`](#write-tests-against-generate)
18. [Trim an over-budget Context](#trim-an-over-budget-context)
19. [Run model-side tools](#run-model-side-tools)
20. [Override the system prompt](#override-the-system-prompt)

---

## Smallest possible plan

```python
from essarion_build import Context, reason

r = reason("write a Python email validator", context=Context().with_skill("secure_coding"))
print(r.plan)
print(r.verdict)
```

## Generate code from a plan

```python
from essarion_build import Context, generate

g = generate(
    "write a Python email validator",
    context=Context().with_skills(["secure_coding", "python_idioms", "testing"]),
)
print(g.code)
print(g.defense)
```

## Ground in your codebase

```python
from essarion_build import Context, reason

ctx = (
    Context()
    .with_all_skills()
    .add_repo("./src", include=["**/*.py"], max_files=50)
)
r = reason("audit error handling", context=ctx)
```

## Review a PR diff

```python
import subprocess
from essarion_build import workflows, Context

diff = subprocess.check_output(["git", "diff", "main"]).decode()
ctx = Context().with_skills(["code_review", "secure_coding"])
r = workflows.review("the change above", context=ctx, diff=diff)
print(r.verdict)
```

## Run the same plan against multiple models

```python
from essarion_build import reason, Context

ctx = Context().with_skills(["code_review", "scope_discipline"])
task = "review the schema migration"

cheap = reason(task, context=ctx, provider="openrouter", model="openai/gpt-4o-mini")
strong = reason(task, context=ctx, provider="anthropic", model="claude-sonnet-4-6")

# Compare verdicts side by side.
print("CHEAP:", cheap.verdict)
print("STRONG:", strong.verdict)
```

## Cap your token budget

```python
from essarion_build import generate, Context, configure

# Global default
configure(max_tokens=2000)

# Per-call override
g = generate("write a JWT validator", context=Context().with_all_skills(), max_tokens=1500)

# Pre-flight estimate
ctx = Context().with_all_skills().add_repo("./src")
print(f"context: {ctx.estimate_tokens():,} tokens")
```

## Cache responses during dev iteration

```python
from essarion_build import (
    CachingProvider, Context, LiteRuntime, ResponseCache,
    build_provider, reason,
)

cache = ResponseCache("./.essarion-cache")
inner = build_provider(name="openrouter", api_key=None, model="openai/gpt-4o-mini")
prov = CachingProvider(inner, cache, provider_name="openrouter")

# First call: hits the network.
r1 = reason("foo", context=Context(), _runtime=LiteRuntime(prov))
# Second call: served from disk.
r2 = reason("foo", context=Context(), _runtime=LiteRuntime(prov))
print(cache.hits, "hits,", cache.misses, "misses")
```

## Stream tokens to a terminal

```python
from essarion_build import Context, stream_generate

for event in stream_generate(
    "write a Python email validator",
    context=Context().with_skills(["python_idioms", "testing"]),
):
    if event.kind == "token":
        print(event.text, end="", flush=True)
    elif event.kind == "complete":
        print(f"\n# usage: {event.usage}")
```

## Stream to a web client

```python
from flask import Flask, Response, request
from essarion_build import Context, stream_generate

app = Flask(__name__)

@app.post("/generate")
def generate_endpoint():
    task = request.json["task"]
    ctx = Context().with_all_skills()

    def gen():
        for ev in stream_generate(task, context=ctx):
            yield f"data: {ev.model_dump_json()}\n\n"

    return Response(gen(), mimetype="text/event-stream")
```

## Run many tasks concurrently

```python
from essarion_build import Context, batch_generate, run_batch

tasks = [
    "review src/auth.py",
    "review src/billing.py",
    "review src/notifications.py",
]
results = run_batch(
    batch_generate(tasks, context=Context().with_all_skills(), max_concurrency=4)
)
print(f"{len(results.ok)} ok, {len(results.errors)} errors")
```

## Carry context across multiple turns

```python
from essarion_build import Context, Conversation

conv = Conversation(context=Context().with_skills(["data_modeling", "migrations"]))
r1 = conv.reason("design a users-and-orgs schema")
g2 = conv.generate("write the migration for the schema above")
g3 = conv.generate("write integration tests for the migration")
print(f"{len(conv.history)} turns, total {conv.usage.total_tokens} tokens")
```

## Inject team-specific guidance

```python
from essarion_build import Context

ctx = (
    Context()
    .with_all_skills()
    .with_custom_skill("house_style", open("./docs/house_style.md").read())
    .with_skills_dir("./team_skills")
    .add_note("Avoid the legacy auth path; it's deprecated.")
)
```

## Wire telemetry into your observability stack

```python
import logging
from essarion_build import configure_telemetry, reason, Context

logger = logging.getLogger("essarion")

def emit(ev: dict) -> None:
    logger.info(ev["kind"], extra={"essarion": ev})

configure_telemetry(on_event=emit)
reason("anything", context=Context())
```

## Set up an eval suite

```python
from essarion_build.evals import EvalCase, contains_all, run_eval
from essarion_build import Context, reason

GOLD = [
    EvalCase(task="audit alg=none in JWT", expected="alg=none, whitelist"),
    EvalCase(task="audit SQL injection", expected="parameterized, prepared"),
]

def runner(task: str):
    r = reason(task, context=Context().with_skills(["secure_coding"]))
    return r.plan, r.usage   # tuple → usage is aggregated

report = run_eval(GOLD, runner, contains_all, name="security-v1")
print(report.summary())
```

## Use a local Ollama model

```bash
# In one terminal:
ollama serve
ollama pull llama3.2
```

```python
from essarion_build import Context, generate

# No API key needed. Ollama defaults to http://localhost:11434.
g = generate(
    "write a JWT validator",
    context=Context().with_skills(["secure_coding", "auth_security"]),
    provider="ollama",
    model="llama3.2",
)
```

## Plug in a private model gateway

```python
from essarion_build import (
    Context, LiteRuntime, ProviderResponse, Usage,
    build_provider, register_provider, reason,
)

class _InternalGateway:
    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model
        # Set up your gateway client here.

    def complete(self, *, system, messages, max_tokens):
        # Call your gateway, return ProviderResponse.
        text = "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>"
        return ProviderResponse(text=text, usage=Usage())

register_provider("internal", _InternalGateway)

reason("anything", context=Context(),
       provider="internal", model="house-model-v3")
```

## Write tests against `generate()`

For a quick no-network smoke test, the `stub` provider auto-answers every
phase — no scripting needed:

```python
from essarion_build import generate

g = generate("anything", provider="stub", model="test")
assert g.code and g.defense
```

When you need to assert on exact output, script an explicit `StubProvider`
(strict: one response per phase; running out raises):

```python
from essarion_build import Context, StubProvider, LiteRuntime, generate

def test_my_workflow():
    stub = StubProvider(responses=[
        "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
        "<code>def x(): pass</code>",
        "<verdict>ship</verdict><defense>safe</defense>",
    ])
    g = generate("anything", context=Context(), _runtime=LiteRuntime(stub))
    assert "def x" in g.code
    assert stub.call_count == 3
```

Or use the pytest plugin's fixtures:

```python
# conftest.py
pytest_plugins = ["essarion_build.pytest_plugin"]

# test_my.py
def test_with_fixture(essarion_runtime, essarion_stub):
    essarion_stub.push("<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>")
    essarion_stub.push("<verdict>ship</verdict>")
    from essarion_build import reason, Context
    r = reason("task", context=Context(), _runtime=essarion_runtime)
    assert r.verdict == "ship"
```

## Trim an over-budget Context

```python
from essarion_build import Context, compact, truncate_files, keep_only_files

ctx = Context().with_all_skills().add_repo("./src")
print(f"before: {ctx.estimate_tokens():,} tokens")

# Drop low-signal content first.
ctx = compact(ctx, max_tokens=20_000)

# Or cap each file to N chars.
ctx = truncate_files(ctx, max_chars_per_file=2000)

# Or filter to a subdirectory.
ctx = keep_only_files(ctx, patterns=["src/auth/*"])

print(f"after:  {ctx.estimate_tokens():,} tokens")
```

## Run model-side tools

```python
from essarion_build import register_tool, run_tools_in_plan

@register_tool("read_file", description="read a file from disk")
def _read(path: str) -> str:
    return open(path).read()

# Suppose the model emits:
plan = """
<plan>
1. Look at the schema.
   <tool_call name='read_file'>{"path": "schema.sql"}</tool_call>
2. Etc.
</plan>
"""

evaluated = run_tools_in_plan(plan, allow={"read_file"})
print(evaluated)  # <tool_result> now in place of <tool_call>
```

You wire the evaluated text into the next provider call yourself:
this surface is intentionally explicit so you control the I/O.

## Override the system prompt

```python
from essarion_build import configure_prompts, reset_prompts, reason, Context

configure_prompts(
    system="You are essarion_build for ACME Corp. Always cite the house "
           "style guide (./docs/style.md) in your verdict."
)

reason("anything", context=Context())

# Restore defaults later
reset_prompts()
```

---

## More

- [`examples/`](../examples) — runnable scripts for each major feature
- [`README.md`](../README.md) — top-level overview
- [`CHANGELOG.md`](../CHANGELOG.md) — version history
