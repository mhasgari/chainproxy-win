#!/usr/bin/env python3
"""
Build the end-user zip, or check the Windows-script rules.

    python3 dev/package.py           -> dist/chainproxy-<version>.zip
    python3 dev/package.py --check   -> fail if a Windows script breaks the rules below

Rules for files that Windows runs (.bat .cmd .ps1): ASCII only (PowerShell 5.1 reads BOM-less
files as ANSI) and CRLF line endings (cmd.exe misparses LF-only batch files in edge cases).
The zip always gets CRLF for those files, whatever the working tree has.
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ["Run.bat", "setup.ps1", "chain.py", "gui.py", "config.json", "subs.txt",
           "start.bat", "next.bat", "stop.bat", "chainproxy.ico", "README.md",
           "docs/USER-GUIDE.md", "docs/DEVELOPER.md", "offline/README.txt"]
WIN_SCRIPTS = [".bat", ".cmd", ".ps1"]


def version():
    m = re.search(r'^__version__ = "([^"]+)"', (ROOT / "chain.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "dev"


def windows_scripts():
    for p in ROOT.rglob("*"):
        if p.suffix.lower() in WIN_SCRIPTS and ".git" not in p.parts and "artifacts" not in p.parts:
            yield p


def check():
    bad = []
    for p in windows_scripts():
        data = p.read_bytes()
        rel = p.relative_to(ROOT)
        if any(b > 127 for b in data):
            bad.append(f"{rel}: non-ASCII bytes")
        if re.search(rb"(?<!\r)\n", data):
            bad.append(f"{rel}: LF line endings (want CRLF; see .gitattributes)")
    for b in bad:
        print("FAIL ", b)
    print("windows script rules:", "FAIL" if bad else "ok")
    return 1 if bad else 0


def build():
    out = ROOT / "dist" / f"chainproxy-{version()}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in RELEASE:
            src = ROOT / rel
            data = src.read_bytes()
            if src.suffix.lower() in WIN_SCRIPTS:
                data = re.sub(rb"\r?\n", b"\r\n", data)
            z.writestr(f"chainproxy/{rel}", data)
    print(f"built {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KiB, {len(RELEASE)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else build())
