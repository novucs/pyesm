"""Read ``[tool.pyesm]`` configuration from a consumer ``pyproject.toml``."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .shims import ESMS_VERSION, should_inject

# ``integrity`` defaults to True (SRI on); set False to omit the import map's
# integrity block.
_DEFAULTS = {
    "provider": "jsdelivr",
    "output-dir": "static/pyesm",
    "base-url": "/static/pyesm/",
    "importmap": "static/pyesm/importmap.json",
    "production": True,
    "shims": "auto",
    "concurrency": 16,
    "integrity": True,
}

_VALID_SHIMS = {"auto", "always", "never"}


@dataclass
class Config:
    """Resolved pyesm configuration plus the project root it was read from."""

    project_root: Path
    provider: str = "jsdelivr"
    output_dir: str = "static/pyesm"
    base_url: str = "/static/pyesm/"
    importmap: str = "static/pyesm/importmap.json"
    production: bool = True
    shims: str = "auto"
    concurrency: int = 16
    integrity: bool = True
    dependencies: dict[str, str] = field(default_factory=dict)

    @property
    def output_path(self) -> Path:
        return (self.project_root / self.output_dir).resolve()

    @property
    def importmap_path(self) -> Path:
        return (self.project_root / self.importmap).resolve()

    @property
    def lock_path(self) -> Path:
        return self.project_root / "pyesm.lock"

    @property
    def pyproject_path(self) -> Path:
        return self.project_root / "pyproject.toml"

    def inputs_hash(self) -> str:
        """Stable ``sha256-<hex>`` over the inputs that affect resolution
        (provider, production flag, dependencies, shims). Drives lock staleness."""
        payload = {
            "provider": self.provider,
            "production": self.production,
            "dependencies": dict(sorted(self.dependencies.items())),
            "shims": ESMS_VERSION if should_inject(self.shims) else False,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256-{hashlib.sha256(blob).hexdigest()}"


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward from ``start`` to the nearest directory with pyproject.toml."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ConfigError("no pyproject.toml found in this or any parent directory")


def load_config(project_root: Path | None = None) -> Config:
    """Load and validate ``[tool.pyesm]`` from the project's pyproject.toml."""
    root = project_root or find_project_root()
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise ConfigError(f"no pyproject.toml at {pyproject}")

    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)

    # A missing [tool.pyesm] section means "all defaults"; `pyesm add` works on
    # a bare pyproject.toml without any setup.
    tool = data.get("tool", {}).get("pyesm") or {}
    if "integrity" in tool and not isinstance(tool["integrity"], bool):
        raise ConfigError(f"integrity must be a boolean, got {tool['integrity']!r}")

    merged = {**_DEFAULTS, **{k: v for k, v in tool.items() if k != "dependencies"}}

    cfg = Config(
        project_root=root,
        provider=str(merged["provider"]),
        output_dir=str(merged["output-dir"]),
        base_url=str(merged["base-url"]),
        importmap=str(merged["importmap"]),
        production=bool(merged["production"]),
        shims=str(merged["shims"]),
        concurrency=int(merged["concurrency"]),
        integrity=bool(merged["integrity"]),
        dependencies=_normalize_dependencies(tool.get("dependencies", {})),
    )
    _validate(cfg)
    return cfg


def _normalize_dependencies(deps: dict) -> dict[str, str]:
    """Expand the dependency table into a flat ``specifier -> range`` map.

    A value is either a range string, or a table ``{version, subpaths, root}``.
    A table with ``subpaths`` expands to one ``"<package>/<subpath>"`` entry per
    subpath (all sharing the one version); with no subpaths it is the package
    root. ``root = true`` additionally imports the bare package alongside its
    subpaths. Both inline and nested-sub-table TOML syntaxes parse the same.
    """
    out: dict[str, str] = {}
    for key, val in deps.items():
        key = str(key)
        if isinstance(val, str):
            out[key] = val
            continue
        if not isinstance(val, dict):
            raise ConfigError(f"dependency {key!r} must be a version string or a table")
        unknown = set(val) - {"version", "subpaths", "root"}
        if unknown:
            raise ConfigError(f"dependency {key!r} has unknown keys: {sorted(unknown)}")
        version = val.get("version", "")
        if not isinstance(version, str):
            raise ConfigError(f"dependency {key!r}: version must be a string")
        subpaths = val.get("subpaths", [])
        if not isinstance(subpaths, list) or not all(isinstance(s, str) for s in subpaths):
            raise ConfigError(f"dependency {key!r}: subpaths must be a list of strings")
        root = val.get("root", False)
        if not isinstance(root, bool):
            raise ConfigError(f"dependency {key!r}: root must be a boolean")
        if subpaths:
            for sub in subpaths:
                out[f"{key}/{sub.strip('/')}"] = version
            if root:  # import the bare package too, not only its subpaths
                out[key] = version
        else:
            out[key] = version
    return out


def _validate(cfg: Config) -> None:
    if cfg.shims not in _VALID_SHIMS:
        raise ConfigError(f"invalid shims={cfg.shims!r}; expected one of {sorted(_VALID_SHIMS)}")
    if cfg.concurrency < 1:
        raise ConfigError(f"concurrency must be >= 1, got {cfg.concurrency}")
    if not cfg.base_url.endswith("/"):
        raise ConfigError(f"base-url should end with '/', got {cfg.base_url!r}")
