"""A deterministic in-memory CDN graph plus a live HTTP server, for tests.

The in-memory graph drives the hermetic crawler/resolve/vendor/CLI tests
(injected as a ``fetch`` callable). The live server exercises the real
``requests`` network layer (redirect following, pooled session).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pyesm.providers import get_provider
from pyesm.shims import ESMS_VERSION

J = "https://cdn.jsdelivr.net"

# Module bodies. react-dom references its siblings by *root-relative* path,
# exactly like real jsDelivr +esm output.
# a jsDelivr-style build banner (stripped at fetch time)
_BANNER = (
    b"/**\n * Bundled by jsDelivr using Rollup v2.79.2 and Terser v5.48.0.\n"
    b" * Do NOT use SRI with dynamically generated files!\n */\n"
)
REACT = _BANNER + b'export default {name:"react"};'
# trailing source-map comment, as jsDelivr appends; stripped at fetch time
SCHEDULER = b'export default {name:"scheduler"};\n//# sourceMappingURL=/sm/abc123.map'
REACT_DOM = (
    b'import e from"/npm/react@18.2.0/+esm";'
    b'import n from"/npm/scheduler@0.23.2/+esm";'
    b'export default {name:"react-dom"};'
)
SHIM = b"/* es-module-shims mock */(function(){})();"
# track the provider's real shims URL so the fake never drifts from it
SHIM_URL = get_provider("jsdelivr").shims_url(ESMS_VERSION)

# A raw CSS dep with a relative font ref (the CSS pathway) + a @import of a
# sibling stylesheet, exercising recursion and structure-preserving vendoring.
WIDGET_CSS = (
    b'@import "base.css";\n.w{background:url(fonts/widget.woff2)}'
    b";.x{mask:url('data:image/svg+xml,<svg/>')}"  # data: URI is left untouched
)
WIDGET_BASE_CSS = b".w{margin:0}"
WIDGET_FONT = b"FONT-BYTES"

# request URL -> (canonical URL after redirects, raw bytes). Entry URLs are
# already version-pinned because jsDelivr pinning happens via the data API
# (see VERSIONS / fake_get_json) before crawling.
GRAPH: dict[str, tuple[str, bytes]] = {
    f"{J}/npm/react@18.2.0/+esm": (f"{J}/npm/react@18.2.0/+esm", REACT),
    f"{J}/npm/scheduler@0.23.2/+esm": (f"{J}/npm/scheduler@0.23.2/+esm", SCHEDULER),
    f"{J}/npm/react-dom@18.2.0/+esm": (f"{J}/npm/react-dom@18.2.0/+esm", REACT_DOM),
    # scheduler subpaths, for exercising grouped subpath deps
    f"{J}/npm/scheduler@0.23.2/foo/+esm": (
        f"{J}/npm/scheduler@0.23.2/foo/+esm",
        b"export default 1;",
    ),
    f"{J}/npm/scheduler@0.23.2/bar/+esm": (
        f"{J}/npm/scheduler@0.23.2/bar/+esm",
        b"export default 2;",
    ),
    SHIM_URL: (SHIM_URL, SHIM),
    # raw CSS assets (no +esm): the entry css, its @import, and a font
    f"{J}/npm/widget@1.0.0/dist/widget.css": (
        f"{J}/npm/widget@1.0.0/dist/widget.css",
        WIDGET_CSS,
    ),
    f"{J}/npm/widget@1.0.0/dist/base.css": (
        f"{J}/npm/widget@1.0.0/dist/base.css",
        WIDGET_BASE_CSS,
    ),
    f"{J}/npm/widget@1.0.0/dist/fonts/widget.woff2": (
        f"{J}/npm/widget@1.0.0/dist/fonts/widget.woff2",
        WIDGET_FONT,
    ),
}

# What the jsDelivr data API resolves each package name to (range -> latest).
VERSIONS = {"react": "18.2.0", "react-dom": "18.2.0", "scheduler": "0.23.2", "widget": "1.0.0"}

# Published version lists (for the backtracking resolver's enumeration).
VERSION_LISTS = {
    "react": ["18.2.0"],
    "react-dom": ["18.2.0"],
    "scheduler": ["0.23.2"],
    "widget": ["1.0.0"],
}

# package.json dependency ranges, for the npm-semver resolver.
MANIFESTS: dict[tuple[str, str], dict] = {
    ("react", "18.2.0"): {},
    ("react-dom", "18.2.0"): {
        "dependencies": {"scheduler": "^0.23.2"},
        "peerDependencies": {"react": "^18.2.0"},
    },
    ("scheduler", "0.23.2"): {},
    ("widget", "1.0.0"): {},
}


def _pkg_ver(body: str) -> tuple[str, str]:
    at = body.find("@", 1) if body.startswith("@") else body.find("@")
    return body[:at], body[at + 1 :]


def _packument(name: str) -> dict:
    # the singular /v1/package/npm endpoint returns versions as plain strings
    return {"versions": VERSION_LISTS[name], "tags": {"latest": VERSIONS[name]}}


async def fake_get_json(url: str) -> dict:
    """Stand in for the jsDelivr data API and ``package.json`` endpoints."""
    if url.endswith("/package.json"):
        body = url.split("/npm/", 1)[1][: -len("/package.json")]
        pkg, ver = _pkg_ver(body)
        return MANIFESTS.get((pkg, ver), {})
    after = url.split("/npm/", 1)[1]
    if "/resolved" in after:  # .../npm/<name>/resolved?specifier=...
        return {"version": VERSIONS[after.split("/resolved", 1)[0]]}
    return _packument(after)  # .../npm/<name> -> version list + tags


class RecordingFetch:
    """An async crawler/vendor ``fetch`` over the in-memory graph; counts calls."""

    def __init__(self, graph: dict[str, tuple[str, bytes]] | None = None) -> None:
        self.graph = graph if graph is not None else GRAPH
        self.calls: list[str] = []

    # crawler fetch: url -> (canonical, bytes)
    async def crawl(self, url: str) -> tuple[str, bytes]:
        self.calls.append(url)
        return self.graph[url]

    # vendor fetch: url -> bytes  (url is already the canonical/pinned URL)
    async def download(self, url: str) -> bytes:
        self.calls.append(url)
        # vendor passes canonical URLs; find body by canonical match.
        for canonical, body in self.graph.values():
            if canonical == url:
                return body
        return self.graph[url][1]


async def no_network(url: str):  # pragma: no cover - only hit on failure
    raise AssertionError(f"unexpected network call to {url}")


def mock_client(concurrency: int = 16):
    """An ``httpx.AsyncClient`` whose transport serves the in-memory graph.

    Used to stub the real network path end-to-end (the CLI builds its client via
    ``http.make_client``), so tests exercise the actual httpx code while staying
    offline.
    """
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "data.jsdelivr.com":
            after = path.split("/npm/", 1)[1]
            if after.endswith("/resolved"):
                return httpx.Response(200, json={"version": VERSIONS[after[: -len("/resolved")]]})
            return httpx.Response(200, json=_packument(after))  # version list
        if path.endswith("/package.json"):
            pkg, ver = _pkg_ver(path.split("/npm/", 1)[1][: -len("/package.json")])
            return httpx.Response(200, json=MANIFESTS.get((pkg, ver), {}))
        url = f"https://{request.url.host}{path}"
        if url in GRAPH:
            return httpx.Response(200, content=GRAPH[url][1])
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


# --------------------------------------------------------------------------- #
# Live HTTP server (real requests path)
# --------------------------------------------------------------------------- #


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, bytes, str | None]] = {}

    def log_message(self, format, *args):  # noqa: A002 - silence server logs
        pass

    def do_GET(self):
        entry = self.routes.get(self.path)
        if entry is None:
            self.send_error(404)
            return
        status, body, location = entry
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class LiveServer:
    def __init__(self, routes: dict[str, tuple[int, bytes, str | None]]) -> None:
        _Handler.routes = routes
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> LiveServer:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
