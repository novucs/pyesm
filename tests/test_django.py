"""Django integration: request-time import map through staticfiles storage.

Covers acceptance tests #6 (hashed URLs + integrity still valid after
collectstatic with ManifestStaticFilesStorage) and #9 (the storage does not
rewrite the root-relative CDN specifiers inside vendored modules).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from fake_cdn import RecordingFetch, fake_get_json
from pyesm.config import load_config
from pyesm.hashing import sri_hash
from pyesm.lockfile import dump_lock
from pyesm.resolve import resolve
from pyesm.vendor import sync


@pytest.fixture(scope="module")
def django_project(tmp_path_factory):
    base = tmp_path_factory.mktemp("djproj")
    project = base / "site"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "site"
            version = "0.0.0"

            [tool.pyesm]
            output-dir = "static/pyesm"
            base-url = "/static/pyesm/"
            shims = "auto"

            [tool.pyesm.dependencies]
            react = "^18.2.0"
            "react-dom" = "^18.2.0"
            """
        ).lstrip(),
        encoding="utf-8",
    )

    import os

    os.environ["PYESM_CACHE_DIR"] = str(base / "cache")
    cfg = load_config(project)
    lock = resolve(cfg, fetch=RecordingFetch().crawl, get_json=fake_get_json)
    dump_lock(lock, cfg.lock_path)
    sync(lock, cfg.output_path, fetch=RecordingFetch().download)

    static_root = base / "collected"

    import django
    from django.conf import settings

    settings.configure(
        DEBUG=False,
        SECRET_KEY="test",
        INSTALLED_APPS=[
            "django.contrib.staticfiles",
            "pyesm.contrib.django",
        ],
        STATIC_URL="/static/",
        STATIC_ROOT=str(static_root),
        STATICFILES_DIRS=[str(project / "static")],
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
            },
        },
        PYESM_PROJECT_ROOT=str(project),
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {},
            }
        ],
    )
    django.setup()

    from django.core.management import call_command

    call_command("collectstatic", interactive=False, verbosity=0)

    from pyesm.contrib.django import rendering

    rendering.clear_cache()
    return {"project": project, "static_root": static_root, "lock": lock}


def _render(django_project):
    from django.template import Context, Template

    tpl = Template("{% load pyesm %}{% pyesm_importmap %}")
    return tpl.render(Context({}))


def test_template_tag_renders_hashed_urls_with_integrity(django_project):
    html = _render(django_project)
    assert '<script type="importmap">' in html
    start = html.index("{")
    end = html.rindex("}") + 1
    data = json.loads(html[start:end])

    react_url = data["imports"]["react"]
    # Manifest storage hashed the filename.
    assert react_url.startswith("/static/pyesm/react@18.2.0/+esm.")
    assert react_url.endswith(".js")
    assert react_url != "/static/pyesm/react@18.2.0/+esm.js"

    # Root-relative key remaps to the hashed local URL, not a CDN URL.
    assert data["imports"]["/npm/react@18.2.0/+esm"] == react_url
    # Integrity present for every importable URL.
    for url in data["imports"].values():
        assert url in data["integrity"]


def test_integrity_valid_against_hashed_bytes(django_project):
    """#6: integrity from the lock still validates the served (hashed) bytes."""
    html = _render(django_project)
    data = json.loads(html[html.index("{") : html.rindex("}") + 1])
    static_root: Path = django_project["static_root"]

    for url, integrity in data["integrity"].items():
        rel = url[len("/static/") :]
        served = (static_root / rel).read_bytes()
        assert sri_hash(served) == integrity


def test_shim_tag_is_local_and_integrity_checked(django_project):
    """The es-module-shims tag points at the hashed local file, not a CDN."""
    html = _render(django_project)
    assert "<script async src=" in html
    assert "es-module-shims@" in html
    assert 'integrity="sha384-' in html
    # no CDN dependency at runtime
    assert "jspm.io" not in html
    assert "cdn.jsdelivr.net" not in html
    assert "esm.sh" not in html

    # the shim src is a hashed static URL and the served bytes match the integrity
    import re

    m = re.search(r'<script async src="([^"]+)" integrity="([^"]+)">', html)
    assert m, html
    src, integrity = m.group(1), m.group(2)
    assert "/es-module-shims@" in src
    static_root: Path = django_project["static_root"]
    served = (static_root / src[len("/static/") :]).read_bytes()
    assert sri_hash(served) == integrity


def test_manifest_does_not_rewrite_cdn_specifiers(django_project):
    """#9: absolute/root-relative CDN imports inside modules are untouched."""
    static_root: Path = django_project["static_root"]
    # Find the hashed react-dom file.
    matches = list((static_root / "pyesm").glob("react-dom@18.2.0/+esm.*.js"))
    assert matches, "hashed react-dom file not found"
    content = matches[0].read_text()
    assert 'import e from"/npm/react@18.2.0/+esm"' in content
    assert 'import n from"/npm/scheduler@0.23.2/+esm"' in content
