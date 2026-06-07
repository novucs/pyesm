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
from resolvelib.resolvers import ResolutionError
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
        manifest = self._manifest(candidate.name, candidate.version)
        out: list[_Req] = []
        for name, rng in (manifest.get("dependencies") or {}).items():
            out.append(_Req(str(name), str(rng)))
        meta = manifest.get("peerDependenciesMeta") or {}
        for name, rng in (manifest.get("peerDependencies") or {}).items():
            if not (meta.get(name) or {}).get("optional"):
                out.append(_Req(str(name), str(rng)))
        return out


async def resolve_graph(
    deps: list[tuple[str, str]],
    *,
    fetch_packument: FetchPackument,
    fetch_manifest: FetchManifest,
    concurrency: int = 16,  # noqa: ARG001 - resolvelib explores sequentially
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

    def run() -> dict[str, str]:
        result = Resolver(provider, BaseReporter()).resolve([_Req(pkg, rng) for pkg, rng in deps])
        return {name: cand.version for name, cand in result.mapping.items()}

    try:
        return await loop.run_in_executor(None, run)
    except ResolutionError as exc:
        raise ResolveError(_format_conflict(exc)) from exc


def _format_conflict(exc: ResolutionError) -> str:
    causes = getattr(exc, "causes", None)
    if not causes:
        return "could not resolve a compatible set of dependency versions"
    pkg = causes[0].requirement.name
    wants = sorted({f"{c.requirement.range_ or '*'}" for c in causes if c.requirement.name == pkg})
    return f"cannot resolve a single version of {pkg!r}: incompatible constraints {wants}"
