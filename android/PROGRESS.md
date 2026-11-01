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
- [ ] 10. Emulator end-to-end test (lab via 10.0.2.2) + real Lantern if the network allows; signed release APK in `dist/`

## Log
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
