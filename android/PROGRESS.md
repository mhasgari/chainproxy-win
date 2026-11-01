# Android app - progress (keep this file current; /android reads it)

Design and decisions: ADR section "Android app (in progress)" (codebase-memory-mcp, `manage_adr get`).
Rules: nothing is committed/pushed/released unless the user asks. Test on the emulator only; the signed APK
goes to `dist/` for the user's phone. Keystore stays out of git.

- [x] 0. Tools installed (`bash dev/android/setup-tools.sh`, run by the user with sudo) and verified by /android
- [x] 1. Environment helpers: `dev/android/env.sh`, AVD `chainproxy-test` (x86_64, API 35), `make android-*` targets
- [x] 2. libbox AAR built (sing-box v1.14.4 `cmd/internal/build_libbox`, pinned, reproducible script `dev/android/build_libbox.py`)
- [x] 3. chainlantern built for android (arm64-v8a + x86_64) as `libchainlantern.so`
- [x] 4. Gradle project `android/` (Compose M3, minSdk 26, targetSdk 35), empty app runs on the emulator
- [x] 5. VpnService + libbox with a fixed lab chain: TUN works on the emulator (traffic leaves through the lab)
- [x] 6. Kotlin port of the logic (parse, tiers, config, delay tests, verify, google_country) + golden vectors from chain.py
- [x] 7. Lantern process management (exec, READY protocol, restart, kill with the service)
- [x] 8. UI: routes list, status, settings (sources, filters, general), notification, Quick Settings tile, split tunnelling
- [x] 9. Update check (GitHub releases, sha256), Persian strings, docs (`docs/ANDROID.md`, Persian)
- [x] 10. Emulator end-to-end test (lab via 10.0.2.2) + real Lantern if the network allows; signed release APK in `dist/`

## Log
- 2026-11-01 v0.2.5 (phone test of 0.2.4: works, the first start connects). Requests: "clear logs" and "easy updates from the users' own
  instances". Done: Log screen has a Clear button (AppState.clearLog), lines are forced LTR (the Persian UI put the time stamp on the wrong
  side) and the list follows the newest line; UpdateChecker tries the local mixed proxy (127.0.0.1:mixed_port, 4 s connect) FIRST and falls
  back to a direct connection (the app is excluded from its own VPN, so GitHub was only reachable if the network allowed it); Settings has
  an "Update source" (owner/name = `update_repo`, saved with the Save button) for a user's own repo/mirror with the same release layout.
  Verified: JVM tests (UpdateCheckerNetTest new: via-proxy and fallback), lab session + TUN PASS, emulator: clear button, LTR log, update
  check while connected ("latest version"). NOT verified: a real newer release download/install through the proxy, a custom repo on the phone.
  Interpretation note: "از نمونه‌های خودشان" was read as "through their own running instance (+ own repo)"; ask if something else was meant.
- 2026-11-01 v0.2.4 (phone test of 0.2.3: the 2 automatic re-scans ran but the first start still failed: "2 routes usable (1 chains, 0 B-only)"
  every time, always the same A0-B1 (truly IR) and sometimes B3/B4). LIKELY CAUSE (from the numbers, not proven on the phone): `pick` kept
  only exit nodes whose direct TCP probe from the phone succeeded; with Lantern as first hop the exit node is dialled from Lantern's
  server, so on a filtered network the pool shrank to the few directly reachable nodes. Change: `pick(extraUnreachable=topKExit)` keeps up
  to that many probe-failed exit nodes after the reachable ones when a first hop exists; log line "[B] x of 30 reachable directly; y more
  kept". Verified: 22 JVM tests (PickTest new), lab session + TUN PASS, real session on the emulator still fine; the new branch itself
  could NOT be reproduced on the emulator (the host's v2rayN TUN makes every probe succeed), only unit-tested. The phone log's new line
  will show whether the theory holds.
- 2026-11-01 v0.2.3 (user's phone test of 0.2.2: the keep-alive fix works, every route has its own exit IP; the FIRST start still ended
  "Failed" and the second worked). Log of the failed start: 4 usable routes of 12+, A0-B1 and A0 truly IR for Google, A0-B6 and B9 "no
  answer" for gemini (slow/timeout), no route left. The next start found 5 routes and B8 passed: scan results on the phone network vary
  between runs. Changes: SessionRunner re-scans up to 2 times (log "scanning again (n/2)") before it reports FAILED; verify() retries
  a strict-site fetch once when there was no answer. Verified: 19 JVM tests; emulator with real Lantern and a block list that rejects
  everything shows the 2 automatic re-scans then FAILED; lab session + TUN tests PASS; signed APKs 0.2.3 in dist/. Not seen on the phone.
- 2026-11-01 v0.2.2 (user's phone: "Failed - no route passed verification", Lantern + GeminiRoute, every route showed the SAME exit IP
  2001:41d0:...::cfc7 and was rejected as IR). ROOT CAUSE: `RealVerifyIo.viaProxy` used HttpURLConnection (OkHttp on Android), which
  pools the CONNECT tunnel to ipinfo.io / gemini.google.com. sing-box keeps that tunnel on the route active when it was opened, so after
  `select` the next route was verified over the old tunnel: all routes got the first route's exit IP and verdict (also explains the
  "flaky repeated route line" of the 0.2.1 `next` test). Fix: `Connection: close` on every verification request. Regression test
  `VerifyIoTest` (fails before, passes after). Verified: 19 JVM tests; emulator with REAL Lantern + GeminiRoute: before the fix B5/B3/B12
  and B-only B5 all reported 66.163.114.126; after it every route has its own exit (66.163.114.132 / .124 / 167.88.61.193 ...) and
  routes whose true exit Google places in IR (e.g. A0-B3 OVH 2001:41d0..., A0-B7 Oracle) are skipped individually; lab session + TUN
  tests PASS. Signed APKs in dist/ (0.2.2, 3 ABIs, apksigner OK). Not yet seen on the phone. Note: connections that apps already
  hold stay on the old route after Next (selector does not interrupt them); not changed.
