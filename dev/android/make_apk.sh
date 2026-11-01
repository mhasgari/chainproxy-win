#!/usr/bin/env bash
# Builds the signed release APK and copies it (+ sha256) to dist/ChainProxy-<version>.apk.
# Needs: libbox.aar (dev/android/build_libbox.py), jniLibs (python3 dev/build_lantern.py --android),
#        dev/android/keys/keystore.properties (git-ignored; created once with keytool, see docs/ANDROID.md).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
source "$HERE/env.sh"
[ -f "$HERE/keys/keystore.properties" ] || { echo "no signing key: dev/android/keys/keystore.properties" >&2; exit 1; }
(cd "$ROOT/android" && ./gradlew -q :app:assembleRelease)
VERSION=$(sed -n 's/.*versionName = "\(.*\)".*/\1/p' "$ROOT/android/app/build.gradle.kts" | head -1)
mkdir -p "$ROOT/dist"
for abi in arm64-v8a armeabi-v7a x86_64; do
  OUT="$ROOT/dist/ChainProxy-$VERSION-$abi.apk"
  cp "$ROOT/android/app/build/outputs/apk/release/app-$abi-release.apk" "$OUT"
  "$ANDROID_HOME/build-tools/35.0.0/apksigner" verify "$OUT"
  (cd "$ROOT/dist" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
  echo "built $OUT"; cat "$OUT.sha256"
done
