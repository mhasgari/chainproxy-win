# chainproxy — notes for Claude Code

Windows tool that chains two proxy subscriptions (client -> node of list A -> node of list B ->
internet) with sing-box, picks the best route that passes verification, sets the Windows
system proxy, and lets the user rotate routes (GUI, console, `next.bat`). Development happens
on a CachyOS (Arch) host; Windows behaviour is tested in a libvirt VM driven over ssh.

The user writes in Persian. Answer in Persian; keep code, comments, UI strings and log
messages in English (Windows consoles mangle RTL text). End-user and developer docs are
Persian (`docs/`, `dev/README.md`).

## Verified state (last full run on a real Windows 11 VM, 2026-10-28)
`make vm-all`: deploy, install, unit (27), e2e (29 checks, real sing-box, lab logs prove
VM -> A -> B1) and gui all PASS. Real subscriptions were run once by hand in the VM (download, rank, traffic through the chain, abrupt-kill recovery). Not yet verified: Chrome itself, a Windows 10 VM, a clean-machine first run without the `offline/` files.

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
- `/vm-test`, `/check`, `/release` slash commands wrap the above

## When to test where
- Pure Python logic (parsing, ranking, config): `make test`; add a unit test.
- Anything touching sing-box config: also `make e2e-local` (real core on this host).
- Registry / proxy / setup.ps1 / shortcuts / GUI on Windows / paths: `make vm-all` (or the
  relevant stage). These cannot be verified on Linux.
- Never claim Windows behaviour works without a VM run; say what was and was not run.

## Rules
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
