from pyesm.scanner import scan_imports


def test_all_four_import_forms():
    src = (
        'import a from"/npm/react@18.2.0/+esm";'
        "export * from '/npm/foo@1/+esm';"
        'import"/npm/side@1/+esm";'
        'const x = await import("/npm/dyn@1/+esm");'
        'import {useState, useEffect} from "/npm/named@2/+esm";'
    )
    specs = scan_imports(src)
    assert specs == [
        "/npm/react@18.2.0/+esm",
        "/npm/foo@1/+esm",
        "/npm/named@2/+esm",
        "/npm/side@1/+esm",
        "/npm/dyn@1/+esm",
    ]


def test_dedup_preserves_first_order():
    src = 'import a from"/x";import b from"/x";import c from"/y";'
    assert scan_imports(src) == ["/x", "/y"]


def test_absolute_and_scoped_specifiers():
    src = 'import x from"/scheduler@^0.23.0?target=es2022";export{a}from"/@scope/pkg@1/+esm";'
    assert "/scheduler@^0.23.0?target=es2022" in scan_imports(src)
    assert "/@scope/pkg@1/+esm" in scan_imports(src)


def test_no_imports():
    assert scan_imports("export default 42;") == []
