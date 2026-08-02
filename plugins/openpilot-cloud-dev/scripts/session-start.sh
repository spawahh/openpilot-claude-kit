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

# Nothing in a SessionStart hook may ever wait on a human. A prompt here does not fail,
# it hangs the session silently and forever. Refuse git's credential and host-key
# prompts up front; each sub-step below also gets </dev/null.
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -oBatchMode=yes -oStrictHostKeyChecking=accept-new}"

# 3. Submodules. pyproject path-sources (opendbc, msgq, panda, ...) live inside these
#    checkouts, so they must exist before uv resolves the lockfile.
git submodule update --jobs 4 --init --recursive < /dev/null

# 4. System build deps + Python env.
#
# UV_GITHUB_TOKEN authenticates GitHub fetches so they don't hit the anonymous rate
# limit behind a container proxy.
#
# Deliberately NOT forcing a system interpreter. An earlier version set
# UV_PYTHON_PREFERENCE=only-system with UV_PYTHON=/usr/bin/python3.12, which broke the
# build outright: a distro python without its -dev package ships no Python.h, so every
# Cython extension failed with
#     msgq_repo/msgq/ipc_pyx.cpp:33:10: fatal error: Python.h: No such file or directory
# uv's managed interpreters bundle their headers, so letting uv choose needs no root.
#
# Set OP_UV_SYSTEM_PYTHON=1 to force the system interpreter anyway; you then need the
# matching -dev package installed.
export UV_GITHUB_TOKEN="${UV_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"
if [ "${OP_UV_SYSTEM_PYTHON:-0}" = "1" ]; then
  export UV_PYTHON_PREFERENCE="only-system"
  export UV_PYTHON="${UV_PYTHON:-/usr/bin/python3.12}"
fi

# Resolve the interpreter BEFORE anything runs uv, and never depend on a particular
# uv version's download manifest.
#
# uv embeds its list of available Python builds, so an older uv simply does not know
# newer patch releases exist. openpilot's .python-version pins an exact patch
# (e.g. 3.12.13) that uv 0.8.17 — the version in Claude Code cloud containers as of
# 2026.08 — cannot provide; it tops out at 3.12.11. uv then fails with
#     error: No interpreter found for Python 3.12.13 in managed installations
# and because this script runs under `set -e`, the whole hook aborts before submodules,
# scons, or the env-file step. The session comes up completely unprovisioned, and the
# real cause is buried inside tools/setup_dependencies.sh where it is invisible.
#
# pyproject.toml only requires >= 3.12.3, < 3.13 — the exact patch comes solely from
# .python-version. A full fork test suite has been run green on 3.12.11, so relaxing to
# the minor series is safe rather than merely expedient. UV_PYTHON overrides
# .python-version (verified), and it must be exported here so it also reaches the
# uv sync inside tools/setup_dependencies.sh below.
if [ "${OP_UV_SYSTEM_PYTHON:-0}" != "1" ] && [ -f .python-version ] && command -v uv >/dev/null 2>&1; then
  op_pin="$(tr -d '[:space:]' < .python-version)"
  if [ -n "$op_pin" ] && ! uv python find "$op_pin" >/dev/null 2>&1; then
    if uv python install "$op_pin" </dev/null >/dev/null 2>&1; then
      echo "openpilot-cloud-dev: installed pinned Python $op_pin"
    else
      export UV_PYTHON="${UV_PYTHON:-${op_pin%.*}}"
      echo "openpilot-cloud-dev: this uv ($(uv --version 2>/dev/null)) cannot provide the" \
           "pinned Python $op_pin; falling back to $UV_PYTHON (pyproject allows it)"
      if ! uv python find "$UV_PYTHON" >/dev/null 2>&1 \
         && ! uv python install "$UV_PYTHON" </dev/null >/dev/null 2>&1; then
        echo "FATAL: no interpreter available for $UV_PYTHON. Upgrade uv, or install a" \
             "matching Python, or set UV_PYTHON to one that exists." >&2
        exit 1
      fi
    fi
  fi
