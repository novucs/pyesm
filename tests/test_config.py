import textwrap

import pytest

from pyesm.config import Config, load_config
from pyesm.errors import ConfigError


def _write(root, body):
    (root / "pyproject.toml").write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def test_defaults_and_dependencies(config: Config):
    assert config.provider == "jsdelivr"
    assert config.output_dir == "static/pyesm"
    assert config.base_url == "/static/pyesm/"
    assert config.shims == "auto"
    assert config.concurrency == 16
    assert config.dependencies == {"react": "^18.2.0", "react-dom": "^18.2.0"}


def test_inputs_hash_stable_and_order_independent(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write(
        a,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        react = "^18.2.0"
        lit = "3"
    """,
    )
    _write(
        b,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        lit = "3"
        react = "^18.2.0"
    """,
    )
    assert load_config(a).inputs_hash() == load_config(b).inputs_hash()


def test_inputs_hash_changes_with_provider(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        provider = "jsdelivr"
        [tool.pyesm.dependencies]
        react = "^18.2.0"
    """,
    )
    cfg = load_config(tmp_path)
    h1 = cfg.inputs_hash()
    cfg.provider = "esmsh"
    assert cfg.inputs_hash() != h1


def test_table_dependencies_expand_to_subpaths(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        react = "^18.2.0"
        "@codemirror/legacy-modes" = { version = "^6.5.3", subpaths = ["mode/toml", "/mode/lua/"] }
    """,
    )
    deps = load_config(tmp_path).dependencies
    assert deps == {
        "react": "^18.2.0",
        "@codemirror/legacy-modes/mode/toml": "^6.5.3",
        "@codemirror/legacy-modes/mode/lua": "^6.5.3",
    }


def test_root_flag_imports_package_alongside_subpaths(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        sigma = { version = "^3.0.0", subpaths = ["rendering"], root = true }
    """,
    )
    deps = load_config(tmp_path).dependencies
    assert deps == {"sigma": "^3.0.0", "sigma/rendering": "^3.0.0"}


def test_root_must_be_boolean(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        sigma = { version = "^3.0.0", subpaths = ["rendering"], root = "yes" }
    """,
    )
    with pytest.raises(ConfigError, match="root must be a boolean"):
        load_config(tmp_path)


def test_table_and_equivalent_flat_hash_identically(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write(
        a,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        "@codemirror/legacy-modes" = { version = "^6.5.3", subpaths = ["mode/toml", "mode/lua"] }
    """,
    )
    _write(
        b,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        "@codemirror/legacy-modes/mode/toml" = "^6.5.3"
        "@codemirror/legacy-modes/mode/lua" = "^6.5.3"
    """,
    )
    assert load_config(a).inputs_hash() == load_config(b).inputs_hash()


def test_malformed_table_dependency_rejected(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        [tool.pyesm.dependencies]
        "x" = { version = "1", subpath = "a" }
    """,
    )
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(tmp_path)


def test_inputs_hash_changes_with_shims(config: Config):
    h_auto = config.inputs_hash()
    config.shims = "never"
    assert config.inputs_hash() != h_auto


def test_integrity_defaults_on(config: Config):
    assert config.integrity is True


def test_integrity_can_be_disabled(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        integrity = false
        [tool.pyesm.dependencies]
        react = "^18.2.0"
    """,
    )
    assert load_config(tmp_path).integrity is False


def test_integrity_must_be_boolean(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        integrity = "yes"
    """,
    )
    with pytest.raises(ConfigError, match="integrity must be a boolean"):
        load_config(tmp_path)


def test_invalid_shims_rejected(tmp_path):
    _write(
        tmp_path,
        """
        [tool.pyesm]
        shims = "sometimes"
    """,
    )
    with pytest.raises(ConfigError, match="shims"):
        load_config(tmp_path)


def test_missing_section_uses_defaults(tmp_path):
    _write(
        tmp_path,
        """
        [project]
        name = "x"
    """,
    )
    cfg = load_config(tmp_path)
    assert cfg.provider == "jsdelivr"
    assert cfg.dependencies == {}
