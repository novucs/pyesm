"""The resolve pipeline: pyproject deps -> crawled graph -> ``Lock``.

Async; ``resolve()`` is a synchronous wrapper via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from . import http
from .config import Config
from .crawler import Crawler, FetchFn
from .hashing import sri_hash
from .lockfile import Lock, Module, ShimAsset
from .providers import get_provider
from .resolver import resolve_graph
from .shims import ESMS_VERSION, should_inject


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
                return await http.get_module(client, url)

            async def gj(url: str) -> dict:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()

            return await _resolve(config, prov_name, provider, fetch or f, get_json or gj)
    return await _resolve(config, prov_name, provider, fetch, get_json)


async def _resolve(config, prov_name, provider, fetch, get_json) -> Lock:
    # Each dependency key is "<package>[/<subpath>]"; the value is the range.
    user_deps = [
        (specifier, *provider._split_subpath(specifier), str(range_).strip())
        for specifier, range_ in config.dependencies.items()
    ]

    # Resolve the whole graph to one version per package (semver dedup), and
    # build a rewrite that maps any in-byte module URL to the resolved version.
    resolved: dict[str, str] = {}
    rewrite: Callable[[str], str] | None = None
    if provider.supports_dedup and user_deps:

        async def _fetch_packument(pkg: str) -> dict:
            data = await get_json(provider.versions_url(pkg))
            # the singular endpoint already gives version strings
            return {"versions": data.get("versions", []), "tags": data.get("tags", {})}

        async def _fetch_manifest(pkg: str, ver: str) -> dict:
            return await get_json(provider.manifest_url(pkg, ver))

        resolved = await resolve_graph(
            [(pkg, rng) for _, pkg, _, rng in user_deps],
            fetch_packument=_fetch_packument,
            fetch_manifest=_fetch_manifest,
            concurrency=config.concurrency,
        )

        def _rewrite(url: str) -> str:
            parsed = provider.parse_module(url)
            if parsed is None:
                return url
            pkg, _, subpath = parsed
            ver = resolved.get(pkg)
            return provider.build_module(pkg, ver, subpath) if ver else url

        rewrite = _rewrite

    # Entry request URL per user dependency (from the resolved version).
    entry_requests: dict[str, str] = {}
    for specifier, pkg, subpath, rng in user_deps:
        ver = resolved.get(pkg)
        if ver is not None:
            entry_requests[specifier] = provider.build_module(pkg, ver, subpath)
        else:
            entry_requests[specifier] = await provider.resolve_entry(
                specifier, rng, production=config.production, get_json=get_json
            )

    crawler = Crawler(provider, fetch=fetch, concurrency=config.concurrency, rewrite=rewrite)
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
