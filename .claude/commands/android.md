---
description: Check the Android build tools on this host and, if they are fine, continue building the Android app
---
Work on the Android version of Chain Proxy. Answer in Persian, keep code/UI strings/logs in English.
Do not commit, push or release anything unless the user asks.

## 1. Orient (read only)
- `manage_adr(project="home-hadi-projects-chainproxy-win", mode="get")` and read the section "Android app (in progress)".
  If the project is not indexed run `index_repository(repo_path="/home/hadi/projects/chainproxy-win", mode="full")`.
- Read `android/PROGRESS.md` (checklist + log) and `CLAUDE.md`. `git status --short`.

## 2. Verify the tools (one Bash call, report a table)
Use `ANDROID_HOME=${ANDROID_HOME:-$HOME/Android/Sdk}` and source `dev/android/env.sh` if it exists.
Check and print version or MISSING for each:
- `java -version` is 17 (`/usr/lib/jvm/java-17-openjdk`; a newer default JDK is fine only if JAVA_HOME points to 17)
- `$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --list_installed` contains platform-tools, emulator,
  `platforms;android-35`, `build-tools;35.0.0`, `ndk;27.2.12479018`, `system-images;android-35;google_apis;x86_64`
- `adb version`, `emulator -version`, `go version`, `git`, `curl`, `unzip`
- `/dev/kvm` exists and is writable by this user (`id -nG` contains kvm); free disk space (`df -h /home`)
- an AVD named `chainproxy-test` (`emulator -list-avds`); if the image exists but the AVD does not, create it:
  `avdmanager create avd -n chainproxy-test -k "system-images;android-35;google_apis;x86_64" -d pixel_6`
If something is MISSING: do NOT try to install system packages (no sudo here). Tell the user exactly what is
missing and to run `bash dev/android/setup-tools.sh` again (it is safe to re-run), and stop. Tools that can be
installed without sudo (gomobile via `go install`, Gradle wrapper, Go toolchains via GOTOOLCHAIN) you may install.
Never read `dev/vm/.ssh/` or `dev/vm/vm.conf`.

## 3. If everything is OK, continue
- Tick step 0 in `android/PROGRESS.md`, then take the first unchecked step and carry it out following the ADR design
  (libbox + VpnService TUN, Lantern as a separate process, logic rewritten in Kotlin, golden vectors from chain.py).
- Keep `make test` green for the desktop code (`make check` if chain.py/tests were touched).
- Test only on the emulator (start it headless: `emulator -avd chainproxy-test -no-window -no-audio -gpu swiftshader_indirect`,
  wait with `adb wait-for-device` and `getprop sys.boot_completed`; stop it when done). Use the lab at `10.0.2.2`
  (see dev/lab). Say clearly what was and was not verified on the emulator; the user will test the APK on a phone.
- After each finished step: update `android/PROGRESS.md` (checkbox + a dated log line), and when a decision or
  file layout changed update the ADR (`manage_adr set_sections`). Docs are part of the change.
- Build a signed APK into `dist/` only when step 10 is reached (or when the user asks); keystore lives in
  `dev/android/keys/` which must be git-ignored.
- Finish the turn with the usual wrap-up: what works, what was verified on the emulator, what is next.
