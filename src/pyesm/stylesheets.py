"""Build ``<link rel="stylesheet">`` tags from a lock's vendored stylesheets.

Like the import map, the builder takes a ``public_url(path) -> str`` callable so
URLs are formed per mode (``base-url`` for static, ``staticfiles_storage.url``
for Django) without the builder knowing which.
"""

from __future__ import annotations

import os
from pathlib import Path

from .lockfile import Lock


def stylesheet_links(lock: Lock, public_url, *, integrity: bool = True) -> list[str]:
    """One ``<link rel="stylesheet">`` tag per entry stylesheet, sorted."""
    by_path = {a.path: a for a in lock.assets}
    tags: list[str] = []
    for path in sorted(lock.stylesheets):
        attrs = f'rel="stylesheet" href="{public_url(path)}"'
        asset = by_path.get(path)
        if integrity and asset is not None:
            attrs += f' integrity="{asset.integrity}" crossorigin'
        tags.append(f"<link {attrs}>")
    return tags


def render_stylesheets(lock: Lock, public_url, *, integrity: bool = True) -> str:
    """The newline-joined ``<link>`` tags (empty string if none)."""
    return "\n".join(stylesheet_links(lock, public_url, integrity=integrity))


def dump_stylesheets_html(html: str, path: Path) -> None:
    """Atomically write the ``<link>`` snippet (write-temp-then-rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(html + "\n", encoding="utf-8")
    os.replace(tmp, path)
