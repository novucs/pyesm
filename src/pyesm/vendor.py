"""``sync``: make the local ``output-dir`` match the lock.

Downloads missing modules (through the global cache) concurrently, materializes
them via hardlink/copy, verifies every file's integrity, and prunes anything
not in the lock. Offline and effectively instant when the cache is warm.

Async underneath (concurrent downloads bounded by ``concurrency``); ``sync()``
is a synchronous wrapper via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from . import http
from .cache import Cache, materialize
from .errors import HashMismatchError
from .hashing import sri_hash
from .lockfile import Lock


@dataclass
class SyncReport:
    downloaded: int = 0
    reused: int = 0
    pruned: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pruned is None:
            self.pruned = []


async def sync_async(
    lock: Lock,
    output_dir: Path,
    *,
    cache: Cache | None = None,
    fetch=None,
    offline: bool = False,
    protect: set[str] | None = None,
    concurrency: int = 16,
) -> SyncReport:
    """Vendor every module in ``lock`` into ``output_dir`` and verify it."""
    cache = cache or Cache()
    protect = protect or set()
    report = SyncReport()

    output_dir.mkdir(parents=True, exist_ok=True)
    expected = {m.path for m in lock.modules} | set(protect)
    if lock.shims is not None:
        expected.add(lock.shims.path)

    # 1. Prune files not in the lock (keep protected paths, e.g. importmap.json).
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_dir():
            continue
        rel = path.relative_to(output_dir).as_posix()
        if rel not in expected:
            path.unlink()
            report.pruned.append(rel)

    # 2. Ensure cache + materialize + verify each module (downloads in parallel).
    if fetch is None and not offline:
        async with http.make_client(concurrency) as client:

            async def dl(url: str) -> bytes:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content

            await _materialize_all(lock, output_dir, cache, dl, offline, concurrency, report)
    else:
        await _materialize_all(lock, output_dir, cache, fetch, offline, concurrency, report)

    # 3. Remove now-empty directories left by pruning.
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()

    return report


async def _materialize_all(lock, output_dir, cache, fetch, offline, concurrency, report):
    sem = asyncio.Semaphore(concurrency)

    async def one(module):
        async with sem:
            had = cache.has(module.integrity)
            cache_path = await cache.ensure_async(
                module.url, module.integrity, fetch=fetch, offline=offline
            )
        dest = output_dir / module.path
        materialize(cache_path, dest)
        actual = sri_hash(dest.read_bytes())
        if actual != module.integrity:
            raise HashMismatchError(module.url, module.integrity, actual)
        return had

    items = [*lock.modules, *([lock.shims] if lock.shims is not None else [])]
    results = await asyncio.gather(*(one(m) for m in items))
    for had in results:
        if had:
            report.reused += 1
        else:
            report.downloaded += 1


def sync(
    lock: Lock,
    output_dir: Path,
    *,
    cache: Cache | None = None,
    fetch=None,
    offline: bool = False,
    protect: set[str] | None = None,
    concurrency: int = 16,
) -> SyncReport:
    """Synchronous wrapper around :func:`sync_async`."""
    return asyncio.run(
        sync_async(
            lock,
            output_dir,
            cache=cache,
            fetch=fetch,
            offline=offline,
            protect=protect,
            concurrency=concurrency,
        )
    )
