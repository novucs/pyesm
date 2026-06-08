# pyesm

**Use modern JavaScript libraries in a Python web app, without Node, npm, a bundler, or a CDN dependency at runtime.**

You want a JS library (React, lit, htmx, Alpine, CodeMirror) in a site with a Python backend. The
usual options are to load it from a CDN at runtime (now your site depends on that CDN being up, fast,
and untampered, and it breaks offline) or to stand up a whole Node + npm + bundler toolchain just to
ship a few `.js` files.

pyesm is a third way. Declare the library in `pyproject.toml`, run one command, and pyesm downloads the
compiled ES modules (the *entire* dependency graph) into your static directory and writes a standard
[import map](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/script/type/importmap). You
serve your own files: nothing hits a CDN at runtime, it works offline, and the whole thing is pinned by
a lockfile and checked with Subresource Integrity.

- **Pure Python, no Node.** `pip install pyesm` with no Node toolchain, no `node_modules`, no bundler, no compiled extensions.
- **Vendors the whole graph.** A real backtracking npm-semver resolver picks one version per package and downloads every module locally, deduped to a single copy.
- **Standard import maps.** Emits a plain `importmap.json` the browser understands natively, so `import "react"` just works. Framework-agnostic.
- **Locked & reproducible.** A committed `pyesm.lock` makes `sync` deterministic and offline; every file carries a `sha384`, re-verified on every sync.
- **Optional Django integration** that survives `ManifestStaticFilesStorage` / WhiteNoise filename hashing.

Requires Python 3.12+. Four pure-Python dependencies (`httpx`, `tomlkit`, `semantic-version`,
`resolvelib`); only `httpx` pulls a transitive stack.

---

## Quick start

```console
$ pip install pyesm
$ pyesm add react@^18.2.0 react-dom@^18.2.0   # resolve → lock → download → write the import map
```

Reference the generated import map and import as normal:

```html
<script type="importmap" src="/static/pyesm/importmap.json"></script>
<script type="module">import "react"</script>
```

That's it: `react` and its whole module graph now load from your own static files, with zero requests
to a CDN at runtime. Omit the `@range` to take the latest; already have deps in `pyproject.toml`? Skip
`add` and run `pyesm sync`.

---

## How it works

`pyesm add react` runs four steps, all reproducible from the lockfile afterward:

1. **Resolve.** Reads each package's `package.json` ranges and runs a real **backtracking** resolver
   (`resolvelib` + `semantic-version` for npm semver) to choose one version per package satisfying
   every constraint, so shared transitive dependencies collapse to a single copy. An unsatisfiable
   graph (e.g. react 17 vs 18) is a clean error that changes nothing.
2. **Vendor.** Downloads the compiled ESM for the entire graph from a CDN (jsDelivr's `+esm` by
   default) into `output-dir`. Files are content-addressed in a shared global cache
   (`~/.cache/pyesm/<hash>`) and hardlinked into place, so identical modules download once, ever.
3. **Remap.** CDN modules reference their siblings by absolute path (`/npm/react@18.3.1/+esm`); pyesm
   points each of those at the local copy through the import map. It never rewrites the imports inside
   the files (the import map is the only indirection), so a module's bytes don't depend on what else
   you vendor.
4. **Verify.** Each module's `sha384` is written to the lock and the import map, and `sync` re-checks
   it on every run, **failing loudly** if a CDN ever serves different bytes under a pinned URL.

---

## Configuration

All configuration lives under `[tool.pyesm]` in `pyproject.toml`.

| Key           | Default                         | Meaning                                                                  |
|---------------|---------------------------------|--------------------------------------------------------------------------|
| `provider`    | `"jsdelivr"`                    | CDN to vendor from: `jsdelivr` or `esmsh`.                               |
| `output-dir`  | `"static/pyesm"`                | Where vendored files are written (relative to project root).             |
| `base-url`    | `"/static/pyesm/"`              | Public URL prefix used in the **static** import map. Must end with `/`.  |
| `importmap`   | `"static/pyesm/importmap.json"` | Output path for the static import map.                                   |
| `production`  | `true`                          | Request production (vs dev) builds where the CDN distinguishes (esm.sh). |
| `shims`       | `"auto"`                        | es-module-shims injection: `auto`, `always`, or `never`.                 |
| `concurrency` | `16`                            | Max parallel downloads.                                                  |
| `integrity`   | `true`                          | Emit the SRI `integrity` block in the import map.                        |

Dependencies go in a separate table. Keys containing dots, slashes, or scopes must be quoted. Each
value is a version range; the key is what you `import`. Deep imports work too: list a package's
subpaths under one entry so they share a single pinned version:

```toml
[tool.pyesm.dependencies]
react       = "^18.2.0"
"react-dom" = "^18.2.0"
lit         = "3"
"htmx.org"  = "2"

# multiple subpaths of one package, one shared version (one vendored copy):
lodash-es = { version = "^4.17.21", subpaths = ["cloneDeep", "debounce", "throttle"] }
```

