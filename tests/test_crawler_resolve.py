import asyncio

from fake_cdn import RecordingFetch, fake_get_json
from pyesm.crawler import Crawler
from pyesm.providers import get_provider
from pyesm.resolve import resolve


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
    assert lock.shims.path == "es-module-shims@1.10.0.js"
    assert lock.shims.integrity.startswith("sha384-")


def test_resolve_skips_shim_when_never(config):
    config.shims = "never"
    lock = resolve(config, fetch=RecordingFetch().crawl, get_json=fake_get_json)
    assert lock.shims is None
