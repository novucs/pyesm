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
    """Vendor every module in ``lock`` into ``output_dir`` and verify it.

    Atomic: every module is downloaded and integrity-verified into the cache
    *first*; only once they are all present do we touch ``output_dir`` (prune +
    materialize, a local step). So a download/hash failure never leaves
    ``output_dir`` half-vendored.
    """
    cache = cache or Cache()
    protect = protect or set()
    report = SyncReport()
    items = [*lock.modules, *([lock.shims] if lock.shims is not None else [])]

    # Phase 1: ensure every item is in the cache, verified. No output mutation.
    if fetch is None and not offline:
        async with http.make_client(concurrency) as client:

            async def dl(url: str) -> bytes:
                _, raw = await http.get_module(client, url)
                return raw

            ensured = await _ensure_cached(items, cache, dl, offline, concurrency)
    else:
        ensured = await _ensure_cached(items, cache, fetch, offline, concurrency)

    for _item, _path, had in ensured:
        if had:
            report.reused += 1
        else:
            report.downloaded += 1

    # Phase 2: all bytes are cached and verified; now mutate output_dir.
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = {item.path for item, _, _ in ensured} | set(protect)
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_dir():
            continue
        rel = path.relative_to(output_dir).as_posix()
        if rel not in expected:
            path.unlink()
            report.pruned.append(rel)

    for item, cache_path, _had in ensured:
        dest = output_dir / item.path
        materialize(cache_path, dest)
        actual = sri_hash(dest.read_bytes())
        if actual != item.integrity:
            raise HashMismatchError(item.url, item.integrity, actual)

    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()

    return report


async def _ensure_cached(items, cache, fetch, offline, concurrency):
    """Download + verify every item into the cache. Returns (item, cache_path, had)."""
    sem = asyncio.Semaphore(concurrency)

    async def one(item):
        async with sem:
            had = cache.has(item.integrity)
            path = await cache.ensure_async(item.url, item.integrity, fetch=fetch, offline=offline)
        return item, path, had

    return await asyncio.gather(*(one(i) for i in items))


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
