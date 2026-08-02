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

`openpilot-device` is transcribed from [comma's published API spec](https://api.comma.ai/)
and openpilot's own client code (`tools/lib/api.py`, `system/athena/athenad.py`). **No
endpoint has been called against a live account** — that needs a token. Expect
response-shape surprises on first real use, especially in `verify_connection`. Run it
before trusting anything else.

The read-only guarantee *is* tested and does not depend on a token:

```
python plugins/openpilot-device/mcp/test_safety.py
```

It asserts that every billing, pairing, user-management, and navigation endpoint is
refused, that the rate limiter trips, and that no registered tool name implies a
mutation. No network, no dependencies.

Because openpilot moves fast, anything here can go stale. Issues and PRs welcome,
especially "this no longer matches upstream" corrections.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by comma.ai.
