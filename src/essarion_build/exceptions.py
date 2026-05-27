"""Exception hierarchy for essarion_build."""


class EssarionError(Exception):
    """Base class for all essarion_build errors."""


class CloudRuntimeNotAvailable(EssarionError):
    """Raised when CloudRuntime is requested but the backend is not yet callable."""


class ProviderNotAvailable(EssarionError):
    """Raised when a provider name is recognized but not implemented in this release."""


class ContextError(EssarionError):
    """Raised when Context construction or rendering fails."""
