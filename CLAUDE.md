# chainproxy — notes for Claude Code

Windows tool that chains two proxy subscriptions (client -> node of list A -> node of list B ->
internet) with sing-box, picks the best route that passes verification, sets the Windows
system proxy, and lets the user rotate routes (GUI, console, `next.bat`). Development happens
on a CachyOS (Arch) host; Windows behaviour is tested in a libvirt VM driven over ssh.

The user writes in Persian. Answer in Persian; keep code, comments, UI strings and log
messages in English (Windows consoles mangle RTL text). End-user and developer docs are
Persian (`docs/`, `dev/README.md`).

## Verified state (2026-11-01; desktop 1.3.2, Android 0.2.5)
Desktop: `make check` PASS (lint, 42 unit, 13 dev-tool, GUI smoke on Xvfb incl. collapsed log, local e2e). Windows 11 VM: deploy,
install, unit (42), e2e (real sing-box) PASS, `vm-installer-full` PASS; the VM GUI stage was SKIPPED (the VM desktop sat at the lock
screen and logging in needs the user's password) so the 1.3.2 window changes (flat status text, collapsed log, hand cursor) were
checked under Tk on Linux only. Not yet verified: Chrome itself, a Windows 10 VM, a clean-machine first run without `offline/`.
Android: 18 JVM tests, emulator lab session + TUN tests PASS (x86_64 debug), real Lantern on the emulator; 0.1 was tested on the
user's real phone (worked), 0.2.0 was also tested on the phone (works, incl. finding the tile); 0.2.1 (tile icon, no duplicate hint) only on the emulator; 0.2.2 (verification used a pooled keep-alive tunnel, so every route was judged by the first route's exit) tested on the phone (works; first attempt still failed on a noisy network); 0.2.3 (auto-rescan x2 when nothing passes, one retry when Google gives no answer) on the phone: still failed on the first start sometimes; 0.2.4 (works on the phone; exit nodes the phone cannot reach directly are kept for the chain test) only on the emulator, where all 30 nodes are reachable so that path is covered by PickTest only; 0.2.5 (clear-log button, LTR auto-scrolling log, update check/download through the local proxy first + update-source field) only on the emulator.

## Codebase index (codebase-memory-mcp) - use it first
This project is indexed as `home-hadi-projects-chainproxy-win` (git-watch keeps it fresh; re-index with
`index_repository(repo_path="/home/hadi/projects/chainproxy-win", mode="full")` if `index_status` says stale).
- Start a new conversation with `/onboard` (loads the ADR, architecture, state) or at least
  `manage_adr(project, mode="get")` - it holds the architecture notes, decisions, workflows and the release recipe.
- Navigate with `search_graph` / `get_code_snippet` / `trace_path` / `get_architecture` / `detect_changes` instead of
  reading whole files (chain.py is ~1200 lines). Use grep/Read for what the graph does not model: `.ps1`/`.bat`
  (`clean.ps1` is only partly parsed), `.iss`, docs, Makefile targets, config values, comments.
- Not indexed by design: `subs.txt` (real links), `dev/vm/vm.conf`, `.claude/`, `dist/`, `dev/artifacts/`.
- After a notable change, update the ADR (`manage_adr mode=set_sections`) and the docs together.

## Layout
- `chain.py` - all logic (parse, config, core, Windows proxy, watchdog, control socket, CLI)
- `gui.py` - tkinter window, thin layer over `chain.App`
- `setup.ps1` + `Run.bat` - first-run bootstrap on Windows (Python, sing-box, shortcuts)
- `tests/` - `run_tests.py` (unit, mock core), `gui_smoke.py`, `mock_core.py`
- `dev/lab/` - hermetic e2e lab with the REAL sing-box: `lab.py` (A/B nodes + fake internet),
  `e2e_client.py` (client flow, runs on Linux or in the VM), `e2e_local.py`
- `dev/vm/` - `vmtest.py` (VM driver), `guest/*.ps1` (run inside Windows), `vm.conf`
- `docs/USER-GUIDE.md`, `docs/DEVELOPER.md`, `dev/README.md` (dev environment + VM testing)

## Commands
- `make test` - unit tests, ~10 s, no network. Run after every change.
- `make check` - lint + unit + dev-tool tests + GUI smoke (Xvfb) + local e2e (real sing-box)
- `make vm-all` - full Windows suite (deploy, install, unit, e2e, gui). ~5-15 min.
- single stages: `make vm-unit`, `make vm-e2e`, `make vm-gui`, `make vm-install`
- `python3 dev/vm/vmtest.py ps "<PowerShell>"` - run one command in the VM
- results: `dev/artifacts/vm-latest/` (summary.json, *.log, gui-*.png, lab evidence)
- `make installer` / `python3 dev/make_installer.py` - builds `dist/ChainProxy-Setup-<ver>.exe` with Inno Setup 6 INSIDE the VM (installer/chainproxy.iss; Inno comes from github.com/jrsoftware/issrc releases, check its signature). `make pdf` rebuilds the quick-start PDF; rebuild BEFORE the zip/installer.
- `make lantern` builds the Lantern engine zip (Go, pinned radiance commit, no C compiler needed for Windows); `make vm-lantern` runs the real engine in the VM (internet); `make vm-update` tests the self-update against a fake release server on the host.
- `make vm-clean` - removes EVERYTHING the project put into the VM (test copy, installed app, installers, shortcuts, Python, Inno Setup, proxy settings; keeps sshd/key/autologon). `make vm-clean-light` keeps Python + Inno. `make vm-installer` / `vm-installer-full` test a built installer (install, first run, upgrade, uninstall); run `vm-clean` first for a true clean-machine test and again afterwards.
- `/vm-test`, `/check`, `/release` slash commands wrap the above; `/android` checks the Android build tools and continues the Android app (state: `android/PROGRESS.md`, design: ADR "Android app (in progress)")

