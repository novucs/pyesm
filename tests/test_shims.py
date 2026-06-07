from pyesm.shims import shims_script_tag, should_inject


def test_should_inject():
    assert should_inject("auto")
    assert should_inject("always")
    assert not should_inject("never")


def test_tag_points_at_local_src_with_integrity():
    tag = shims_script_tag("/static/pyesm/es-module-shims@1.10.0.js", "sha384-xyz")
    assert tag == (
        '<script async src="/static/pyesm/es-module-shims@1.10.0.js" '
        'integrity="sha384-xyz"></script>'
    )
    # no remote CDN, and SRI is present
    assert "http" not in tag
    assert "integrity=" in tag
