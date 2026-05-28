"""Register a custom provider.

Useful when you have an internal model gateway, a local fine-tune you serve
yourself, or a provider essarion_build doesn't ship yet.

Run with:
    python examples/07_custom_provider.py
"""

from __future__ import annotations

from essarion_build import (
    Context,
    LiteRuntime,
    ProviderResponse,
    Usage,
    build_provider,
    register_provider,
    reason,
)


class _MyInternalProvider:
    """Hypothetical wrapper for the team's internal model gateway."""

    def __init__(self, *, api_key: str | None = None, model: str) -> None:
        # In real code, hit your gateway. For this demo we hardcode replies.
        self.model = model
        self._scripted = [
            "<plan>1. validate</plan><tradeoffs>- chosen: strict allow-list</tradeoffs><verdict>preliminary: ship</verdict>",
            "<verdict>final: ship</verdict>",
        ]

    def complete(self, *, system, messages, max_tokens):
        if not self._scripted:
            raise RuntimeError("script exhausted")
        text = self._scripted.pop(0)
        return ProviderResponse(text=text, usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


def main() -> None:
    register_provider("internal-gw", _MyInternalProvider)

    prov = build_provider(name="internal-gw", api_key=None, model="house-model-v3")
    r = reason("review the JWT validation", context=Context(), _runtime=LiteRuntime(prov))
    print("PLAN:\n", r.plan)
    print("\nVERDICT:\n", r.verdict)


if __name__ == "__main__":
    main()
