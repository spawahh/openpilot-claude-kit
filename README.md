# openpilot claude-kit

Claude Code plugins for working on [openpilot](https://github.com/commaai/openpilot) and
its forks.

The first plugin targets the case where you **don't have a local Linux dev environment**:
provisioning an openpilot checkout inside an ephemeral cloud container, and knowing what
that environment can and cannot actually verify.

## Install

```
/plugin marketplace add spawahh/openpilot-claude-kit
/plugin install openpilot-cloud-dev@openpilot-claude-kit
/reload-plugins
```

## Plugins

### `openpilot-cloud-dev`

| Component | What it does |
|---|---|
| `openpilot-cloud-dev` skill | Provisioning steps, headless test running, and an explicit list of what a container cannot validate |
| `environment-limits` reference | Every container failure mode we hit, with the one-line fix — the part worth reading first |
| `SessionStart` hook | Provisions the toolchain automatically: submodules → deps/`uv sync` → LFS → minimal `scons` → persisted venv |

**The hook is conservatively gated.** It runs only when all of these hold:

- `CLAUDE_CODE_REMOTE=true` — a local machine is never touched
- the working directory looks like an openpilot checkout (`SConstruct`, `pyproject.toml`, a `selfdrive/`)
- `OP_CLOUD_DEV_AUTOSETUP` is not `0`

Set `OP_CLOUD_DEV_AUTOSETUP=0` to disable it and follow the skill's manual steps instead.

Tunables: `OP_SCONS_ARGS` (default `--minimal`), `UV_PYTHON`, `RAYLIB_BACKEND`.

### `openpilot-device`

Read-only access to a comma device through the [comma connect API](https://api.comma.ai/).
No SSH, no local network, no Prime proxy config — one token covers everything.

| Component | What it does |
|---|---|
| MCP server | 13 read-only tools: routes, signed rlog URLs, device stats, boot/crash logs, live cereal messages |
| `openpilot-device` skill | When each transport works, how to find a drive, and what the API cannot do |
| `api-surface` reference | Every endpoint, and the list of ones deliberately left unreachable |

```
/plugin install openpilot-device@openpilot-claude-kit
export COMMA_JWT="..."   # from https://jwt.comma.ai/, valid 90 days
```

Then run `verify_connection` before anything else.

**Read-only by construction.** Every tool builds its own URL — there is no generic
request tool — and a path guard refuses anything touching billing, pairing, user
management, or navigation. `POST /v1/prime/cancel` and "push a destination to a moving
car" are both real endpoints on this API; allowlisting is the entire safety model.
Athena helps here too: it exposes no shell, no reboot, and no parameter writes.

Requires [`uv`](https://docs.astral.sh/uv/) on PATH — the server declares its own
dependencies inline, so there is nothing to install by hand. Ships disabled
(`defaultEnabled: false`); it needs a credential, so opt in deliberately.

Your `COMMA_JWT` is a bearer credential for the whole account, not just the device.
Keep it in the environment. Never paste it into a chat.

### `openpilot-device-ssh`

The other half of device work: everything needing a shell. **Knowledge and scripts only
— no MCP server and no command tool.**

| Component | What it does |
|---|---|
| `comma-device-ssh` skill | Connecting (local and Prime proxy), deploying a fork branch to a second checkout, on-device builds, the headless verification ladder |
| `can-signal-hunt` skill | Finding the CAN message behind a physical car action, and the false positives that produce confident wrong answers |
| 4 scripts | `can_probe`, `bit_watch`, `event_watch`, `rlog_analyze` — read-only; nothing transmits to the car |

**Why no server here.** `openpilot-device` is read-only *by construction* — athena has
no dangerous methods, so there is nothing to allowlist. An SSH server would have a shell
on a car computer, and the guarantee would degrade to "safe by allowlist", which is
leaky for shell (`;`, `&&`, `$()`, quoting). The dangerous half of device work is exactly
what SSH unlocks, so this plugin ships the knowledge and lets your existing shell run it.

Which to use: if you need routes, logs, or a live snapshot, use `openpilot-device` — no
key, no local network. If you need a build, a deploy, params, live CAN, or a device with
no internet, you need SSH.

## What this is not

A container has no CAN bus, no comma device, no display, and no camera. Plenty of
openpilot work simply cannot be validated without hardware. The skill is deliberate
about naming that boundary, because the expensive mistake is not a failed build — it's
believing a change is verified when it isn't.

## Safety

openpilot is driver-assistance software that actuates a real vehicle.

Nothing in this repository validates a change for road use. Passing tests in a container
means code imports and behaves as specified in simulation. It does not mean the change is
safe to drive. Test on a road course or closed route, keep your hands on the wheel, and
follow [comma's safety documentation](https://github.com/commaai/openpilot/blob/master/docs/SAFETY.md).

## Provenance and verification status

The provisioning hook is generalized from a working setup used against a sunnypilot
checkout in Claude Code on the web. The generalized version — fork auto-detection, the
upstream-openpilot path — **has not yet been run end to end against upstream
`commaai/openpilot`**. Treat v0.1.0 as unverified on upstream and report what breaks.

The documented failure modes and fixes are each drawn from a real debugging session, not
from reading source.

`openpilot-device` **has been fully verified against a live account and an awake
device.** All 13 tools return real data, including the athena ones — `deviceState`
(34 fields), `carState` (50), `controlsState` (11), and a 2266-entry device file listing.

That run found four places where comma's published spec does not match the running API —
`/devices/:id/segments` 404s, `routes_segments` takes `start`/`end` rather than
`from`/`to`, `/route/:name/segments` does not exist, and there is no `is_online` field.
All four are fixed and documented in
[api-surface.md](plugins/openpilot-device/skills/openpilot-device/references/api-surface.md).
It also found that the `mcp` SDK renamed `FastMCP` to `MCPServer` in 2.0; the server
imports whichever is present.

## Verifying

One command runs everything that does not need a credential. This is also what CI runs.

```
./verify-kit.sh
```

24 checks: manifest structure, `claude plugin validate --strict` on every plugin, Python
compilation, the read-only safety suite, MCP server startup, the cloud hook's guard
conditions, and a scan for committed secrets.

| Suite | Needs | Covers |
|---|---|---|
| `test_safety.py` | nothing | Billing/pairing/navigation endpoints unreachable, rate limiter trips, no mutating tool names, GPS and VIN stripped by default |
| `test_startup.py` | `uv` | The server actually launches, resolves its own dependencies, and registers 13 described tools |
| `test_live.py` | `COMMA_JWT` | Every tool against a real account |

`test_live.py` is deliberately excluded from CI — the token is a bearer credential for a
personal comma account and does not belong in a secrets store for this.

**One thing remains unverified**: the cloud provisioning hook needs an actual cloud
container with `CLAUDE_CODE_REMOTE=true`, which cannot be faked locally. Its guard
conditions are tested; its provisioning body is not.

Because openpilot moves fast, anything here can go stale. Issues and PRs welcome,
especially "this no longer matches upstream" corrections.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by comma.ai.
