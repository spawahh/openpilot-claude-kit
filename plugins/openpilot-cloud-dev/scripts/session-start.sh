#!/bin/bash
# SessionStart hook — provision an openpilot (or fork) toolchain so linters and tests
# run in an ephemeral cloud container. Mirrors the repo's own setup flow:
#   submodules -> system deps + uv sync -> LFS -> minimal scons build -> persist env.
#
# Safe by construction:
#   - Runs ONLY when CLAUDE_CODE_REMOTE=true, so a local machine is never touched.
#   - Runs ONLY inside something that looks like an openpilot checkout.
#   - Opt out entirely with OP_CLOUD_DEV_AUTOSETUP=0.
#   - Idempotent and non-interactive; safe to re-run.
#
# Tunables (all optional):
#   OP_CLOUD_DEV_AUTOSETUP=0   skip provisioning entirely
#   OP_SCONS_ARGS="--minimal"  scons arguments (set to "" for a full build)
#   UV_PYTHON=/usr/bin/python3.12
set -euo pipefail

[ "${OP_CLOUD_DEV_AUTOSETUP:-1}" = "0" ] && exit 0

# 1. Only provision in a remote/cloud environment. A developer's own machine already
#    has a working toolchain, and a surprise 10-minute build there is hostile.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# 2. Only provision an actual openpilot-family checkout. Guards against the plugin
#    being enabled globally and firing in an unrelated repo.
if [ ! -f SConstruct ] || [ ! -f pyproject.toml ]; then
  exit 0
fi
if [ ! -d selfdrive ] && [ ! -d openpilot/selfdrive ]; then
  exit 0
fi

echo "openpilot-cloud-dev: provisioning toolchain (set OP_CLOUD_DEV_AUTOSETUP=0 to skip)"

# 3. Submodules. pyproject path-sources (opendbc, msgq, panda, ...) live inside these
#    checkouts, so they must exist before uv resolves the lockfile.
git submodule update --jobs 4 --init --recursive

# 4. System build deps + Python env.
#    uv overrides needed in a managed container:
#    - UV_GITHUB_TOKEN: authenticate GitHub fetches so they don't hit the anonymous
#      rate limit behind the container's proxy.
#    - UV_PYTHON / UV_PYTHON_PREFERENCE: the lockfile pins an exact 3.12.x that often
#      has no python-build-standalone managed build. Use the in-range system CPython
#      instead of trying to download one that does not exist.
export UV_GITHUB_TOKEN="${UV_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"
export UV_PYTHON_PREFERENCE="only-system"
export UV_PYTHON="${UV_PYTHON:-/usr/bin/python3.12}"

if [ -x ./tools/setup_dependencies.sh ]; then
  # Forks that ship a one-shot setup script (installs cross-distro build deps, then
  # runs uv sync itself). A no-op once satisfied.
  ./tools/setup_dependencies.sh
else
  # --all-extras is REQUIRED. Without it the comma-deps build packages (bzip2, acados,
  # capnproto, ...) are missing and scons dies at "ModuleNotFoundError: No module
  # named 'bzip2'" — a confusing failure that looks like a broken checkout.
  uv sync --frozen --all-extras
fi

# 5. Git LFS assets. A missing or rate-limited LFS mirror must not fail the session;
#    model files are not needed for lint or Python tests.
git lfs pull || true

# 6. Build the Cython/capnp targets that Python imports.
#    RAYLIB_BACKEND=headless lets the font-atlas step run without a display.
#    -k keeps building past a headless-only UI-asset failure that would otherwise
#    stop the Cython/capnp targets pytest imports.
[ -f .venv/bin/activate ] && source .venv/bin/activate
export RAYLIB_BACKEND="${RAYLIB_BACKEND:-headless}"
scons -j"$(nproc)" ${OP_SCONS_ARGS-"--minimal"} -k \
  || echo "scons: some non-critical (UI-asset) targets failed; continuing"

# Trust an assertion, not the exit code above: confirm the import-critical extension
# actually built, so a real breakage still fails loudly.
if [ ! -f common/params_pyx.so ] && [ ! -f openpilot/common/params_pyx.so ]; then
  echo "FATAL: params_pyx.so did not build — the Python environment is not usable" >&2
  exit 1
fi

# 7. Persist the venv + headless raylib for the rest of the session, so in-session
#    pytest / ruff / scons runs work without re-sourcing.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export VIRTUAL_ENV=\"$PWD/.venv\""
    echo "export PATH=\"$PWD/.venv/bin:\$PATH\""
    echo "export PYTHONPATH=\"$PWD\""
    echo "export RAYLIB_BACKEND=headless"
  } >> "$CLAUDE_ENV_FILE"
fi

echo "openpilot-cloud-dev: ready"
