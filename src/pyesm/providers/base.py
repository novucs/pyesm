"""The ``Provider`` interface.

CDN-built ESM references siblings by root-relative path (e.g.
``/npm/react@18.2.0/+esm``). So the import-map key is that root-relative
string, while the module's canonical identity is the absolute CDN URL
(``origin + path``).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit


@dataclass
class Metadata:
    """Optional CDN-provided dependency/integrity info for a module URL."""

    deps: list[str]
    integrity: str | None = None


class Provider(abc.ABC):
    name: str
    origin: str  # e.g. "https://cdn.jsdelivr.net"

    @staticmethod
    def _split_subpath(name: str) -> tuple[str, str]:
        """Split a bare specifier into ``(package, subpath)``; scope-aware.

        ``lodash-es/debounce`` -> ``("lodash-es", "debounce")``;
        ``react`` -> ``("react", "")``.
        """
        if name.startswith("@"):
            parts = name.split("/", 2)
            return "/".join(parts[:2]), parts[2] if len(parts) > 2 else ""
        pkg, _, subpath = name.partition("/")
        return pkg, subpath

    @abc.abstractmethod
    def entry_url(self, name: str, range_: str, *, production: bool) -> str:
        """The ESM endpoint to request for a bare ``name@range`` (+ subpath)."""

    async def resolve_entry(
        self, name: str, range_: str, *, production: bool, get_json=None
    ) -> str:
        """Return a version-pinned entry URL for ``name@range``.

        Default relies on the CDN redirecting a range URL to a pinned one;
        providers whose endpoint does not redirect override this to pin via a
        metadata API. ``get_json(url) -> dict`` is the injectable async fetch.
        """
        return self.entry_url(name, range_, production=production)

    @abc.abstractmethod
    def is_module_url(self, url: str) -> bool:
        """Does this absolute URL belong to this CDN's module space?

        Such URLs should be vendored and remapped; anything else is left alone.
        """

    @abc.abstractmethod
    def local_path(self, url: str) -> str:
        """Local path (under ``output-dir``) for a vendored module URL."""

    @abc.abstractmethod
    def shims_url(self, version: str) -> str:
        """URL of the raw (classic IIFE) es-module-shims script on this CDN."""

    def absolutize(self, referrer: str, specifier: str) -> str:
        """Resolve an in-byte ``specifier`` (found inside ``referrer``) to an
        absolute CDN URL.

        Root-relative specifiers (``/npm/...``) resolve against the provider
        origin; already-absolute specifiers pass through ``urljoin``.
        """
        if specifier.startswith("//"):
            scheme = urlsplit(self.origin).scheme
            return f"{scheme}:{specifier}"
        if specifier.startswith("/"):
            return self.origin + specifier
        return urljoin(referrer, specifier)

    def import_map_key(self, url: str) -> str:
        """The import-map key for a module URL: the in-byte specifier form.

        This is the absolute CDN URL minus the origin (path + query), i.e. the
        exact root-relative string the browser will try to resolve.
        """
        parts = urlsplit(url)
        key = parts.path
        if parts.query:
            key += "?" + parts.query
        return key

    async def metadata(self, client, url: str) -> Metadata | None:  # noqa: D401
        """Optional: CDN metadata endpoint (deps/integrity). Default: none."""
        return None
