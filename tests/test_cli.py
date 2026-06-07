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