`pyesm add lodash-es/debounce` writes/merges that grouped table for you; plain packages stay in the
`name = "range"` shorthand. (For long subpath lists, the equivalent nested form
`[tool.pyesm.dependencies.lodash-es]` reads the same.) A grouped table imports only its `subpaths`;
add `root = true` to also import the bare package (`pyesm add sigma` followed by `pyesm add
sigma/rendering` sets this for you, so both `sigma` and `sigma/rendering` resolve).

---

## CLI reference

The single entry point is `pyesm`. Running it bare prints help.

| Command                        | Network?     | Behavior                                                                                                                                              |
|--------------------------------|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `pyesm add <pkg>[@range] …`    | yes          | Add to `[tool.pyesm.dependencies]`, re-resolve, update lock, vendor.                                                                                  |
| `pyesm remove <pkg> …`         | yes          | Remove from deps, re-resolve, prune now-unused vendored files.                                                                                        |
| `pyesm lock`                   | yes          | Re-resolve from `pyproject.toml`, rewrite `pyesm.lock`.                                                                                               |
| `pyesm sync` (alias `install`) | only if cold | Make local files + import map match the lock; download missing modules and verify every integrity. **Offline & near-instant when the cache is warm.** |
| `pyesm build`                  | no           | (Re)emit the static `importmap.json` from the lock.                                                                                                   |
| `pyesm clean`                  | no           | Remove the contents of `output-dir` (keeps the lock).                                                                                                 |
| `pyesm outdated`               | yes          | Report deps whose range now resolves to a newer pinned version.                                                                                       |

`add` accepts version ranges inline, scope-aware:

```console
$ pyesm add lit@3 "@scope/pkg@1.2.3"
$ pyesm remove react-dom
```

### Global flags

| Flag             | Effect                                                                        |
|------------------|-------------------------------------------------------------------------------|
| `--frozen`       | Fail if `pyesm.lock` is missing or stale. Never mutates the lock (a CI gate). |
| `--offline`      | Never hit the network; fail if a needed module isn't cached.                  |
| `--provider <p>` | Override the configured provider for this run.                                |
| `-q` / `-v`      | Quieter / more verbose output.                                                |
| `--version`      | Print the pyesm version.                                                      |

---

## The lockfile (`pyesm.lock`)

`lock` writes a deterministic JSON lockfile next to `pyproject.toml`. **Commit it**: it drives
reproducible, offline `sync` in CI and deploys. It captures:

- `provider` and `inputs_hash`: a hash of the resolution inputs (provider, declared dependency table,
  production flag, shims); lets `sync` skip re-resolution when `pyproject.toml` is unchanged.
- `imports`: each bare specifier → its pinned entry-module URL.
- `modules`: every node in the crawled graph: `url` (canonical CDN URL), `path` (local file),
  `integrity` (`sha384-…`), `deps`, and `keys` (the root-relative specifiers that map to it).

Two `lock` runs on an unchanged `pyproject.toml` produce byte-identical files (modulo genuine CDN
drift, which surfaces as an explicit failure, never a silent change).

---

## Static mode (default)

`pyesm build` (and `sync`) writes `importmap.json` using `base-url` to form public URLs. Embed it
however you like:

```html
<!-- external -->
<script type="importmap" src="/static/pyesm/importmap.json"></script>

<!-- or inline the JSON contents directly into a <script type="importmap"> -->

<script type="module">import "react"</script>
```

### es-module-shims and cross-browser SRI

There are two distinct integrity layers, and only the first is unconditional:

- **At vendor time**, every module's `sha384` is stored in the lock and re-verified by `sync` on every
  run (it **fails loudly** on mismatch). This always holds; it's what guarantees the bytes you ship
  are the bytes you locked.
- **In the browser**, the import map's `integrity` field is enforced only where the runtime understands
  it. Recent Chromium enforces it natively; browsers that have import maps but not native import-map
  integrity (currently Firefox and Safari) **ignore** the field and load those modules unverified.

