"""jsDelivr provider (default).

jsDelivr serves transformed ESM at ``/npm/<name>@<range>/+esm`` and resolves
ranges via redirect to a pinned version. Cross-module imports inside the bytes
are root-relative (``/npm/<pkg>@<ver>/+esm``).
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from ..errors import ResolveError
from .base import Provider

ORIGIN = "https://cdn.jsdelivr.net"
DATA_API = "https://data.jsdelivr.com/v1/packages/npm"

# Characters that mean a value is a range/tag rather than an exact version.
_RANGE_CHARS = set("^~*xX <>=|| -")


class JsDelivrProvider(Provider):
    name = "jsdelivr"
    origin = ORIGIN

    def entry_url(self, name: str, range_: str, *, production: bool) -> str:
        # +esm has no prod/dev distinction; range may be empty (latest).
        pkg, subpath = self._split_subpath(name)
        spec = f"{pkg}@{range_}" if range_ else pkg
        tail = f"/{subpath}" if subpath else ""
        return f"{ORIGIN}/npm/{spec}{tail}/+esm"

    async def resolve_entry(
        self, name: str, range_: str, *, production: bool, get_json=None
    ) -> str:
        # jsDelivr's +esm endpoint serves range URLs with HTTP 200 (no redirect),
        # so we must pin the version ourselves via the data API. Otherwise a
        # caret range would vendor a *second*, unpinned copy alongside the pinned
        # copy that sibling modules reference. The version pins on the package;
        # any subpath (e.g. .../debounce) is appended after it.
        if get_json is None:
            raise ResolveError("jsDelivr resolution requires an HTTP client")
        pkg, subpath = self._split_subpath(name)
        version = await self._resolve_version(pkg, range_, get_json)
        tail = f"/{subpath}" if subpath else ""
        return f"{ORIGIN}/npm/{pkg}@{version}{tail}/+esm"

    async def _resolve_version(self, name: str, range_: str, get_json) -> str:
        rng = range_.strip()
        if rng and not (set(rng) & _RANGE_CHARS):
            # Already an exact version or a non-range tag we can use directly.
            return rng
        url = f"{DATA_API}/{name}/resolved"
        if rng:
            url += f"?specifier={quote(rng, safe='')}"
        data = await get_json(url)
        version = data.get("version")
        if not version:
            raise ResolveError(f"jsDelivr could not resolve {name}@{rng or 'latest'}")
        return str(version)

    def is_module_url(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.netloc == "cdn.jsdelivr.net" and parts.path.startswith("/npm/")

    def local_path(self, url: str) -> str:
        # /npm/react@18.2.0/+esm  ->  react@18.2.0/+esm.js
        path = urlsplit(url).path
        if path.startswith("/npm/"):
            path = path[len("/npm/") :]
        path = path.lstrip("/")
        if not path.endswith(".js"):
            path += ".js"
        return path

    def shims_url(self, version: str) -> str:
        return f"{ORIGIN}/npm/es-module-shims@{version}/dist/es-module-shims.js"
