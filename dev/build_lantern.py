#!/usr/bin/env python3
"""
Build the Lantern engine for Chain Proxy: dist/engine/chainlantern-<commit>-windows-amd64.zip

    python3 dev/build_lantern.py            Windows exe + zip + sha256 (what the app downloads)
    python3 dev/build_lantern.py --linux    also a Linux binary in dev/bin/ (local tests, needs a C compiler)
    python3 dev/build_lantern.py --android  only: android/app/src/main/jniLibs/<abi>/libchainlantern.so for the
                                            Android app (an executable named lib*.so, started by the app; needs the NDK)

The engine is dev/lantern/chainlantern/main.go compiled INSIDE a checkout of github.com/getlantern/radiance
(pinned commit below) with the `novpn` tag: Lantern's own client backend with free-plan servers and a local
SOCKS5/HTTP inbound instead of a TUN device. Needs git and Go; radiance wants the toolchain named in its
go.mod, which Go downloads itself (GOTOOLCHAIN). radiance is GPL-3.0: the zip carries the licence and the
exact source pointers, and the app's THIRD-PARTY-NOTICES.txt names them.

After a rebuild: upload the zip to the `engine-<commit>` GitHub release and put its sha256 into
LANTERN_ENGINE in chain.py (the app refuses a download whose hash differs).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RADIANCE_URL = "https://github.com/getlantern/radiance.git"
RADIANCE_COMMIT = "72fe1e906ee530a9784e9c1337b26d1a198fe73f"        # 2026-10-30
TAGS = "novpn,with_gvisor,with_quic,with_dhcp,with_wireguard,with_utls,with_acme"
WORK = ROOT / "dev" / "cache" / "radiance"
OUT = ROOT / "dist" / "engine"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def checkout():
    if not (WORK / ".git").exists():
        WORK.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--quiet", RADIANCE_URL, str(WORK)])
    run(["git", "-C", str(WORK), "fetch", "--quiet", "origin", RADIANCE_COMMIT])
    run(["git", "-C", str(WORK), "checkout", "--quiet", "--force", RADIANCE_COMMIT])
    run(["git", "-C", str(WORK), "clean", "-fdq", "cmd/chainlantern"])
    dst = WORK / "cmd" / "chainlantern"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "dev" / "lantern" / "chainlantern" / "main.go", dst / "main.go")


def toolchain():
    gomod = (WORK / "go.mod").read_text()
    return "go" + re.search(r"^go (\S+)", gomod, re.M).group(1)


def build(goos, cgo, out):
    env = dict(os.environ, GOTOOLCHAIN=toolchain(), GOOS=goos, GOARCH="amd64", CGO_ENABLED="1" if cgo else "0")
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["go", "build", "-tags", TAGS, "-trimpath", "-ldflags",
         f"-s -w -X github.com/getlantern/radiance/common.Commit={RADIANCE_COMMIT[:7]}",
         "-o", str(out), "./cmd/chainlantern"], cwd=WORK, env=env)


ANDROID_API = 26
ANDROID_ABIS = {"arm64-v8a": ("arm64", "aarch64-linux-android"), "armeabi-v7a": ("arm", "armv7a-linux-androideabi"),
                "x86_64": ("amd64", "x86_64-linux-android")}


def build_android():
    """Engine for the Android app: a Go executable stored as lib*.so (Android only extracts such names)."""
    sdk = Path(os.environ.get("ANDROID_HOME", Path.home() / "Android" / "Sdk"))
    ndks = sorted((sdk / "ndk").glob("*"))
    if not ndks:
        sys.exit(f"no NDK in {sdk}/ndk (run dev/android/setup-tools.sh)")
    # sing-box's auto_detect_interface starts a netlink network monitor, which Android forbids to apps
    # ("netlink socket in Android is banned by Google"); the engine only needs the default route.
    opts = WORK / "vpn" / "boxoptions.go"
    text = opts.read_text()
    if "AutoDetectInterface: true," not in text:
        sys.exit("radiance changed: AutoDetectInterface patch no longer applies")
    opts.write_text(text.replace("AutoDetectInterface: true,", "AutoDetectInterface: false,"))
    bin_dir = ndks[-1] / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    for abi, (goarch, triple) in ANDROID_ABIS.items():
        out = ROOT / "android" / "app" / "src" / "main" / "jniLibs" / abi / "libchainlantern.so"
        out.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, GOTOOLCHAIN=toolchain(), GOOS="android", GOARCH=goarch, CGO_ENABLED="1",
                   CC=str(bin_dir / f"{triple}{ANDROID_API}-clang"), CXX=str(bin_dir / f"{triple}{ANDROID_API}-clang++"),
                   CGO_LDFLAGS="-static-libstdc++")      # no libc++_shared.so next to the executable
        if goarch == "arm":
            env["GOARM"] = "7"
        run(["go", "build", "-tags", TAGS, "-trimpath", "-ldflags",
             f"-s -w -checklinkname=0 -X github.com/getlantern/radiance/common.Commit={RADIANCE_COMMIT[:7]}",
             "-o", str(out), "./cmd/chainlantern"], cwd=WORK, env=env)
        print(f"built {out.relative_to(ROOT)} ({out.stat().st_size // 1024 // 1024} MiB)")


def main():
    checkout()
    if "--android" in sys.argv[1:]:
        build_android()
        return
    short = RADIANCE_COMMIT[:7]
    exe = ROOT / "dev" / "bin" / "chainlantern.exe"
    build("windows", False, exe)                        # no CGO needed on Windows: no C compiler required
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / f"chainlantern-{short}-windows-amd64.zip"
    notes = (f"chainlantern {short} - Lantern client backend for Chain Proxy\n"
             f"Built from https://github.com/getlantern/radiance at commit {RADIANCE_COMMIT}\n"
             f"plus dev/lantern/chainlantern/main.go of the Chain Proxy source tree\n"
             f"Build: go build -tags {TAGS} -trimpath (see dev/build_lantern.py)\n"
             "License: GNU GPL v3 or later (LICENSE). Corresponding source: the two repositories above.\n")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in (("chainlantern.exe", exe.read_bytes()), ("LICENSE", (WORK / "LICENSE").read_bytes()),
                           ("SOURCE.txt", notes.encode())):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))     # fixed time: same bytes every build
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data, compresslevel=9)
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (OUT / (zpath.name + ".sha256")).write_text(f"{digest}  {zpath.name}\n")
    print(f"built {zpath.relative_to(ROOT)} ({zpath.stat().st_size // 1024} KiB)\nsha256 {digest}")
    if "--linux" in sys.argv[1:]:
        build("linux", True, ROOT / "dev" / "bin" / "chainlantern")
        print("built dev/bin/chainlantern (Linux)")


if __name__ == "__main__":
    main()