fi

# tools/setup_dependencies.sh (upstream openpilot and most forks ship it) installs
# system build deps AND writes udev rules. The udev block runs unconditionally — even
# when the build deps are already present — and it uses sudo.
#
# Without a usable sudo that hangs FOREVER on the password prompt, with no output:
# observed blocking for 60 minutes on `sudo tee /etc/udev/rules.d/11-openpilot.rules`,
# no error, no timeout, the session simply never becomes usable. That is the worst
# failure shape a SessionStart hook can have, so only take this path when we can
# actually run it unattended.
#
# uv sync alone needs no privileges, and udev rules only matter for plugging in a
# panda over USB — irrelevant in a container.
if [ -x ./tools/setup_dependencies.sh ] && { [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null; }; then
  echo "openpilot-cloud-dev: running tools/setup_dependencies.sh"
  # </dev/null so nothing downstream can block on stdin; timeout as a hard backstop
  # so an unexpected prompt becomes a failure we can see rather than a hang.
  timeout "${OP_SETUP_TIMEOUT:-900}" ./tools/setup_dependencies.sh < /dev/null
else
  if [ -x ./tools/setup_dependencies.sh ]; then
    echo "openpilot-cloud-dev: skipping tools/setup_dependencies.sh (needs root or" \
         "passwordless sudo for its udev step); using uv directly instead"
  fi
  # --all-extras is REQUIRED. Without it the comma-deps build packages (bzip2, acados,
  # capnproto, ...) are missing and scons dies at "ModuleNotFoundError: No module
  # named 'bzip2'" — a confusing failure that looks like a broken checkout.
  uv sync --frozen --all-extras < /dev/null
fi

# 4b. GLES/EGL runtime libraries for raylib.
#
# RAYLIB_BACKEND=headless is NOT sufficient: the headless backend still links GLES at
# import time, so without these `import pyray` dies with
#     ImportError: libGLESv2.so.2: cannot open shared object file
# and a raylib-based fork cannot even *collect* its UI tests. openpilot's own
# tools/setup_dependencies.sh does not install them (no gles/egl/mesa entry at all).
#
# Best effort only — a missing UI toolchain must never fail the session, and plenty of
# work needs no raylib. `apt-get update` first: installing straight from a stale index
# 404s on libegl-mesa0.
if command -v apt-get >/dev/null 2>&1 \
   && { [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null; }; then
  op_sudo=""; [ "$(id -u)" -eq 0 ] || op_sudo="sudo -n"
  if ! ldconfig -p 2>/dev/null | grep -q "libGLESv2\.so\.2"; then
    echo "openpilot-cloud-dev: installing GLES/EGL runtime for raylib"
    $op_sudo apt-get update -qq </dev/null >/dev/null 2>&1 || true
    $op_sudo apt-get install -y -qq libgles2 libegl1 libegl-mesa0 </dev/null >/dev/null 2>&1 \
      || echo "openpilot-cloud-dev: GLES/EGL install failed; raylib UI tests will not import"
  fi
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

# Trust an assertion, not the exit code above: -k means scons reports success while
# leaving real targets unbuilt.
#
# Assert on BEHAVIOUR, not a filename. An earlier version checked for params_pyx.so,
# which does not exist in current upstream openpilot at all — params.py is pure Python
# there and the SConscript builds libparams_c.so instead. That check turned every
# successful upstream build into "FATAL: params_pyx.so did not build". Artifact names
# vary by fork and by version; instantiating Params does not, and it genuinely requires
# the compiled library to be present and loadable.
if ! PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" python -c \
     "from openpilot.common.params import Params; Params()" >/dev/null 2>&1; then
  echo "FATAL: openpilot.common.params is not usable — the build did not produce a" \
       "working compiled extension. Re-run scons without -k to see the real error." >&2
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
