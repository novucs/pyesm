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


def _read_group(cur) -> tuple[str, list[str], bool]:
    """Decompose a dependency value into ``(version, subpaths, root)``. A bare
    string is a root dep; a table carries its own fields."""
    if cur is None:
        return "", [], False
    if isinstance(cur, str):
        return str(cur), [], True
    subpaths = [str(s) for s in (cur.get("subpaths") or [])]
    return str(cur.get("version", "")), subpaths, bool(cur.get("root", False))


def _store_group(deps, package: str, version: str, subpaths: list[str], root: bool) -> None:
    """Write ``package`` back: a bare ``version`` string when it is only a root,
    else a freshly-built grouped inline table (rebuilt to dodge a tomlkit bug
    where appending a key to a parsed inline table drops its separator)."""
    if not subpaths:
        deps[package] = version
        return
    table = tomlkit.inline_table()
    table["version"] = version
    table["subpaths"] = sorted(subpaths)
    if root:
        table["root"] = True
    deps[package] = table


def add_dependency(pyproject: Path, name: str, range_: str) -> None:
    """Add or update the package root. Preserves an existing grouped (subpaths)
    table by flagging its root rather than clobbering the subpaths."""
    doc = _load(pyproject)
    deps = _ensure_deps(doc)
    version, subpaths, _ = _read_group(deps.get(name))
    if subpaths:  # keep the subpaths; just (re)assert the root import
        _store_group(deps, name, range_ or version, subpaths, root=True)
    else:
        deps[name] = range_
    _save(pyproject, doc)


def add_subpath_dependency(pyproject: Path, package: str, version: str, subpath: str) -> None:
    """Add ``subpath`` under a grouped table for ``package``, merging into an
    existing entry. A pre-existing bare root dep keeps importing the root."""
    doc = _load(pyproject)
    deps = _ensure_deps(doc)
    cur_version, subpaths, root = _read_group(deps.get(package))
    if subpath not in subpaths:
        subpaths.append(subpath)
    _store_group(deps, package, version or cur_version, subpaths, root=root)
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
    """Remove ``subpath`` from ``package``'s table; collapse to a bare root dep
    if ``root`` was set, else drop the dep once no subpaths remain."""
    doc = _load(pyproject)
    deps = _get_deps(doc)
    if deps is None:
        return False
    version, subpaths, root = _read_group(deps.get(package))
    if subpath not in subpaths:
        return False
    subpaths.remove(subpath)
    if subpaths:
        _store_group(deps, package, version, subpaths, root=root)
    elif root:
        deps[package] = version  # collapse back to a bare root dependency
    else:
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


def _sort_deps(deps) -> None:
    """Reorder the dependency table alphabetically by package key. Standalone
    comments survive (they migrate to the top of the table)."""
    items = sorted(deps.items(), key=lambda kv: kv[0])
    for key in [k for k, _ in items]:
        del deps[key]
    for key, val in items:
        deps[key] = val


def _save(pyproject: Path, doc) -> None:
    deps = _get_deps(doc)
    if deps is not None:
        _sort_deps(deps)
    tmp = pyproject.with_name(f".{pyproject.name}.tmp.{os.getpid()}")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp, pyproject)
