"""The ``pyesm.lock`` data model and deterministic JSON (de)serialization.

The lock captures the full crawled module graph.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import LockNotFoundError

LOCK_VERSION = 1


@dataclass
class Module:
    """One node in the crawled graph.

    Attributes:
        url: Absolute CDN URL, the canonical identity used for fetching,
            caching and dedup.
        path: Local path under ``output-dir`` where the bytes are written.
        integrity: ``sha384-<base64>`` over the exact vendored bytes.
        deps: Absolute CDN URLs this module imports.
        keys: Import-map keys, the root-relative specifiers as they appear in
            the bytes (e.g. ``/npm/react@18.2.0/+esm``). A module may be reached
            by more than one specifier, so this is a list; empty for an entry
            module reached only via a bare specifier.
    """

    url: str
    path: str
    integrity: str
    deps: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)


@dataclass
class ShimAsset:
    """The vendored es-module-shims polyfill (url, local path, integrity)."""

    url: str
    path: str
    integrity: str


@dataclass
class Asset:
    """One vendored raw asset (a CSS file, font, or image): url, path, integrity."""

    url: str
    path: str
    integrity: str


@dataclass
class Lock:
    """Top-level lockfile contents."""

    provider: str
    inputs_hash: str
    imports: dict[str, str] = field(default_factory=dict)  # bare specifier -> url
    modules: list[Module] = field(default_factory=list)
    shims: ShimAsset | None = None
    # CSS pathway: every vendored CSS/font/image, plus the entry stylesheet paths
    # the consumer should ``<link>`` (a subset of ``assets`` by path).
    assets: list[Asset] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    version: int = LOCK_VERSION

    def module_by_url(self, url: str) -> Module | None:
        for m in self.modules:
            if m.url == url:
                return m
        return None

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        out: dict = {
            "version": self.version,
            "provider": self.provider,
            "inputs_hash": self.inputs_hash,
            "imports": dict(sorted(self.imports.items())),
            "modules": [
                {
                    "url": m.url,
                    "path": m.path,
                    "integrity": m.integrity,
                    "deps": sorted(m.deps),
                    "keys": sorted(m.keys),
                }
                for m in sorted(self.modules, key=lambda m: m.url)
            ],
        }
        if self.shims is not None:
            out["shims"] = {
                "url": self.shims.url,
                "path": self.shims.path,
                "integrity": self.shims.integrity,
            }
        if self.assets:
            out["assets"] = [
                {"url": a.url, "path": a.path, "integrity": a.integrity}
                for a in sorted(self.assets, key=lambda a: a.url)
            ]
        if self.stylesheets:
            out["stylesheets"] = sorted(self.stylesheets)
        return out

    def to_json(self) -> str:
        # Deterministic: sorted keys handled in to_dict; trailing newline for
        # clean diffs.
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: dict) -> Lock:
        shims = data.get("shims")
        return cls(
            version=int(data.get("version", LOCK_VERSION)),
            provider=str(data["provider"]),
            inputs_hash=str(data["inputs_hash"]),
            imports=dict(data.get("imports", {})),
            modules=[
                Module(
                    url=m["url"],
                    path=m["path"],
                    integrity=m["integrity"],
                    deps=list(m.get("deps", [])),
                    keys=list(m.get("keys", [])),
                )
                for m in data.get("modules", [])
            ],
            shims=ShimAsset(shims["url"], shims["path"], shims["integrity"]) if shims else None,
            assets=[
                Asset(url=a["url"], path=a["path"], integrity=a["integrity"])
                for a in data.get("assets", [])
            ],
            stylesheets=list(data.get("stylesheets", [])),
        )


def load_lock(path: Path) -> Lock:
    if not path.is_file():
        raise LockNotFoundError(f"no lockfile at {path}")
    with path.open("rb") as fh:
        return Lock.from_dict(json.load(fh))


def dump_lock(lock: Lock, path: Path) -> None:
    """Atomically write the lock (write-temp-then-rename)."""
    _atomic_write_text(path, lock.to_json())


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
