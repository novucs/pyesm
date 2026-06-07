from pyesm.lockfile import Lock, Module, dump_lock, load_lock


def _lock():
    return Lock(
        provider="jsdelivr",
        inputs_hash="sha256-abc",
        imports={"react": "https://cdn.jsdelivr.net/npm/react@18.2.0/+esm"},
        modules=[
            Module(
                url="https://cdn.jsdelivr.net/npm/react@18.2.0/+esm",
                path="react@18.2.0/+esm.js",
                integrity="sha384-xxx",
                deps=[],
                keys=["/npm/react@18.2.0/+esm"],
            )
        ],
    )


def test_shims_roundtrip(tmp_path):
    from pyesm.lockfile import ShimAsset

    lock = _lock()
    lock.shims = ShimAsset(
        url="https://cdn.jsdelivr.net/npm/es-module-shims@1.10.0/dist/es-module-shims.js",
        path="es-module-shims@1.10.0.js",
        integrity="sha384-shim",
    )
    path = tmp_path / "pyesm.lock"
    dump_lock(lock, path)
    loaded = load_lock(path)
    assert loaded.shims is not None
    assert loaded.shims.path == "es-module-shims@1.10.0.js"
    assert loaded.shims.integrity == "sha384-shim"
    # absent shims serialize to no key / None
    lock.shims = None
    dump_lock(lock, path)
    assert load_lock(path).shims is None


def test_roundtrip(tmp_path):
    path = tmp_path / "pyesm.lock"
    dump_lock(_lock(), path)
    loaded = load_lock(path)
    assert loaded.provider == "jsdelivr"
    assert loaded.imports["react"].endswith("/+esm")
    assert loaded.modules[0].keys == ["/npm/react@18.2.0/+esm"]


def test_serialization_is_deterministic(tmp_path):
    p1 = tmp_path / "a.lock"
    p2 = tmp_path / "b.lock"
    dump_lock(_lock(), p1)
    dump_lock(_lock(), p2)
    assert p1.read_bytes() == p2.read_bytes()


def test_atomic_write_leaves_no_temp(tmp_path):
    path = tmp_path / "pyesm.lock"
    dump_lock(_lock(), path)
    assert [p.name for p in tmp_path.iterdir()] == ["pyesm.lock"]
