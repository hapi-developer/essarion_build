# Examples

Runnable examples for `essarion-build`. All examples assume:

```bash
pip install essarion-build
export OPENROUTER_API_KEY=sk-or-...
```

| # | File | What it shows |
|---|---|---|
| 1 | [`01_quick_start.py`](01_quick_start.py) | Load skills + repo, run `reason()` and `generate()` |
| 2 | [`02_workflows.py`](02_workflows.py) | High-level workflows: `review`, `fix_bug`, `write_tests` |
| 3 | [`03_streaming.py`](03_streaming.py) | Stream `generate()` events in real time |
| 4 | [`04_async_batch.py`](04_async_batch.py) | Concurrent `batch_reason()` over a directory |
| 5 | [`05_conversation.py`](05_conversation.py) | Multi-turn `Conversation` chaining reason + generate |
| 6 | [`06_telemetry.py`](06_telemetry.py) | Pipe SDK events into your observability stack |
| 7 | [`07_custom_provider.py`](07_custom_provider.py) | Register and use a custom provider (no key required) |
| 8 | [`08_cache.py`](08_cache.py) | Skip duplicate provider calls with `ResponseCache` |
| 9 | [`09_agent_programmatic.py`](09_agent_programmatic.py) | Drive the `essarion` CLI agent's plan-first loop from Python |
| 10 | [`10_project_setup.py`](10_project_setup.py) | Bootstrap a project for the agent: `.essarion/` + memory + custom commands |
| 11 | [`11_reasoning_effort.py`](11_reasoning_effort.py) | Adaptive reasoning depth: `quick`/`standard`/`deep`/`max`/`auto` |

Run any of them with `python examples/01_quick_start.py`.

## CI templates

| File | What it shows |
|---|---|
| [`github-action-review.yml`](github-action-review.yml) | GitHub Action: review every PR with a cross-model second opinion (`essarion-build review`). Copy to `.github/workflows/`. See [`../docs/CI.md`](../docs/CI.md). |

Examples 7 and 8 are self-contained: 7 uses a scripted provider so no key
is needed; 8 demonstrates caching live against OpenRouter.
