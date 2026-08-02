#!/usr/bin/env bash
# Run every check that does not need a credential or a comma device.
#
#   ./verify-kit.sh
#
# This is what CI runs. It is also the fastest way to know whether a change broke
# something before you publish it.
#
# NOT covered here (both need a real account):
#   plugins/openpilot-device/mcp/test_live.py   - needs COMMA_JWT
#   the athena success path                     - needs the device awake and online
set -uo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
fi
[ -n "$PY" ] || { echo "FATAL: no python interpreter found"; exit 1; }

pass=0; fail=0; skip=0
ok()   { echo "  PASS  $1"; pass=$((pass + 1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail + 1)); }
note() { echo "  SKIP  $1"; skip=$((skip + 1)); }
section() { echo; echo "== $1"; }   # not `head` — that shadows the coreutil

# ---------------------------------------------------------------- manifests
section "Manifest structure"
"$PY" - <<'EOF' && ok "marketplace.json and every plugin.json are structurally valid" || bad "manifest structure"
import json, sys
from pathlib import Path

errs = []
mp = Path(".claude-plugin/marketplace.json")
try:
    market = json.loads(mp.read_text(encoding="utf-8"))
except Exception as e:
    print(f"    {mp}: {e}"); sys.exit(1)

for field in ("name", "owner", "plugins"):
    if field not in market:
        errs.append(f"marketplace.json missing required field {field!r}")

for entry in market.get("plugins", []):
    name, source = entry.get("name"), entry.get("source")
    if not name or not source:
        errs.append(f"plugin entry missing name/source: {entry}"); continue
    # Relative sources must start with ./ — a bare path fails to load.
    if isinstance(source, str):
        if not source.startswith("./"):
            errs.append(f"{name}: source {source!r} must start with './'")
        d = Path(source)
        if not d.is_dir():
            errs.append(f"{name}: source directory {source} does not exist"); continue
        pj = d / ".claude-plugin" / "plugin.json"
        if not pj.is_file():
            errs.append(f"{name}: missing {pj}"); continue
        try:
            manifest = json.loads(pj.read_text(encoding="utf-8"))
        except Exception as e:
            errs.append(f"{name}: {pj} is not valid JSON: {e}"); continue
        if manifest.get("name") != name:
            errs.append(f"{name}: plugin.json name is {manifest.get('name')!r}, "
                        f"marketplace says {name!r}")

for extra in Path(".").glob("plugins/*/.claude-plugin/plugin.json"):
    owner = extra.parents[1].name
    if owner not in {e.get("name") for e in market.get("plugins", [])}:
        errs.append(f"plugin {owner} exists on disk but is not listed in marketplace.json")

for e in errs:
    print(f"    {e}")
sys.exit(1 if errs else 0)
EOF

