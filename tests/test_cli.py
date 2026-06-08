import json
import tomllib

import pytest

from pyesm.cli import main


@pytest.fixture
def in_project(project, cache_dir, stub_network, monkeypatch):
    monkeypatch.chdir(project)
    return project


def test_lock_then_build(in_project):
    assert main(["lock"]) == 0
    lock = json.loads((in_project / "pyesm.lock").read_text())
    assert lock["provider"] == "jsdelivr"
    assert set(lock["imports"]) == {"react", "react-dom"}

    assert main(["build"]) == 0
    im = json.loads((in_project / "static/pyesm/importmap.json").read_text())
    assert im["imports"]["react"] == "/static/pyesm/react@18.2.0/+esm.js"
    assert "/npm/react@18.2.0/+esm" in im["imports"]
    # integrity present for every importable URL
    for url in im["imports"].values():
        assert url in im["integrity"]


def test_bare_shows_help_and_does_nothing(in_project, capsys):
    assert main([]) == 0
    assert "usage: pyesm" in capsys.readouterr().out
    # No subcommand => no side effects.
    assert not (in_project / "pyesm.lock").exists()
    assert not (in_project / "static/pyesm").exists()


def test_sync_offline_warm_cache(in_project):
    assert main(["sync"]) == 0
    # Remove vendored files (keep cache + lock), re-sync offline.
    for p in sorted((in_project / "static/pyesm").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else None
    assert main(["--offline", "sync"]) == 0
    assert (in_project / "static/pyesm/react@18.2.0/+esm.js").is_file()


def test_frozen_missing_lock_fails(in_project):
    assert main(["--frozen", "sync"]) == 2


def test_frozen_stale_lock_fails(in_project):
    assert main(["lock"]) == 0
    # Make the lock stale by editing deps.
    from pyesm._pyproject import add_dependency

    add_dependency(in_project / "pyproject.toml", "scheduler", "0.23.2")
    assert main(["--frozen", "sync"]) == 2


def test_add_mutates_pyproject_and_vendors(in_project):
    assert main(["add", "scheduler@0.23.2"]) == 0
    deps = tomllib.loads((in_project / "pyproject.toml").read_text())["tool"]["pyesm"][
        "dependencies"
    ]
    assert deps["scheduler"] == "0.23.2"
    lock = json.loads((in_project / "pyesm.lock").read_text())
    assert "scheduler" in lock["imports"]


def test_atomic_files_rollback(tmp_path):
    from pyesm.cli import _atomic_files

    existing = tmp_path / "keep.toml"
    existing.write_text("original")
    created = tmp_path / "new.lock"  # does not exist yet

    with pytest.raises(ValueError), _atomic_files(existing, created):
        existing.write_text("mutated")
        created.write_text("created")
        raise ValueError("boom")

    assert existing.read_text() == "original"  # restored
    assert not created.exists()  # removed (didn't exist before)


def test_add_subpaths_group_into_inline_table(in_project):
    # the fake graph resolves these to scheduler@0.23.2; use its subpaths
    assert main(["add", "scheduler/foo", "scheduler/bar"]) == 0
    deps = tomllib.loads((in_project / "pyproject.toml").read_text())["tool"]["pyesm"][
        "dependencies"
    ]
    assert deps["scheduler"] == {"version": "^0.23.2", "subpaths": ["foo", "bar"]}
    # both subpath specifiers are in the lock's imports, one shared package version
    lock = json.loads((in_project / "pyesm.lock").read_text())
    assert "scheduler/foo" in lock["imports"]
    assert "scheduler/bar" in lock["imports"]
    assert main(["--frozen", "sync"]) == 0  # not left stale

    assert main(["remove", "scheduler/foo"]) == 0
    deps = tomllib.loads((in_project / "pyproject.toml").read_text())["tool"]["pyesm"][
        "dependencies"
    ]
    assert deps["scheduler"]["subpaths"] == ["bar"]


def test_vendored_modules_strip_cdn_boilerplate(in_project):
    # fake scheduler ends with `//# sourceMappingURL=/sm/…` and fake react starts
    # with a jsDelivr banner; vendoring through the real fetch path strips both.
    assert main(["add", "scheduler"]) == 0
    scheduler = (in_project / "static/pyesm/scheduler@0.23.2/+esm.js").read_text()
    react = (in_project / "static/pyesm/react@18.2.0/+esm.js").read_text()
    assert "sourceMappingURL" not in scheduler
    assert "Bundled by jsDelivr" not in react
    assert main(["--frozen", "sync"]) == 0  # integrity still matches (hash over served bytes)


def test_add_root_then_subpath_keeps_both_imports(in_project):
    # `pyesm add scheduler` then `pyesm add scheduler/foo` must import BOTH the
    # bare package and the subpath (regression: the root used to be dropped).
    assert main(["add", "scheduler"]) == 0
    assert main(["add", "scheduler/foo"]) == 0
    deps = tomllib.loads((in_project / "pyproject.toml").read_text())["tool"]["pyesm"][
        "dependencies"
    ]
    assert deps["scheduler"] == {"version": "^0.23.2", "subpaths": ["foo"], "root": True}
    lock = json.loads((in_project / "pyesm.lock").read_text())
    assert "scheduler" in lock["imports"]
    assert "scheduler/foo" in lock["imports"]
    assert main(["--frozen", "sync"]) == 0  # not left stale


def test_add_without_version_backfills_caret_range(in_project):
    assert main(["add", "scheduler"]) == 0
    deps = tomllib.loads((in_project / "pyproject.toml").read_text())["tool"]["pyesm"][
        "dependencies"
    ]
    # resolved version (0.23.2 in the fake graph) pinned as a caret range
    assert deps["scheduler"] == "^0.23.2"
    # and the lock isn't left stale by the specifier rewrite
    assert main(["--frozen", "sync"]) == 0


def test_clean_keeps_lock(in_project):
    assert main(["sync"]) == 0
    assert main(["clean"]) == 0
    assert not (in_project / "static/pyesm/react@18.2.0/+esm.js").exists()
    assert (in_project / "pyesm.lock").is_file()


def test_outdated_up_to_date(in_project, capsys):
    assert main(["lock"]) == 0
    assert main(["outdated"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_remove_reresolves(in_project):
    assert main(["sync"]) == 0
    assert main(["remove", "react-dom"]) == 0
    lock = json.loads((in_project / "pyesm.lock").read_text())
    assert "react-dom" not in lock["imports"]
