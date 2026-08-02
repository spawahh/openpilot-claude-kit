# Contributing to openpilot — full rules

Source: `docs/CONTRIBUTING.md` and `docs/SAFETY.md` on master, verified 2026-07-25. Verify live before quoting specifics: `https://raw.githubusercontent.com/commaai/openpilot/master/docs/CONTRIBUTING.md`

## Philosophy

- openpilot's priorities are **safety, stability, quality, and features, in that order**.
- Mission framing: "solve self-driving cars while delivering shippable intermediaries."
- The probability of a PR being merged is a function of its **value to the project** vs. the **effort it takes maintainers to merge it**. Some value + high review cost = closed.
- Coordination happens on Discord (discord.comma.ai) and GitHub. Docs: docs.comma.ai and blog.comma.ai.

## What gets merged — with example PRs

| Type | Example |
|---|---|
| Typo fix | commaai/openpilot#30678 |
| Removing unused code | commaai/openpilot#30573 |
| Simple car model port | commaai/openpilot#30245 |
| Car brand port | commaai/openpilot#23331 |

Simple, well-tested bug fixes are the easiest merge. New features are the hardest.

## What doesn't get merged

- **Style changes** — "code is art, and it's up to the author to make it beautiful"
- **500+ line PRs** — clean up, split up, or both
- **PRs without a clear goal** — every PR must have one singular, clear goal
- **UI design** — no good review process for it yet
- **New features** — openpilot is considered mostly feature-complete; refinement and bug fixes are the remaining work. Feature PRs are usually closed immediately. Features live in forks.
- **Negative expected value** — real improvement, but risk or validation cost exceeds it. Mitigation path: get a *failing test* merged first, then the fix.

## PR checklist

A good PR (against `master`) has all of:

1. Clearly stated purpose
2. Every changed line directly contributes to that purpose
3. Verification — how was it tested?
4. Justification — benchmarks for optimizations; before/after plots for tuning changes
5. Passing CI

## First contribution

The openpilot bounties project board (github.com/orgs/commaai/projects/26) is the recommended entry point and documents expectations for bounty work. Many bounties require **no comma device and no car**.

## Contributing without code

- Report bugs as GitHub issues
- Report driving issues in the `#driving-feedback` Discord channel
- Opt into driver camera uploads (improves the driver monitoring model)
- Keep the device on Wi-Fi so training data can be pulled
- Run the `nightly` branch (master, but built like a release) and report issues
- Annotate images in the comma10k dataset (github.com/commaai/comma10k)

## Fork rules

### Safety requirements (from SAFETY.md)

- Do **not** disable or weaken driver monitoring (`openpilot/selfdrive/monitoring`)
- Do **not** disable or weaken excessive actuation checks (`openpilot/selfdrive/selfdrived/helpers.py`)
- If a fork modifies anything in `opendbc/safety/`:
  - it cannot use the openpilot trademark
  - it must preserve the full safety test suite (`opendbc/safety/tests`) with all tests passing, including new coverage for the fork's changes
- Non-compliance → fork author and users banned from comma.ai servers

Safety design basis: driver can always immediately retake control (brake or cancel); actuators constrained so trajectory can't change faster than a driver can react (ISO11270 / ISO15622 limits; ISO26262 guidelines; MISRA C:2012 on safety-relevant code).

### Training-data eligibility (fork data feeding comma's training set)

- cereal messaging structs must remain compatible (see `openpilot/cereal` custom-forks notes)
- Stock struct definitions must not change — don't alter how any stock field is set (`selfdriveState.enabled`, `carState.steeringAngleDeg`, etc.). Add your own structs instead.
- Don't include cars unsupported upstream under existing platforms — create new opendbc platforms instead, even for trim-level differences.

## Code style & CI conventions

From `pyproject.toml` (verify live — this changes):

- **ruff** with 2-space indent, line length 160, extensive lint selection (E/F/W, bugbear, pyupgrade, numpy rules, etc.)
- **Banned APIs** (flake8-tidy-imports):
  - `pytest` imports → "Use unittest" (tests are *run* by pytest, *written* unittest-style)
  - `time.time` → use `time.monotonic`
  - raylib: `pyray.measure_text_ex` → `openpilot.system.ui.lib.text_measure`; `pyray.is_mouse_button_pressed` → `Widget._handle_mouse_press`
- **pytest** config: `-Werror --strict-config`, test files `test_*.py`, testpaths `openpilot`
- **codespell** runs in CI
