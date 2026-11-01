#!/usr/bin/env bash
# Runs Gradle for the Android project with the right JDK; uses the wrapper in android/ (created by `make android-wrapper`).
# Usage: dev/android/gradlew.sh :app:assembleDebug
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/env.sh"
cd "$HERE/../../android"
exec ./gradlew --console=plain "$@"
