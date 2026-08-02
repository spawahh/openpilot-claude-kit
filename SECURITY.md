# Security

## Reporting

Use **[private vulnerability reporting](https://github.com/spawahh/openpilot-claude-kit/security/advisories/new)**
— the Security tab on this repository. Please do not open a public issue for anything in
the "in scope" list below.

**Never include a `COMMA_JWT` in a report.** It is a bearer credential for an entire comma
account — routes, GPS traces, device list. If you believe a token has been exposed,
generate a new one at <https://jwt.comma.ai/> and say so in the report without pasting
either token. Note that JWTs are stateless: generating a replacement does not necessarily
invalidate the old one, which stays valid until its `exp`.

## What this project claims

`openpilot-device` claims to be **read-only by construction**, and that is the claim worth
attacking:

1. Every tool builds its own URL path. There is no generic request tool.
2. `_guard_path()` refuses any path containing `/prime`, `pilotpair`, `unpair`, `add_user`,
   `del_user`, `/navigation`, or `payment` — even if a future edit adds a tool that would
   reach one.
3. GPS coordinates and VIN are stripped from routes, segments, and device records unless
   the caller explicitly passes `include_sensitive=True`.
4. Athena itself exposes no shell, no reboot, and no parameter writes.

`plugins/openpilot-device/mcp/test_safety.py` asserts all of this and runs with no network
and no dependencies.

## In scope

- Any way to make the MCP server reach a mutating comma endpoint — particularly
  `POST /v1/prime/cancel` or `POST /v1/navigation/:id/set_destination`, which would cancel
  a subscription or push a destination to a moving car
- A bypass of the location/VIN redaction that leaks coordinates or VIN by default
- Anything that logs, returns, or otherwise discloses `COMMA_JWT`
- A path traversal or injection through a tool argument (for example a crafted
  `dongle_id` or `route_name` that escapes the intended path)
- Anything in the cloud provisioning hook that runs outside its guard conditions —
  it must stay inert unless `CLAUDE_CODE_REMOTE=true` **and** the working directory is an
  openpilot checkout

## Out of scope

- **Vulnerabilities in openpilot, opendbc, panda, or comma's services.** Report those to
  [commaai](https://github.com/commaai/openpilot/security) — not here.
- **The `openpilot-device-ssh` plugin's documented workflows.** That plugin ships knowledge
  and scripts only, with no server and no command tool; the commands run in your own shell
  under your own key. If you have SSH to a comma device you already have full control of it.
- **Requiring a valid `COMMA_JWT`.** Every tool needs one. "An attacker with the user's
  token can read the user's routes" is the design, not a flaw.
- **CAN-bus access.** If someone can inject frames on a vehicle bus, the car is already
  compromised. The CAN scripts here are read-only and transmit nothing.

## Safety, which is not the same as security

openpilot is driver-assistance software that actuates a real vehicle. Nothing in this
repository validates a change for road use, and no test here — including a green CI run —
means a change is safe to drive.

If you find something that could cause this tooling to affect a vehicle in motion, treat it
as in scope and report it privately, whether or not it fits the categories above.
