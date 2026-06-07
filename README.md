# pyesm

A fast, Python-native, **npm-free** tool that reads ESM dependencies from `pyproject.toml`,
vendors the compiled module graph from a CDN into a local static directory, and emits a standard
**import map** with **Subresource Integrity (SRI)** on by default.

- **No Node, no npm, no bundler.** Pure Python: `pip install pyesm` (or `uv add pyesm`) and go.
- **Framework-agnostic core** writes a static `importmap.json` + vendored files.
- **Optional Django integration** renders the import map through `staticfiles` storage at request
  time, so it survives `ManifestStaticFilesStorage` / WhiteNoise filename hashing.
- Deterministic, lockfile-driven, SRI on by default.

---

## Install

```console
$ pip install pyesm           # or: uv add pyesm
$ pip install "pyesm[django]" # with the optional Django integration
```

- **Python 3.12+.**
- Four pure-Python runtime dependencies — `httpx` (async HTTP), `tomlkit` (comment-preserving
  `pyproject.toml` edits), and `semantic-version` + `resolvelib` (npm-range dependency resolution).
  Three are zero-dependency; only `httpx` pulls a transitive stack (httpcore/anyio/certifi). **No Node
  toolchain and no compiled extensions, ever.**

---

## Quick start

```console
$ pyesm add react@^18.2.0 react-dom@^18.2.0   # resolve, lock, vendor, and write the import map
```

```html
<script type="importmap" src="/static/pyesm/importmap.json"></script>
<script type="module">import "react"</script>
```

That's it: `react` (and its whole module graph) now loads from your own static files, with
integrity enforced and zero requests to the CDN at runtime. (Drop the `@range` to take the latest.)

Already have deps in `pyproject.toml`? Skip `add` and run `pyesm sync`.

---

## How it works

The design follows four load-bearing decisions:

1. **pyesm resolves the dependency graph (one version per package).** It reads each package's
   `package.json` dependency ranges and runs a real **backtracking** resolver (`resolvelib`, pip's
   resolver, with `semantic-version` for npm ranges) to pick, for every package, a single version
   satisfying *all* constraints — backtracking off a "latest" choice when an earlier version of an
   intermediate package is needed to satisfy something downstream. When it crawls the module graph it
   rewrites each bundle's version-pinned imports to the resolved version, so shared transitive deps
   collapse to **one** vendored copy instead of the many the CDN's independently-pinned bundles would
   produce. A graph with no solution (e.g. react 17 vs 18) is a hard error and changes nothing, so you
   always get a consistent 1:1 import mapping or a clean failure.
2. **Relocate via the import map, never by editing bytes.** CDN-built ESM references sibling modules
   by *root-relative* path (e.g. `/npm/react@18.3.1/+esm`). pyesm adds each such specifier to the
   import map as a key pointing at the local vendored copy. The browser resolves the specifier against
   your site's origin and the map transparently redirects it to the local file. Vendored `.js` is
   written byte-for-byte as fetched.
3. **No fragile relative edges.** Because cross-module references are absolute (root-relative) paths,
   the import map is the single indirection layer; there is nothing to rewrite inside the files.
4. **Integrity is computed over the vendored bytes.** Every module gets a `sha384` stored in the lock;
   `sync` recomputes and verifies on every run and **fails loudly** on mismatch (the CDN changed bytes
   under a pinned URL) rather than silently overwriting. By default the import map also carries an SRI
   `integrity` entry for every URL (opt out with `integrity = false`). Because bytes are never edited,
   the hash stays valid even when `ManifestStaticFilesStorage` renames the *file*.

A **global content-addressed cache** (`~/.cache/pyesm/<hash>`) is shared across all projects;
identical modules are downloaded once, ever, and hardlinked into each project's output directory.

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
value is a version range; the key is what you `import`. Deep imports work too — list a package's
subpaths under one entry so they share a single pinned version:

```toml
[tool.pyesm.dependencies]
react       = "^18.2.0"
"react-dom" = "^18.2.0"
lit         = "3"
"htmx.org"  = "2"

# multiple subpaths of one package, one shared version (one vendored copy):
lodash-es = { version = "^4.17.21", subpaths = ["debounce", "throttle", "cloneDeep"] }
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

Native import-map `integrity` shipped in Chromium and Safari, but not everywhere; browsers that don't
understand the `integrity` key silently ignore it and load modules **unverified**. To enforce SRI
everywhere, pyesm can inject the [es-module-shims](https://github.com/guybedford/es-module-shims)
polyfill, controlled by `shims`:

- `auto` (default): vendor and inject the polyfill so integrity is enforced even where the browser
  wouldn't.
- `always`: same as auto.
- `never`: don't vendor or inject.

The polyfill is **vendored** like every other file: downloaded once (at lock/sync) from the
configured provider, stored in the lock with its own `sha384`, and served from `output-dir` with an
`integrity` attribute. Production makes no CDN request for it. In Django mode the `<script>` tag is
emitted for you; in static mode reference the vendored file yourself
(`<base-url>es-module-shims@<version>.js`, integrity in the lock).

---

## Django integration

Add the app to your settings:

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
from the lock and stay valid because the bytes are never edited. The rendered map is cached per
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
  pyesm resolves the whole dependency graph itself (decision 1) — enumerating versions from jsDelivr's
  data API and reading each `package.json` — then vendors exactly those resolved versions, deduped to
  one copy per package.
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