if command -v claude >/dev/null 2>&1; then
  if claude plugin validate . >/dev/null 2>&1; then
    ok "claude plugin validate (marketplace)"
  else
    bad "claude plugin validate (marketplace)"; claude plugin validate . 2>&1 | sed 's/^/        /'
  fi
  for d in plugins/*/; do
    n=$(basename "$d")
    if claude plugin validate "$d" --strict >/dev/null 2>&1; then
      ok "claude plugin validate --strict ($n)"
    else
      bad "claude plugin validate --strict ($n)"; claude plugin validate "$d" --strict 2>&1 | sed 's/^/        /'
    fi
  done
else
  note "claude CLI not on PATH — manifest checks limited to the structural pass above"
fi

# ---------------------------------------------------------------- python
section "Python"
while IFS= read -r f; do
  if "$PY" -m py_compile "$f" 2>/dev/null; then ok "compiles: $f"; else bad "compiles: $f"; fi
done < <(find plugins -name '*.py' | sort)

if "$PY" plugins/openpilot-device/mcp/test_safety.py >/tmp/kit_safety.$$ 2>&1; then
  n=$(grep -c '^PASS' /tmp/kit_safety.$$ || true)
  ok "read-only safety suite ($n checks)"
else
  bad "read-only safety suite"; sed 's/^/        /' /tmp/kit_safety.$$
fi
rm -f /tmp/kit_safety.$$

# The MCP server actually starting is a separate question from the code being
# correct: it also exercises uv, the PEP 723 dependency block, and tool registration.
section "MCP server startup"
if command -v uv >/dev/null 2>&1; then
  if "$PY" plugins/openpilot-device/mcp/test_startup.py >/tmp/kit_startup.$$ 2>&1; then
    grep '^PASS' /tmp/kit_startup.$$ | sed 's/^PASS  /  PASS  /'
    pass=$((pass + $(grep -c '^PASS' /tmp/kit_startup.$$)))
  else
    bad "MCP server startup"; sed 's/^/        /' /tmp/kit_startup.$$
  fi
  rm -f /tmp/kit_startup.$$
else
  note "uv not on PATH — cannot launch the MCP server"
fi

# ---------------------------------------------------------------- shell
section "Shell"
while IFS= read -r f; do
  if bash -n "$f" 2>/dev/null; then ok "syntax: $f"; else bad "syntax: $f"; fi
done < <(find plugins -name '*.sh' | sort)

# The provisioning hook must stay inert unless it is genuinely in a cloud container
# sitting on an openpilot checkout. A false positive would start a 10-minute build
# in someone's unrelated repo.
section "Cloud hook guards"
HOOK="$PWD/plugins/openpilot-cloud-dev/scripts/session-start.sh"
if [ -f "$HOOK" ]; then
  D=$(mktemp -d)
  # No subshell here: a ( ... ) block would lose the pass/fail counters.
  silent() { # label, env...
    local label="$1"; shift
    local out rc
    out=$(env "$@" bash "$HOOK" 2>&1); rc=$?
    if [ $rc -eq 0 ] && [ -z "$out" ]; then ok "$label"; else bad "$label (exit $rc) $out"; fi
  }
  silent "inert on a local session"             CLAUDE_PROJECT_DIR="$D"
  silent "inert outside an openpilot checkout"  CLAUDE_CODE_REMOTE=true CLAUDE_PROJECT_DIR="$D"
  touch "$D/SConstruct" "$D/pyproject.toml"
  silent "inert without a selfdrive/ directory" CLAUDE_CODE_REMOTE=true CLAUDE_PROJECT_DIR="$D"
  mkdir -p "$D/selfdrive"
  silent "honours OP_CLOUD_DEV_AUTOSETUP=0"     OP_CLOUD_DEV_AUTOSETUP=0 CLAUDE_CODE_REMOTE=true CLAUDE_PROJECT_DIR="$D"
  guard_out=$(env CLAUDE_CODE_REMOTE=true CLAUDE_PROJECT_DIR="$D" bash "$HOOK" 2>&1)
  case "$guard_out" in
    *"provisioning toolchain"*) ok "fires on a real openpilot checkout" ;;
    *) bad "did not fire on a real openpilot checkout: $guard_out" ;;
  esac
  rm -rf "$D"
else
  note "cloud hook not found at $HOOK"
fi

# ---------------------------------------------------------------- hygiene
section "Hygiene"
if grep -rIn -E 'eyJ[A-Za-z0-9_-]{20,}\.' --include='*.py' --include='*.md' --include='*.json' --include='*.sh' . 2>/dev/null | grep -v '^\./\.git/'; then
  bad "a JWT-shaped string is committed"
else
  ok "no JWT-shaped strings committed"
fi

# Anything with a shebang is meant to be run directly. git on Windows does not track
# the executable bit by default, so a script can be committed 100644 and then fail with
# "Permission denied" on Linux — which is how the SessionStart hook would break in a
# real container. Check the mode recorded in git, not the working copy.
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  notexec=""
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    # `head` here must be the coreutil. An earlier version of this script defined a
    # shell function named `head` for section titles, which shadowed it and made this
    # check silently unable to fail.
    case "$(head -1 "$f" 2>/dev/null)" in
      '#!'*) ;;
      *) continue ;;
    esac
    mode=$(git ls-files -s -- "$f" | awk '{print $1}')
    [ "$mode" = "100755" ] || notexec="$notexec $f"
  done < <(git ls-files)
  if [ -n "$notexec" ]; then
    bad "shebang files not executable in git:$notexec"
    echo "        fix: git update-index --chmod=+x <file>"
  else
    ok "every shebang file is executable in git"
  fi
else
  note "not a git checkout — cannot check executable bits"
fi

# ---------------------------------------------------------------- summary
echo
echo "================================"
echo " $pass passed, $fail failed, $skip skipped"
echo "================================"
[ "$fail" -eq 0 ] || exit 1
echo
echo "Not covered (needs a real account):"
echo "  COMMA_JWT=... $PY plugins/openpilot-device/mcp/test_live.py"
