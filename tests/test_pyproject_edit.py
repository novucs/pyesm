import textwrap
import tomllib

from pyesm._pyproject import add_dependency, remove_dependency, split_spec


def test_split_spec():
    assert split_spec("react@^18.2.0") == ("react", "^18.2.0")
    assert split_spec("@scope/pkg@1.2.3") == ("@scope/pkg", "1.2.3")
    assert split_spec("lit") == ("lit", "")


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
