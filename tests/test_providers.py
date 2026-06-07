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


def test_jsdelivr_subpath_pins_package_version():
    import asyncio

    p = get_provider("jsdelivr")
    # entry_url keeps the subpath after the package@range
    assert p.entry_url("@codemirror/legacy-modes/mode/toml", "6.5.2", production=True) == (
        "https://cdn.jsdelivr.net/npm/@codemirror/legacy-modes@6.5.2/mode/toml/+esm"
    )

    # resolve_entry pins the *package* version (via the data API) then appends
    # the subpath; the get_json call must target the package, not the subpath.
    seen = {}

    async def fake_get_json(url):
        seen["url"] = url
        return {"version": "6.5.3"}

    url = asyncio.run(
        p.resolve_entry(
            "@codemirror/legacy-modes/mode/toml", "", production=True, get_json=fake_get_json
        )
    )
    assert "@codemirror/legacy-modes/resolved" in seen["url"]
    assert url == "https://cdn.jsdelivr.net/npm/@codemirror/legacy-modes@6.5.3/mode/toml/+esm"


def test_esmsh_subpath():
    p = get_provider("esmsh")
    assert p.entry_url("@codemirror/legacy-modes/mode/toml", "6.5.2", production=True) == (
        "https://esm.sh/@codemirror/legacy-modes@6.5.2/mode/toml"
    )


def test_jsdelivr_parse_build_manifest():
    p = get_provider("jsdelivr")
    assert p.supports_dedup is True
    assert p.versions_url("react") == "https://data.jsdelivr.com/v1/packages/npm/react"
    assert p.manifest_url("react", "18.3.1") == (
        "https://cdn.jsdelivr.net/npm/react@18.3.1/package.json"
    )
    assert p.parse_module("https://cdn.jsdelivr.net/npm/react@18.2.0/+esm") == (
        "react",
        "18.2.0",
        "",
    )
    assert p.parse_module(
        "https://cdn.jsdelivr.net/npm/@codemirror/legacy-modes@6.5.3/mode/toml/+esm"
    ) == ("@codemirror/legacy-modes", "6.5.3", "mode/toml")
    assert p.parse_module("https://esm.sh/react@18") is None
    assert p.build_module("react", "18.3.1", "") == (
        "https://cdn.jsdelivr.net/npm/react@18.3.1/+esm"
    )
    assert p.build_module("@codemirror/legacy-modes", "6.5.3", "mode/toml") == (
        "https://cdn.jsdelivr.net/npm/@codemirror/legacy-modes@6.5.3/mode/toml/+esm"
    )


def test_esmsh_no_dedup():
    p = get_provider("esmsh")
    assert p.supports_dedup is False
    assert p.parse_module("https://esm.sh/react@18.2.0") is None


def test_unknown_provider_rejected():
    import pytest

    from pyesm.errors import ConfigError

    with pytest.raises(ConfigError):
        get_provider("jspm")
