#!/usr/bin/env python3
"""Builds libbox.aar (sing-box's Android library: TUN + all protocols) for the Chain Proxy app.

Same recipe as sing-box's own `cmd/internal/build_libbox` (gomobile bind of ./experimental/libbox), but with
only the build tags the app needs, so the AAR stays small. Pinned tag; output: android/app/libs/libbox.aar
(git-ignored). Needs: JDK 17, Android SDK + NDK (dev/android/setup-tools.sh), Go (any; GOTOOLCHAIN pins one).

    python3 dev/android/build_libbox.py [--arch arm64,amd64] [--api 26]
"""
import argparse
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "dev" / "cache"
SINGBOX_TAG = "v1.14.4"
SINGBOX_COMMIT = "c005f35300ce76427dc285481ec5695f5b179cd2"
GOMOBILE = "v0.1.13"
GOTOOLCHAIN = "go1.26.10"          # any recent Go works because of -checklinkname=0 below (as in sing-box)
TAGS = ["with_gvisor", "with_quic", "with_utls", "with_clash_api", "badlinkname", "tfogo_checklinkname0"]
OUT = ROOT / "android" / "app" / "libs" / "libbox.aar"


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="arm64,amd64", help="android ABIs: arm64 (phones), amd64 (emulator)")
    ap.add_argument("--api", type=int, default=26)
    a = ap.parse_args()

    sdk = pathlib.Path(os.environ.get("ANDROID_HOME", pathlib.Path.home() / "Android" / "Sdk"))
    ndks = sorted((sdk / "ndk").glob("*"))
    if not ndks:
        sys.exit(f"no NDK in {sdk}/ndk (run dev/android/setup-tools.sh)")
    ndk = ndks[-1]
    env = dict(os.environ, GOTOOLCHAIN=GOTOOLCHAIN, ANDROID_HOME=str(sdk), ANDROID_NDK_HOME=str(ndk), NDK=str(ndk),
               JAVA_HOME=os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk"))
    gobin = pathlib.Path(subprocess.run(["go", "env", "GOPATH"], capture_output=True, text=True, env=env).stdout.strip()) / "bin"
    env["PATH"] = f"{gobin}:{ndk}/toolchains/llvm/prebuilt/linux-x86_64/bin:{env['PATH']}"

    src = CACHE / "sing-box"
    if not src.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--branch", SINGBOX_TAG, "https://github.com/SagerNet/sing-box.git", str(src)])
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != SINGBOX_COMMIT:
        sys.exit(f"{src} is at {head}, expected {SINGBOX_COMMIT} ({SINGBOX_TAG})")
    for tool in ("gomobile", "gobind"):
        if not (gobin / tool).exists():
            run(["go", "install", f"github.com/sagernet/gomobile/cmd/{tool}@{GOMOBILE}"], env=env)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    targets = ",".join(f"android/{x}" for x in a.arch.split(","))
    run([str(gobin / "gomobile"), "bind", "-v", "-o", str(OUT), "-target", targets, "-androidapi", str(a.api),
         "-javapkg=io.nekohasekai", "-libname=box", "-trimpath", "-buildvcs=false",
         "-ldflags", f"-X github.com/sagernet/sing-box/constant.Version={SINGBOX_TAG[1:]} "
         "-X runtime.godebugDefault=multipathtcp=0,tlssha1=1 -checklinkname=0 -s -w -buildid=", "-tags", ",".join(TAGS), "./experimental/libbox"], cwd=src, env=env)
    print(f"built {OUT} ({OUT.stat().st_size // 1024 // 1024} MiB)")


if __name__ == "__main__":
    main()
