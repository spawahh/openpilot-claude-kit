---
name: comma-device-ssh
description: >-
  Work on a comma 3X or comma four over SSH — connect locally or through the Prime
  proxy, deploy a fork branch to a second checkout without disturbing the daily
  driver, build on-device, and verify headlessly. Use when asked to deploy to the
  device, test a change on real hardware, build on the device, run the UI, or
  diagnose a device that will not come back after a reboot. Trigger on "comma 3X",
  "comma four", "deploy to device", "ssh.comma.ai", "/data/openpilot", "AGNOS",
  "on-device build", or "scons" in a device context.
---

# Working on a comma device over SSH

SSH is for what the connect API cannot reach: a shell. Builds, deploys, params,
live CAN capture, reboots, and any device with no internet. If you only need routes,
logs, or a live cereal snapshot, use the `openpilot-device` plugin instead — it needs
no key and no local network.

## Connecting

Enable SSH in device settings and enter your GitHub username; the device pulls your
public keys from GitHub once. Re-enter the username to refresh them.

```bash
# Local network
ssh comma@<device-ip> -i ~/.ssh/your_key

# Through the Prime proxy, from anywhere. Dongle id is the HOST, user is still 'comma'.
# ~/.ssh/config:
#   Host comma-*
#     ProxyCommand ssh %h@ssh.comma.ai -W %h:%p
#     IdentityFile ~/.ssh/your_key
#     User comma
#     Port 22
ssh comma-<dongleid>
```

The proxy is two hops. Set up `ControlMaster` if you are making many calls, or every
command pays a full handshake.

## Before any deploy, check three things

```bash
ssh … 'cat /data/params/d/IsOffroad; git -C /data/openpilot remote -v | head -2
       free -m | sed -n 2p; df -h /data | tail -1'
```

`IsOffroad` must be `1`. Note free RAM and free disk — both bite later.

**The daily driver lives at `/data/openpilot`. Never build into it.** Use a sibling
directory (`/data/<forkname>`) so the working install keeps running throughout.

## Footguns that cost an hour each

⚠️ **`systemctl restart comma` can launch the factory reset.** `comma.sh` gates reset on
`[ ! -f /tmp/booted ]` plus a *cumulative* `touch_count > 4`, which is always true on a
used device — only the `/tmp/booted` marker prevents `$RESET --tap-reset`. A restart has
been observed printing `launching system reset, got taps` and drawing the reset UI. It
exited without wiping that time; do not rely on that. **Use `sudo reboot`** — clean
`/tmp`, reset counter, same code path.

⚠️ **`systemctl is-active comma` reports `active` with the entire stack dead.** The unit
is `Type=oneshot` with `RemainAfterExit=true`. Check
`ps -eo pid,etimes,cmd | grep manager\.py` instead, and allow ~2 minutes before calling
it failed.

⚠️ **Never run the fork's `launch_openpilot.sh` on the device.** If the fork pins a
different AGNOS version than the one installed, the launch script starts an **OS
reflash** before anything else. It writes to the inactive boot slot and only switches
after verification, so killing it early is recoverable — but do not start it.

⚠️ **An unreachable device is almost always WiFi, not a failed boot.** SSH timing out
right after `sudo reboot` proves nothing. When it answers, read
`cut -d. -f1 /proc/uptime` alongside the process list — long uptime with the stack up
means it booted cleanly and only the link was down. Never describe a boot as broken
without evidence about the boot itself, and never stack another deploy on an unverified
one.

⚠️ **Verify base64-over-SSH transfers by size** (`stat -c %s` device-side vs local).
Flaky car WiFi has silently truncated a bundle mid-push, and the later `git fetch` error
looks unrelated.

⚠️ **If the deploy touched `log.capnp` or `custom.capnp`, the reboot's launch build is
long** — capnp C++ regeneration plus everything downstream, 10–20 minutes with a dark
screen. That is not a failed deploy. Do not intervene before ~20 minutes.

## Getting local-only commits onto the device

No GitHub repo needed. Clone upstream on-device, then fetch a bundle of just your commits.

```bash
# workstation
git bundle create work.bundle <branch> --not upstream/master    # a few KB
base64 -w0 work.bundle | ssh … "base64 -d > /data/work.bundle"
```

```bash
# device
cd /data && GIT_LFS_SKIP_SMUDGE=1 git clone --filter=blob:none --no-checkout \
  https://github.com/commaai/openpilot.git <forkname>
cd <forkname> && export GIT_LFS_SKIP_SMUDGE=1 && git config lfs.fetchexclude "*"
git fetch /data/work.bundle "<branch>:<branch>" && git checkout -f <branch>
```

⚠️ **`GIT_LFS_SKIP_SMUDGE=1 git clone …` covers only the clone.** A later `git checkout`
in the same chain re-smudges and starts pulling LFS blobs. `export` it, or set
`lfs.fetchexclude` before checking out.

## LFS is mandatory for UI work

`.gitattributes` puts `*.png *.svg *.ttf *.otf *.wav` in LFS — every font and icon the
UI draws. Skip LFS and the UI cannot render.

