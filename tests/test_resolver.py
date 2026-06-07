import asyncio

import pytest

from pyesm.errors import ResolveError
from pyesm.resolver import resolve_graph


def _registry(versions: dict[str, list[str]], manifests: dict[tuple[str, str], dict]):
    """Fake fetch_packument / fetch_manifest over an in-memory registry."""

    async def fetch_packument(pkg):
        return {"versions": versions[pkg], "tags": {"latest": versions[pkg][-1]}}

    async def fetch_manifest(pkg, ver):
        return manifests.get((pkg, ver), {})

    return fetch_packument, fetch_manifest


def _resolve(deps, versions, manifests):
    fp, fm = _registry(versions, manifests)
    return asyncio.run(resolve_graph(deps, fetch_packument=fp, fetch_manifest=fm))


def test_transitive_dedup_to_one_version():
    versions = {
        "react": ["18.2.0", "18.3.1"],
        "react-dom": ["18.2.0", "18.3.1"],
        "scheduler": ["0.23.0", "0.23.2"],
    }
    manifests = {
        ("react-dom", "18.3.1"): {
            "dependencies": {"scheduler": "^0.23.0"},
            "peerDependencies": {"react": "^18.3.1"},  # peer deps are constraints too
        },
    }
    resolved = _resolve([("react", "^18.2.0"), ("react-dom", "^18.2.0")], versions, manifests)
    assert resolved == {"react": "18.3.1", "react-dom": "18.3.1", "scheduler": "0.23.2"}


def test_backtracks_to_compatible_intermediate_version():
    # A->B ; C->B, C->D@^2 ; B@latest->D@^3 but B@earlier->D@^2.
    # Greedy would pick B@2.0.0 -> D conflict; a real resolver backtracks to
    # B@1.9.0 (which needs D@^2) so D@2.5.0 satisfies everyone.
    versions = {"A": ["1.0.0"], "C": ["1.0.0"], "B": ["1.9.0", "2.0.0"], "D": ["2.5.0", "3.1.0"]}
    manifests = {
        ("A", "1.0.0"): {"dependencies": {"B": ">=1.0.0"}},
        ("C", "1.0.0"): {"dependencies": {"B": ">=1.0.0", "D": "^2.0.0"}},
        ("B", "2.0.0"): {"dependencies": {"D": "^3.0.0"}},
        ("B", "1.9.0"): {"dependencies": {"D": "^2.0.0"}},
    }
    resolved = _resolve([("A", ">=1.0.0"), ("C", ">=1.0.0")], versions, manifests)
    assert resolved["B"] == "1.9.0"  # backtracked off the latest
    assert resolved["D"] == "2.5.0"


def test_genuine_conflict_raises():
    versions = {"A": ["1.0.0"], "C": ["1.0.0"], "dep": ["1.4.9", "2.1.0"]}
    manifests = {
        ("A", "1.0.0"): {"dependencies": {"dep": "~1.4.0"}},  # 1.4.x only
        ("C", "1.0.0"): {"dependencies": {"dep": "^2.0.0"}},  # 2.x only
    }
    with pytest.raises(ResolveError, match="cannot resolve a single version of 'dep'"):
        _resolve([("A", "1.0.0"), ("C", "1.0.0")], versions, manifests)


def test_optional_peer_dependency_is_not_required():
    versions = {"a": ["1.0.0"]}
    manifests = {
        ("a", "1.0.0"): {
            "peerDependencies": {"react": "^18.0.0"},
            "peerDependenciesMeta": {"react": {"optional": True}},
        },
    }
    # react is an *optional* peer and not published here; resolution must not
    # try to pull it in.
    assert _resolve([("a", "^1.0.0")], versions, manifests) == {"a": "1.0.0"}
