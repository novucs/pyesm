"""The resolve pipeline: pyproject deps -> crawled graph -> ``Lock``.

Async; ``resolve()`` is a synchronous wrapper via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

from . import http
from .config import Config
from .crawler import Crawler, FetchFn
from .hashing import sri_hash
from .lockfile import Lock, Module, ShimAsset
from .providers import get_provider
from .shims import ESMS_VERSION, should_inject


def _split_spec(name: str, range_: str) -> tuple[str, str]:
    # A dependency key is the package name; the value is the range. Ranges like
    # "^18.2.0", "3", "2", or "" (latest) are passed through to the provider.
    return name, str(range_).strip()


async def resolve_async(
    config: Config,
    *,
    provider_name: str | None = None,
    fetch: FetchFn | None = None,
    get_json=None,
) -> Lock:
    """Resolve all dependencies and return a fully populated :class:`Lock`."""
    prov_name = provider_name or config.provider
    provider = get_provider(prov_name)

    if fetch is None or get_json is None:
        async with http.make_client(config.concurrency) as client:

            async def f(url: str) -> tuple[str, bytes]:
                resp = await client.get(url)
                resp.raise_for_status()
                return str(resp.url), resp.content

            async def gj(url: str) -> dict:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()

            return await _resolve(config, prov_name, provider, fetch or f, get_json or gj)
    return await _resolve(config, prov_name, provider, fetch, get_json)


async def _resolve(config, prov_name, provider, fetch, get_json) -> Lock:
    # Pin each bare specifier to a version-pinned entry request URL.
    entry_requests: dict[str, str] = {}
    for name, range_ in config.dependencies.items():
        pkg, rng = _split_spec(name, range_)
        entry_requests[name] = await provider.resolve_entry(
            pkg, rng, production=config.production, get_json=get_json
        )

    crawler = Crawler(provider, fetch=fetch, concurrency=config.concurrency)
    result = await crawler.crawl(list(entry_requests.values()))

    # bare specifier -> canonical (pinned) entry URL
    imports: dict[str, str] = {}
    for name, req_url in entry_requests.items():
        canonical = result.request_to_canonical.get(req_url)
        if canonical is not None:
            imports[name] = canonical

    modules = [
        Module(
            url=cm.url,
            path=provider.local_path(cm.url),
            integrity=cm.integrity,
            deps=sorted(cm.deps),
            keys=sorted(cm.keys),
        )
        for cm in result.modules.values()
    ]

    shims = None
    if should_inject(config.shims):
        shims_url = provider.shims_url(ESMS_VERSION)
        _, raw = await fetch(shims_url)
        shims = ShimAsset(
            url=shims_url,
            path=f"es-module-shims@{ESMS_VERSION}.js",
            integrity=sri_hash(raw),
        )

    return Lock(
        provider=prov_name,
        inputs_hash=config.inputs_hash(),
        imports=imports,
        modules=modules,
        shims=shims,
    )


def resolve(
    config: Config,
    *,
    provider_name: str | None = None,
    fetch: FetchFn | None = None,
    get_json=None,
) -> Lock:
    """Synchronous wrapper around :func:`resolve_async`."""
    return asyncio.run(
        resolve_async(config, provider_name=provider_name, fetch=fetch, get_json=get_json)
    )
