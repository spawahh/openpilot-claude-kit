# openpilot claude-kit

Four Claude Code plugins for working on [openpilot](https://github.com/commaai/openpilot)
and its forks: codebase knowledge, a cloud dev environment, read-only access to your comma
device, and the SSH workflows for everything that needs a shell.

They are independent — install only what you need.

## Which one do I want?

| I want to… | Plugin | Needs |
|---|---|---|
| Understand the codebase, or know whether my PR will merge | [`openpilot-dev`](#openpilot-dev) | nothing |
| Work on openpilot without a local Linux box | [`openpilot-cloud-dev`](#openpilot-cloud-dev) | a cloud session |
| Look at my drives, logs, and live device state | [`openpilot-device`](#openpilot-device) | comma account, `uv` |
| Deploy to a device, build on it, hunt CAN signals | [`openpilot-device-ssh`](#openpilot-device-ssh) | SSH key, physical device |

**The two device plugins split by transport, and the split is real.** `openpilot-device`
reads through comma's cloud API — no key, no local network, works from anywhere. But it
cannot give you a shell. `openpilot-device-ssh` covers everything that needs one: builds,
deploys, params, live CAN, and any device with no internet at all.

## Prerequisites

- **Claude Code** — all four plugins.
- **[`uv`](https://docs.astral.sh/uv/) on PATH** — `openpilot-device` only. Its MCP server
  declares dependencies inline, so `uv` installs them; there is nothing to `pip install`.
- **A comma prime subscription** — only for the `ssh.comma.ai` proxy in
  `openpilot-device-ssh`. Local-network SSH and the whole connect API work without it.

## Install

```
/plugin marketplace add spawahh/openpilot-claude-kit
```

Then install whichever you want:

```
/plugin install openpilot-dev@openpilot-claude-kit
/plugin install openpilot-cloud-dev@openpilot-claude-kit
/plugin install openpilot-device-ssh@openpilot-claude-kit
/plugin install openpilot-device@openpilot-claude-kit
/reload-plugins
```

`openpilot-device` ships **disabled** because it needs a credential. Turn it on
deliberately, after setting your token (see [its section](#openpilot-device)):

```
/plugin enable openpilot-device@openpilot-claude-kit
```

## Plugins

### `openpilot-dev`

Working knowledge of the openpilot codebase and what upstream actually merges. Pure
knowledge — no hook, no server, no credential.

| Component | What it does |
|---|---|
| `openpilot-dev` skill | The will-it-merge test, repo layout, code style hard rules, safety red lines |
| `contributing` reference | Merge criteria with examples, fork rules, PR checklist |
| `dev-setup` reference | Local setup (Ubuntu / macOS / WSL), build, tests, log format |
| `repo-map` reference | Repo and submodule layout, what each `selfdrive` process does |
| `tools` reference | replay, cabana, PlotJuggler, LogReader, MetaDrive sim, joystick, camerastream |

The single most useful thing here is knowing that **car ports and CAN safety live in
opendbc, not openpilot** — proposing them in the wrong repo is the most common wasted PR.

The skill states the date its facts were verified against `master` and links the raw
upstream files to re-check. openpilot moves fast; trust the live repo over the skill when
they disagree.

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

Tunables: `OP_SCONS_ARGS` (default `--minimal`), `OP_SETUP_TIMEOUT`, `OP_UV_SYSTEM_PYTHON`, `RAYLIB_BACKEND`.

### `openpilot-device`

Read-only access to a comma device through the [comma connect API](https://api.comma.ai/).
No SSH, no local network, no Prime proxy config — one token covers everything.

| Component | What it does |
|---|---|
| MCP server | 13 read-only tools: routes, signed rlog URLs, device stats, boot/crash logs, live cereal messages |
| `openpilot-device` skill | When each transport works, how to find a drive, and what the API cannot do |
| `api-surface` reference | Every endpoint, and the list of ones deliberately left unreachable |

Generate a token at <https://jwt.comma.ai/> (valid 90 days), then put it where **Claude
Code itself** will inherit it:

```powershell
# Windows — then restart Claude Code
setx COMMA_JWT "<token>"
```

```bash
# macOS / Linux — add to your shell profile, then restart Claude Code
export COMMA_JWT="<token>"
```

**Exporting it in an already-running terminal will not work.** The MCP server is launched
by Claude Code and inherits the environment Claude Code started with, not whatever you type
into a shell afterwards. If `verify_connection` reports the token missing, this is why —
set it, then fully restart.

Then:

```
/plugin enable openpilot-device@openpilot-claude-kit
```

Run `verify_connection` before anything else. It confirms the token works and lists your
devices without echoing the token back.

**Read-only by construction.** Every tool builds its own URL — there is no generic
request tool — and a path guard refuses anything touching billing, pairing, user
management, or navigation. `POST /v1/prime/cancel` and "push a destination to a moving
car" are both real endpoints on this API; allowlisting is the entire safety model.
Athena helps here too: it exposes no shell, no reboot, and no parameter writes.

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

## What this is not

A container has no CAN bus, no comma device, no display, and no camera. Plenty of openpilot
work simply cannot be validated without hardware. The skills are deliberate about naming
that boundary, because the expensive mistake is not a failed build — it's believing a
change is verified when it isn't.

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

25 checks: manifest structure, `claude plugin validate --strict` on every plugin, Python
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
especially "this no longer matches upstream" corrections — see
[CONTRIBUTING.md](CONTRIBUTING.md) for the checks to run and the rules that keep each
plugin safe to install.

Found a way to make `openpilot-device` write something, or to get GPS out of it by
default? That is exactly the bug worth reporting — privately, via
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by comma.ai.
