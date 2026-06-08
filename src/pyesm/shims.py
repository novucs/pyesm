"""es-module-shims, controlled by the ``shims`` setting:

* ``auto`` (default) / ``always`` -> vendor the polyfill and inject it. It
  extends import-map ``integrity`` enforcement to browsers with no native
  import-map support (where the polyfill fully engages); on browsers that have
  import maps but not native integrity (Firefox/Safari) the field stays
  advisory, since the polyfill defers to the native loader there.
* ``never`` -> do not vendor or inject.

The polyfill is vendored locally (from the configured provider) and served from
``output-dir`` with its own SRI, so production makes no CDN request for it.
"""

from __future__ import annotations

ESMS_VERSION = "2.8.1"


def should_inject(setting: str) -> bool:
    return setting in ("auto", "always")


def shims_script_tag(src: str, integrity: str) -> str:
    """Return the es-module-shims ``<script>`` tag for a local ``src``."""
    return f'<script async src="{src}" integrity="{integrity}"></script>'
