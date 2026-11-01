#!/usr/bin/env bash
# Installs everything needed to build and test the Android app of Chain Proxy on Arch/CachyOS.
#   1) system packages with sudo (JDK 17, emulator runtime libraries)
#   2) the Android SDK, NDK and an emulator image in ~/Android/Sdk (no sudo)
# Safe to run again: what is already installed is skipped.
set -euo pipefail

SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
CMDLINE_SHA256="2d2d50857e4eb553af5a6dc3ad507a17adf43d115264b1afc116f95c92e5e258"   # sha256 of that zip (computed when this script was written)
NDK="ndk;27.2.12479018"
IMAGE="system-images;android-35;google_apis;x86_64"

echo "== 1/3 system packages (sudo) =="
sudo pacman -S --needed --noconfirm jdk17-openjdk libpulse nss libxkbcommon-x11 xcb-util-cursor mesa unzip
sudo archlinux-java set java-17-openjdk 2>/dev/null || true   # JDK 17 is what the Android Gradle plugin wants
if ! id -nG | tr ' ' '\n' | grep -qx kvm; then
  echo "NOTE: you are not in the 'kvm' group; the emulator will be slow. Fix: sudo usermod -aG kvm $USER  (then log in again)"
fi

echo "== 2/3 Android command-line tools in $SDK =="
mkdir -p "$SDK/cmdline-tools"
if [ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  tmp="$(mktemp -d)"
  curl -fL "$CMDLINE_URL" -o "$tmp/cmdline.zip"
  echo "$CMDLINE_SHA256  $tmp/cmdline.zip" | sha256sum -c -
  unzip -q "$tmp/cmdline.zip" -d "$tmp"
  rm -rf "$SDK/cmdline-tools/latest"
  mv "$tmp/cmdline-tools" "$SDK/cmdline-tools/latest"
  rm -rf "$tmp"
fi

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk}"
SM="$SDK/cmdline-tools/latest/bin/sdkmanager"
echo "== 3/3 SDK packages (running this script means you accept the Android SDK licenses) =="
set +o pipefail                       # 'yes' ends with SIGPIPE when sdkmanager stops reading
yes | "$SM" --sdk_root="$SDK" --licenses >/dev/null
yes | "$SM" --sdk_root="$SDK" "platform-tools" "emulator" "platforms;android-35" "build-tools;35.0.0" "$NDK" "$IMAGE"
set -o pipefail
test -x "$SDK/platform-tools/adb" && test -x "$SDK/emulator/emulator" && test -d "$SDK/ndk/27.2.12479018" \
  && test -d "$SDK/system-images/android-35/google_apis/x86_64" || { echo "SDK install is incomplete"; exit 1; }

echo "== environment =="
cat <<ENV
Add to ~/.config/fish/config.fish (fish) or your shell profile:
  set -gx ANDROID_HOME $SDK
  set -gx JAVA_HOME /usr/lib/jvm/java-17-openjdk
  fish_add_path $SDK/platform-tools $SDK/emulator $SDK/cmdline-tools/latest/bin
ENV
echo "Done. Tell Claude: tools installed."
