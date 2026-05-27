"""essarion_build — a BYOK reasoning amplification SDK for coding tasks.

Bring your own model provider; the SDK provides the reasoning loop, the
grounding context (codebase, docs, software-dev skills), and the structured
outputs. v0 ships with OpenRouter as the default provider (cheap-model
friendly) and Anthropic as an alternative.
"""

from ._config import configure
from ._context import Context
from ._decorators import ReasonedFunction, list_reasoned, reasoned
from ._generate import Generation, generate
from ._providers import Usage
from ._reasoning import Reasoning, reason
from ._skills import list_skills
from .exceptions import (
    CloudRuntimeNotAvailable,
    ContextError,
    EssarionError,
    ProviderAuthError,
    ProviderError,
    ProviderHTTPError,
    ProviderNotAvailable,
    ProviderRateLimitError,
    ProviderResponseError,
    ReasoningFormatError,
)

__version__ = "0.2.0"

__all__ = [
    "Context",
    "Reasoning",
    "Generation",
    "ReasonedFunction",
    "Usage",
    "reason",
    "generate",
    "reasoned",
    "list_reasoned",
    "list_skills",
    "configure",
    "EssarionError",
    "CloudRuntimeNotAvailable",
    "ProviderNotAvailable",
    "ProviderError",
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ProviderHTTPError",
    "ProviderResponseError",
    "ContextError",
    "ReasoningFormatError",
    "__version__",
]
