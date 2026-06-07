"""Exercise the real httpx client built by make_client (redirect following)."""

import asyncio

from fake_cdn import LiveServer
from pyesm.http import make_client


def test_client_follows_redirects_and_exposes_final_url():
    routes = {
        "/npm/react@18/+esm": (302, b"", "/npm/react@18.2.0/+esm"),
        "/npm/react@18.2.0/+esm": (200, b"export default 1;", None),
    }

    async def go():
        async with make_client() as client:
            resp = await client.get(server.base + "/npm/react@18/+esm")
            resp.raise_for_status()
            return str(resp.url), resp.content

    with LiveServer(routes) as server:
        final_url, body = asyncio.run(go())
        assert final_url == server.base + "/npm/react@18.2.0/+esm"
        assert body == b"export default 1;"
