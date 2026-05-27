"""Exception hierarchy for essarion_build."""


class EssarionError(Exception):
    """Base class for all essarion_build errors."""


class CloudRuntimeNotAvailable(EssarionError):
    """Raised when CloudRuntime is requested but the backend is not yet callable."""


class ProviderNotAvailable(EssarionError):
    """Raised when a provider name is recognized but not implemented in this release."""


class ContextError(EssarionError):
    """Raised when Context construction or rendering fails."""


class ProviderError(EssarionError):
    """Base for runtime errors raised by a Provider during a `complete()` call."""


class ProviderAuthError(ProviderError):
    """The provider rejected the API key (HTTP 401 / 403)."""


class ProviderRateLimitError(ProviderError):
    """The provider rate-limited the request (HTTP 429)."""


class ProviderHTTPError(ProviderError):
    """The provider returned a non-2xx response that isn't auth or rate-limit."""


class ProviderResponseError(ProviderError):
    """The provider returned a 2xx response that couldn't be parsed."""


class ReasoningFormatError(EssarionError):
    """The model's structured output is missing required tags after a repair pass."""