## When to test where
- Pure Python logic (parsing, ranking, config): `make test`; add a unit test.
- Anything touching sing-box config: also `make e2e-local` (real core on this host).
- Registry / proxy / setup.ps1 / shortcuts / GUI on Windows / paths: `make vm-all` (or the
  relevant stage). These cannot be verified on Linux.
- Never claim Windows behaviour works without a VM run; say what was and was not run.

## Rules
- NO personal name, GitHub account or repository address as plain text inside the shipped software (desktop files, Windows
  window, installer metadata, APK strings, package id, signing certificate): filtering systems may key on them. The release
  repository is kept base64-encoded (`REPO` in chain.py, `UpdateChecker.DEFAULT_REPO` in Kotlin); LICENSE says "Chain Proxy
  contributors"; Android package is `app.chainproxy`, cert `CN=Chain Proxy`. Third-party credits (GeminiRoute, sing-box, radiance) stay.
- Standard library only (the Windows bootstrap has no pip). tkinter is the only GUI toolkit.
- `.bat`, `.cmd`, `.ps1`: ASCII only + CRLF (`make lint` checks; `.gitattributes` enforces).
  PowerShell must work on Windows PowerShell 5.1.
- Every change to the Windows proxy must stay restorable (`.proxy_state.json` is written once,
  before the first change, and only `sys_proxy_restore()` removes it).
- Listen on 127.0.0.1 only. Never log or print subscription contents or node passwords.
- New config keys: add to `DEFAULTS` in chain.py and the table in docs/DEVELOPER.md.
- Docs are part of the change: update `docs/` when behaviour or options change.
- Do not modify the host's own network/proxy settings. The VM is disposable; the host is not.
- Do not commit/push unless asked. Never read `dev/vm/.ssh/` or `dev/vm/vm.conf` secrets.

## Gotchas
- `subs.txt` holds the user's REAL links: git-ignored, never commit/pack it (`subs.example.txt` is the tracked template; chain.py creates `subs.txt` from it). `make vm-all` overwrites the VM copy with lab links: `make vm-deploy` again before a real-subscription run.
- Lantern: the engine is `dev/lantern/chainlantern/main.go` built INSIDE radiance (`novpn` tag = SOCKS inbound, no TUN/admin/IPC pipe). First hop priority 1, then subscription, then profiles; exit hop: subscription, then profiles (tiers in `App.tier`). The engine zip lives in the `engine-<commit>` GitHub release (pre-release) and its sha256 is pinned in `LANTERN_ENGINE`.
- Window icon: use `iconphoto` ONLY. `iconbitmap` + `iconphoto` together shows the Python logo on Windows 11 (verified by screenshot). Closing the window hides it in the tray (`tray.py`); only the tray's Exit quits. `quit.bat` = off + close the tray window (installer/updater use it).
- Gemini strict check reads the page body: Google can answer 200 with the "not available in your location" app when it places the exit IP in IR (ipinfo may say DE). `google_country()` parses `"XX","ZZ"` from WIZ_global_data (~135 KB in).
- `fetch_nodes` must go through `http_get` (TLS fallback): 1.2.2 only fixed `http_get` and the subscription download still failed on the PC with the old root store.
- Windows crash safety: sing-box runs in a kill-on-close Job Object and `chain.py guard <pid>` restores the proxy if the app dies; test with `Stop-Process -Force` in the VM.
- Unit tests that start a session on Windows touch the REAL registry: register `env.close` FIRST (`addCleanup`) so `app.cleanup()` still finds `.proxy_state.json`.
- Use `make -j1`: unit tests and GUI smoke share ports and must not run in parallel.
- An ssh session in Windows has no visible desktop: GUI work in the VM goes through an
  interactive scheduled task (`Start-Interactive` in dev/vm/guest/common.ps1) and needs a
  logged-on user (bootstrap `--autologon`).
- Processes started inside an ssh session die when it ends; long-running things either stay
  inside one `ps()` call or run as a scheduled task.
- urllib bypasses an explicit proxy for hosts in the Windows ProxyOverride list (127.*, 192.168.*):
  the lab therefore uses the TEST-NET address 198.51.100.10 and `private_direct: false`.
- `chain.py serve` = headless mode (no console input); use it for automation.
- Route labels like `B2:lab-B1` carry the node's POSITION in its list, which changes between
  runs (nodes are ordered by connect time). Tests must match node NAMES (`lab-B1`), never the
  `A1`/`B1` index.
- The VM deploy puts real installers into `offline/`; the unit-test project copy therefore
  ignores `*.zip *.exe *.msi`, otherwise installer tests use the real sing-box zip.
- Test VM facts: libvirt NAT 192.168.122.0/24, host 192.168.122.1; the VM may have a second
  (bridged) NIC - `vm_ip()` prefers the libvirt subnet. Domain account `DOMAIN\user` is
  used as `user@DOMAIN@host` for ssh (OpenSSH rejects the backslash).
- Host firewall: with ufw active the rule `sudo ufw allow in on virbr0` is needed for the lab.
- UEFI VMs refuse internal snapshots; `vmtest.py snapshot` falls back to a disk-only EXTERNAL
  snapshot, which libvirt cannot `snapshot-revert`. Do not use `all --clean` with it.
- The guest agent may refuse `guest-exec` ("Permission denied"); bootstrap then falls back to
  the manual one-liner. The user's shell on the host is fish: no `$?` (use `$status`).
- ssh output from PowerShell is cleaned of CLIXML in `ps()`; keep `$InformationPreference`.
