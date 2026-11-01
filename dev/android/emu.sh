#!/usr/bin/env bash
# Headless emulator helper:  dev/android/emu.sh start | stop | shot <file.png> | status
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"
AVD="${AVD:-chainproxy-test}"
LOG="${TMPDIR:-/tmp}/chainproxy-emulator.log"
case "${1:-status}" in
  start)
    if adb devices | grep -q "^emulator-"; then echo "already running"; exit 0; fi
    nohup emulator -avd "$AVD" -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot -netdelay none -netspeed full \
      >"$LOG" 2>&1 &
    adb wait-for-device
    for _ in $(seq 1 120); do
      [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && { echo "booted"; exit 0; }
      sleep 2
    done
    echo "emulator did not boot, see $LOG"; exit 1 ;;
  stop) adb emu kill 2>/dev/null || true ;;
  shot) adb exec-out screencap -p >"${2:?file.png}" ;;
  status) adb devices ;;
esac
