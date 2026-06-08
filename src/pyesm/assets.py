"""Vendor raw CSS plus its ``@import`` / ``url()`` asset closure (fonts, images).

Unlike the JS crawler, which follows ESM imports and remaps versions through the
import map, CSS references are vendored as-is at their relative paths: a
``url(fonts/x.woff2)`` inside a stylesheet resolves against the vendored copy
with no byte rewriting, as long as the directory structure is preserved.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

from .hashing import sri_hash
from .providers.base import Provider

# fetch(request_url) -> (canonical_url, raw_bytes)
FetchFn = Callable[[str], Awaitable["tuple[str, bytes]"]]

# @import "x"  |  @import url(x)  |  @import url("x")
_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(['"]?)([^'")\s]+)\1""", re.IGNORECASE)
# url(x) | url("x") | url('x')
_URL = re.compile(r"""\burl\(\s*(['"]?)([^'")]+?)\1\s*\)""", re.IGNORECASE)


def scan_css(text: str) -> list[str]:
    """Return the ``@import`` / ``url()`` references in CSS, deduped in order."""
    seen: set[str] = set()
    out: list[str] = []
    for pat in (_IMPORT, _URL):
        for m in pat.finditer(text):
            ref = m.group(2).strip()
            if ref and ref not in seen:
                seen.add(ref)
                out.append(ref)
    return out


def _followable(ref: str) -> bool:
    """Vendor only relative references; leave data URIs, fragment-only refs, and
    external/protocol-relative URLs untouched."""
    return not (ref.lower().startswith(("data:", "#")) or "://" in ref or ref.startswith("//"))


class AssetCrawler:
    """BFS over CSS files, vendoring each file and the assets it references."""

    def __init__(self, provider: Provider, *, fetch: FetchFn, concurrency: int = 16) -> None:
        self.provider = provider
        self.fetch = fetch
        self.concurrency = concurrency
        self._origin = urlsplit(provider.origin).netloc

    async def crawl(self, entry_urls: list[str]) -> tuple[dict[str, tuple[str, str]], list[str]]:
        """Vendor the entry CSS plus their closure.

        Returns ``(assets, entry_paths)`` where ``assets`` maps each canonical
        URL to ``(local_path, integrity)`` and ``entry_paths`` is the local path
        of each entry stylesheet (for ``<link>``).
        """
        sem = asyncio.Semaphore(self.concurrency)
        assets: dict[str, tuple[str, str]] = {}
        req_to_can: dict[str, str] = {}
        seen: set[str] = set(entry_urls)
        frontier = list(entry_urls)

        while frontier:
            results = await asyncio.gather(*(self._fetch_one(sem, u) for u in frontier))
            next_frontier: list[str] = []
            for req, canonical, raw in results:
                req_to_can[req] = canonical
                if canonical in assets:
                    continue
                assets[canonical] = (self.provider.asset_local_path(canonical), sri_hash(raw))
                if urlsplit(canonical).path.endswith(".css"):
                    for child in self._children(canonical, raw):
                        if child not in seen:
                            seen.add(child)
                            next_frontier.append(child)
            frontier = next_frontier

        entry_paths = [assets[req_to_can[u]][0] for u in entry_urls if req_to_can.get(u) in assets]
        return assets, entry_paths

    async def _fetch_one(self, sem: asyncio.Semaphore, url: str) -> tuple[str, str, bytes]:
        async with sem:
            canonical, raw = await self.fetch(url)
        return url, canonical, raw

    def _children(self, css_url: str, raw: bytes) -> list[str]:
        out: list[str] = []
        for ref in scan_css(raw.decode("utf-8", errors="replace")):
            if not _followable(ref):
                continue
            # strip fragment/query before resolving; the CSS bytes keep the ref
            child = urljoin(css_url, ref.split("#", 1)[0].split("?", 1)[0])
            parts = urlsplit(child)
            if parts.netloc == self._origin and "/npm/" in parts.path:
                out.append(child)
        return out
