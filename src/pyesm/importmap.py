"""Build a standard import map from a lock.

The builder takes a ``public_url(path) -> str`` callable so the public URL can
be formed per mode (``base-url`` + path for static, ``staticfiles_storage.url``
for Django) without the builder knowing which.

URL keys are the root-relative specifiers from ``module.keys`` (what appears in
the bytes), not full CDN URLs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .lockfile import Lock

PublicURL = "Callable[[str], str]"


def build_import_map(lock: Lock, public_url, *, integrity: bool = True) -> dict:
    """Return the import-map dict.

    ``{imports, integrity}`` by default. When ``integrity`` is False the SRI
    block is omitted; the modules still load, just unverified (the lock keeps
    the hashes regardless, for cache and tamper verification).
    """
    by_url = {m.url: m for m in lock.modules}

    imports: dict[str, str] = {}
    integ: dict[str, str] = {}

    # Bare specifiers -> entry module public URL.
    for bare, url in lock.imports.items():
        module = by_url.get(url)
        if module is None:
            continue
        imports[bare] = public_url(module.path)

    # Root-relative URL specifiers (as they appear in the bytes) -> public URL,
    # plus an integrity entry for every module's public URL.
    for module in lock.modules:
        pub = public_url(module.path)
        integ[pub] = module.integrity
        for key in module.keys:
            imports[key] = pub

    result: dict = {"imports": dict(sorted(imports.items()))}
    if integrity:
        result["integrity"] = dict(sorted(integ.items()))
    return result


def static_public_url(base_url: str):
    """A ``public_url`` callable for static mode using ``base-url``."""

    def _url(path: str) -> str:
        return base_url + path

    return _url


def dump_import_map(import_map: dict, path: Path) -> None:
    """Atomically write the import map JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(import_map, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
