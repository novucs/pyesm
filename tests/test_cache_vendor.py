import pytest

from fake_cdn import RecordingFetch, fake_get_json, no_network
from pyesm.cache import Cache
from pyesm.errors import HashMismatchError, OfflineColdCacheError
from pyesm.hashing import sri_hash
from pyesm.resolve import resolve
from pyesm.vendor import sync


def _lock(config):
    return resolve(config, fetch=RecordingFetch().crawl, get_json=fake_get_json)


def test_sync_vendors_and_verifies(config, cache_dir):
    lock = _lock(config)
    fetch = RecordingFetch()
    report = sync(lock, config.output_path, fetch=fetch.download)
    assert report.downloaded == 4  # 3 modules + es-module-shims
    for module in lock.modules:
        dest = config.output_path / module.path
        assert dest.is_file()
        assert sri_hash(dest.read_bytes()) == module.integrity
    # the shim is vendored and integrity-verified too
    assert lock.shims is not None
    shim = config.output_path / lock.shims.path
    assert sri_hash(shim.read_bytes()) == lock.shims.integrity


def test_warm_cache_offline_makes_no_network_calls(config, cache_dir):
    lock = _lock(config)
    # First sync warms the cache.
    sync(lock, config.output_path, fetch=RecordingFetch().download)
    # Wipe the output dir but keep the cache.
    for p in sorted(config.output_path.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    # Second sync is offline and must not call fetch.
    report = sync(lock, config.output_path, fetch=no_network, offline=True)
    assert report.reused == 4  # 3 modules + es-module-shims, all from cache
    assert report.downloaded == 0


def test_offline_cold_cache_fails(config, cache_dir):
    lock = _lock(config)
    with pytest.raises(OfflineColdCacheError):
        sync(lock, config.output_path, fetch=no_network, offline=True)


def test_corrupted_vendored_file_fails_with_url(config, cache_dir):
    lock = _lock(config)
    sync(lock, config.output_path, fetch=RecordingFetch().download)
    # Corrupt one vendored file in place.
    target = lock.modules[0]
    dest = config.output_path / target.path
    dest.unlink()
    dest.write_bytes(b"// tampered")
    with pytest.raises(HashMismatchError) as exc:
        # Cache still has good bytes; materialize overwrites, so corrupt the
        # cache entry too to simulate CDN drift.
        cache = Cache()
        cache.path_for(target.integrity).write_bytes(b"// tampered")
        sync(lock, config.output_path, fetch=no_network, offline=True)
    assert exc.value.url == target.url


def test_prune_removes_unlocked_files(config, cache_dir):
    lock = _lock(config)
    sync(lock, config.output_path, fetch=RecordingFetch().download)
    stray = config.output_path / "stray.js"
    stray.write_text("orphan")
    report = sync(lock, config.output_path, fetch=no_network, offline=True)
    assert "stray.js" in report.pruned
    assert not stray.exists()


def test_protect_keeps_importmap(config, cache_dir):
    lock = _lock(config)
    sync(lock, config.output_path, fetch=RecordingFetch().download)
    keep = config.output_path / "importmap.json"
    keep.write_text("{}")
    sync(lock, config.output_path, fetch=no_network, offline=True, protect={"importmap.json"})
    assert keep.exists()
