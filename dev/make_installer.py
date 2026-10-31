#!/usr/bin/env python3
"""
Build dist/ChainProxy-Setup-<version>.exe (Inno Setup) in the Windows test VM.

    python3 dev/make_installer.py          -> dist/ChainProxy-Setup-<ver>.exe  (downloads Python/sing-box on first run)
    python3 dev/make_installer.py --full   -> dist/ChainProxy-Setup-Full-<ver>.exe (Python and sing-box inside)
    python3 dev/make_installer.py --fake-version 9.9.9   -> dist/test-update/ (the "newer release" of `vmtest.py update`)

--full takes the files from dev/vm/cache (make vm-fetch: version and signature/hash checked).

Needs the VM (see dev/README.md). Inno Setup 6 is downloaded into the VM when it is missing
(official GitHub release, installed only if its Authenticode signature is valid; `make vm-clean`
removes it again). The installer itself is unsigned: SmartScreen warns on it.
"""
import io
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "vm"))
import package   # noqa: E402
import vmtest    # noqa: E402

INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
WORK = "chainproxy-installer"        # under the VM user's home


def main():
    full = "--full" in sys.argv[1:]
    fake = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--fake-version"), None)
    ver = fake or package.version()
    with tempfile.TemporaryDirectory() as d:
        stage = Path(d) / "stage"
        package.stage(stage)
        if fake:                       # a "newer release" for the updater test: only the staged copy changes
            src = (stage / "chain.py").read_text(encoding="utf-8")
            (stage / "chain.py").write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{fake}"', src, 1),
                                            encoding="utf-8", newline="\n")
        if full:
            for pattern in (f"python-{vmtest.CONF['PY_VERSION']}-amd64.exe", "sing-box-*-windows-amd64.zip"):
                f = vmtest.cached(pattern)
                if not f:
                    sys.exit(f"{pattern} is not in dev/vm/cache: run `make vm-fetch` first")
                shutil.copy(f, stage / "offline" / f.name)
            engine = sorted((ROOT / "dist" / "engine").glob("chainlantern-*-windows-amd64.zip"))
            if not engine:
                sys.exit("no Lantern engine in dist/engine/: run `python3 dev/build_lantern.py` first")
            shutil.copy(engine[-1], stage / "offline" / engine[-1].name)
            shutil.copy(ROOT / "installer" / "THIRD-PARTY-NOTICES.txt", stage / "THIRD-PARTY-NOTICES.txt")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(stage, arcname="stage")
            tar.add(ROOT / "installer" / "chainproxy.iss", arcname="chainproxy.iss")
        tgz = Path(d) / "installer.tar.gz"
        tgz.write_bytes(buf.getvalue())
        vmtest.scp_to(tgz, f"{WORK}.tar.gz")
    rc, out = vmtest.ps(f'''
$ErrorActionPreference = "Stop"
$iscc = "$env:LOCALAPPDATA\\Programs\\Inno Setup 6\\ISCC.exe"
if (-not (Test-Path $iscc)) {{
    $f = "$env:TEMP\\innosetup.exe"
    Invoke-WebRequest -UseBasicParsing "{INNO_URL}" -OutFile $f
    $sig = Get-AuthenticodeSignature $f
    if ($sig.Status -ne "Valid") {{ throw "Inno Setup download has no valid signature ($($sig.Status))" }}
    Start-Process $f -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/CURRENTUSER" -Wait
    if (-not (Test-Path $iscc)) {{ throw "Inno Setup did not install" }}
}}
$w = "$HOME\\{WORK}"
if (Test-Path $w) {{ Remove-Item -Recurse -Force $w }}
New-Item -ItemType Directory -Force $w | Out-Null
tar -xzf "$HOME\\{WORK}.tar.gz" -C $w
Remove-Item "$HOME\\{WORK}.tar.gz"
& $iscc "/DAppVersion={ver}" {"/DFull=1" if full else ""} "/DStageDir=$w\\stage" "/O$w\\output" "$w\\chainproxy.iss"
if ($LASTEXITCODE -ne 0) {{ throw "ISCC failed ($LASTEXITCODE)" }}
Get-ChildItem "$w\\output" | ForEach-Object {{ $_.Name + " " + $_.Length }}
''', timeout=600)
    print(out.strip())
    if rc != 0:
        sys.exit("installer build failed")
    name = f"ChainProxy-Setup-Full-{ver}.exe" if full else f"ChainProxy-Setup-{ver}.exe"
    dest = ROOT / "dist" / ("test-update" if fake else "") / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not vmtest.scp_from(f"{WORK}/output/{name}", dest):
        sys.exit("could not copy the installer back from the VM")
    print(f"built {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
