"""Platform API auth helpers. Stub in v0."""

from __future__ import annotations


def from_platform_api(token: str) -> None:
    """Exchange an Essarion Platform API token for runtime credentials.

    Stub in v0; lands when the Platform API is publicly exposed.
    """
    raise NotImplementedError(
        "Platform API auth is coming soon. "
        "For now, pass api_key=... directly to configure() or as an env var."
    )
