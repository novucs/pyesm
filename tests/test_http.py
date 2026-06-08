from pyesm.http import strip_jsdelivr_banner, strip_source_map

_BANNER = (
    b"/**\n * Bundled by jsDelivr using Rollup v2.79.2 and Terser v5.48.0.\n"
    b" * Do NOT use SRI with dynamically generated files!\n */\n"
)


def test_strips_leading_jsdelivr_banner():
    assert strip_jsdelivr_banner(_BANNER + b"import x from'y';") == b"import x from'y';"
    # the .min.js banner says "Minified by jsDelivr" rather than "Bundled"
    minified = b"/**\n * Minified by jsDelivr using Terser v5.39.0.\n */\n!function(){}();"
    assert strip_jsdelivr_banner(minified) == b"!function(){}();"


def test_keeps_package_license_header():
    lic = b"/*! @license MIT some-lib */\nexport default 1;"
    assert strip_jsdelivr_banner(lic) == lic


def test_banner_signature_only_matches_leading_block():
    mid = b'const s = "Bundled by jsDelivr";\nexport default s;'
    assert strip_jsdelivr_banner(mid) == mid
    assert strip_jsdelivr_banner(b"export default 1;") == b"export default 1;"


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