The working tree needs ~130 MB, but a bare `git lfs pull` also drags in history and can
balloon `.git/lfs` past 1 GB. Unset `fetchexclude`, pull, then **verify by hunting
pointers rather than watching progress**:

```bash
find openpilot/selfdrive/assets -type f | while read f; do
  head -c 45 "$f" | grep -q "version https://git-lfs" && echo "POINTER: $f"; done
```

No output means complete — kill the fetch, it is only doing history. `git lfs prune`
fails offline.

Submodules: `git submodule update --init --recursive --depth 1`, under a minute.

## Building on-device

```bash
export PATH=/usr/local/venv/bin:$PATH     # REQUIRED
export PYTHONPATH=/data/<forkname>
scons -j2 > /data/build.log 2>&1; echo "EXIT=$?" >> /data/build.log
```

- **`PATH` is not optional.** Calling `/usr/local/venv/bin/scons` by absolute path still
  fails at ~11% with `cythonize: command not found` — scons shells out to venv tools.
- **Use `-j2`, the project's own default.** The device has ~3.6 GB RAM and **no swap**,
  and a running openpilot holds ~1.8 GB. `-j4` OOM-kills rednose's generated kalman code:
  `Error -9`. **−9 is SIGKILL, not a missing file** — read the `Error` line, never the log
  tail, which shows an unrelated last-success line.
- `--minimal` is a no-op on-device; `extras` already defaults off for release builds.
- Redirect to a log file. **Never pipe a long build through `tail`** — it buffers, and a
  live build looks identical to a hung one. Poll with
  `until ssh … 'grep -q EXIT= /data/build.log'; do sleep 45; done` in a background call.

**Most changes need no build at all.** A Python-only change is `git fetch` +
`git merge --ff-only FETCH_HEAD` + `sudo reboot`. A new params key needs only
`scons -j2 openpilot/common/libparams_c.so` (~1 min). A capnp schema change is the
expensive one.

Run the fork's own tests on-device before rebooting — the venv python has every real
dependency, so it catches what a stubbed local env hid:

```bash
export PATH=/usr/local/venv/bin:$PATH PYTHONPATH=/data/<forkname>
cd /data/<forkname> && python3 -m pytest openpilot/<pkg>/ -q
```

## Verifying a boot

```bash
until ssh … 'ps -eo cmd | grep -q "[m]anager\.py"'; do sleep 20; done
ssh … 'git -C /data/<forkname> log --oneline -1; cut -d. -f1 /proc/uptime;
        ps -eo etimes,cmd | grep -E "[m]anager\.py|[u]i\.ui";
        tmux capture-pane -pt comma -S -500 | grep -c Traceback'
```

⚠️ **Grep the process list by the pattern you actually mean.** A loose `grep -c <name>`
has matched a stale "not running" line and read as healthy. Use the bracket trick
(`grep "[m]anager\.py"`) so the grep never matches itself. The same PID across two checks
proves it never crash-looped.

⚠️ **Verify the python process itself** (`pgrep -af "python3 <script>"`), never
`pgrep -f <name>` — that matches your own tmux/bash wrapper and reports a dead process
as RUNNING.

## Headless verification ladder

Climb in order; each rung catches a different class of breakage.

1. **Unit tests.** Pure-Python tests can run without building anything.
2. **Import-level state checks.** Import through the *real* module path the app uses and
   assert values change. This proves the wiring, not a stub. Print RGBA explicitly — a
   bare `print(color)` gives `<cdata 'struct Color'>` and tells you nothing.
3. **Layout construction.** `gui_app.init_window("check")`, then build the real layout
   tree. Catches broken widget construction, missing params, and panel-registration
   errors. raylib gets a DRM/gbm context fine alongside the running UI.
4. **On the display** — needs a person at the car. Stop the daily driver and run only the
   UI; do not run `launch_openpilot.sh` (see above). Stopping someone's daily driver is
   their call, not something to do unasked.

## Screenshots do not work — do not promise a picture

- **`rl.take_screenshot("/abs/path.png")` silently fails.** It resolves relative to cwd,
  so an absolute path becomes `<cwd>//abs/path.png`. Pass a bare filename.
- **A hand-rolled `begin_drawing`/`end_drawing` loop bypasses `gui_app`'s rotation and
  render-texture transform.** The grab comes out in native portrait orientation and
  near-empty. Symptom: two captures byte-identical with 1–2 unique colors.
- **`ffmpeg` is not installed**, so the `RECORD=1` mp4 path is unavailable.

Verify through rungs 1–3, then have the person at the car look at the screen.

## Cleanup

Remove pushed scripts, logs, and bundles. A built checkout is **~4.2 GB**. On a device
that was already near full, say so explicitly and let the owner decide whether it stays
between sessions. Re-verify `df -h /data` and that `/data/openpilot` is untouched.

## Safety

Everything here runs on a computer bolted to a real car. Confirm `IsOffroad` is `1`
before any deploy or build. Never modify the daily-driver checkout in place, and never
start, stop, or reconfigure anything while the car is in use.
