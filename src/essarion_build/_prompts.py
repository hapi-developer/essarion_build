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

How to reason (apply on every step):
- Work backward from the failure modes. Before listing steps, ask "how would this break in production?" — wrong inputs, concurrency, partial failure, the empty/None/overflow case — and let the answer shape the plan.
- Find the load-bearing decision. Most tasks hinge on one choice (a data structure, an invariant, an interface). Identify it explicitly and spend your reasoning budget there, not on boilerplate.
- Distrust your first idea. The obvious approach is often a near-miss that solves a simpler adjacent problem. State what it gets wrong before you commit.
- Prefer the smallest correct change. Scope creep is a bug. Touch only what the task needs.

Operating rules:
- Ground every claim in the provided <context>. Quote file paths and source URLs when relevant. Never invent an API, a function name, or a file path you have not seen in the context.
- If the context does not contain enough information to answer responsibly, say so in the verdict and stop — do not guess.
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


# ---- Adaptive reasoning-effort prompts ----
#
# These power the `effort` parameter. The whole point is cheap-but-deep:
# spend tokens proportional to task difficulty. A triage call sizes the
# task; a critique→revise round fixes the plan's biggest flaw; an
# alt-plan→synthesis round (for `max`) explores a genuinely different
# approach before committing.

TRIAGE_INSTRUCTION = """Rate how much careful reasoning this coding task needs, on a 1-5 scale.

1 = trivial (rename, typo, one-line change, obvious lookup)
2 = simple (small function, clear requirements, low blast radius)
3 = moderate (multiple files or edge cases, some design choices)
4 = hard (concurrency, security, data integrity, or subtle correctness)
5 = critical (irreversible, security-sensitive, or wide blast radius)

Task: {task}

Judge by the failure cost and the number of non-obvious decisions, not by length. Respond with exactly this XML and nothing else:

<complexity>N</complexity>
<reason>One short phrase: the single factor that drove the rating.</reason>
"""

CRITIQUE_PLAN_INSTRUCTION = """Critique the plan you just produced. Find its single biggest weakness — the one flaw most likely to cause a bug, a security hole, or rework. Be specific and concrete; name the step and the failure it invites.

If the plan is genuinely solid with no material weakness, say exactly that.

Respond with exactly this XML structure and nothing else:

<critique>One paragraph: the single biggest weakness and the concrete failure it would cause, OR "no material weakness found".</critique>
"""

REVISE_PLAN_INSTRUCTION = """Given your critique above, produce an improved plan that resolves the weakness you identified. Keep what was already good; change only what the critique requires. If the critique found no material weakness, return the same plan unchanged.

Respond with exactly this XML structure and nothing else:

<plan>
1. First concrete step.
2. Second concrete step.
...
</plan>
<tradeoffs>
- Option A (chosen): why.
- Option B (rejected): why.
</tradeoffs>
<verdict>One paragraph: is the revised approach sound? End with "ship" / "do not ship without resolving X".</verdict>
"""

ALT_PLAN_INSTRUCTION = """Set aside the plan you just produced. Solve the same task a genuinely different way — a different data structure, a different decomposition, or a different point in the design space. Do not just reword the first plan; if you cannot find a real alternative, say so in the verdict.

Respond with exactly this XML structure and nothing else:

<plan>
1. First concrete step of the alternative approach.
2. ...
</plan>
<tradeoffs>
- What this alternative is better at than the first plan.
- What it is worse at.
</tradeoffs>
<verdict>One paragraph: when this alternative beats the first plan. End with "ship" / "do not ship without resolving X".</verdict>
"""

SYNTHESIZE_PLAN_INSTRUCTION = """You now have two candidate plans above (the original and the alternative). Choose the better one, or synthesize a plan that takes the strongest elements of each. Justify the choice in one line inside the verdict.

Respond with exactly this XML structure and nothing else:

<plan>
1. First concrete step of the chosen/synthesized plan.
2. ...
</plan>
<tradeoffs>
- Why this beats both candidates (or which candidate it is and why).
</tradeoffs>
<verdict>One paragraph: final verdict on the chosen approach. End with "ship" / "do not ship without resolving X".</verdict>
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


def current_triage() -> str:
    return _current("triage", TRIAGE_INSTRUCTION)


def current_critique_plan() -> str:
    return _current("critique_plan", CRITIQUE_PLAN_INSTRUCTION)


def current_revise_plan() -> str:
    return _current("revise_plan", REVISE_PLAN_INSTRUCTION)


def current_alt_plan() -> str:
    return _current("alt_plan", ALT_PLAN_INSTRUCTION)


def current_synthesize_plan() -> str:
    return _current("synthesize_plan", SYNTHESIZE_PLAN_INSTRUCTION)


__all__ = [
    "SYSTEM_PROMPT",
    "PLAN_INSTRUCTION",
    "DRAFT_INSTRUCTION",
    "SELFCHECK_REASON_INSTRUCTION",
    "SELFCHECK_GENERATE_INSTRUCTION",
    "TRIAGE_INSTRUCTION",
    "CRITIQUE_PLAN_INSTRUCTION",
    "REVISE_PLAN_INSTRUCTION",
    "ALT_PLAN_INSTRUCTION",
    "SYNTHESIZE_PLAN_INSTRUCTION",
    "configure_prompts",
    "reset_prompts",
    "current_system",
    "current_plan",
    "current_draft",
    "current_selfcheck_reason",
    "current_selfcheck_generate",
    "current_triage",
    "current_critique_plan",
    "current_revise_plan",
    "current_alt_plan",
    "current_synthesize_plan",
]