pyesm can vendor and inject the [es-module-shims](https://github.com/guybedford/es-module-shims)
polyfill to extend runtime enforcement, controlled by `shims`:

- `auto` (default) / `always`: vendor and inject the polyfill. It enforces integrity only when it
  actually takes over module loading: on browsers with **no** native import-map support (where it
  fully engages), or in its opt-in "shim mode". On a browser that already has native import maps but
  not native integrity, the polyfill stays out of the native loader's way, so there the `integrity`
  field stays **advisory**. In other words the polyfill closes the gap for older browsers, not for
  current Firefox/Safari.
- `never`: don't vendor or inject.

The polyfill is **vendored** like every other file: downloaded once (at lock/sync) from the
configured provider (the minified ~43KB build on jsDelivr), stored in the lock with its own `sha384`,
and served from `output-dir` with an `integrity` attribute. Production makes no CDN request for it. In Django mode the `<script>` tag is
emitted for you; in static mode reference the vendored file yourself
(`<base-url>es-module-shims@<version>.js`, integrity in the lock).

---

## Django integration

Install the extra and add the app to your settings:

```console
$ pip install "pyesm[django]"
```

```python
INSTALLED_APPS = [
    # …
    "pyesm.contrib.django",
]
```

Render the map at request time with the template tag:

```django
{% load pyesm %}
<head>
  {% pyesm_importmap %}   {# emits <script type="importmap">…</script>, plus the shims tag per `shims` #}
</head>

<script type="module">import "react"</script>
```

Why request-time instead of a static file: the tag routes **only the values** through
`staticfiles_storage.url("pyesm/<path>")`, so the rendered map contains the storage-hashed URL
(e.g. `/static/pyesm/react@18.3.1/+esm.4af3.js`). This makes it survive
`ManifestStaticFilesStorage` and WhiteNoise filename hashing. The `integrity` values come straight
from the lock and stay valid because the vendored content is never rewritten. The rendered map is cached per
process and invalidated when the staticfiles manifest changes.

A typical deploy is `pyesm sync` → `collectstatic`.

Relevant settings (optional):

| Setting               | Default       | Meaning                                               |
|-----------------------|---------------|-------------------------------------------------------|
| `PYESM_PROJECT_ROOT`  | auto-detected | Directory containing `pyproject.toml` / `pyesm.lock`. |
| `PYESM_STATIC_PREFIX` | `"pyesm"`     | Static path prefix the vendored files live under.     |

---

## Caching & performance

- **Global content-addressed cache** at `~/.cache/pyesm/<sha384>`, shared across projects. Override
  the location with the `PYESM_CACHE_DIR` environment variable (or `XDG_CACHE_HOME`).
- Modules are **hardlinked** from the cache into `output-dir` (a byte copy only when crossing
  filesystems). Bytes are never rewritten.
- The crawl and the downloads run concurrently on `asyncio` via a single pooled `httpx.AsyncClient`,
  bounded by `concurrency`.
- A warm-cache `sync` of a small graph completes in well under a second and makes **no network
  calls**.

---

## Continuous integration

`sync` is the command to run in CI and on deploy. It's deterministic and needs no network when the
cache is warm.

```console
$ pyesm sync --frozen     # fail if pyesm.lock is missing or out of date with pyproject.toml
$ pyesm sync --offline    # fail rather than touch the network (requires a warm cache)
```

`--frozen` never mutates the lock, so it's a safe gate against forgetting to commit a lock update.

---

## Providers

No provider requires Node. (JSPM is intentionally excluded: its generator is Node-only.)

- **`jsdelivr`** (default): vendors transformed ESM from `cdn.jsdelivr.net/npm/<name>@<ver>/+esm`.
  pyesm resolves the whole dependency graph itself (the *Resolve* step above), enumerating versions
  from jsDelivr's data API and reading each `package.json`, then vendors exactly those resolved
  versions, deduped to one copy per package.
- **`esmsh`**: vendors from `esm.sh`, which pins a range by redirect. Its entry URLs aren't
  version-pinned in the path, so pyesm follows the redirect and vendors the frozen re-export shim plus
  its pinned target. esm.sh dedupes its graph server-side, so pyesm doesn't run its own resolver for
  this provider; everything is locked by integrity.

Switch per-run with `--provider`, or set `provider` in config.

---

## Limitations

- **Runtime-computed dynamic imports** (`import(someVariable)`) can't be discovered statically, so
  their targets aren't vendored; they'd load from the CDN at runtime. Static `import("…literal…")`
  *is* discovered.
- **`outdated` is a no-op for esm.sh** deps, because esm.sh entry URLs don't pin a version in the URL
  to compare against. jsDelivr pins exactly and reports accurately.
- **Runtime SRI enforcement is browser-dependent.** The `integrity` field is always emitted (and
  always verified at vendor time), but the browser only *enforces* it natively on recent Chromium; on
  Firefox/Safari (import maps, no native integrity) the field is advisory, and the es-module-shims
  polyfill only covers browsers without native import maps. See *es-module-shims and cross-browser SRI*.
- CDN output (`+esm`, esm.sh transforms) is **not guaranteed byte-stable** across CDN updates. That's
  fine at serve time because you host your own frozen copy, but a `sync` that finds a hash mismatch
  against a still-pinned URL **fails loudly** rather than silently overwriting.

---

## Development

```console
$ uv sync                      # create the venv and install deps
$ uv run pre-commit install    # enable the git hooks (ruff + pyright)
$ uv run pytest                # run the test suite
$ uv build                     # build the wheel/sdist
```

Pre-commit runs `ruff format`, `ruff check`, the standard hygiene hooks, and `pyright`. Run them on
demand with `uv run pre-commit run --all-files`.

### Releasing

Pushing a `v*` tag (matching the `pyproject.toml` version) builds the sdist + wheel and publishes to
PyPI via Trusted Publishing (OIDC, no stored token):

```console
$ git tag v0.1.0 && git push --tags
```
