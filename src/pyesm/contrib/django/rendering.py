"""Render the import map at request time through Django's staticfiles storage.

Routing only the values through ``staticfiles_storage.url("pyesm/<path>")``
yields storage-hashed URLs, so the map survives ``ManifestStaticFilesStorage``
/ WhiteNoise filename hashing. The rendered map is cached per process and
invalidated when the staticfiles manifest changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage

from ...config import Config, find_project_root, load_config
from ...importmap import build_import_map
from ...lockfile import Lock, load_lock
from ...shims import shims_script_tag, should_inject

_cache: dict | None = None


def _project_root() -> Path:
    root = getattr(settings, "PYESM_PROJECT_ROOT", None)
    return Path(root) if root else find_project_root()


def _static_prefix() -> str:
    return getattr(settings, "PYESM_STATIC_PREFIX", "pyesm").strip("/")


def _load() -> tuple[Config, Lock]:
    cfg = load_config(_project_root())
    lock = load_lock(cfg.lock_path)
    return cfg, lock


def _manifest_version() -> str:
    """A token that changes when the staticfiles manifest changes."""
    for attr in ("manifest_hash", "manifest_version"):
        val = getattr(staticfiles_storage, attr, None)
        if val:
            return str(val)
    # Non-manifest storages (e.g. plain StaticFilesStorage): identity is stable
    # enough within a process.
    return f"id:{id(staticfiles_storage)}"


def _django_public_url():
    prefix = _static_prefix()

    def _url(path: str) -> str:
        return staticfiles_storage.url(f"{prefix}/{path}")

    return _url


def render_import_map(*, force: bool = False) -> str:
    """Return the ``<script type="importmap">…</script>`` HTML (plus shims).

    Cached per process, keyed by the staticfiles manifest version.
    """
    global _cache
    version = _manifest_version()
    if not force and _cache is not None and _cache["version"] == version:
        return _cache["html"]

    cfg, lock = _load()
    public_url = _django_public_url()
    import_map = build_import_map(lock, public_url, integrity=cfg.integrity)
    payload = json.dumps(import_map, ensure_ascii=False, separators=(",", ":"))
    parts = []
    if should_inject(cfg.shims) and lock.shims is not None:
        src = public_url(lock.shims.path)
        parts.append(shims_script_tag(src, lock.shims.integrity))
    parts.append(f'<script type="importmap">{payload}</script>')
    html = "\n".join(parts)

    _cache = {"version": version, "html": html}
    return html


def clear_cache() -> None:
    global _cache
    _cache = None
