#!/usr/bin/env python3
"""
Build dist/ChainProxy-Setup-<version>.exe (Inno Setup) in the Windows test VM.

    python3 dev/make_installer.py

Needs the VM (see dev/README.md) with Inno Setup 6 installed for the test user
(https://github.com/jrsoftware/issrc/releases, `innosetup-6.x.exe /VERYSILENT /CURRENTUSER`;
verify its Authenticode signature first). The installer is unsigned: SmartScreen warns on it.
"""
import io
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

WORK = "chainproxy-installer"        # under the VM user's home


def main():
    ver = package.version()
    with tempfile.TemporaryDirectory() as d:
        stage = Path(d) / "stage"
        package.stage(stage)
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
if (-not (Test-Path $iscc)) {{ throw "Inno Setup 6 is not installed in the VM (see dev/make_installer.py)" }}
$w = "$HOME\\{WORK}"
if (Test-Path $w) {{ Remove-Item -Recurse -Force $w }}
New-Item -ItemType Directory -Force $w | Out-Null
tar -xzf "$HOME\\{WORK}.tar.gz" -C $w
Remove-Item "$HOME\\{WORK}.tar.gz"
& $iscc "/DAppVersion={ver}" "/DStageDir=$w\\stage" "/O$w\\output" "$w\\chainproxy.iss"
if ($LASTEXITCODE -ne 0) {{ throw "ISCC failed ($LASTEXITCODE)" }}
Get-ChildItem "$w\\output" | ForEach-Object {{ $_.Name + " " + $_.Length }}
''', timeout=600)
    print(out.strip())
    if rc != 0:
        sys.exit("installer build failed")
    name = f"ChainProxy-Setup-{ver}.exe"
    dest = ROOT / "dist" / name
    dest.parent.mkdir(exist_ok=True)
    if not vmtest.scp_from(f"{WORK}/output/{name}", dest):
        sys.exit("could not copy the installer back from the VM")
    print(f"built {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
