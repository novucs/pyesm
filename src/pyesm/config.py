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
    deps = dict(tool.get("dependencies", {}))

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
        dependencies={str(k): str(v) for k, v in deps.items()},
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.shims not in _VALID_SHIMS:
        raise ConfigError(f"invalid shims={cfg.shims!r}; expected one of {sorted(_VALID_SHIMS)}")
    if cfg.concurrency < 1:
        raise ConfigError(f"concurrency must be >= 1, got {cfg.concurrency}")
    if not cfg.base_url.endswith("/"):
        raise ConfigError(f"base-url should end with '/', got {cfg.base_url!r}")