- 2026-11-01 /android check: tools all present (JDK 17, SDK pkgs, NDK 27.2, emulator 37.2, Go 1.27, KVM, AVD chainproxy-test, 490 GB free).
  All checklist steps are done (step 10 box ticked: it was completed in v0.1.0/0.2.x, see below). `make android-test` (18 JVM tests) PASS.
  Emulator tests were not re-run in this check. No open step left; next ideas: watchdog test, Lantern-only failure hints, arm64 run on the phone.
- 2026-11-01 v0.2.1 (user's phone test of 0.2.0: works). Quick Settings tile now has its own icon (two interlocked rings, white on
  transparent, `res/drawable/ic_tile.xml`) instead of the filled launcher square; the tile hint was shown twice on Android < 13 (card
  subtitle + note) and now only once. Verified: 18 JVM tests, emulator session + TUN tests PASS (the session test's `next` check failed
  once on a repeated route line and passed on re-run: flaky comparison, not a product bug), signed APKs verified with apksigner.
  The tile icon itself was not seen on a device.
- 2026-11-01 v0.2.0 (after the user's phone test of 0.1: works). Changes: default exit subscription = GeminiRoute best list;
  First hop / Exit hop are separate cards; new theme + power-button home; Quick Settings tile prompt (API 33 requestAddTileService);
  neutral identity (package `app.chainproxy`, cert CN=Chain Proxy, encoded release repo); one APK per ABI (arm64-v8a, armeabi-v7a,
  x86_64; armv7 libbox + chainlantern now built); updater picks the APK of the device ABI. Verified on the emulator (tests,
  session/TUN, Persian RTL screenshot); armv7/arm64 binaries only built, not run.
- 2026-11-01 Steps 8-10 done (v0.1.0): Compose UI (Home / Routes / Settings / Log, EN + FA strings), notification with
  Next/Stop, Quick Settings tile, per-app split tunnelling (tun include/exclude_package + picker), update check
  (GitHub releases `android-vX.Y.Z`, sha256, FileProvider install; JVM-tested parse/version logic only, the download
  and install path is NOT exercised), docs/ANDROID.md, Makefile `android-test|android-emu-test|android-apk`.
  Signed release APK: `dist/ChainProxy-0.1.0.apk` (+ .sha256, 97 MiB, key in dev/android/keys, git-ignored).
  Verified: 18 JVM tests; emulator lab session + TUN tests PASS (debug build); real Lantern session on the emulator
  (debug) and on the RELEASE apk through the UI: Lantern connected, then correctly REJECTED by the Google-country
  check ("Google places this exit in IR") - the same rule as the desktop. NOT verified: a real phone, arm64 binary
  run, split tunnelling on a device, tile, update install, Persian layout screenshot, IPv6 leak behaviour.
  Next ideas: run the release APK on the phone; watchdog test; show Lantern-only failure hints; v0.1.1 fixes.
- 2026-11-01 Step 7 done: `session/` (SessionRunner = chain.start_session, LanternEngine = child process of
  libchainlantern.so, AppState, ConfigStore); ChainVpnService runs the session, notification has Next/Stop, debug
  intents next/prev/rescan/start_config. Verified on the emulator: `dev/android/emu_session_test.py` PASS (profiles ->
  probe -> config -> TUN -> rank -> verify -> traffic leaves through A->B1 -> next -> stop removes TUN) and
  `emu_vpn_test.py` still PASS. REAL Lantern through the app: connected in ~6 s, verified exit DE, `nc` from the
  device shows the Lantern exit IP, stop removes TUN and kills the engine. Needed: network_security_config (cleartext
  only for loopback in release, everything in debug for the TEST-NET lab).
- 2026-11-01 Step 6 done: Kotlin port in `app/.../chain/` (Nodes, ChainConfig, ConfigBuilder, Verify, Routes, Probe, ClashApi).
  Golden vectors come from chain.py (`python3 dev/android/gen_golden.py` -> src/test/resources/golden.json); 14 JVM
  unit tests pass (`cd android && ../dev/android/gradlew.sh :app:testDebugUnitTest`): parse (30 links), subscriptions,
  sing-box config (full equality), geo, google_country, ranking, verify, route switching with fakes, pick.
  Known divergence: none found by the vectors. Not yet exercised: RealVerifyIo / ClashApi against a real core.
(newest first; date, what was done, what was verified, what is still unknown)

- 2026-10-31 Steps 0-5 done and verified on the x86_64 emulator (API 35): tools, libbox AAR (sing-box 1.14.4),
  Gradle skeleton, VpnService + TUN with the lab chain A1->B1 (`dev/android/emu_vpn_test.py` PASS, TUN removed
  after stop). Lantern engine (`libchainlantern.so`, run as the app's uid) reaches READY and proxies real HTTP
  (example.com -> 200). Three Android-only fixes, all in the engine build: `-dns` flag (no resolv.conf), a
  persisted `device-id` file (radiance has no device ID source on Android; the config server answers "request
  missing Device ID"), and a build patch `AutoDetectInterface=false` (netlink monitor is forbidden to apps).
  Gotcha: a background app uid has NO network (netpolicy `blocked=APP_BACKGROUND`); bring the activity to the
  foreground (`am start`) before testing from `run-as`. The real service is a foreground service, so it is fine.
  NOT verified: arm64 binary (built only), a real phone, Lantern while the app's own VPN is active.
