"""Provider registry. No provider may require Node."""

from __future__ import annotations

from ..errors import ConfigError
from .base import Provider
from .esmsh import EsmShProvider
from .jsdelivr import JsDelivrProvider


def get_provider(name: str) -> Provider:
    """Return a provider instance by config name."""
    if name == "jsdelivr":
        return JsDelivrProvider()
    if name in ("esmsh", "esm.sh"):
        return EsmShProvider()
    raise ConfigError(f"unknown provider {name!r}; expected 'jsdelivr' or 'esmsh'")


__all__ = ["Provider", "get_provider"]
