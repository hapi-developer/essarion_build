"""essarion_build — a BYOK reasoning amplification SDK for coding tasks.

Bring your own model provider; the SDK provides the reasoning loop, the
grounding context (codebase, docs, software-dev skills), and the structured
outputs. v0.3 ships:

- 6 providers (OpenRouter default, plus Anthropic, OpenAI, Gemini, Ollama, Stub)
- sync API: `reason()`, `generate()`
- async API: `areason()`, `agenerate()`
- streaming: `stream_reason()`, `stream_generate()`
- multi-turn: `Conversation`
- response cache: `ResponseCache`, `CachingProvider`
- high-level workflows: `review`, `fix_bug`, `write_tests`, `refactor`, `docs`
- custom providers and custom skills
- CLI: `essarion-build`
"""

from . import auth, evals, recipes, redact, validators, workflows
from ._async_api import agenerate, areason
from ._async_streaming import astream_generate, astream_reason
from ._batch import BatchResult, batch_generate, batch_reason, run_batch
from ._async_providers import (
    AsyncProvider,
    AsyncStubProvider,
    build_async_provider,
    register_async_provider,
    unregister_async_provider,
)
from ._async_runtime import AsyncLiteRuntime, AsyncRuntime, select_async_runtime
from ._cache import CachingProvider, ResponseCache
from ._compaction import compact, keep_only_files, truncate_files
from ._config import configure
from ._config_file import load_config_file, starter_skills
from ._effort import (
    EFFORT_LEVELS,
    VALID_EFFORTS,
    approx_generate_calls,
    approx_reason_calls,
)
from ._context import Context, Diff
from ._conversation import Conversation, ConversationTurn
from ._decorators import ReasonedFunction, list_reasoned, reasoned
from ._generate import Generation, generate
from ._providers import (
    Provider,
    ProviderResponse,
    StreamChunk,
    StreamingProvider,
    StubProvider,
    Usage,
    build_provider,
    list_providers,
    register_provider,
    unregister_provider,
)
from ._reasoning import Reasoning, reason
from ._schemas import SchemaValidationError, agenerate_json, generate_json
from ._runtime import LiteRuntime, Runtime, select_runtime
from ._skills import list_skills, load_skill
from ._prompts import configure_prompts, reset_prompts
from .tools import (
    Tool,
    list_tools,
    register_tool,
    run_tools_in_plan,
    tool_manifest,
    unregister_tool,
)
from ._content import image_block, text_block  # multimodal message blocks
from . import computer  # reactive computer-use toolkit (browser tier; opt-in)
from ._streaming import ReasoningEvent, stream_generate, stream_reason
from ._telemetry import TelemetryCallback, configure_telemetry
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

__version__ = "0.3.3"

__all__ = [
    # Subpackages
    "computer",
    # Core types
    "Context",
    "Diff",
    "Reasoning",
    "Generation",
    "ReasonedFunction",
    "Usage",
    "Provider",
    "ProviderResponse",
    "StreamChunk",
    "StreamingProvider",
    "AsyncProvider",
    "Conversation",
    "ConversationTurn",
    "ReasoningEvent",
    # Sync API
    "reason",
    "generate",
    "generate_json",
    "stream_reason",
    "stream_generate",
    # Async API
    "areason",
    "agenerate",
    "agenerate_json",
    "astream_reason",
    "astream_generate",
    # Batch
    "batch_reason",
    "batch_generate",
    "run_batch",
    "BatchResult",
    # Decorators
    "reasoned",
    "list_reasoned",
    # Skills / providers / config
    "list_skills",
    "load_skill",
    "list_providers",
    "register_provider",
    "unregister_provider",
    "register_async_provider",
    "unregister_async_provider",
    "configure",
    "load_config_file",
    "starter_skills",
    # Reasoning effort (adaptive depth)
    "EFFORT_LEVELS",
    "VALID_EFFORTS",
    "approx_reason_calls",
    "approx_generate_calls",
    # Cache
    "ResponseCache",
    "CachingProvider",
    # Compaction
    "compact",
    "truncate_files",
    "keep_only_files",
    # Telemetry
    "configure_telemetry",
    "TelemetryCallback",
    # Prompt overrides
    "configure_prompts",
    "reset_prompts",
    # Tool registry (model-side, opt-in)
    "Tool",
    "register_tool",
    "unregister_tool",
    "list_tools",
    "run_tools_in_plan",
    "tool_manifest",
    # Multimodal content (vision)
    "image_block",
    "text_block",
    # Stub provider (for users' tests)
    "StubProvider",
    "AsyncStubProvider",
    # Runtimes (mostly internal, exposed for power users)
    "Runtime",
    "AsyncRuntime",
    "LiteRuntime",
    "AsyncLiteRuntime",
    "select_runtime",
    "select_async_runtime",
    "build_provider",
    "build_async_provider",
    # Exceptions
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
    "SchemaValidationError",
    "auth",
    "evals",
    "recipes",
    "redact",
    "validators",
    "workflows",
    "__version__",
]
