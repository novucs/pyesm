"""Edit ``[tool.pyesm.dependencies]`` with tomlkit, preserving the rest of the
file (comments, formatting, key order)."""

from __future__ import annotations

import os
from pathlib import Path

import tomlkit


def split_spec(spec: str) -> tuple[str, str]:
    """Split ``name[@range][/subpath]`` into ``(name+subpath, range)``.

    The version sits between the package name and any subpath, npm-style:

    ``react@^18.2.0``               -> ``("react", "^18.2.0")``;
    ``lodash-es/debounce``          -> (unchanged, "");
    ``lit``                         -> ``("lit", "")``.
    """
    # The version '@' is the first '@' after a leading scope '@'.
    at = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
    if at <= 0:
        return spec, ""
    rest = spec[at + 1 :]
    slash = rest.find("/")
    if slash == -1:
        return spec[:at], rest
    version, subpath = rest[:slash], rest[slash:]  # subpath keeps its leading /
    return spec[:at] + subpath, version


def split_subpath(name: str) -> tuple[str, str]:
    """Split a bare specifier into ``(package, subpath)``; scope-aware."""
    if name.startswith("@"):
        parts = name.split("/", 2)
        return "/".join(parts[:2]), parts[2] if len(parts) > 2 else ""
    pkg, _, subpath = name.partition("/")
    return pkg, subpath


def add_dependency(pyproject: Path, name: str, range_: str) -> None:
    """Add or update ``name = "range"`` (string form) in the dependencies table."""
    doc = _load(pyproject)
    _ensure_deps(doc)[name] = range_
    _save(pyproject, doc)


def add_subpath_dependency(pyproject: Path, package: str, version: str, subpath: str) -> None:
    """Add ``subpath`` under an inline-table dep for ``package``, merging into an
    existing entry (and setting ``version`` when given)."""
    doc = _load(pyproject)
    deps = _ensure_deps(doc)
    cur = deps.get(package)
    if cur is None or isinstance(cur, str):
        table = tomlkit.inline_table()
        table["version"] = version or (cur if isinstance(cur, str) else "")
        table["subpaths"] = [subpath]
        deps[package] = table
    else:
        if version:
            cur["version"] = version
        subs = cur.get("subpaths")
        if subs is None:
            cur["subpaths"] = [subpath]
        elif subpath not in subs:
            subs.append(subpath)
    _save(pyproject, doc)


def remove_dependency(pyproject: Path, name: str) -> bool:
    """Remove ``name`` from the dependencies table. Returns True if removed."""
    doc = _load(pyproject)
    deps = _get_deps(doc)
    if deps is None or name not in deps:
        return False
    del deps[name]
    _save(pyproject, doc)
    return True


def remove_subpath_dependency(pyproject: Path, package: str, subpath: str) -> bool:
    """Remove ``subpath`` from ``package``'s table; drop the dep if none remain."""
    doc = _load(pyproject)
    deps = _get_deps(doc)
    if deps is None:
        return False
    cur = deps.get(package)
    if cur is None or isinstance(cur, str):
        return False
    subs = cur.get("subpaths") or []
    if subpath not in subs:
        return False
    subs.remove(subpath)
    if not subs:
        del deps[package]
    _save(pyproject, doc)
    return True


# --------------------------------------------------------------------------- #


def _load(pyproject: Path):
    return tomlkit.parse(pyproject.read_text(encoding="utf-8"))


def _get_deps(doc):
    """Return the existing ``[tool.pyesm.dependencies]`` table, or None."""
    node = doc
    for part in ("tool", "pyesm", "dependencies"):
        node = node.get(part)
        if node is None:
            return None
    return node


def _ensure_deps(doc):
    """Return the ``[tool.pyesm.dependencies]`` table, creating it if absent."""
    node = doc
    for part in ("tool", "pyesm", "dependencies"):
        child = node.get(part)
        if child is None:
            child = tomlkit.table()
            node[part] = child
        node = child
    return node


def _save(pyproject: Path, doc) -> None:
    tmp = pyproject.with_name(f".{pyproject.name}.tmp.{os.getpid()}")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp, pyproject)
