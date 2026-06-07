"""Exception hierarchy for pyesm."""

from __future__ import annotations


class PyesmError(Exception):
    """Base class for all pyesm errors."""


class ConfigError(PyesmError):
    """Invalid or missing ``[tool.pyesm]`` configuration."""


class ResolveError(PyesmError):
    """A dependency could not be resolved against the provider."""


class HashMismatchError(PyesmError):
    """Vendored bytes do not match the integrity recorded in the lock."""

    def __init__(self, url: str, expected: str, actual: str) -> None:
        self.url = url
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"integrity mismatch for {url}\n  expected {expected}\n  actual   {actual}"
        )


class StaleLockError(PyesmError):
    """``pyesm.lock`` is missing or out of date relative to pyproject.toml."""


class OfflineColdCacheError(PyesmError):
    """``--offline`` was requested but a needed module is not in the cache."""


class LockNotFoundError(PyesmError):
    """No ``pyesm.lock`` exists where one was required."""
