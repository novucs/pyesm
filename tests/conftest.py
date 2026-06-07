from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pyesm.config import Config


@pytest.fixture
def cache_dir(tmp_path, monkeypatch) -> Path:
    """Isolated global cache for the run (avoids touching ~/.cache)."""
    d = tmp_path / "cache"
    monkeypatch.setenv("PYESM_CACHE_DIR", str(d))
    return d


@pytest.fixture
def project(tmp_path) -> Path:
    """A tmp project dir with a pyproject.toml declaring react + react-dom."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "demo"
            version = "0.0.0"

            [tool.pyesm]
            provider = "jsdelivr"
            output-dir = "static/pyesm"
            base-url = "/static/pyesm/"

            [tool.pyesm.dependencies]
            react = "^18.2.0"
            "react-dom" = "^18.2.0"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def config(project) -> Config:
    from pyesm.config import load_config

    return load_config(project)


@pytest.fixture
def stub_network(monkeypatch):
    """Make every real network path serve the in-memory graph.

    The CLI builds its client via ``http.make_client``; patching that to return
    a MockTransport-backed client routes crawl, download, and the jsDelivr data
    API through the in-memory graph in one place, through the real httpx stack.
    """
    from fake_cdn import mock_client

    monkeypatch.setattr("pyesm.http.make_client", lambda concurrency=16: mock_client())
