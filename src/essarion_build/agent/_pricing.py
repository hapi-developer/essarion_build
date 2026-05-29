"""Pre-flight cost prediction for a context + model.

The session's cost meter is honest — it shows what we actually spent.
But that doesn't help if the user sends a context that's accidentally
huge ("attached the whole repo, forgot to filter"). This module makes
the *projected* cost visible BEFORE the call so the user can trim if
they need to.

How: we know the per-Mtok input price (from `_session._PRICE_TABLE`),
we estimate the prompt size with `Context.estimate_tokens()`, and we
multiply.

We deliberately under-estimate completion cost (assume only the
existing `max_tokens` cap, not the full budget). Users care about input
size — that's the main lever they have.
"""

from __future__ import annotations

from .. import Context
from ._session import _PRICE_TABLE


def estimate_input_cost_usd(
    context: Context, *, provider: str, model: str
) -> tuple[int, float]:
    """Return `(estimated_input_tokens, projected_input_cost_usd)`.

    Cost is 0.0 when the model isn't in our price table — we don't
    pretend to know prices we haven't catalogued.
    """
    tokens = context.estimate_tokens()
    for (p, m_sub), (in_p, _out_p) in _PRICE_TABLE.items():
        if p == provider and (m_sub == "" or m_sub in model):
            return tokens, (tokens / 1_000_000) * in_p
    return tokens, 0.0


def estimate_turn_cost_usd(
    context: Context,
    *,
    provider: str,
    model: str,
    max_tokens: int,
    n_calls: int = 3,
) -> tuple[int, float]:
    """Estimate a full reason+draft+selfcheck turn.

    Three calls × prompt-tokens-each (since the SDK reuses the cached
    system block) + n_calls × completion-tokens-each. Conservative.
    """
    input_tokens = context.estimate_tokens()
    for (p, m_sub), (in_p, out_p) in _PRICE_TABLE.items():
        if p == provider and (m_sub == "" or m_sub in model):
            input_cost = (n_calls * input_tokens / 1_000_000) * in_p
            # Assume the model uses ~30% of max_tokens per call on average.
            output_cost = (n_calls * max_tokens * 0.30 / 1_000_000) * out_p
            return input_tokens, input_cost + output_cost
    return input_tokens, 0.0


def format_cost(cost_usd: float) -> str:
    """Pretty-print a USD cost. Tiny costs are shown with extra precision."""
    if cost_usd == 0:
        return "$0.00"
    if cost_usd < 0.001:
        return f"${cost_usd:.5f}"
    if cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    return f"${cost_usd:.3f}"


__all__ = ["estimate_input_cost_usd", "estimate_turn_cost_usd", "format_cost"]
