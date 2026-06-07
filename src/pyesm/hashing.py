"""SHA-384 hashing formatted for Subresource Integrity (SRI)."""

from __future__ import annotations

import base64
import hashlib

ALGO = "sha384"


def sri_hash(data: bytes) -> str:
    """Return the SRI string ``sha384-<base64>`` for ``data``."""
    digest = hashlib.sha384(data).digest()
    return f"{ALGO}-{base64.b64encode(digest).decode('ascii')}"


def cache_key(integrity: str) -> str:
    """Filesystem-safe cache key derived from an SRI string.

    base64 contains ``/`` and ``+`` which are awkward in paths, so we
    re-encode the raw digest as base32 (lowercase, no padding).
    """
    algo, _, b64 = integrity.partition("-")
    raw = base64.b64decode(b64)
    return f"{algo}-{base64.b32encode(raw).decode('ascii').rstrip('=').lower()}"
