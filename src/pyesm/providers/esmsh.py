"""esm.sh provider.

esm.sh serves ESM at ``/<name>@<range>`` and resolves ranges via redirect.
Cross-module imports inside the bytes are root-relative and may be unpinned
with a query string (e.g. ``/scheduler@^0.23.0?target=es2022``); following the
redirect pins them. esm.sh also exposes a ``?meta`` endpoint for
dependency/integrity info.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .base import Metadata, Provider

ORIGIN = "https://esm.sh"


class EsmShProvider(Provider):
    name = "esmsh"
    origin = ORIGIN

    def entry_url(self, name: str, range_: str, *, production: bool) -> str:
        pkg, subpath = self._split_subpath(name)
        spec = f"{pkg}@{range_}" if range_ else pkg
        tail = f"/{subpath}" if subpath else ""
        url = f"{ORIGIN}/{spec}{tail}"
        if not production:
            url += "?dev"
        return url

    def is_module_url(self, url: str) -> bool:
        return urlsplit(url).netloc == "esm.sh"

    def local_path(self, url: str) -> str:
        parts = urlsplit(url)
        path = parts.path.lstrip("/")
        # Fold a target query (e.g. ?target=es2022) into the path so distinct
        # build targets vendor to distinct files. Final pinned URLs usually have
        # no query, but be defensive.
        if parts.query:
            safe = parts.query.replace("&", "_").replace("=", "-")
            path = f"{path}__{safe}"
        if not path.endswith((".js", ".mjs")):
            path += ".mjs"
        return path

    def shims_url(self, version: str) -> str:
        # ?raw bypasses esm.sh's ESM transform so we get the classic IIFE script.
        return f"{ORIGIN}/es-module-shims@{version}/dist/es-module-shims.js?raw"

    async def metadata(self, client, url: str) -> Metadata | None:
        """Fetch esm.sh ``?meta`` for ``url``; ``None`` on any failure."""
        sep = "&" if urlsplit(url).query else "?"
        try:
            resp = await client.get(url + sep + "meta")
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None
        deps = data.get("deps") or data.get("dependencies") or []
        if isinstance(deps, dict):
            deps = list(deps.values())
        integrity = data.get("integrity")
        return Metadata(deps=[str(d) for d in deps], integrity=integrity)
