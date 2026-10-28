#!/usr/bin/env python3
"""
Build docs/Chain-Proxy-Quick-Start-fa.pdf from docs/QUICKSTART.md (Persian, right-to-left).
Needs pandoc and chromium / google-chrome on the host (development machine only):

    python3 dev/make_pdf.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "QUICKSTART.md"
OUT = ROOT / "docs" / "Chain-Proxy-Quick-Start-fa.pdf"

CSS = """
@page { size: A4; margin: 16mm 15mm; }
html { direction: rtl; }
body { font-family: 'Vazirmatn', 'Noto Sans Arabic', 'Noto Naskh Arabic', 'DejaVu Sans', sans-serif;
       font-size: 11pt; line-height: 1.75; color: #1b1b1b; text-align: right; }
h1 { font-size: 21pt; border-bottom: 3px solid #1b7f2a; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 14pt; color: #1b7f2a; margin: 18px 0 4px; }
blockquote { margin: 8px 0; padding: 4px 12px; border-right: 4px solid #b36b00; background: #fff7e8; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #c8c8c8; padding: 4px 8px; text-align: right; vertical-align: top; }
th { background: #eef6ef; }
code { direction: ltr; unicode-bidi: embed; font-family: Consolas, 'DejaVu Sans Mono', monospace;
       background: #f1f1f1; padding: 0 4px; border-radius: 3px; font-size: 10pt; }
a { color: #1b5fb3; text-decoration: none; }
li { margin: 2px 0; }
"""


def main():
    pandoc = shutil.which("pandoc")
    chrome = next((shutil.which(c) for c in ("chromium", "google-chrome-stable", "google-chrome", "chrome")
                   if shutil.which(c)), None)
    if not pandoc or not chrome:
        sys.exit("pandoc and chromium (or google-chrome) are required")
    with tempfile.TemporaryDirectory() as d:
        html = Path(d) / "q.html"
        body = subprocess.run([pandoc, "-f", "gfm", "-t", "html", str(SRC)], capture_output=True,
                              text=True, check=True).stdout
        html.write_text(f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
                        f"<title>Chain Proxy</title><style>{CSS}</style></head><body>{body}</body></html>",
                        encoding="utf-8")
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={d}/profile", f"--print-to-pdf={OUT}", html.as_uri()],
                       check=True, capture_output=True, timeout=120)
    print(f"built {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
