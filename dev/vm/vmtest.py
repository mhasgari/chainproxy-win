#!/usr/bin/env python3
"""
vmtest - drive the Windows test VM (libvirt / virt-manager) from the Linux host.

Transport: OpenSSH into the VM with a dedicated key (set up once by `bootstrap`).
Every guest command runs as `powershell -EncodedCommand`, so quoting never breaks.

    vmtest.py doctor               check host, libvirt, VM, ssh, firewall, cache
    vmtest.py fetch                download installers into dev/vm/cache (python, sing-box, OpenSSH)
    vmtest.py bootstrap [--autologon] [--manual]
                                   one-time: OpenSSH + key inside the VM (guest agent or one-liner)
    vmtest.py snapshot [NAME]      snapshot the prepared VM (default: SNAPSHOT from vm.conf)
    vmtest.py revert [NAME]        go back to it
    vmtest.py deploy [--online]    copy the project (+ cached installers in offline\\) into the VM
    vmtest.py install              first-run path: setup.ps1 (Python, sing-box, shortcuts)
    vmtest.py unit                 tests/run_tests.py on Windows
    vmtest.py e2e                  real sing-box chain against the host lab, registry checks
    vmtest.py gui                  GUI on the real desktop + screenshots (needs a logged-on user)
    vmtest.py all [--clean] [--online] [--skip-gui]
                                   (revert) deploy install unit e2e gui, summary + artifacts
    vmtest.py shell                interactive ssh session
    vmtest.py ps "<PowerShell>"    run one PowerShell command in the VM
    vmtest.py screenshot           save the VM screen to dev/artifacts
    vmtest.py pull-logs            copy runtime logs from the VM to dev/artifacts

Settings: dev/vm/vm.conf (copy vm.conf.example). Any key can be overridden by an environment
variable of the same name, e.g.  VM_NAME=win10 make vm-all
"""
import argparse
import base64
import getpass
import http.server
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zlib
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VMDIR = ROOT / "dev" / "vm"
GUEST = VMDIR / "guest"
CACHE = VMDIR / "cache"
SSHDIR = VMDIR / ".ssh"
ARTROOT = ROOT / "dev" / "artifacts"
sys.path.insert(0, str(ROOT / "dev" / "lab"))

DEFAULTS = {
    "LIBVIRT_URI": "qemu:///system",
    "VM_NAME": "",
    "WIN_USER": "",
    "VM_IP": "",
    "HOST_IP": "",
    "LIBVIRT_NET": "default",
    "SNAPSHOT": "chainproxy-clean",
    "SSH_KEY": "dev/vm/.ssh/id_ed25519",
    "REMOTE_DIR": "chainproxy-test",
    "LAB_PORT": "18080",
    "NODE_PORT_BASE": "18101",
    "BOOT_PORT": "18765",
    "PY_VERSION": "3.12.10",
    "BOOT_TIMEOUT": "2400",
}
EXCLUDE_DIRS = {".git", "__pycache__", "cache", "runtime", "core", "dist", "artifacts", ".ssh",
                ".pytest_cache", ".venv", "bin"}
EXCLUDE_FILES = {".proxy_state.json", ".shortcuts_done", "vm.conf"}

C = {"g": "\033[32m", "r": "\033[31m", "y": "\033[33m", "b": "\033[1m", "0": "\033[0m"}
if not sys.stdout.isatty():
    C = {k: "" for k in C}


def say(msg, color="b"):
    print(f"{C[color]}{msg}{C['0']}", flush=True)


def die(msg):
    say(f"error: {msg}", "r")
    sys.exit(2)


# ------------------------------------------------------------------ config
def load_conf():
    conf = dict(DEFAULTS)
    path = VMDIR / "vm.conf"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
    for k in list(conf):
        if os.environ.get(k):
            conf[k] = os.environ[k]
    key = Path(conf["SSH_KEY"]).expanduser()
    conf["SSH_KEY"] = str(key if key.is_absolute() else ROOT / key)
    return conf


CONF = load_conf()


def need(*keys):
    missing = [k for k in keys if not CONF.get(k)]
    if missing:
        die(f"set {', '.join(missing)} in dev/vm/vm.conf (see vm.conf.example)")


# ------------------------------------------------------------------ process helpers
def run(cmd, check=True, timeout=None, input=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input)
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        if check:
            die(f"timed out: {' '.join(cmd[:4])} ...")
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")
    if check and r.returncode != 0:
        die(f"{' '.join(cmd[:6])} failed:\n{r.stdout}{r.stderr}")
    return r


def virsh(*args, check=True, timeout=60):
    return run(["virsh", "-c", CONF["LIBVIRT_URI"], *args], check=check, timeout=timeout)


