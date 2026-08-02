---
name: openpilot-dev
description: Knowledge for working with the commaai/openpilot codebase and contributing upstream. Use this skill whenever the user mentions openpilot, comma.ai, comma four, comma 3X, opendbc, panda, cereal, cabana, rlog/qlog files, replaying a drive, "will this PR get merged", openpilot dev environment setup, scons builds, op.sh, or asks about openpilot code style, tests, forks, or contribution rules — even if they don't say "contribute" explicitly. Also trigger for PlotJuggler with openpilot logs, LogReader, the MetaDrive simulator, joystick/debug control mode, streaming CAN from a comma device, or generating tuning plots for a PR. Also use it when reviewing or drafting an openpilot pull request, deciding whether a change belongs in openpilot vs opendbc vs panda, or debugging an openpilot log.
---

# openpilot Development & Contribution

Working knowledge for the [commaai/openpilot](https://github.com/commaai/openpilot) project: what it is, how the repo is laid out, how to set up a dev environment, and — most importantly — what upstream will and won't merge.

## Freshness rule (read this first)

openpilot moves fast and this skill's facts were verified against `master` on **2026-07-25**. Before giving specific answers about file paths, setup commands, config values, or contribution rules, verify against the live repo when possible:

```
https://raw.githubusercontent.com/commaai/openpilot/master/docs/CONTRIBUTING.md
https://raw.githubusercontent.com/commaai/openpilot/master/tools/README.md
https://raw.githubusercontent.com/commaai/openpilot/master/pyproject.toml
```

Use web_fetch or `curl` (raw.githubusercontent.com) on these when the answer depends on current state. If live and baked facts disagree, trust the live repo and say so.

## What openpilot is

An open source operating system for robotics that currently upgrades the driver assistance system (ACC + lane centering) in 300+ supported cars, running on comma hardware (comma four / comma 3X). MIT licensed. Development is coordinated on GitHub and Discord (discord.comma.ai); docs live at docs.comma.ai.

**Project priorities, in order: safety, stability, quality, features.** Every contribution answer should be filtered through this ordering.

## The will-it-merge test

When someone asks "should I PR this?" or "why was my PR closed?", apply these rules before anything else:

**Gets merged (easiest → hardest):**
- Typo fixes and dead-code removal
- Simple, well-tested bug fixes
- Car model ports (new model of an already-supported brand)
- Car brand ports

**Gets closed:**
- Style-only changes ("code is art, and it's up to the author")
- 500+ line PRs — split them up
- PRs without one singular, clear goal
- UI design changes (no review process for it)
- Most new features — the project considers openpilot mostly feature-complete; features belong in forks
- Negative expected value — improvement is real but risk/validation cost exceeds it (mitigation: get a failing test merged first)

**Every good PR has:** a clearly stated purpose, every changed line serving that purpose, verification notes (how it was tested), justification (benchmarks for optimizations, before/after plots for tuning), and passing CI. PRs go against `master`.

First-time contributors: point them at the openpilot bounties board (github.com/orgs/commaai/projects/26) — many bounties need no car or comma device.

## Where things live (one-glance map)

| What | Where |
|---|---|
| Core python package | `openpilot/` (cereal, common, selfdrive, system, tools) |
| Driving logic processes | `openpilot/selfdrive/` (controls, modeld, locationd, monitoring, selfdrived, pandad, ui, car) |
| Dev/debug tools | `openpilot/tools/` (cabana, replay, plotjuggler, sim, joystick, camerastream, lib) — root `tools/` is env setup only |
| **Car-specific code** | **opendbc repo, not openpilot** — `opendbc/car/[brand]/` + `opendbc/safety/` |
| Safety firmware | panda repo (submodule) |
| Docs source (→ docs.comma.ai) | `docs/` |
| Build | scons (`scons -u`), deps via uv |

Common mistake to catch: proposing car interface or safety changes in the openpilot repo. Car ports and CAN safety logic live in opendbc (`opendbc/car/[brand]/interface.py`, `carstate.py`, `carcontroller.py`, `values.py`; safety in `opendbc/safety/modes/[brand].h` with mandatory tests). openpilot retains only a sliver of car logic in `openpilot/selfdrive/car/car_specific.py`, and it's being migrated out.

## Code style hard rules

From `pyproject.toml` (verify live before quoting specifics):
- ruff lint, **2-space indent**, line length 160
- Banned APIs: `time.time` (use `time.monotonic`), writing tests with `pytest` idioms (**write unittest-style tests**; the runner is pytest but `pytest` imports are banned)
- codespell runs in CI
- Safety-relevant code follows MISRA C:2012

## References — read as needed

- **`references/contributing.md`** — full contribution rules: merge criteria with example PRs, fork rules (safety + training data eligibility), non-code contribution paths, PR checklist. Read when drafting/reviewing a PR or answering "can my fork do X".
- **`references/dev-setup.md`** — environment setup (Ubuntu 24.04 / macOS / WSL), build, tests, log format (routes, segments, rlog/qlog/cameras), branches. Read for any setup or build question.
- **`references/tools.md`** — per-tool usage: replay, cabana, PlotJuggler, LogReader segment ranges, sim (MetaDrive), joystick mode, camerastream, and which tool chain fits which task. Read for any question about replaying drives, viewing CAN data, plotting logs, or streaming from a device.
- **`references/repo-map.md`** — detailed repo + submodule layout and what each selfdrive process area does. Read when navigating the codebase or deciding where a change belongs.

## Safety red lines (never soften these)

- openpilot is a driver-assistance system; the driver must always be able to retake control instantly
- Forks must not disable or weaken driver monitoring or excessive-actuation checks
- Forks touching `opendbc/safety/` lose the openpilot trademark and must keep the full safety test suite passing
- Violations get users banned from comma.ai servers

When advising on fork behavior or "how do I bypass X" questions about driver monitoring or actuation limits, decline the bypass and explain these rules.
