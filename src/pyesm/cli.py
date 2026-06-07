"""pyesm command-line interface (stdlib argparse for fast cold start).

Heavy modules (resolve/crawl/vendor/network) are imported lazily inside the
command handlers so the CLI stays cheap to start.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import PyesmError, StaleLockError


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    ctx = _Ctx(
        frozen=args.frozen,
        offline=args.offline,
        provider=args.provider,
        verbosity=args.verbose - args.quiet,
    )
    handler = args.handler
    try:
        return handler(args, ctx) or 0
    except StaleLockError as exc:
        ctx.error(f"stale lock: {exc}")
        return 2
    except PyesmError as exc:
        ctx.error(str(exc))
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


# --------------------------------------------------------------------------- #
# Context / logging
# --------------------------------------------------------------------------- #


class _Ctx:
    def __init__(self, *, frozen, offline, provider, verbosity) -> None:
        self.frozen = frozen
        self.offline = offline
        self.provider = provider
        self.verbosity = verbosity

    def info(self, msg: str) -> None:
        if self.verbosity >= 0:
            print(msg)

    def detail(self, msg: str) -> None:
        if self.verbosity >= 1:
            print(msg)

    def error(self, msg: str) -> None:
        print(f"pyesm: error: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _load_config(ctx: _Ctx):
    from .config import load_config

    cfg = load_config()
    if ctx.provider:
        cfg.provider = ctx.provider
    return cfg


def _lock_is_stale(cfg, lock) -> bool:
    return lock.inputs_hash != cfg.inputs_hash() or lock.provider != cfg.provider


def _protected_rel(cfg) -> set[str]:
    """importmap.json path relative to output-dir, so prune never deletes it."""
    try:
        rel = cfg.importmap_path.relative_to(cfg.output_path).as_posix()
        return {rel}
    except ValueError:
        return set()


def _do_resolve_and_write(cfg, ctx: _Ctx):
    from .lockfile import dump_lock
    from .resolve import resolve

    if ctx.offline:
        raise PyesmError("cannot resolve while --offline (needs network)")
    ctx.info(f"resolving {len(cfg.dependencies)} dependencies via {cfg.provider}…")
    lock = resolve(cfg, provider_name=cfg.provider)
    dump_lock(lock, cfg.lock_path)
    ctx.info(f"wrote {cfg.lock_path.name} ({len(lock.modules)} modules)")
    return lock


def _build_static_map(cfg, lock, ctx: _Ctx) -> None:
    from .importmap import build_import_map, dump_import_map, static_public_url

    import_map = build_import_map(lock, static_public_url(cfg.base_url), integrity=cfg.integrity)
    dump_import_map(import_map, cfg.importmap_path)
    ctx.detail(f"wrote {cfg.importmap_path}")


def _do_sync(cfg, lock, ctx: _Ctx):
    from .vendor import sync

    report = sync(
        lock,
        cfg.output_path,
        offline=ctx.offline,
        protect=_protected_rel(cfg),
        concurrency=cfg.concurrency,
    )
    _build_static_map(cfg, lock, ctx)
    msg = f"synced {len(lock.modules)} modules "
    msg += f"({report.downloaded} downloaded, {report.reused} cached)"
    if report.pruned:
        msg += f", pruned {len(report.pruned)}"
    ctx.info(msg)
    return report


def _load_lock_or_fail(cfg, ctx: _Ctx):
    from .lockfile import load_lock

    if not cfg.lock_path.is_file():
        if ctx.frozen:
            raise StaleLockError("pyesm.lock is missing")
        return None
    return load_lock(cfg.lock_path)


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #


def cmd_lock(args, ctx: _Ctx) -> int:
    if ctx.frozen:
        raise PyesmError("--frozen cannot be used with 'lock' (it mutates the lock)")
    cfg = _load_config(ctx)
    _do_resolve_and_write(cfg, ctx)
    return 0


def cmd_sync(args, ctx: _Ctx) -> int:
    cfg = _load_config(ctx)
    lock = _load_lock_or_fail(cfg, ctx)
    if lock is None:
        lock = _do_resolve_and_write(cfg, ctx)
    elif _lock_is_stale(cfg, lock):
        if ctx.frozen:
            raise StaleLockError("pyesm.lock is out of date with pyproject.toml")
        ctx.info("lock is stale; re-resolving…")
        lock = _do_resolve_and_write(cfg, ctx)
    _do_sync(cfg, lock, ctx)
    return 0


def cmd_build(args, ctx: _Ctx) -> int:
    cfg = _load_config(ctx)
    lock = _load_lock_or_fail(cfg, ctx)
    if lock is None:
        raise StaleLockError("pyesm.lock is missing; run 'pyesm lock' first")
    if _lock_is_stale(cfg, lock) and ctx.frozen:
        raise StaleLockError("pyesm.lock is out of date with pyproject.toml")
    _build_static_map(cfg, lock, ctx)
    ctx.info(f"wrote import map to {cfg.importmap_path}")
    return 0


def cmd_add(args, ctx: _Ctx) -> int:
    from ._pyproject import add_dependency, split_spec

    if ctx.frozen:
        raise PyesmError("--frozen cannot be used with 'add'")
    cfg = _load_config(ctx)
    for spec in args.packages:
        name, range_ = split_spec(spec)
        add_dependency(cfg.pyproject_path, name, range_)
        ctx.info(f"added {name} = {range_ or '(latest)'}")
    cfg = _load_config(ctx)  # reload with new deps
    lock = _do_resolve_and_write(cfg, ctx)
    _do_sync(cfg, lock, ctx)
    return 0


def cmd_remove(args, ctx: _Ctx) -> int:
    from ._pyproject import remove_dependency

    if ctx.frozen:
        raise PyesmError("--frozen cannot be used with 'remove'")
    cfg = _load_config(ctx)
    for name in args.packages:
        if remove_dependency(cfg.pyproject_path, name):
            ctx.info(f"removed {name}")
        else:
            ctx.info(f"{name} not found in dependencies")
    cfg = _load_config(ctx)
    if cfg.dependencies:
        lock = _do_resolve_and_write(cfg, ctx)
        _do_sync(cfg, lock, ctx)
    else:
        from .lockfile import Lock, dump_lock

        lock = Lock(provider=cfg.provider, inputs_hash=cfg.inputs_hash())
        dump_lock(lock, cfg.lock_path)
        _do_sync(cfg, lock, ctx)
    return 0


def cmd_clean(args, ctx: _Ctx) -> int:
    import shutil

    cfg = _load_config(ctx)
    out = cfg.output_path
    if out.exists():
        for child in out.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        ctx.info(f"cleaned {out}")
    else:
        ctx.info(f"nothing to clean at {out}")
    return 0


def cmd_outdated(args, ctx: _Ctx) -> int:
    import asyncio

    from . import http
    from .providers import get_provider

    if ctx.offline:
        raise PyesmError("cannot check outdated while --offline")
    cfg = _load_config(ctx)
    lock = _load_lock_or_fail(cfg, ctx)
    locked = dict(lock.imports) if lock else {}
    provider = get_provider(cfg.provider)

    async def pin_all():
        async with http.make_client(cfg.concurrency) as client:

            async def get_json(u):
                resp = await client.get(u)
                resp.raise_for_status()
                return resp.json()

            out = {}
            for name, range_ in cfg.dependencies.items():
                out[name] = await provider.resolve_entry(
                    name,
                    str(range_).strip(),
                    production=cfg.production,
                    get_json=get_json,
                )
            return out

    pinned = asyncio.run(pin_all())
    rows: list[tuple[str, str, str]] = []
    for name in cfg.dependencies:
        current = locked.get(name, "?")
        if pinned[name] != current:
            rows.append((name, current, pinned[name]))
    if not rows:
        ctx.info("all dependencies are up to date")
    else:
        for name, cur, new in rows:
            ctx.info(f"{name}\n  locked:  {cur}\n  newest:  {new}")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyesm", description=__doc__)
    parser.add_argument("--version", action="version", version=f"pyesm {__version__}")
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="fail if pyesm.lock is missing or stale (never mutate it)",
    )
    parser.add_argument(
        "--offline", action="store_true", help="never hit the network; fail if the cache is cold"
    )
    parser.add_argument(
        "--provider", default=None, help="override the configured provider for this run"
    )
    parser.add_argument("-q", "--quiet", action="count", default=0)
    parser.add_argument("-v", "--verbose", action="count", default=0)

    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="add dependencies, resolve, vendor")
    p_add.add_argument("packages", nargs="+")
    p_add.set_defaults(handler=cmd_add)

    p_remove = sub.add_parser("remove", help="remove dependencies, re-resolve, prune")
    p_remove.add_argument("packages", nargs="+")
    p_remove.set_defaults(handler=cmd_remove)

    sub.add_parser("lock", help="re-resolve and rewrite pyesm.lock (network)").set_defaults(
        handler=cmd_lock
    )

    for name in ("sync", "install"):
        sub.add_parser(name, help="make local files + import map match the lock").set_defaults(
            handler=cmd_sync
        )

    sub.add_parser("build", help="emit the static importmap.json from the lock").set_defaults(
        handler=cmd_build
    )

    sub.add_parser("clean", help="remove output-dir contents (keep the lock)").set_defaults(
        handler=cmd_clean
    )

    sub.add_parser("outdated", help="report deps that now resolve to a newer pin").set_defaults(
        handler=cmd_outdated
    )

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
