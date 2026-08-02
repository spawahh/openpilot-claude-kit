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

### uv tries to download a Python that does not exist

The lockfile pins an exact patch version (for example 3.12.13) that often has no
python-build-standalone managed build. Use the in-range system interpreter:

```bash
export UV_PYTHON_PREFERENCE=only-system
export UV_PYTHON=/usr/bin/python3.12
```

Any 3.12.x satisfying `requires-python` works — it does not have to match the pin.

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

`-k` continues past failures and can mask a real one. Assert the artifact instead of
trusting the exit code:

```bash
ls common/params_pyx.so openpilot/common/params_pyx.so 2>/dev/null
```

The path differs by fork layout — some forks nest the package under `openpilot/`.

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