# ------------------------------------------------------------------ VM state / addresses
def vm_state():
    r = virsh("domstate", CONF["VM_NAME"], check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def vm_start():
    st = vm_state()
    if st is None:
        die(f"libvirt domain '{CONF['VM_NAME']}' not found (virsh -c {CONF['LIBVIRT_URI']} list --all)")
    if st != "running":
        say(f"starting VM {CONF['VM_NAME']} ({st}) ...")
        virsh("start", CONF["VM_NAME"])


def parse_domifaddr(text, prefer=None):
    """First usable IPv4 in `virsh domifaddr` output. A VM with several NICs (e.g. the libvirt
    network plus a bridged one) lists several: `prefer` is a prefix like '192.168.122.' and wins."""
    found = []
    for line in text.splitlines():
        m = re.search(r"\bipv4\s+(\d+\.\d+\.\d+\.\d+)/\d+", line)
        if m and not m.group(1).startswith(("127.", "169.254.")):
            found.append(m.group(1))
    if prefer:
        for ip in found:
            if ip.startswith(prefer):
                return ip
    return found[0] if found else None


def _net_prefix():
    """'192.168.122.' for the libvirt network, or None when it cannot be read."""
    try:
        r = virsh("net-dumpxml", CONF["LIBVIRT_NET"], check=False)
        m = re.search(r"<ip\b[^>]*\baddress=['\"](\d+\.\d+\.\d+)\.\d+['\"]", r.stdout or "")
        return m.group(1) + "." if m else None
    except Exception:
        return None


def vm_ip(wait=0):
    """The VM's address ON THE LIBVIRT NETWORK (the host can reach the lab only there)."""
    if CONF["VM_IP"]:
        return CONF["VM_IP"]
    prefix = _net_prefix()
    deadline = time.time() + wait
    while True:
        best = None
        for src in ("lease", "agent", "arp"):
            r = virsh("domifaddr", CONF["VM_NAME"], "--source", src, check=False, timeout=15)
            ip = parse_domifaddr(r.stdout, prefix) if r.returncode == 0 else None
            if ip and (not prefix or ip.startswith(prefix)):
                return ip
            best = best or ip
        if time.time() >= deadline:
            return best
        time.sleep(3)


def host_ip():
    if CONF["HOST_IP"]:
        return CONF["HOST_IP"]
    r = virsh("net-dumpxml", CONF["LIBVIRT_NET"], check=False)
    m = re.search(r"<ip\b[^>]*\baddress=['\"](\d+\.\d+\.\d+\.\d+)['\"]", r.stdout or "")
    if not m:
        die(f"cannot read the host address of libvirt network '{CONF['LIBVIRT_NET']}'; set HOST_IP in vm.conf")
    return m.group(1)


def agent_ok():
    r = virsh("qemu-agent-command", CONF["VM_NAME"], '{"execute":"guest-ping"}', "--timeout", "5",
              check=False, timeout=15)
    return r.returncode == 0 and '"return"' in r.stdout


# ------------------------------------------------------------------ ssh
def ssh_opts():
    SSHDIR.mkdir(parents=True, exist_ok=True)
    return ["-i", CONF["SSH_KEY"], "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={SSHDIR / 'known_hosts'}",
            "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "-o", "LogLevel=ERROR"]


_IP = None


def ssh_user():
    """OpenSSH clients (9.6+) reject a backslash in the user name, so DOMAIN\\user becomes the
    form Windows sshd also accepts: user@DOMAIN (the full target is then user@DOMAIN@host)."""
    u = CONF["WIN_USER"]
    if "\\" in u:
        dom, name = u.split("\\", 1)
        return f"{name}@{dom}"
    return u


def target():
    global _IP
    if not _IP:
        _IP = vm_ip(wait=120)
        if not _IP:
            die("cannot find the VM's IP address (is it running? set VM_IP in vm.conf)")
    return f"{ssh_user()}@{_IP}"


def tcp_open(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def ssh_ok():
    r = run(["ssh", *ssh_opts(), target(), "echo chainproxy-ok"], check=False, timeout=30)
    return "chainproxy-ok" in r.stdout


def wait_ssh(timeout=300):
    global _IP
    deadline = time.time() + timeout
    while time.time() < deadline:
        _IP = vm_ip(wait=0) or _IP
        if _IP and tcp_open(_IP, 22) and ssh_ok():
            return True
        time.sleep(4)
    return False


def encode_ps(script):
    prefix = "$ProgressPreference='SilentlyContinue'; $ErrorActionPreference='Continue';\n"
    return base64.b64encode((prefix + script).encode("utf-16-le")).decode()


def remote_dir():
    return f"$HOME\\{CONF['REMOTE_DIR']}"


def clean_clixml(text):
    """Remove PowerShell's serialized-stream XML from ssh output, keeping error messages."""
    def errors(m):
        # error records AND Write-Host text (PowerShell serializes late host output as
        # InformationRecords too: dropping them lost the last PASS lines of a stage)
        found = re.findall(r'<S S="Error">(.*?)</S>|<Obj S="information"[^>]*>.*?<S N="Message">(.*?)</S>',
                           m.group(0), re.S)
        msgs = []
        for err, info in found:
            msgs.append(err if err else info + "\n")
        msgs = [x.replace("_x000D__x000A_", "\n").replace("&lt;", "<").replace("&gt;", ">")
                 .replace("&quot;", '"').replace("&amp;", "&") for x in msgs]
        return "".join(msgs)
    text = re.sub(r"<Objs\b.*?</Objs>", errors, text, flags=re.S)
    return "\n".join(l for l in text.split("\n") if not l.startswith("#< CLIXML"))


def ps(script, check=False, timeout=None, stream=False, log=None):
    """Run PowerShell in the VM. Returns (exit code, output)."""
    # no serialized InformationRecords (CLIXML) on stderr for every Write-Host: the text itself
    # still reaches stdout
    script = "$InformationPreference = 'SilentlyContinue'; $ProgressPreference = 'SilentlyContinue'\n" + script
    enc = encode_ps(script)
    if len(enc) > 7500:                    # cmd.exe line limit: ship the script as a file
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:
            f.write(script)
        name = f"vmtest-{os.getpid()}-{int(time.time())}.ps1"
        scp_to(f.name, name)
        os.unlink(f.name)
        enc = encode_ps(f"& \"$HOME\\{name}\"; $rc=$LASTEXITCODE; Remove-Item \"$HOME\\{name}\"; exit $rc")
    cmd = ["ssh", *ssh_opts(), target(),
           f"powershell -NoProfile -NonInteractive -OutputFormat Text -ExecutionPolicy Bypass -EncodedCommand {enc}"]
    if not stream:
        r = run(cmd, check=False, timeout=timeout)
        out = (r.stdout + r.stderr).replace("\r\n", "\n")
        out = clean_clixml(out)
        if check and r.returncode != 0:
            die(f"remote command failed ({r.returncode}):\n{out}")
        return r.returncode, out
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    buf = []
    lf = open(log, "a", encoding="utf-8") if log else None
    start = time.time()
    pending = ""                                # an <Objs> block that is still open
    try:
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").replace("\r", "")
            if pending or "<Objs" in line:
                pending += line
                if "</Objs>" not in pending:
                    continue
                line, pending = clean_clixml(pending), ""
                if not line.strip():
                    continue
                line = line if line.endswith("\n") else line + "\n"
            elif line.startswith("#< CLIXML"):
                continue
            buf.append(line)
            color = "g" if line.startswith("PASS") else "r" if line.startswith("FAIL") else None
            sys.stdout.write(f"{C[color]}{line}{C['0']}" if color else line)
            sys.stdout.flush()
            if lf:
                lf.write(line)
            if timeout and time.time() - start > timeout:
                p.kill()
                buf.append("FAIL  timed out\n")
                break
        rc = p.wait()
    finally:
        if lf:
            lf.close()
    if check and rc != 0:
        die(f"remote command failed ({rc})")
    return rc, "".join(buf)


def scp_to(local, remote_rel):
    run(["scp", "-q", *ssh_opts(), str(local), f"{target()}:{remote_rel}"], timeout=600)


def scp_from(remote_rel, local):
    r = run(["scp", "-q", *ssh_opts(), f"{target()}:{remote_rel}", str(local)], check=False, timeout=120)
    return r.returncode == 0


def guest_prelude():
    rd = remote_dir()
    return (f'$Root = "{rd}"; $Repo = "{rd}\\repo"; '
            f'. "$Repo\\dev\\vm\\guest\\common.ps1"; $py = Find-Python\n')


def require_python():
    rc, out = ps(guest_prelude() + 'if ($py) { $py; exit 0 } else { exit 3 }')
    if rc != 0:
        die("Python is not installed in the VM yet: run `vmtest.py install` first")
    return out.strip().splitlines()[-1]


# ------------------------------------------------------------------ artifacts / screenshots
_ART = None


def artifacts():
    global _ART
    if _ART is None:
        _ART = ARTROOT / time.strftime("vm-%Y%m%d-%H%M%S")
        _ART.mkdir(parents=True, exist_ok=True)
        latest = ARTROOT / "vm-latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(_ART.name)
        except OSError:
            pass
    return _ART


def ppm_to_png(data):
    """Convert a binary PPM (P6, maxval 255) to PNG with the standard library."""
    if not data.startswith(b"P6"):
        return data                          # already PNG (newer QEMU) or unknown: keep as is
    fields, pos = [], 2
    while len(fields) < 3:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos) + 1
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(int(data[pos:end]))
        pos = end
    w, h, maxval = fields
    pos += 1
    pixels = data[pos:pos + w * h * 3]
    if maxval != 255:
        return data
    raw = b"".join(b"\x00" + pixels[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def screenshot(name):
    tmp = Path(tempfile.mkstemp(suffix=".ppm")[1])
    r = virsh("screenshot", CONF["VM_NAME"], str(tmp), "--screen", "0", check=False, timeout=30)
    if r.returncode != 0:
        say(f"screenshot failed: {r.stderr.strip()}", "y")
        return None
    out = artifacts() / f"{name}.png"
    out.write_bytes(ppm_to_png(tmp.read_bytes()))
    tmp.unlink()
    say(f"  screenshot: {out.relative_to(ROOT)}")
    return out


# ------------------------------------------------------------------ download cache
def http_get(url, binary=True, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "chainproxy-vmtest"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode()


def github_asset(repo, pattern):
    rel = json.loads(http_get(f"https://api.github.com/repos/{repo}/releases/latest", binary=False))
    for a in rel["assets"]:
        if re.fullmatch(pattern, a["name"]):
            return a["name"], a["browser_download_url"], a.get("digest")
    raise RuntimeError(f"no asset matching {pattern} in {repo} {rel.get('tag_name')}")


def cached(pattern):
    hits = sorted(CACHE.glob(pattern)) if CACHE.exists() else []
    return hits[-1] if hits else None


def cmd_fetch(_a):
    import hashlib
    CACHE.mkdir(parents=True, exist_ok=True)
    pyv = CONF["PY_VERSION"]
    jobs = [
        ("Python installer", f"python-{pyv}-amd64.exe",
         lambda: (f"python-{pyv}-amd64.exe", f"https://www.python.org/ftp/python/{pyv}/python-{pyv}-amd64.exe", None)),
        ("sing-box for Windows", "sing-box-*-windows-amd64.zip",
         lambda: github_asset("SagerNet/sing-box", r"sing-box-[\d.]+-windows-amd64\.zip")),
        ("OpenSSH MSI (optional bootstrap fallback)", "OpenSSH-Win64*.msi",
         lambda: github_asset("PowerShell/Win32-OpenSSH", r"OpenSSH-Win64-v[\d.]+\.msi")),
    ]
    ok = True
    for label, pattern, resolve in jobs:
        optional = "optional" in label
        have = cached(pattern)
        if have:
            say(f"  have  {label}: {have.name}", "g")
            continue
        try:
            name, url, digest = resolve()
            say(f"  get   {label}: {url}")
            data = http_get(url)
            if digest and digest.startswith("sha256:"):
                if hashlib.sha256(data).hexdigest() != digest.split(":", 1)[1]:
                    raise RuntimeError("sha256 mismatch")
                say("        sha256 verified", "g")
            (CACHE / name).write_bytes(data)
        except Exception as e:
            ok = ok and optional
            say(f"  {'warn' if optional else 'FAIL'}  {label}: {e}", "y" if optional else "r")
            say(f"        put the file into {CACHE.relative_to(ROOT)}/ by hand", "y")
    return 0 if ok else 1


# ------------------------------------------------------------------ bootstrap
def ensure_key():
    key = Path(CONF["SSH_KEY"])
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "chainproxy-vmtest", "-f", str(key)])
        say(f"created ssh key {key}")
    return (key.with_suffix(".pub") if key.suffix else Path(str(key) + ".pub")).read_text().strip()


def serve_files(host, port, files):
    files = {k: v for k, v in files.items() if v is not None}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = files.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            say(f"  VM fetched {self.path}", "g")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def agent_bootstrap(url):
    """Run the bootstrap through the QEMU guest agent. True = it ran and exited 0.
    False = the agent refused to start a program (typical: 'Permission denied' when the
    guest-exec command is blocked by the agent's allow-list/policy), so the caller falls back
    to the manual one-liner."""
    ps_exe = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    cmd_exe = r"C:\Windows\System32\cmd.exe"
    ps_args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"irm {url} | iex"]
    attempts = [(ps_exe, ps_args),
                (cmd_exe, ["/c", "powershell.exe"] + ps_args)]
    pid = None
    for path, args in attempts:
        req = {"execute": "guest-exec", "arguments": {"path": path, "arg": args,
                                                       "capture-output": True}}
        r = virsh("qemu-agent-command", CONF["VM_NAME"], json.dumps(req), "--timeout", "30",
                  check=False, timeout=60)
        if r.returncode == 0:
            pid = json.loads(r.stdout)["return"]["pid"]
            break
        say((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
            else "guest-exec failed", "y")
    if pid is None:
        return False
    deadline = time.time() + int(CONF["BOOT_TIMEOUT"])
    while time.time() < deadline:
        st = json.loads(virsh("qemu-agent-command", CONF["VM_NAME"],
                              json.dumps({"execute": "guest-exec-status", "arguments": {"pid": pid}}),
                              "--timeout", "30", timeout=60).stdout)["return"]
        if st.get("exited"):
            for key in ("out-data", "err-data"):
                if st.get(key):
                    print(base64.b64decode(st[key]).decode("utf-8", "replace"))
            if st.get("exitcode", 1) != 0:
                die(f"bootstrap failed in the VM (exit {st.get('exitcode')}); try --manual")
            return True
        time.sleep(5)
    die("the bootstrap did not finish in time; try --manual")


def cmd_bootstrap(a):
    need("VM_NAME", "WIN_USER")
    pub = ensure_key()
    vm_start()
    say("waiting for the VM's network address ...")
    ip = vm_ip(wait=300)
    if not ip:
        die("the VM got no IP address within 5 minutes (is it booted and on the libvirt network?)")
    global _IP
    _IP = ip
    hip, bport = host_ip(), int(CONF["BOOT_PORT"])
    if tcp_open(ip, 22) and ssh_ok():
        say(f"ssh already works ({target()}) - nothing to do", "g")
        return 0
    password = ""
    if a.autologon:
        password = getpass.getpass(f"Windows password of {CONF['WIN_USER']} (stored in the VM for autologon): ")
    msi = cached("OpenSSH-Win64*.msi")
    script = (GUEST / "bootstrap.ps1").read_text()
    script = (script.replace("__PUBKEY__", pub.replace("'", "''"))
                    .replace("__WIN_USER__", CONF["WIN_USER"].replace("'", "''"))
                    .replace("__MSI_URL__", f"http://{hip}:{bport}/openssh.msi" if msi else "")
                    .replace("__AUTOLOGON_PASSWORD__", password.replace("'", "''")))
    srv = serve_files(hip, bport, {"/bootstrap.ps1": script.encode(),
                                   "/openssh.msi": msi.read_bytes() if msi else None})
    url = f"http://{hip}:{bport}/bootstrap.ps1"
    oneliner = f'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm {url} | iex"'
    try:
        used_agent = False
        if not a.manual and agent_ok():
            say("QEMU guest agent found: running the bootstrap automatically (as SYSTEM) ...")
            used_agent = agent_bootstrap(url)
            if not used_agent:
                say("the guest agent cannot start programs in this VM (see the message above) - "
                    "falling back to the manual step", "y")
        if not used_agent:
            say("Do this once by hand inside the VM:", "y")
            print(f"  1. open the VM window, start PowerShell **as Administrator**\n"
                  f"  2. run:\n\n     {oneliner}\n")
            say("waiting for ssh (Ctrl+C to stop) ...")
        if not wait_ssh(int(CONF["BOOT_TIMEOUT"])):
            die("ssh did not come up. If the VM could not download the script, the host firewall "
                f"blocks {hip}:{bport} (see `vmtest.py doctor`).")
    finally:
        srv.shutdown()
    say(f"ssh works: {target()}", "g")
    rc, out = ps("whoami; [Environment]::OSVersion.VersionString")
    print(out.strip())
    if a.autologon:
        say("restart the VM once so the autologon takes effect: virsh reboot " + CONF["VM_NAME"], "y")
    say("next: vmtest.py snapshot   (a clean base to return to before each full run)")
    return 0


# ------------------------------------------------------------------ snapshots
def cmd_snapshot(a):
    need("VM_NAME")
    name = a.name or CONF["SNAPSHOT"]
    if virsh("snapshot-info", CONF["VM_NAME"], name, check=False).returncode == 0:
        die(f"snapshot '{name}' exists; delete it first: virsh -c {CONF['LIBVIRT_URI']} snapshot-delete {CONF['VM_NAME']} {name}")
    say(f"creating snapshot '{name}' ...")
    r = virsh("snapshot-create-as", CONF["VM_NAME"], name, "chainproxy test base", check=False, timeout=900)
    if r.returncode != 0:
        say(r.stderr.strip(), "y")
        say("full snapshot refused (typical for UEFI VMs); trying a disk-only external snapshot ...", "y")
        r = virsh("snapshot-create-as", CONF["VM_NAME"], name, "chainproxy test base",
                  "--disk-only", "--atomic", check=False, timeout=900)
        if r.returncode != 0:
            die("snapshot failed:\n" + r.stderr + "\nShut the VM down and create one in virt-manager, "
                "or run the suite without --clean.")
    say(f"snapshot '{name}' created", "g")
    return 0


def cmd_revert(a):
    need("VM_NAME")
    name = getattr(a, "name", None) or CONF["SNAPSHOT"]
    say(f"reverting to snapshot '{name}' ...")
    r = virsh("snapshot-revert", CONF["VM_NAME"], name, "--running", check=False, timeout=900)
    if r.returncode != 0:
        r = virsh("snapshot-revert", CONF["VM_NAME"], name, "--running", "--force", check=False, timeout=900)
        if r.returncode != 0:
            die("revert failed:\n" + r.stderr)
    if not wait_ssh(600):
        die("VM is not reachable over ssh after the revert")
    say("reverted, ssh is back", "g")
    return 0


# ------------------------------------------------------------------ deploy
def build_tar(online):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(ROOT.rglob("*")):
            rel = path.relative_to(ROOT)
            if any(part in EXCLUDE_DIRS for part in rel.parts) or path.name in EXCLUDE_FILES:
                continue
            if path.is_file():
                tar.add(path, arcname=f"repo/{rel.as_posix()}")
        staged = []
        if not online:
            for pattern in (f"python-{CONF['PY_VERSION']}-amd64.exe", "sing-box-*-windows-amd64.zip"):
                f = cached(pattern)
                if f:
                    tar.add(f, arcname=f"repo/offline/{f.name}")
                    staged.append(f.name)
    return buf.getvalue(), staged


def cmd_deploy(a):
    need("VM_NAME", "WIN_USER")
    data, staged = build_tar(getattr(a, "online", False))
    say(f"deploying {len(data) // 1024} KiB to {target()}:{CONF['REMOTE_DIR']}\\repo"
        + (f"  (offline: {', '.join(staged)})" if staged else "  (online: installers are downloaded in the VM)"))
    rd = remote_dir()
    ps(f'''
$Root = "{rd}"; $Repo = "$Root\\repo"
if (Test-Path "$Repo\\dev\\vm\\guest\\common.ps1") {{
    . "$Repo\\dev\\vm\\guest\\common.ps1"
    $py = Find-Python
    if ($py -and (Test-Path "$Repo\\chain.py")) {{ & $py "$Repo\\chain.py" off | Out-Null }}
    if ($py -and (Test-Path "$Repo\\dev\\lab\\e2e_client.py")) {{ & $py "$Repo\\dev\\lab\\e2e_client.py" reg restore | Out-Null }}
    Get-ScheduledTask -TaskName 'chainproxy-*' -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Interactive $_.TaskName }}
    Stop-TestProcesses $Repo
    Start-Sleep -Seconds 1
}}
New-Item -ItemType Directory -Force -Path $Root | Out-Null
''', timeout=120)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
        f.write(data)
    scp_to(f.name, f"{CONF['REMOTE_DIR']}.tar.gz")
    os.unlink(f.name)
    rc, out = ps(f'''
$Root = "{rd}"; $Repo = "$Root\\repo"; $tgz = "$HOME\\{CONF['REMOTE_DIR']}.tar.gz"
if (Test-Path $Repo) {{ Remove-Item $Repo -Recurse -Force -ErrorAction Stop }}
tar -xzf $tgz -C $Root
$rc = $LASTEXITCODE
Remove-Item $tgz
if ($rc -ne 0 -or -not (Test-Path "$Repo\\chain.py")) {{ Write-Host "extract failed ($rc)"; exit 1 }}
Write-Host "deployed to $Repo"
''', timeout=300)
    print(out.strip())
    if rc != 0:
        die("deploy failed (is a file in the test folder still in use?)")
    return 0


# ------------------------------------------------------------------ test stages
def stage_install(a):
    rc, out = ps(guest_prelude() + '& "$Repo\\dev\\vm\\guest\\install.ps1" -Repo $Repo; exit $LASTEXITCODE',
                 stream=True, log=artifacts() / "install.log", timeout=3600)
    return rc == 0


def stage_unit(a):
    require_python()
    rc, out = ps(guest_prelude() + 'Set-Location $Repo; & $py -X utf8 tests\\run_tests.py; exit $LASTEXITCODE',
                 stream=True, log=artifacts() / "unit.log", timeout=1200)
    return rc == 0


def start_lab():
    from lab import Lab
    lab = Lab(host_ip(), int(CONF["LAB_PORT"]), int(CONF["NODE_PORT_BASE"]),
              singbox=shutil.which("sing-box") or str(ROOT / "dev" / "bin" / "sing-box"),
              workdir=artifacts() / "lab")
    try:
        lab.start()
    except Exception as e:
        lab.stop()
        say(f"lab failed to start: {e}", "r")
        return None
    rc, out = ps(f"$c = New-Object Net.Sockets.TcpClient; $t = $c.ConnectAsync('{lab.listen}', {lab.lab_port}); "
                 "if ($t.Wait(5000) -and $c.Connected) { 'reachable' } else { 'blocked' }; $c.Close()")
    if "reachable" not in out:
        lab.stop()
        say(f"the VM cannot reach the lab on {lab.listen}:{lab.lab_port} - host firewall? (vmtest.py doctor)", "r")
        return None
    return lab


def lab_args(lab):
    from lab import EXPECT_EXIT, EXPECT_RANKED, EXPECT_VALID
    return (f"--lab-host {lab.listen} --lab-port {lab.lab_port} --expect-exit {EXPECT_EXIT} "
            f"--expect-valid {EXPECT_VALID} --expect-ranked {EXPECT_RANKED}")


def lab_verdict(lab, client_ok):
    ev = lab.chain_evidence()
    (artifacts() / "lab-evidence.json").write_text(json.dumps(ev, indent=2))
    ok_chain = bool(ev["a_nodes_forwarding_to_B1"]) and ev["B1_saw_hop_from_A"]
    say(("PASS  " if ok_chain else "FAIL  ") + f"lab logs prove VM -> A -> B1 ({ev})", "g" if ok_chain else "r")
    from lab import EXPECT_EXIT
    ok_exit = ev["whoami_sources"] == [EXPECT_EXIT]
    say(("PASS  " if ok_exit else "FAIL  ") + f"every probe left through B1 ({ev['whoami_sources']})",
        "g" if ok_exit else "r")
    return client_ok and ok_chain and ok_exit


def stage_e2e(a):
    require_python()
    lab = start_lab()
    if not lab:
        return False
    try:
        rc, out = ps(guest_prelude() +
                     f'& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" run --app $Repo {lab_args(lab)}; exit $LASTEXITCODE',
                     stream=True, log=artifacts() / "e2e.log", timeout=1800)
        for f in ("runtime/core.log", "runtime/config.json", "runtime/e2e-serve.log"):
            scp_from(f"{CONF['REMOTE_DIR']}/repo/{f}", artifacts() / ("e2e-" + Path(f).name))
        return lab_verdict(lab, rc == 0)
    finally:
        lab.stop()


def stage_gui(a):
    require_python()
    rc, out = ps(guest_prelude() + "if (Test-InteractiveUser) { 'yes' } else { 'no' }")
    if "yes" not in out:
        say("SKIP  gui: nobody is logged on to the VM desktop. Log in (or bootstrap with --autologon "
            "and reboot) and run again.", "y")
        return None
    log = artifacts() / "gui.log"
    results = []

    def check(ok, msg):
        results.append(bool(ok))
        say(("PASS  " if ok else "FAIL  ") + msg, "g" if ok else "r")
        with open(log, "a") as f:
            f.write(("PASS  " if ok else "FAIL  ") + msg + "\n")

    # 1. tkinter smoke test on the real desktop (mock core)
    say("== GUI smoke test on the desktop (mock core) ==")
    rc, out = ps(guest_prelude() + r'''
$log = "$Root\gui-smoke.log"; Remove-Item $log -ErrorAction SilentlyContinue
$cmdFile = "$Root\gui-smoke.cmd"
Set-Content -Path $cmdFile -Encoding ASCII -Value @(
  '@echo off', "cd /d `"$Repo`"", "`"$py`" -X utf8 tests\gui_smoke.py > `"$log`" 2>&1", 'exit /b %errorlevel%')
Start-Interactive 'chainproxy-gui-smoke' 'cmd.exe' "/c `"$cmdFile`"" $Repo
$code = Wait-Interactive 'chainproxy-gui-smoke' 300
Stop-Interactive 'chainproxy-gui-smoke'
if (Test-Path $log) { Get-Content $log }
Write-Host "SMOKE_EXIT=$code"
''', timeout=400)
    print(out)
    check("SMOKE_EXIT=0" in out and "GUI SMOKE: PASS" in out, "gui_smoke.py passed on the Windows desktop")

    # 2. the real window against the lab with the real core
    say("== real window, real sing-box, lab subscriptions ==")
    lab = start_lab()
    if not lab:
        return False
    try:
        rc, out = ps(guest_prelude() + f'''
& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" prepare --app $Repo {lab_args(lab)}
& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" reg save
& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" reg sentinel
Start-Interactive 'chainproxy-gui' (Get-Pythonw $py) "`"$Repo\\gui.py`" --enable" $Repo
$deadline = (Get-Date).AddSeconds(240); $st = ''
while ((Get-Date) -lt $deadline) {{
  $st = (& $py -X utf8 "$Repo\\chain.py" status | Out-String).Trim()
  if ($st.StartsWith('[')) {{ break }}; Start-Sleep -Seconds 2 }}
Write-Host "STATUS=$st"
''', timeout=300)
        print(out.strip())
        check("STATUS=[" in out, "window enabled itself (--enable) and is serving")
        time.sleep(2)
        screenshot("gui-1-active")
        rc, out = ps(guest_prelude() + f'''
& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" reg check-active --app $Repo
& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" probe --app $Repo {lab_args(lab)}
''', timeout=120)
        print(out.strip())
        check("FAIL" not in out and out.count("PASS") >= 2, "system proxy set and traffic exits through B1")
        rc, out = ps(guest_prelude() + '& $py -X utf8 "$Repo\\chain.py" next', timeout=200)
        check(out.strip().startswith("["), f"next while the window is open: {out.strip()}")
        time.sleep(3)
        screenshot("gui-2-next")
        rc, out = ps(guest_prelude() + '''
& $py -X utf8 "$Repo\\chain.py" off | Out-Null
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
  $st = (& $py -X utf8 "$Repo\\chain.py" status | Out-String)
  if ($st -match 'not running') { break }; Start-Sleep -Seconds 1 }
Start-Sleep -Seconds 2
& $py -X utf8 "$Repo\\dev\\lab\\e2e_client.py" reg check-sentinel --app $Repo
''', timeout=120)
        print(out.strip())
        check("PASS" in out and "FAIL" not in out, "stop.bat path: window disabled, original proxy restored")
        time.sleep(1)
        screenshot("gui-3-disabled")
        rc, out = ps(guest_prelude() + '''
$w = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui.py*' }
if ($w) { 'WINDOW_ALIVE' } else { 'WINDOW_GONE' }
''')
        check("WINDOW_ALIVE" in out, "window stayed open after a CLI 'off' (shows Disabled)")
        return lab_verdict(lab, all(results))
    finally:
        ps(guest_prelude() + r'''
Stop-Interactive 'chainproxy-gui'
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui.py*' } |
  ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
& $py -X utf8 "$Repo\chain.py" off | Out-Null
& $py -X utf8 "$Repo\dev\lab\e2e_client.py" reg restore | Out-Null
''', timeout=120)
        lab.stop()


STAGES = {"install": stage_install, "unit": stage_unit, "e2e": stage_e2e, "gui": stage_gui}


def run_stage(name, a):
    say(f"\n===== {name} =====")
    t0 = time.time()
    try:
        ok = STAGES[name](a)
    except SystemExit as e:
        ok = False if e.code else None
    except Exception as e:
        say(f"{name} crashed: {e!r}", "r")
        ok = False
    return {"stage": name, "result": {True: "PASS", False: "FAIL", None: "SKIP"}[ok],
            "seconds": round(time.time() - t0, 1)}


def summarize(rows):
    say("\n===== summary =====")
    for r in rows:
        color = {"PASS": "g", "FAIL": "r", "SKIP": "y"}[r["result"]]
        say(f"  {r['stage']:<10} {r['result']:<5} {r['seconds']:>7}s", color)
    (artifacts() / "summary.json").write_text(json.dumps(rows, indent=2))
    say(f"artifacts: {artifacts().relative_to(ROOT)}")
    return 1 if any(r["result"] == "FAIL" for r in rows) else 0


def cmd_stage(a):
    """A single stage. The current working tree is deployed first (fast) unless --no-deploy."""
    need("VM_NAME", "WIN_USER")
    vm_start()
    if not wait_ssh(300):
        die("VM not reachable over ssh (vmtest.py doctor)")
    if not a.no_deploy:
        cmd_deploy(a)
    return summarize([run_stage(a.cmd, a)])


def cmd_all(a):
    need("VM_NAME", "WIN_USER")
    vm_start()
    if a.clean:
        cmd_revert(argparse.Namespace(name=None))
    if not wait_ssh(300):
        die("VM not reachable over ssh (vmtest.py doctor)")
    rows = []
    t0 = time.time()
    try:
        cmd_deploy(a)
        rows.append({"stage": "deploy", "result": "PASS", "seconds": round(time.time() - t0, 1)})
    except SystemExit:
        rows.append({"stage": "deploy", "result": "FAIL", "seconds": round(time.time() - t0, 1)})
        return summarize(rows)
    rows.append(run_stage("install", a))
    if rows[-1]["result"] != "PASS":
        say("install failed: skipping the remaining stages", "r")
        return summarize(rows)
    for name in ("unit", "e2e") + (() if a.skip_gui else ("gui",)):
        rows.append(run_stage(name, a))
    return summarize(rows)


# ------------------------------------------------------------------ misc commands
def cmd_shell(_a):
    need("VM_NAME", "WIN_USER")
    opts = ssh_opts()
    i = opts.index("BatchMode=yes")
    del opts[i - 1:i + 1]                    # interactive: allow prompts
    os.execvp("ssh", ["ssh", *opts, "-t", target(), "powershell"])


def cmd_ps(a):
    need("VM_NAME", "WIN_USER")
    rc, _ = ps(a.command, stream=True)
    return rc


def run_guest_script(name, **params):
    """Run dev/vm/guest/<name>.ps1 in the VM without deploying anything (its text is sent over ssh)."""
    text = (ROOT / "dev" / "vm" / "guest" / name).read_text(encoding="ascii")
    args = " ".join(f"-{k} ${str(v).lower()}" if isinstance(v, bool) else f"-{k} '{v}'" for k, v in params.items())
    return ps("& {\n" + text + "\n} " + args, stream=True, log=artifacts() / (name.replace(".ps1", "") + ".log"),
              timeout=1800)


def cmd_clean(a):
    """Remove everything the project put into the VM (see dev/vm/guest/clean.ps1)."""
    need("VM_NAME", "WIN_USER")
    vm_start()
    if not wait_ssh(300):
        die("VM not reachable over ssh (vmtest.py doctor)")
    rc, _ = run_guest_script("clean.ps1", Full=not a.keep_tools)
    return rc


def cmd_installer(a):
    """Install / first run / upgrade / uninstall with a built installer (dist/ChainProxy-Setup*.exe)."""
    need("VM_NAME", "WIN_USER")
    full = a.full
    name = next((p.name for p in sorted((ROOT / "dist").glob("ChainProxy-Setup-Full-*.exe" if full else "ChainProxy-Setup-[0-9]*.exe"))[-1:]), None)
    if not name:
        die("no installer in dist/: run `make installer` first")
    vm_start()
    if not wait_ssh(300):
        die("VM not reachable over ssh (vmtest.py doctor)")
    say(f"copying {name} to the VM")
    scp_to(ROOT / "dist" / name, name)
    if a.python:
        py = cached(f"python-{CONF['PY_VERSION']}-amd64.exe")
        if not py:
            die("python installer is not in dev/vm/cache: run `make vm-fetch`")
        scp_to(py, "python-pre.exe")
    rc, out = run_guest_script("installer-test.ps1", Setup=name, Full=full, PrePython=a.python)
    return summarize([{"stage": "installer" + ("-full" if full else "") + (f"+py-{a.python}" if a.python else ""), "result": "PASS" if rc == 0 else "FAIL",
                       "seconds": 0}])


def cmd_screenshot(_a):
    need("VM_NAME")
    return 0 if screenshot(time.strftime("screen-%H%M%S")) else 1


def cmd_pull_logs(_a):
    need("VM_NAME", "WIN_USER")
    for f in ("runtime/core.log", "runtime/config.json", "runtime/e2e-serve.log", "config.json"):   # never subs.txt
        dest = artifacts() / Path(f).name
        say(("  got   " if scp_from(f"{CONF['REMOTE_DIR']}/repo/{f}", dest) else "  none  ") + f)
    say(f"saved to {artifacts().relative_to(ROOT)}")
    return 0


def cmd_doctor(_a):
    bad = 0

    def line(ok, msg, hint=""):
        nonlocal bad
        if ok is False:
            bad += 1
        mark = {True: f"{C['g']}ok  {C['0']}", False: f"{C['r']}FAIL{C['0']}", None: f"{C['y']}warn{C['0']}"}[ok]
        print(f"  {mark} {msg}" + (f"\n       -> {hint}" if hint and ok is not True else ""))

    say("host tools")
    for tool, hint in [("virsh", "sudo pacman -S libvirt"), ("ssh", "sudo pacman -S openssh"),
                       ("scp", "sudo pacman -S openssh"), ("ssh-keygen", "sudo pacman -S openssh")]:
        line(bool(shutil.which(tool)), tool, hint)
    sb = shutil.which("sing-box") or (str(ROOT / "dev/bin/sing-box") if (ROOT / "dev/bin/sing-box").exists() else None)
    if sb:
        ver = run([sb, "version"], check=False).stdout
        line("with_clash_api" in ver, f"sing-box ({ver.splitlines()[0] if ver else '?'})",
             "this build lacks with_clash_api: dev/setup-cachyos.sh --official-singbox")
    else:
        line(False, "sing-box (needed for the e2e lab)", "dev/setup-cachyos.sh")
    say("libvirt")
    if not shutil.which("virsh"):
        return 1
    r = virsh("list", "--all", check=False)
    line(r.returncode == 0, f"access to {CONF['LIBVIRT_URI']}",
         "sudo usermod -aG libvirt $USER && newgrp libvirt ; sudo systemctl enable --now libvirtd.socket")
    if r.returncode != 0:
        return 1
    line(bool(CONF["VM_NAME"]), f"VM_NAME = {CONF['VM_NAME'] or '(unset)'}",
         "cp dev/vm/vm.conf.example dev/vm/vm.conf and set VM_NAME (one of: "
         + ", ".join(l.split()[1] for l in r.stdout.splitlines()[2:] if len(l.split()) > 1) + ")")
    line(bool(CONF["WIN_USER"]), f"WIN_USER = {CONF['WIN_USER'] or '(unset)'}", "your Windows account name in the VM")
    if not CONF["VM_NAME"]:
        return 1
    st = vm_state()
    line(st is not None, f"domain {CONF['VM_NAME']}: {st}")
    if st is None:
        return 1
    net = virsh("net-info", CONF["LIBVIRT_NET"], check=False)
    line("Active:         yes" in net.stdout, f"libvirt network '{CONF['LIBVIRT_NET']}' active",
         f"virsh -c {CONF['LIBVIRT_URI']} net-start {CONF['LIBVIRT_NET']} && virsh -c {CONF['LIBVIRT_URI']} net-autostart {CONF['LIBVIRT_NET']}")
    snap = virsh("snapshot-info", CONF["VM_NAME"], CONF["SNAPSHOT"], check=False).returncode == 0
    line(True if snap else None, f"snapshot '{CONF['SNAPSHOT']}' " + ("exists" if snap else "missing"),
         "vmtest.py snapshot (needed only for `all --clean`)")
    for name, pattern in [("Python installer", f"python-{CONF['PY_VERSION']}-amd64.exe"),
                          ("sing-box zip", "sing-box-*-windows-amd64.zip"), ("OpenSSH MSI", "OpenSSH-Win64*.msi")]:
        f = cached(pattern)
        line(True if f else None, f"cache: {name} " + (f.name if f else "missing"), "vmtest.py fetch")
    fw = None
    for svc in ("ufw", "firewalld"):
        if run(["systemctl", "is-active", "--quiet", svc], check=False).returncode == 0:
            fw = (svc, "sudo ufw allow in on virbr0" if svc == "ufw" else
                  "sudo firewall-cmd --permanent --zone=libvirt --add-port=18000-18999/tcp && sudo firewall-cmd --reload")
    if st != "running":
        line(None, "VM not running: further checks skipped", "virsh start " + CONF["VM_NAME"])
        return 1 if bad else 0
    say("VM")
    line(True if agent_ok() else None, "QEMU guest agent", "optional: install virtio-win guest tools for an automatic bootstrap")
    ip = vm_ip(wait=10)
    line(bool(ip), f"VM address: {ip}", "set VM_IP in vm.conf if the VM is not on a libvirt NAT network")
    line(True, f"host address on the VM network: {host_ip()}")
    if not ip or not CONF["WIN_USER"]:
        return 1
    global _IP
    _IP = ip
    line(Path(CONF["SSH_KEY"]).exists(), f"ssh key {CONF['SSH_KEY']}", "vmtest.py bootstrap")
    reach = tcp_open(ip, 22)
    line(reach, "VM port 22 open", "vmtest.py bootstrap")
    if reach:
        good = ssh_ok()
        line(good, f"ssh login {target()}", "vmtest.py bootstrap")
        if good:
            hip, port = host_ip(), int(CONF["LAB_PORT"])
            try:
                srv = socket.socket()
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind((hip, port))
                srv.listen(5)
                rc, out = ps(f"$c = New-Object Net.Sockets.TcpClient; $t = $c.ConnectAsync('{hip}', {port}); "
                             "if ($t.Wait(5000) -and $c.Connected) { 'reachable' } else { 'blocked' }; $c.Close()")
                srv.close()
                reach = "reachable" in out
                line(reach, f"VM -> host {hip}:{port} (lab traffic)",
                     (f"the host firewall ({fw[0]}) blocks it: {fw[1]}" if fw else
                      "open the host firewall for the libvirt bridge"))
            except OSError as e:
                line(None, f"could not test VM -> host ({e})")
            rc, out = ps("if (-not (Test-Path \"" + remote_dir() + "\\repo\\dev\\vm\\guest\\common.ps1\")) "
                         "{ 'python: none (nothing deployed yet - normal before the first install)'; exit 0 }\n"
                         + guest_prelude() +
                         "if ($py) { \"python: $py\" } else { 'python: none' }; "
                         "if (Test-InteractiveUser) { 'desktop: logged on' } else { 'desktop: nobody logged on' }")
            for l in out.strip().splitlines():
                line(True if ("none" not in l and "nobody" not in l) else None, l.strip(),
                     "vmtest.py install" if "python" in l else "log on, or bootstrap --autologon (GUI test)")
    say("all good" if not bad else f"{bad} problem(s)", "g" if not bad else "r")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="Windows VM test driver for chainproxy",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("fetch")
    b = sub.add_parser("bootstrap")
    b.add_argument("--autologon", action="store_true", help="also enable automatic logon (GUI test)")
    b.add_argument("--manual", action="store_true", help="do not use the guest agent; print a one-liner")
    for n in ("snapshot", "revert"):
        p = sub.add_parser(n)
        p.add_argument("name", nargs="?")
    d = sub.add_parser("deploy")
    d.add_argument("--online", action="store_true", help="do not stage cached installers")
    for n in STAGES:
        p = sub.add_parser(n)
        p.add_argument("--online", action="store_true", help="do not stage cached installers")
        p.add_argument("--no-deploy", action="store_true", help="test what is already in the VM")
    al = sub.add_parser("all")
    al.add_argument("--clean", action="store_true", help="revert to the snapshot first")
    al.add_argument("--online", action="store_true", help="let the VM download Python/sing-box itself")
    al.add_argument("--skip-gui", action="store_true")
    cl = sub.add_parser("clean")
    cl.add_argument("--keep-tools", action="store_true", help="keep Python and Inno Setup (faster next run)")
    ins = sub.add_parser("installer")
    ins.add_argument("--full", action="store_true", help="test the Full installer (Python + sing-box inside)")
    ins.add_argument("--python", choices=["full", "notk"], default="",
                     help="install a Python first: 'full' = working one (must be reused), 'notk' = without tkinter")
    sub.add_parser("shell")
    p = sub.add_parser("ps")
    p.add_argument("command")
    sub.add_parser("screenshot")
    sub.add_parser("pull-logs")
    a = ap.parse_args()

    handlers = {"doctor": cmd_doctor, "fetch": cmd_fetch, "bootstrap": cmd_bootstrap,
                "snapshot": cmd_snapshot, "revert": cmd_revert, "deploy": cmd_deploy,
                "all": cmd_all, "shell": cmd_shell, "ps": cmd_ps, "screenshot": cmd_screenshot,
                "pull-logs": cmd_pull_logs, "clean": cmd_clean, "installer": cmd_installer}
    handlers.update({n: cmd_stage for n in STAGES})
    return handlers[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
