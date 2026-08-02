# Contributing

Corrections are the most valuable contribution here. openpilot moves fast, and a skill that
confidently states something no longer true is worse than no skill at all. If something in
this kit no longer matches upstream, an issue saying so is genuinely useful even without a
fix attached.

## Before you open a PR

```bash
./verify-kit.sh
```

26 checks, none of which need a credential or a device: manifest structure, `claude plugin
validate --strict` on every plugin, Python compilation, the read-only safety suite, MCP
server startup, the cloud hook's guard conditions, committed-secret and executable-bit
scans. CI runs exactly this script, so a green local run means a green CI run.

If you changed `openpilot-device` and have a comma account, also run:

```bash
COMMA_JWT=... uv run plugins/openpilot-device/mcp/test_live.py
```

This is not in CI — the token is a bearer credential for a personal account and does not
belong in a secrets store.

## Hard rules

These are not style preferences. Each one is the reason a plugin is safe to install.

1. **No mutating tool in `openpilot-device`.** No tool may write, and no generic
   request/proxy tool may exist. If you add a tool, it builds its own URL path. See
   [SECURITY.md](SECURITY.md) for what the guard blocks and why.
2. **No arbitrary-command tool in `openpilot-device-ssh`.** That plugin deliberately ships
   no MCP server. A shell tool pointed at a car computer degrades a
   safe-by-construction guarantee into a leaky allowlist. If you want structured SSH
   diagnostics, propose narrow named read-only tools — never `run_command`.
3. **Keep redaction on by default.** GPS and VIN stay stripped unless the caller passes
   `include_sensitive=True`. A route listing is a map of where someone lives and works.
4. **Never commit a token.** Push protection is enabled, but do not rely on it.
5. **Anything with a shebang must be `100755` in git.** `git update-index --chmod=+x <file>`.
   git on Windows does not track this, and the SessionStart hook fails with "Permission
   denied" in a real container without it. `verify-kit.sh` checks it.

## Writing or editing a skill

- **Date-stamp claims about upstream** and link the raw file so a reader can re-check.
  Follow the pattern in `plugins/openpilot-dev/skills/openpilot-dev/SKILL.md`. Do not bump
  a verification date you did not actually re-verify.
- **Say what the thing cannot do**, not only what it can. The expensive mistake with this
  tooling is not a failed command — it is believing something is verified when it isn't.
- **Prefer a documented uncertainty to a confident guess.** Where the shipped code and the
  field notes disagree, say so and tell the reader how to decide. There is a worked example
  in the `can-signal-hunt` skill's per-bit vs per-byte section.
- Keep safety framing intact. Do not soften driver-monitoring or actuation-limit language.

## Adding a plugin

```
plugins/<name>/
├── .claude-plugin/plugin.json      # name must match the marketplace entry
├── skills/<skill-name>/SKILL.md    # plus references/ and scripts/ as needed
├── hooks/hooks.json                # optional
└── .mcp.json                       # optional
```

Add a matching entry to `.claude-plugin/marketplace.json`. `source` must start with `./`
— a bare path fails to load, and `verify-kit.sh` will catch it. Set
`defaultEnabled: false` if the plugin needs a credential.

## Commits and PRs

One focused change per PR, with a body saying what you verified and how. If you could not
verify something, say that too — this repo tracks verification status openly in the README
and it should stay honest.

Test evidence beats assertion. "Ran `./verify-kit.sh`, 26/26" is worth more than "should
work".
