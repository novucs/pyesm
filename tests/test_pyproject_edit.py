import textwrap
import tomllib

from pyesm._pyproject import (
    add_dependency,
    add_subpath_dependency,
    remove_dependency,
    remove_subpath_dependency,
    split_spec,
    split_subpath,
)


def test_split_spec():
    assert split_spec("react@^18.2.0") == ("react", "^18.2.0")
    assert split_spec("@scope/pkg@1.2.3") == ("@scope/pkg", "1.2.3")
    assert split_spec("lit") == ("lit", "")


def test_split_spec_subpaths():
    # subpath without a version
    assert split_spec("@codemirror/legacy-modes/mode/toml") == (
        "@codemirror/legacy-modes/mode/toml",
        "",
    )
    # version sits between the package and the subpath (npm-style)
    assert split_spec("@codemirror/legacy-modes@6.5.2/mode/toml") == (
        "@codemirror/legacy-modes/mode/toml",
        "6.5.2",
    )
    # unscoped subpath
    assert split_spec("d3-array/array") == ("d3-array/array", "")


def _proj(tmp_path, body):
    p = tmp_path / "pyproject.toml"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


def _deps(path):
    return tomllib.loads(path.read_text())["tool"]["pyesm"]["dependencies"]


def test_add_into_existing_section_preserves_comments(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        # keep me
        react = "^18.2.0"
    """,
    )
    add_dependency(p, "lit", "3")
    assert _deps(p) == {"react": "^18.2.0", "lit": "3"}
    assert "# keep me" in p.read_text()


def test_add_updates_existing_key(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        react = "^18.2.0"
    """,
    )
    add_dependency(p, "react", "^18.3.0")
    assert _deps(p) == {"react": "^18.3.0"}


def test_add_quotes_scoped_keys(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        react = "^18.2.0"
    """,
    )
    add_dependency(p, "@scope/pkg", "1")
    assert _deps(p)["@scope/pkg"] == "1"


def test_add_creates_section_when_missing(tmp_path):
    p = _proj(
        tmp_path,
        """
        [project]
        name = "x"
    """,
    )
    add_dependency(p, "react", "^18.2.0")
    assert _deps(p) == {"react": "^18.2.0"}


def test_remove(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        react = "^18.2.0"
        "react-dom" = "^18.2.0"
    """,
    )
    assert remove_dependency(p, "react-dom") is True
    assert _deps(p) == {"react": "^18.2.0"}
    assert remove_dependency(p, "nope") is False


def test_split_subpath():
    assert split_subpath("@codemirror/legacy-modes/mode/toml") == (
        "@codemirror/legacy-modes",
        "mode/toml",
    )
    assert split_subpath("react") == ("react", "")
    assert split_subpath("d3-array/array") == ("d3-array", "array")


def test_add_subpath_creates_and_merges_inline_table(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        react = "^18.2.0"
    """,
    )
    add_subpath_dependency(p, "@codemirror/legacy-modes", "^6.5.3", "mode/toml")
    add_subpath_dependency(p, "@codemirror/legacy-modes", "", "mode/lua")  # merge, keep version
    add_subpath_dependency(p, "@codemirror/legacy-modes", "", "mode/toml")  # dedup
    dep = _deps(p)["@codemirror/legacy-modes"]
    assert dep == {"version": "^6.5.3", "subpaths": ["mode/toml", "mode/lua"]}
    assert _deps(p)["react"] == "^18.2.0"  # string deps untouched


def test_add_subpath_preserves_an_existing_root_dep(tmp_path):
    # `pyesm add sigma` then `pyesm add sigma/rendering` must keep importing the
    # bare `sigma` root (regression: the root used to be silently dropped).
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        sigma = "^3.0.0"
    """,
    )
    add_subpath_dependency(p, "sigma", "", "rendering")
    assert _deps(p)["sigma"] == {"version": "^3.0.0", "subpaths": ["rendering"], "root": True}


def test_add_root_to_an_existing_subpath_table_sets_root(tmp_path):
    # the reverse order: a subpath table already exists, then the root is added.
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        sigma = { version = "^3.0.0", subpaths = ["rendering"] }
    """,
    )
    add_dependency(p, "sigma", "^3.0.0")
    assert _deps(p)["sigma"] == {"version": "^3.0.0", "subpaths": ["rendering"], "root": True}


def test_remove_last_subpath_with_root_collapses_to_root(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        sigma = { version = "^3.0.0", subpaths = ["rendering"], root = true }
    """,
    )
    assert remove_subpath_dependency(p, "sigma", "rendering") is True
    assert _deps(p)["sigma"] == "^3.0.0"  # collapses back to a bare root dep


def test_remove_subpath_drops_one_then_the_dep(tmp_path):
    p = _proj(
        tmp_path,
        """
        [tool.pyesm.dependencies]
        "@codemirror/legacy-modes" = { version = "^6.5.3", subpaths = ["mode/toml", "mode/lua"] }
    """,
    )
    assert remove_subpath_dependency(p, "@codemirror/legacy-modes", "mode/toml") is True
    assert _deps(p)["@codemirror/legacy-modes"]["subpaths"] == ["mode/lua"]
    # removing the last subpath drops the whole dependency
    assert remove_subpath_dependency(p, "@codemirror/legacy-modes", "mode/lua") is True
    assert "@codemirror/legacy-modes" not in _deps(p)
    assert remove_subpath_dependency(p, "@codemirror/legacy-modes", "x") is False
