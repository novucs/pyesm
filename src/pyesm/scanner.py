"""Scan CDN-built ESM for module specifiers.

CDN output is machine-generated with consistent quoting, so a tolerant regex
scanner covers the four static forms:

  * ``import … from "URL"``
  * ``export … from "URL"``
  * bare ``import "URL"`` (side-effect import)
  * statically-analyzable dynamic ``import("URL")``

Runtime-computed dynamic imports (``import(someVar)``) cannot be discovered.
"""

from __future__ import annotations

import re

# A string literal, single or double quoted (no escaped-quote handling needed
# for URL specifiers, which never contain quotes).
_STR = r"""(['"])([^'"\n]+)\1"""

# import/export ... from "spec": the gap excludes ';' so we never cross a
# statement boundary, but allows '{ }' for named bindings and '*' for re-export.
_FROM = re.compile(r"""(?:\bimport\b|\bexport\b)[^;]*?\bfrom\s*""" + _STR)

# bare side-effect import:  import "spec"
_BARE = re.compile(r"""\bimport\s*""" + _STR)

# dynamic import call:  import( "spec" )
_DYNAMIC = re.compile(r"""\bimport\s*\(\s*""" + _STR + r"""\s*\)""")


def scan_imports(source: str) -> list[str]:
    """Return module specifiers found in ``source``, de-duplicated in order."""
    seen: set[str] = set()
    out: list[str] = []

    def add(spec: str) -> None:
        if spec not in seen:
            seen.add(spec)
            out.append(spec)

    for pat in (_FROM, _BARE, _DYNAMIC):
        for m in pat.finditer(source):
            add(m.group(2))

    return out
