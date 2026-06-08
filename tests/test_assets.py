import asyncio

from fake_cdn import RecordingFetch
from pyesm.assets import AssetCrawler, scan_css
from pyesm.providers import get_provider

J = "https://cdn.jsdelivr.net"


def test_scan_css_finds_imports_and_urls():
    css = (
        '@import "base.css";\n'
        "@import url(theme.css) screen;\n"
        ".a{background:url(fonts/x.woff2)}\n"
        '.b{src:url("y.ttf")}\n'
        ".c{mask:url(data:image/svg+xml,<svg/>)}\n"
        ".d{fill:url(#grad)}"
    )
    refs = scan_css(css)
    assert {"base.css", "theme.css", "fonts/x.woff2", "y.ttf"} <= set(refs)
    # the scanner returns data:/fragment refs; the crawler is what filters them
    assert "data:image/svg+xml,<svg/>" in refs
    assert "#grad" in refs


def test_asset_crawl_vendors_closure_preserving_structure():
    provider = get_provider("jsdelivr")
    entry = f"{J}/npm/widget@1.0.0/dist/widget.css"
    assets, entry_paths = asyncio.run(
        AssetCrawler(provider, fetch=RecordingFetch().crawl).crawl([entry])
    )
    # entry stylesheet path is preserved for <link>
    assert entry_paths == ["widget@1.0.0/dist/widget.css"]
    paths = {path for path, _integrity in assets.values()}
    # @import (recursion) and the relative font are vendored at preserved paths,
    # so url(fonts/…) resolves against the vendored CSS with no rewriting
    assert "widget@1.0.0/dist/base.css" in paths
    assert "widget@1.0.0/dist/fonts/widget.woff2" in paths
    # the data: URI ref is not followed
    assert not any("data:" in url for url in assets)
    # every vendored asset has an integrity hash
    assert all(i.startswith("sha384-") for _p, i in assets.values())
