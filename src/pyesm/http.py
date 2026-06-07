"""The shared ``httpx.AsyncClient``. httpx is imported lazily so no-network
paths stay cheap to start."""

from __future__ import annotations

USER_AGENT = "pyesm"
TIMEOUT = 30.0


def make_client(concurrency: int = 16):
    """Return a configured ``httpx.AsyncClient``."""
    import httpx

    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=concurrency),
    )
