import asyncio

from fake_cdn import RecordingFetch, fake_get_json
from pyesm.crawler import Crawler
from pyesm.providers import get_provider
from pyesm.resolve import resolve


def test_crawl_rewrite_dedups_versions():
    # two parents import the SAME dep at different pins; a rewrite maps both to
    # one resolved version -> one module, both pinned specifiers as keys.
    J = "https://cdn.jsdelivr.net"
    a = f"{J}/npm/a@1.0.0/+esm"
    b = f"{J}/npm/b@1.0.0/+esm"
    graph = {
        a: (a, b'import x from"/npm/dep@1.2.0/+esm";export default 1;'),
        b: (b, b'import y from"/npm/dep@1.5.0/+esm";export default 2;'),
        f"{J}/npm/dep@1.9.9/+esm": (f"{J}/npm/dep@1.9.9/+esm", b"export default 0;"),
    }
    fetch = RecordingFetch(graph)
    provider = get_provider("jsdelivr")

    def rewrite(url):  # pretend the resolver unified dep -> 1.9.9
        parsed = provider.parse_module(url)
        if parsed and parsed[0] == "dep":
            return provider.build_module("dep", "1.9.9", parsed[2])
        return url

    result = asyncio.run(Crawler(provider, fetch=fetch.crawl, rewrite=rewrite).crawl([a, b]))
    dep = f"{J}/npm/dep@1.9.9/+esm"
    assert dep in result.modules  # single resolved copy
    assert not any("dep@1.2.0" in u or "dep@1.5.0" in u for u in result.modules)
    # both in-byte pins remap to the one resolved module
    assert result.modules[dep].keys == {"/npm/dep@1.2.0/+esm", "/npm/dep@1.5.0/+esm"}


def test_crawl_ignores_relative_false_positive_specifiers():
    # Syntax-highlighting packages embed import/from text in string literals;
    # the scanner extracts garbage relative specifiers that must not be followed
    # (they would urljoin into bogus same-CDN URLs that 404).
    J = "https://cdn.jsdelivr.net"
    parent = f"{J}/npm/lang-css@6.3.1/+esm"
    body = (
        b'import{a}from"/npm/dep@1.0.0/+esm";'
        b"d('import {${names}} from \"${module}\"');"  # snippet -> ${module}
        b'const t={"@import":118,",":1};'  # token tables -> :118, and ,
        b'"import export from":kw;'  # highlight map -> :kw
    )
    graph = {
        parent: (parent, body),
        f"{J}/npm/dep@1.0.0/+esm": (f"{J}/npm/dep@1.0.0/+esm", b"export default 1;"),
    }
    fetch = RecordingFetch(graph)
    result = asyncio.run(Crawler(get_provider("jsdelivr"), fetch=fetch.crawl).crawl([parent]))
    # only the real /npm/ dep is followed; no comma/${module}/etc. URLs fetched
    assert set(result.modules) == {parent, f"{J}/npm/dep@1.0.0/+esm"}
    assert not any("," in u or "$" in u for u in fetch.calls)


def test_crawl_pins_versions_and_attaches_keys():
    fetch = RecordingFetch()
    provider = get_provider("jsdelivr")
    result = asyncio.run(
        Crawler(provider, fetch=fetch.crawl).crawl(
            ["https://cdn.jsdelivr.net/npm/react-dom@18.2.0/+esm"]
        )
    )
    mods = result.modules
    # react-dom + react + scheduler are discovered
    assert set(mods) == {
        "https://cdn.jsdelivr.net/npm/react-dom@18.2.0/+esm",
        "https://cdn.jsdelivr.net/npm/react@18.2.0/+esm",
        "https://cdn.jsdelivr.net/npm/scheduler@0.23.2/+esm",
    }
    react = mods["https://cdn.jsdelivr.net/npm/react@18.2.0/+esm"]
    assert react.keys == {"/npm/react@18.2.0/+esm"}
    dom = mods["https://cdn.jsdelivr.net/npm/react-dom@18.2.0/+esm"]
    assert dom.deps == {
        "https://cdn.jsdelivr.net/npm/react@18.2.0/+esm",
        "https://cdn.jsdelivr.net/npm/scheduler@0.23.2/+esm",
    }


def test_resolve_builds_lock(config):
    fetch = RecordingFetch()
    lock = resolve(config, fetch=fetch.crawl, get_json=fake_get_json)
    assert lock.provider == "jsdelivr"
    assert lock.inputs_hash == config.inputs_hash()
    assert set(lock.imports) == {"react", "react-dom"}
    assert lock.imports["react"] == "https://cdn.jsdelivr.net/npm/react@18.2.0/+esm"
    assert {m.path for m in lock.modules} == {
        "react@18.2.0/+esm.js",
        "scheduler@0.23.2/+esm.js",
        "react-dom@18.2.0/+esm.js",
    }


def test_resolve_is_deterministic(config):
    lock1 = resolve(config, fetch=RecordingFetch().crawl, get_json=fake_get_json).to_json()
    lock2 = resolve(config, fetch=RecordingFetch().crawl, get_json=fake_get_json).to_json()
    assert lock1 == lock2


def test_resolve_vendors_shim_from_provider_when_enabled(config):
    # default shims=auto -> shim recorded, sourced from the configured provider
    lock = resolve(config, fetch=RecordingFetch().crawl, get_json=fake_get_json)
    assert lock.shims is not None
    assert lock.shims.url.startswith("https://cdn.jsdelivr.net/npm/es-module-shims@")
    assert lock.shims.path == "es-module-shims@2.8.1.js"
    assert lock.shims.integrity.startswith("sha384-")


def test_resolve_skips_shim_when_never(config):
    config.shims = "never"
    lock = resolve(config, fetch=RecordingFetch().crawl, get_json=fake_get_json)
    assert lock.shims is None
