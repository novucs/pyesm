from pyesm.http import strip_source_map


def test_strips_trailing_external_source_map():
    raw = b"export default 1;\n//# sourceMappingURL=/sm/abc.map"
    assert strip_source_map(raw) == b"export default 1;"
    # legacy `//@` form, with trailing newline
    raw2 = b"export default 1;\n//@ sourceMappingURL=/sm/x.map\n"
    assert strip_source_map(raw2) == b"export default 1;"


def test_keeps_inline_data_uri_source_map():
    # a self-contained data: map resolves offline, so it must be preserved
    raw = b"export default 1;\n//# sourceMappingURL=data:application/json;base64,eyJ2IjozfQ=="
    assert strip_source_map(raw) == raw


def test_ignores_non_trailing_or_absent_comment():
    mid = b'const s = "//# sourceMappingURL=/sm/x.map";\nexport default s;'
    assert strip_source_map(mid) == mid
    assert strip_source_map(b"export default 1;") == b"export default 1;"
