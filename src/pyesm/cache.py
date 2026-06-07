"""Global content-addressed cache at ``~/.cache/pyesm/<key>``.

Shared across all projects: an identical module (same bytes -> same sha384) is
downloaded once, ever. Materializing into a project's ``output-dir`` uses a
hardlink (no byte copy on the same filesystem), falling back to a copy across
filesystems. Bytes are never rewritten, so SRI stays valid.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .errors import HashMismatchError, OfflineColdCacheError
from .hashing import cache_key, sri_hash


def default_cache_dir() -> Path:
    env = os.environ.get("PYESM_CACHE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "pyesm"


class Cache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_cache_dir()

    def path_for(self, integrity: str) -> Path:
        return self.root / cache_key(integrity)

    def has(self, integrity: str) -> bool:
        return self.path_for(integrity).is_file()

    def read(self, integrity: str) -> bytes:
        return self.path_for(integrity).read_bytes()

    def put(self, integrity: str, data: bytes) -> Path:
        """Verify ``data`` against ``integrity`` and store it atomically."""
        actual = sri_hash(data)
        if actual != integrity:
            raise HashMismatchError("<download>", integrity, actual)
        dest = self.path_for(integrity)
        if dest.is_file():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.tmp.{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return dest

    async def ensure_async(
        self,
        url: str,
        integrity: str,
        *,
        fetch,
        offline: bool = False,
    ) -> Path:
        """Return the cache path for ``integrity``, downloading via ``fetch``
        if missing. Raises :class:`OfflineColdCacheError` if offline and absent,
        :class:`HashMismatchError` if downloaded bytes don't match ``integrity``.
        """
        if self.has(integrity):
            return self.path_for(integrity)
        if offline:
            raise OfflineColdCacheError(
                f"offline: {url} (integrity {integrity}) not in cache {self.root}"
            )
        data = await fetch(url)
        actual = sri_hash(data)
        if actual != integrity:
            raise HashMismatchError(url, integrity, actual)
        return self.put(integrity, data)


def materialize(src: Path, dest: Path) -> None:
    """Place cache file ``src`` at ``dest`` via hardlink, falling back to copy.

    Never rewrites bytes. Replaces any existing destination so re-runs are
    idempotent.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        # Cross-filesystem or hardlink unsupported: fall back to a byte copy.
        shutil.copyfile(src, dest)
