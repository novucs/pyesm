"""Targeted line edits to ``[tool.pyesm.dependencies]`` that preserve the rest
of the file (comments, other tables) without a TOML-writer dependency."""

from __future__ import annotations

import os
from pathlib import Path

SECTION = "[tool.pyesm.dependencies]"


def split_spec(spec: str) -> tuple[str, str]:
    """Split ``name[@range]`` into ``(name, range)``; scope-aware.

    ``react@^18.2.0`` -> ``("react", "^18.2.0")``;
    ``@scope/pkg@1.2`` -> ``("@scope/pkg", "1.2")``;
    ``lit``           -> ``("lit", "")``.
    """
    at = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
    if at <= 0:
        return spec, ""
    return spec[:at], spec[at + 1 :]


def _toml_key(name: str) -> str:
    # Quote keys containing characters that need it (dots, scopes, slashes).
    bare_ok = all(c.isalnum() or c in "-_" for c in name)
    return name if bare_ok else f'"{name}"'


def _matches_key(line: str, name: str) -> bool:
    stripped = line.strip()
    if "=" not in stripped:
        return False
    lhs = stripped.split("=", 1)[0].strip().strip('"')
    return lhs == name


def add_dependency(pyproject: Path, name: str, range_: str) -> None:
    """Add or update ``name = "range"`` in the dependencies table."""
    lines = pyproject.read_text(encoding="utf-8").splitlines(keepends=True)
    entry = f'{_toml_key(name)} = "{range_}"\n'

    sec_idx = _find_section(lines)
    if sec_idx is None:
        # Append a new section at end of file.
        prefix = "" if not lines or lines[-1].endswith("\n") else "\n"
        block = f"{prefix}\n{SECTION}\n{entry}"
        _write(pyproject, "".join(lines) + block)
        return

    end_idx = _section_end(lines, sec_idx)
    for i in range(sec_idx + 1, end_idx):
        if _matches_key(lines[i], name):
            lines[i] = entry
            _write(pyproject, "".join(lines))
            return
    lines.insert(end_idx, entry)
    _write(pyproject, "".join(lines))


def remove_dependency(pyproject: Path, name: str) -> bool:
    """Remove ``name`` from the dependencies table. Returns True if removed."""
    lines = pyproject.read_text(encoding="utf-8").splitlines(keepends=True)
    sec_idx = _find_section(lines)
    if sec_idx is None:
        return False
    end_idx = _section_end(lines, sec_idx)
    for i in range(sec_idx + 1, end_idx):
        if _matches_key(lines[i], name):
            del lines[i]
            _write(pyproject, "".join(lines))
            return True
    return False


def _find_section(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if line.strip() == SECTION:
            return i
    return None


def _section_end(lines: list[str], sec_idx: int) -> int:
    """Index just past the last entry line of the section (before next table)."""
    end = len(lines)
    for i in range(sec_idx + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    # Trim trailing blank lines back into the section boundary.
    while end > sec_idx + 1 and lines[end - 1].strip() == "":
        end -= 1
    return end


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
