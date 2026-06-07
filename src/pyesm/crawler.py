"""Async crawler over a CDN ESM module graph.

The graph is walked level by level: each frontier is fetched concurrently
(bounded by a semaphore), and its unseen children become the next frontier.

Each fetch follows redirects, so the canonical (pinned) URL is recorded while
the in-byte specifier becomes the module's import-map key.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .hashing import sri_hash
from .providers.base import Provider
from .scanner import scan_imports

# fetch(request_url) -> (canonical_url, raw_bytes)
FetchFn = Callable[[str], Awaitable["tuple[str, bytes]"]]


@dataclass
class CrawlModule:
    url: str  # canonical (pinned) CDN URL
    integrity: str
    deps: set[str] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)


@dataclass
class CrawlResult:
    modules: dict[str, CrawlModule]  # canonical url -> module
    request_to_canonical: dict[str, str]


class Crawler:
    def __init__(
        self,
        provider: Provider,
        *,
        fetch: FetchFn,
        concurrency: int = 16,
    ) -> None:
        self.provider = provider
        self.fetch = fetch
        self.concurrency = concurrency
        self._modules: dict[str, CrawlModule] = {}
        self._req_to_can: dict[str, str] = {}
        self._edges: list[tuple[str, str]] = []  # (parent_canonical, child_request)

    async def crawl(self, entry_urls: list[str]) -> CrawlResult:
        """Crawl from the given entry request URLs and return the graph."""
        sem = asyncio.Semaphore(self.concurrency)
        seen: set[str] = set(entry_urls)
        frontier = list(entry_urls)

        while frontier:
            results = await asyncio.gather(*(self._fetch_one(sem, req) for req in frontier))
            next_frontier: list[str] = []
            for req, canonical, raw in results:
                self._req_to_can[req] = canonical
                if canonical in self._modules:
                    continue  # already scanned via another request URL
                self._modules[canonical] = CrawlModule(url=canonical, integrity=sri_hash(raw))
                for child in self._children(canonical, raw):
                    self._edges.append((canonical, child))
                    if child not in seen:
                        seen.add(child)
                        next_frontier.append(child)
            frontier = next_frontier

        return self._finalize()

    async def _fetch_one(self, sem: asyncio.Semaphore, request_url: str) -> tuple[str, str, bytes]:
        async with sem:
            canonical, raw = await self.fetch(request_url)
        return request_url, canonical, raw

    def _children(self, parent_canonical: str, raw: bytes) -> list[str]:
        text = raw.decode("utf-8", errors="replace")
        out: list[str] = []
        for spec in scan_imports(text):
            # CDN-built ESM references siblings only by root-relative (/npm/...)
            # or absolute URL. A relative specifier is a scanner false positive
            # (import/from text inside a string literal, common in syntax-
            # highlighting packages); resolving it would urljoin a bogus
            # same-CDN URL that 404s, so skip it.
            if not (spec.startswith("/") or "://" in spec):
                continue
            child = self.provider.absolutize(parent_canonical, spec)
            if self.provider.is_module_url(child):
                out.append(child)
        return out

    def _finalize(self) -> CrawlResult:
        for parent_can, child_req in self._edges:
            child_can = self._req_to_can.get(child_req)
            if child_can is None:
                continue
            self._modules[parent_can].deps.add(child_can)
            # The import-map key is the in-byte specifier form: the request URL's
            # path+query (root-relative), which the browser resolves against the
            # deployment origin. Attach it to the *resolved* (canonical) module.
            self._modules[child_can].keys.add(self.provider.import_map_key(child_req))
        return CrawlResult(
            modules=self._modules,
            request_to_canonical=dict(self._req_to_can),
        )
