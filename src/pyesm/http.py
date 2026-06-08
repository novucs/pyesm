"""The shared ``httpx.AsyncClient``. httpx is imported lazily so no-network
paths stay cheap to start."""

from __future__ import annotations

import re

USER_AGENT = "pyesm"
TIMEOUT = 30.0

# A trailing `//# sourceMappingURL=…` comment that points at an external map.
# Inline `data:` maps are left alone (they resolve offline).
_SOURCE_MAP_COMMENT = re.compile(rb"\n?[ \t]*//[#@][ \t]*sourceMappingURL=(?!data:)\S*[ \t\r\n]*\Z")

# jsDelivr prepends a banner to its generated files (`Bundled by jsDelivr` on
# `+esm` bundles, `Minified by jsDelivr` on `.min.js`). Signature-gated to the
# leading block comment so a package's own `/*! @license … */` is never touched.
_JSDELIVR_BANNER = re.compile(rb"\A/\*\*.*?(?:Bundled|Minified) by jsDelivr.*?\*/\r?\n?", re.DOTALL)


def make_client(concurrency: int = 16):
    """Return a configured ``httpx.AsyncClient``."""
    import httpx

    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=concurrency),
    )


def strip_source_map(raw: bytes) -> bytes:
    """Drop a trailing external source-map comment from a fetched module.

    CDN ``+esm`` bundles end with ``//# sourceMappingURL=/sm/<hash>.map``, a
    CDN-only path that 404s once the module is self-hosted. Stripping it (rather
    than vendoring an unreachable map) keeps the browser console clean. Applied
    at every module fetch so the integrity hash is taken over the served bytes.
    """
    return _SOURCE_MAP_COMMENT.sub(b"", raw)


def strip_jsdelivr_banner(raw: bytes) -> bytes:
    """Drop jsDelivr's leading ``+esm`` build banner.

    It carries volatile build-tool versions (``Rollup vX, Terser vY``), which
    would churn the integrity hash on every jsDelivr toolchain bump even when the
    code is unchanged, plus a "Do NOT use SRI with dynamically generated files"
    notice that applies to loading from the CDN, not to a self-hosted frozen copy.
    Only jsDelivr's own banner is removed, never a package's license header.
    """
    return _JSDELIVR_BANNER.sub(b"", raw)


async def get_module(client, url: str) -> tuple[str, bytes]:
    """Fetch a module: return ``(canonical_url, bytes)`` with CDN-injected
    boilerplate (jsDelivr banner + trailing source-map comment) removed. The
    single choke point for module bytes, so lock-time and sync-time fetches hash
    identical content."""
    resp = await client.get(url)
    resp.raise_for_status()
    return str(resp.url), strip_source_map(strip_jsdelivr_banner(resp.content))
