"""Resolve an npm dependency graph to one version per package, with proper
backtracking (via ``resolvelib``, pip's resolver).

We don't trust the versions jsDelivr pins into each ``+esm`` bundle (it pins
each bundle's deps independently, duplicating shared packages). Instead we walk
the declared dependency ranges and let resolvelib find a single version per
package satisfying every constraint, backtracking when a greedy "latest" choice
would create a downstream conflict. A graph with no solution is a hard error.

resolvelib is synchronous and pyesm's HTTP is async, so the resolver runs in an
executor thread whose metadata fetches are dispatched back to the event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from resolvelib import AbstractProvider, BaseReporter, Resolver
from resolvelib.resolvers import ResolutionImpossible, ResolutionTooDeep
from semantic_version import NpmSpec, Version

from .errors import ResolveError

# fetch_packument(pkg) -> {"versions": list[str], "tags": dict[str,str]}
# fetch_manifest(pkg, version) -> package.json dict
FetchPackument = Callable[[str], Awaitable[dict]]
FetchManifest = Callable[[str, str], Awaitable[dict]]


@dataclass(frozen=True)
class _Req:
    name: str
    range_: str


@dataclass(frozen=True)
class _Cand:
    name: str
    version: str


def _spec(range_: str) -> NpmSpec | None:
    try:
        return NpmSpec(range_ or "*")
    except Exception:
        return None


def _ver(v: str) -> Version:
    try:
        return Version(v)
    except ValueError:
        return Version.coerce(v)


def _latest(versions: list[str]) -> str | None:
    """Highest non-prerelease version (falling back to prereleases if that's all)."""
    parsed = [_ver(v) for v in versions]
    pool = [v for v in parsed if not v.prerelease] or parsed
    return str(max(pool)) if pool else None


def _manifest_requirements(manifest: dict) -> list[_Req]:
    """The deps a bundle imports: ``dependencies`` + non-optional ``peerDependencies``."""
    out: list[_Req] = []
    for name, rng in (manifest.get("dependencies") or {}).items():
        out.append(_Req(str(name), str(rng)))
    meta = manifest.get("peerDependenciesMeta") or {}
    for name, rng in (manifest.get("peerDependencies") or {}).items():
        if not (meta.get(name) or {}).get("optional"):
            out.append(_Req(str(name), str(rng)))
    return out


class _NpmProvider(AbstractProvider):
    def __init__(self, packument, manifest) -> None:
        self._packument = packument  # sync (pkg) -> {"versions", "tags"}
        self._manifest = manifest  # sync (pkg, version) -> dict

    def identify(self, requirement_or_candidate) -> str:
        return requirement_or_candidate.name

    def get_preference(self, identifier, resolutions, candidates, information, backtrack_causes):
        # Resolve the most-constrained packages (fewest candidates) first.
        return sum(1 for _ in candidates[identifier])

    def _matches(self, req: _Req, version: str) -> bool:
        spec = _spec(req.range_)
        if spec is not None:
            return spec.match(_ver(version))
        # non-semver range: a dist-tag matches the version it points to
        return self._packument(req.name)["tags"].get(req.range_) == version

    def find_matches(self, identifier, requirements, incompatibilities):
        reqs = list(requirements[identifier])
        bad = {c.version for c in incompatibilities[identifier]}
        versions = sorted(self._packument(identifier)["versions"], key=_ver, reverse=True)
        out = []
        for v in versions:
            if v in bad or _ver(v).prerelease:
                continue
            if all(self._matches(r, v) for r in reqs):
                out.append(_Cand(identifier, v))
        return out

    def is_satisfied_by(self, requirement, candidate) -> bool:
        return self._matches(requirement, candidate.version)

    def get_dependencies(self, candidate):
        return _manifest_requirements(self._manifest(candidate.name, candidate.version))


async def _prewarm(roots, packument, manifest, concurrency: int) -> None:
    """Best-effort concurrent BFS over the dependency closure to fill the
    packument/manifest caches before resolvelib's serial exploration. Per-package
    errors are swallowed — resolvelib lazily fetches (and surfaces) any miss."""
    sem = asyncio.Semaphore(concurrency)
    seen: set[str] = set()

    async def warm(pkg: str) -> list[str]:
        try:
            async with sem:
                pk = await packument(pkg)
            ver = _latest(pk.get("versions") or [])
            if ver is None:
                return []
            async with sem:
                mf = await manifest(pkg, ver)
        except Exception:
            return []
        return [r.name for r in _manifest_requirements(mf)]

    frontier = set(roots)
    while frontier:
        fresh = frontier - seen
        seen |= fresh
        results = await asyncio.gather(*(warm(p) for p in fresh))
        frontier = {name for names in results for name in names}


async def resolve_graph(
    deps: list[tuple[str, str]],
    *,
    fetch_packument: FetchPackument,
    fetch_manifest: FetchManifest,
    concurrency: int = 16,
) -> dict[str, str]:
    """Return ``{package -> version}`` for the whole graph (backtracking).

    Raises :class:`ResolveError` if the constraints have no solution.
    """
    loop = asyncio.get_running_loop()
    pkg_cache: dict[str, dict] = {}
    mf_cache: dict[tuple[str, str], dict] = {}

    async def _packument(pkg: str) -> dict:
        if pkg not in pkg_cache:
            pkg_cache[pkg] = await fetch_packument(pkg)
        return pkg_cache[pkg]

    async def _manifest(pkg: str, ver: str) -> dict:
        if (pkg, ver) not in mf_cache:
            mf_cache[(pkg, ver)] = await fetch_manifest(pkg, ver)
        return mf_cache[(pkg, ver)]

    def packument(pkg: str) -> dict:
        return asyncio.run_coroutine_threadsafe(_packument(pkg), loop).result()

    def manifest(pkg: str, ver: str) -> dict:
        return asyncio.run_coroutine_threadsafe(_manifest(pkg, ver), loop).result()

    provider = _NpmProvider(packument, manifest)

    # resolvelib explores serially through the executor bridge, so fetch the
    # whole dependency closure's metadata concurrently up front; resolvelib then
    # resolves against the warm caches with no serial network round-trips.
    await _prewarm({pkg for pkg, _ in deps}, _packument, _manifest, concurrency)

    def run() -> dict[str, str]:
        result = Resolver(provider, BaseReporter()).resolve([_Req(pkg, rng) for pkg, rng in deps])
        return {name: cand.version for name, cand in result.mapping.items()}

    try:
        return await loop.run_in_executor(None, run)
    except ResolutionImpossible as exc:
        raise ResolveError(_format_conflict(exc)) from exc
    except ResolutionTooDeep as exc:
        raise ResolveError(
            f"could not resolve dependencies: resolution did not settle after "
            f"{exc.round_count} rounds — the constraints are likely contradictory"
        ) from exc


def _format_conflict(exc: ResolutionImpossible) -> str:
    causes = list(exc.causes)
    if not causes:
        return "could not resolve a compatible set of dependency versions"
    pkg = causes[0].requirement.name

    # Backtracking tries many versions of a requirer, each adding a cause for the
    # same dependency. Collapse those to one line per requirer (keeping its
    # highest version's range) so the conflict reads cleanly.
    direct: set[str] = set()
    transitive: dict[str, tuple[Version, str]] = {}
    for c in causes:
        if c.requirement.name != pkg:
            continue
        rng = c.requirement.range_ or "*"
        if c.parent is None:
            direct.add(rng)
        else:
            ver = _ver(c.parent.version)
            if c.parent.name not in transitive or ver > transitive[c.parent.name][0]:
                transitive[c.parent.name] = (ver, rng)

    demands = [(rng, "your pyproject.toml") for rng in sorted(direct)]
    demands += [(rng, f"{name}@{ver}") for name, (ver, rng) in sorted(transitive.items())]

    width = max(len(rng) for rng, _ in demands)
    lines = "\n".join(f"  - {rng.ljust(width)}  required by {who}" for rng, who in demands)
    return (
        f"dependency conflict: no version of {pkg!r} satisfies every requirement:\n"
        f"{lines}\n"
        f"hint: pin compatible ranges for {pkg!r}, or remove one of the conflicting dependencies"
    )
