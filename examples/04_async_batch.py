"""Async + batch: review every Python file under src/ concurrently.

Run with:
    OPENROUTER_API_KEY=... python examples/04_async_batch.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from essarion_build import Context, batch_generate, batch_reason


async def main() -> None:
    paths = sorted(Path("./src/essarion_build").glob("*.py"))[:5]
    tasks = [f"review {p.name} for correctness and security" for p in paths]
    ctx = Context().with_skills(["code_review", "secure_coding"]).add_repo("./src")

    print(f"Running {len(tasks)} reviews in parallel...")
    results = await batch_reason(tasks, context=ctx, max_concurrency=4)

    print(f"\n{len(results.ok)} succeeded, {len(results.errors)} failed\n")
    for task, result in zip(tasks, results):
        if isinstance(result, Exception):
            print(f"ERROR  {task}: {type(result).__name__}: {result}")
        else:
            print(f"OK     {task}: {result.verdict[:120]}…")


if __name__ == "__main__":
    asyncio.run(main())
