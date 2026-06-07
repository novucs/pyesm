from pyesm.providers import get_provider


def test_jsdelivr_urls_and_keys():
    p = get_provider("jsdelivr")
    assert (
        p.entry_url("react", "^18.2.0", production=True)
        == "https://cdn.jsdelivr.net/npm/react@^18.2.0/+esm"
    )
    url = "https://cdn.jsdelivr.net/npm/react@18.2.0/+esm"
    assert p.is_module_url(url)
    assert not p.is_module_url("https://example.com/x.js")
    assert p.local_path(url) == "react@18.2.0/+esm.js"
    assert p.import_map_key(url) == "/npm/react@18.2.0/+esm"
    assert (
        p.absolutize(url, "/npm/scheduler@0.23.2/+esm")
        == "https://cdn.jsdelivr.net/npm/scheduler@0.23.2/+esm"
    )
    assert (
        p.shims_url("1.10.0")
        == "https://cdn.jsdelivr.net/npm/es-module-shims@1.10.0/dist/es-module-shims.js"
    )


def test_esmsh_urls_keys_and_unpinned_query():
    p = get_provider("esmsh")
    assert p.entry_url("react", "18.2.0", production=True) == "https://esm.sh/react@18.2.0"
    assert p.entry_url("react", "18.2.0", production=False) == "https://esm.sh/react@18.2.0?dev"
    # unpinned, query-stringed in-byte specifier resolves against the origin and
    # keeps its exact form as the import-map key
    spec = "/scheduler@^0.23.0?target=es2022"
    abs_url = p.absolutize("https://esm.sh/react-dom@18.2.0/es2022/react-dom.mjs", spec)
    assert abs_url == "https://esm.sh/scheduler@^0.23.0?target=es2022"
    assert p.import_map_key(abs_url) == spec
    assert (
        p.local_path("https://esm.sh/react@18.2.0/es2022/react.mjs")
        == "react@18.2.0/es2022/react.mjs"
    )
    # ?raw bypasses esm.sh's ESM transform to get the classic IIFE polyfill
    assert (
        p.shims_url("1.10.0") == "https://esm.sh/es-module-shims@1.10.0/dist/es-module-shims.js?raw"
    )


def test_unknown_provider_rejected():
    import pytest

    from pyesm.errors import ConfigError

    with pytest.raises(ConfigError):
        get_provider("jspm")
