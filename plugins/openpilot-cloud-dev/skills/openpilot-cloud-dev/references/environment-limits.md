# Cloud container limits and their fixes

Constraints of an ephemeral Linux container running an openpilot checkout, and the
failures each one produces. Most of these look like a broken repository and are not.

## What a container cannot do

| Missing | Consequence |
|---|---|
| CAN bus | No live signal capture, no DBC validation against a real vehicle, no dongle sniffing |
| comma device | No on-device build, no UI verification on real hardware, no panda in the loop |
| Display | Any target needing a framebuffer fails; UI rendering cannot be inspected |
| Camera / GPS | No model inference on live frames, no location-dependent behavior |
| Persistent disk | The environment is rebuilt every session; provisioning is not a one-time cost |

Work that depends on any of the above can be **drafted** here but not **validated**.
State that distinction explicitly rather than letting passing tests imply road-readiness.

## Build and environment failures

### `ModuleNotFoundError: No module named 'bzip2'` during scons

`uv sync` ran without `--all-extras`. The comma-deps build packages (bzip2, acados,
capnproto, ...) live in extras. Re-run:

```bash
uv sync --frozen --all-extras
```

### `fatal error: Python.h: No such file or directory`

Cython extensions (`ipc_pyx`, `visionipc_pyx`, …) need Python development headers. A
distro interpreter does not ship them without its `-dev` package, and installing that
needs root.

**Do not force a system interpreter to avoid a managed download.** uv's managed
interpreters bundle their headers, so letting uv choose is both correct and rootless:

```bash
uv sync --frozen --all-extras        # no UV_PYTHON_PREFERENCE override
```

This was a real, verified failure: forcing `UV_PYTHON_PREFERENCE=only-system` with
`UV_PYTHON=/usr/bin/python3.12` on Ubuntu 24.04 without `python3.12-dev` broke every
Cython target. The justification for that override — "the pinned 3.12.x has no
python-build-standalone build" — turned out to be false; `cpython-3.12.13` is available
as a managed build.

If you genuinely are on a host where no managed build exists, force the system
interpreter *and* install the matching `-dev` package. Note that openpilot's own
`tools/setup_dependencies.sh` does **not** install it.

### `No interpreter found for Python 3.12.x in managed installations`

uv **embeds** its list of downloadable Python builds, so an older uv does not know newer
patch releases exist. Claude Code cloud containers shipped uv 0.8.17 as of 2026.08, which
tops out at `cpython-3.12.11` — while openpilot's `.python-version` pins `3.12.13`.

This is nastier than it looks. Under `set -e` it aborts the whole provisioning step
*before* submodules or scons, and if it happens inside `tools/setup_dependencies.sh` the
cause is invisible from the outside — the session just comes up unprovisioned.

`pyproject.toml` only requires `>= 3.12.3, < 3.13`; the exact patch comes solely from
`.python-version`. A full fork suite has run green on 3.12.11, so relaxing to the minor
series is safe:

```bash
uv python install "$(cat .python-version)"   || export UV_PYTHON=3.12          # UV_PYTHON overrides .python-version (verified)
```

Check what your uv can actually provide with
`uv python list --all-versions | grep cpython-3.12`.

### `ImportError: libGLESv2.so.2: cannot open shared object file`

`RAYLIB_BACKEND=headless` is **not** sufficient — the headless backend still links GLES at
import time. Without the runtime libraries, `import pyray` fails and a raylib-based fork
cannot even *collect* its UI tests. openpilot's `tools/setup_dependencies.sh` does not
install them; it has no gles/egl/mesa entry at all.

```bash
apt-get update && apt-get install -y libgles2 libegl1 libegl-mesa0
```

Run `apt-get update` first: installing straight from a stale index 404s on `libegl-mesa0`.

### `git submodule update` exits 0 having populated nothing

Submodules must be initialized **before** `uv sync`, because `pyproject.toml` declares
path-sources inside them. If the checkout renamed or removed the remote literally named
`origin`, relative submodule URLs in `.gitmodules` resolve against the wrong base and
the bogus URLs get cached into `.git/config`. Recovery:

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

### `raylib failed to load font data`

No display. Set the headless backend and keep going — the artifact is a UI asset, not
something Python imports:

```bash
export RAYLIB_BACKEND=headless
scons -j"$(nproc)" --minimal -k
```

### scons exits 0 but imports still fail

`-k` continues past failures and can mask a real one. Assert instead of trusting the
exit code — but **assert on behaviour, not on a filename**:

```bash
PYTHONPATH="$PWD" python -c "from openpilot.common.params import Params; Params()"
```

Instantiating `Params` requires the compiled library to exist and load, so this catches
a masked failure. Do not check for `params_pyx.so`: it does not exist in current
upstream openpilot, where `params.py` is pure Python and the SConscript builds
`libparams_c.so`. Artifact names vary by fork and by version; a filename check silently
inverts into a false FATAL on a perfectly good build.

For a deeper check once the whole build is done, `from openpilot.cereal import
messaging` additionally requires the compiled `msgq` extensions.

### GitHub fetches rate-limited

Container egress usually goes through a proxy, and anonymous GitHub API requests hit
the rate limit quickly. Give uv a token:

```bash
export UV_GITHUB_TOKEN="${GITHUB_TOKEN:-$GH_TOKEN}"
```

### `git lfs pull` fails or hangs

The LFS mirror may be unreachable or rate-limited. Model files are not needed for lint
or Python tests, so make it non-fatal:

```bash
git lfs pull || true
```

## Test-running gotchas

### `pytest -k "not LF"` silently matches nothing

`-k` matches **case-insensitively against the entire test id, including the file path**.
The string `lf` appears inside `se`**`lf`**`drive`, so that filter excludes everything.
Use a full, distinctive platform substring:

```bash
pytest ... -k "not SONATA_LF"
```

### Phantom flaky failures after editing tests

Hypothesis caches failing examples in `.hypothesis/` and replays them first. Entries
recorded against *older test code* resurface as one-off failures or `Flaky` errors.
Delete the directory when results stop making sense:

```bash
rm -rf .hypothesis/
```

### First test run per platform is very slow

Route CAN logs download from openpilotci on first use, then cache. This is expected;
subsequent runs are fast. In a fresh container the cache is empty again.

### Edits to opendbc safety C code appear to do nothing

`libsafety` self-compiles the opendbc safety C sources with `cc` at first import — no
scons step. Changes take effect in the **next Python process**, not the current one.
Restart the interpreter rather than rebuilding.

## CI expectations

- A personal fork typically has **no CI**. The upstream project's suite only runs once
  a pull request is opened against upstream.
- Upstream smoke runs use a heavily reduced fuzz configuration (low `MAX_EXAMPLES`,
  slow tests skipped). A green upstream check is not equivalent to a full local sweep.
- Do not treat a container run as a substitute for either. Say which one you actually
  ran.
