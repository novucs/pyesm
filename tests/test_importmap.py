from pyesm.importmap import build_import_map, static_public_url
from pyesm.lockfile import Lock, Module

J = "https://cdn.jsdelivr.net"


def _lock():
    return Lock(
        provider="jsdelivr",
        inputs_hash="sha256-abc",
        imports={
            "react": f"{J}/npm/react@18.2.0/+esm",
            "react-dom": f"{J}/npm/react-dom@18.2.0/+esm",
        },
        modules=[
            Module(
                url=f"{J}/npm/react@18.2.0/+esm",
                path="react@18.2.0/+esm.js",
                integrity="sha384-react",
                keys=["/npm/react@18.2.0/+esm"],
            ),
            Module(
                url=f"{J}/npm/scheduler@0.23.2/+esm",
                path="scheduler@0.23.2/+esm.js",
                integrity="sha384-sched",
                keys=["/npm/scheduler@0.23.2/+esm"],
            ),
            Module(
                url=f"{J}/npm/react-dom@18.2.0/+esm",
                path="react-dom@18.2.0/+esm.js",
                integrity="sha384-reactdom",
                keys=[],
            ),
        ],
    )


def test_static_keys_are_root_relative_not_cdn_urls():
    m = build_import_map(_lock(), static_public_url("/static/pyesm/"))
    imports = m["imports"]
    # bare specifiers
    assert imports["react"] == "/static/pyesm/react@18.2.0/+esm.js"
    assert imports["react-dom"] == "/static/pyesm/react-dom@18.2.0/+esm.js"
    # the in-byte (root-relative) keys remap to local files, NOT cdn.jsdelivr URLs
    assert imports["/npm/react@18.2.0/+esm"] == "/static/pyesm/react@18.2.0/+esm.js"
    assert imports["/npm/scheduler@0.23.2/+esm"] == "/static/pyesm/scheduler@0.23.2/+esm.js"
    assert not any(k.startswith("https://") for k in imports)


def test_integrity_present_for_every_public_url():
    m = build_import_map(_lock(), static_public_url("/static/pyesm/"))
    integ = m["integrity"]
    # every value that can be imported has an integrity entry
    for url in m["imports"].values():
        assert url in integ
    assert integ["/static/pyesm/react@18.2.0/+esm.js"] == "sha384-react"
    assert len(integ) == 3  # one per module


def test_integrity_omitted_when_disabled():
    m = build_import_map(_lock(), static_public_url("/static/pyesm/"), integrity=False)
    assert "integrity" not in m
    assert m["imports"]  # imports still emitted


def test_django_style_public_url_routes_values_only():
    def public(path):
        return f"/static/pyesm/{path}?v=HASH"

    m = build_import_map(_lock(), public)
    # keys unchanged; values hashed
    assert "/npm/react@18.2.0/+esm" in m["imports"]
    assert m["imports"]["/npm/react@18.2.0/+esm"].endswith("?v=HASH")
    assert all(v.endswith("?v=HASH") for v in m["imports"].values())
    assert all(k.endswith("?v=HASH") for k in m["integrity"])
