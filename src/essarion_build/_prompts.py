"""System prompts for the LiteRuntime reasoning loop.

Module-level so the prompt prefix is byte-stable across calls; this is what
makes prompt-caching work for the 3-step loop.

The defaults can be replaced at runtime via `configure_prompts(...)` for
teams that want their own house style baked in. Per-call overrides are
also supported via the `_prompts` kwarg on `Context.to_prompt_block()` —
but most users should never need either.
"""

SYSTEM_PROMPT = """You are essarion_build, a reasoning amplification layer for coding tasks.

Your job is to think before you write. You produce structured reasoning — a plan, the tradeoffs you considered (including alternatives you rejected and why), and a verdict on whether the proposed approach is sound. When asked to generate code, you also produce a defense paragraph explaining why the change is safe to ship.

Operating rules:
- Ground every claim in the provided <context>. Quote file paths and source URLs when relevant.
- If the context does not contain enough information to answer responsibly, say so in the verdict and stop.
- Reject elegant-but-wrong solutions in favor of correct-and-boring ones. Surface the temptation in tradeoffs.
- Be concrete. "Validate input" is not a plan step; "reject tokens whose alg header is 'none' (RFC 7519 §6.1)" is.
- Match the response format the user asks for exactly. Output ONLY the requested XML tags, no preamble or postscript.
"""

PLAN_INSTRUCTION = """Produce a structured plan for the following task.

Task: {task}

Respond with exactly this XML structure and nothing else:

<plan>
1. First concrete step.
2. Second concrete step.
...
</plan>
<tradeoffs>
- Option A (chosen): why.
- Option B (rejected): why.
- Option C (rejected): why.
</tradeoffs>
<verdict>One paragraph: is the chosen approach sound? Any preconditions, risks, or open questions? End with a clear "ship" / "do not ship without resolving X".</verdict>
"""

DRAFT_INSTRUCTION = """Given the plan you just produced, write the code that implements step 1 through the final step.

Respond with exactly this XML structure and nothing else:

<code>
The proposed code change. If it's a diff, use unified diff format. If it's a snippet, use plain code. Include only the code, no commentary inside this tag.
</code>
"""

SELFCHECK_REASON_INSTRUCTION = """Re-read the plan and tradeoffs you produced above. Adversarially check them:
- Does the plan actually solve the task, or does it solve a nearby simpler problem?
- Are the rejected options rejected for good reasons, or did you dismiss them too quickly?
- Are there hidden preconditions (env, permissions, schema) the plan assumes?

Respond with exactly this XML structure and nothing else:

<verdict>One paragraph: your refined verdict after the adversarial check. End with "ship" or "do not ship without resolving X".</verdict>
"""

SELFCHECK_GENERATE_INSTRUCTION = """Re-read the plan, tradeoffs, and code draft you produced above. Adversarially check them:
- Does the code actually implement every step of the plan?
- Does the code introduce any vulnerabilities, race conditions, or undefined behavior?
- Would this pass code review from a security-minded engineer?

Respond with exactly this XML structure and nothing else:

<verdict>One paragraph: your refined verdict after the adversarial check. End with "ship" or "do not ship without resolving X".</verdict>
<defense>One paragraph: why this change is safe to ship. Cite the specific guards (input validation, error handling, invariants) that make it safe. If you cannot defend it, say so and refer back to the verdict.</defense>
"""


# Per-runtime prompt overrides. Set via `configure_prompts(...)`. Empty
# string means "use the module default for this slot".
_PROMPT_OVERRIDES: dict[str, str] = {}


def configure_prompts(
    *,
    system: str | None = None,
    plan: str | None = None,
    draft: str | None = None,
    selfcheck_reason: str | None = None,
    selfcheck_generate: str | None = None,
) -> None:
    """Override the system / instruction prompts used by LiteRuntime.

    Pass `None` for a slot to leave the default in place; pass `""` to
    explicitly clear a prior override.

    Use this when:
    - your team has a "house voice" you want baked in
    - the model behaves better with slightly different framing
    - you're benchmarking prompt variants

    Don't use this to add user-task content — that goes through Context.
    """
    if system is not None:
        _PROMPT_OVERRIDES["system"] = system
    if plan is not None:
        _PROMPT_OVERRIDES["plan"] = plan
    if draft is not None:
        _PROMPT_OVERRIDES["draft"] = draft
    if selfcheck_reason is not None:
        _PROMPT_OVERRIDES["selfcheck_reason"] = selfcheck_reason
    if selfcheck_generate is not None:
        _PROMPT_OVERRIDES["selfcheck_generate"] = selfcheck_generate


def reset_prompts() -> None:
    """Clear every prompt override. After this call the SDK uses defaults."""
    _PROMPT_OVERRIDES.clear()


def _current(slot: str, default: str) -> str:
    """Resolve a prompt slot: return override if set, otherwise default."""
    return _PROMPT_OVERRIDES.get(slot) or default


def current_system() -> str:
    return _current("system", SYSTEM_PROMPT)


def current_plan() -> str:
    return _current("plan", PLAN_INSTRUCTION)


def current_draft() -> str:
    return _current("draft", DRAFT_INSTRUCTION)


def current_selfcheck_reason() -> str:
    return _current("selfcheck_reason", SELFCHECK_REASON_INSTRUCTION)


def current_selfcheck_generate() -> str:
    return _current("selfcheck_generate", SELFCHECK_GENERATE_INSTRUCTION)


__all__ = [
    "SYSTEM_PROMPT",
    "PLAN_INSTRUCTION",
    "DRAFT_INSTRUCTION",
    "SELFCHECK_REASON_INSTRUCTION",
    "SELFCHECK_GENERATE_INSTRUCTION",
    "configure_prompts",
    "reset_prompts",
    "current_system",
    "current_plan",
    "current_draft",
    "current_selfcheck_reason",
    "current_selfcheck_generate",
]
