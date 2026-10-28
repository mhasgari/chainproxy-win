#!/usr/bin/env python3
"""
chainproxy - chain two subscriptions (A -> B -> internet) with sing-box,
pick the best working route, set the Windows system proxy, and let the user
rotate to the next suitable route on demand.

Usage:
    python chain.py                 start (default)
    python chain.py next|prev       switch route (talks to the running instance)
    python chain.py status|list     show current route / ranked routes
    python chain.py rescan          re-measure all routes
    python chain.py off             stop + restore Windows proxy settings
    python chain.py serve           start without the interactive console (stop with 'off')
    python chain.py ensure          make sure a working sing-box is installed
    python chain.py install-core    (re)download sing-box.exe into ./core
"""
__version__ = "1.2.0"

import atexit
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse as up
import urllib.request as ur
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
CFG_FILE = BASE / "config.json"
SUBS_FILE = BASE / "subs.txt"
CACHE_DIR = BASE / "cache"
RUNTIME_DIR = BASE / "runtime"
STATE_FILE = BASE / ".proxy_state.json"
CORE_DIR = BASE / "core"
IS_WIN = os.name == "nt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) chainproxy/1.0"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_private = ";".join(["localhost", "127.*", "10.*", "192.168.*"] +
                    [f"172.{i}.*" for i in range(16, 32)] + ["<local>"])
DEFAULTS = {
    "mixed_port": 10808,
    "api_port": 19090,
    "control_port": 19091,
    "top_k": 5,                      # how many nodes from each list to try
    "tcp_timeout": 3.0,
    "delay_timeout_ms": 7000,
    "check_urls": ["https://www.gstatic.com/generate_204",
                   "https://cp.cloudflare.com/generate_204"],
    "strict_urls": [],               # sites that must answer < 400 through the route
    "blocked_countries": ["IR"],     # reject routes whose exit IP is in these countries
    "direct_suffixes": [".ir"],      # domains that bypass the proxy
    "bypass": _private,
    "watchdog_seconds": 60,          # 0 = off; auto-switch when route dies
    "watchdog_failures": 2,
    "log_level": "warn",
    "geo_url": "https://ipinfo.io/json",   # exit IP/country lookup ("" = skip)
    "geo_fallback_urls": ["https://api.country.is/", "https://ipwho.is/"],   # tried when geo_url fails
    "verify_timeout": 12,            # seconds per request of the route verification
    "rank_by_speed": False,          # False: chains, then B-only, then A-only; True: pure speed order
    "private_direct": True,          # private/LAN destinations bypass the route
}


def normalize_url(u):
    """'gemini.google.com' -> 'https://gemini.google.com' (a bare host is not a valid URL for urllib)."""
    u = str(u).strip()
    if not u:
        return ""
    return u if re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I) else "https://" + u

NOPROXY = ur.build_opener(ur.ProxyHandler({}))
LOCK = threading.RLock()


LOG_HOOK = None      # the GUI sets this to receive log lines


def log(*a):
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    if LOG_HOOK:
        LOG_HOOK(line)


def load_cfg():
    cfg = dict(DEFAULTS)
    if CFG_FILE.exists():
        try:
            cfg.update(json.loads(CFG_FILE.read_text(encoding="utf-8-sig")))
        except ValueError as e:
            sys.exit(f"config.json is not valid JSON ({e}); fix it or delete the file")
    for key in ("strict_urls", "check_urls", "geo_fallback_urls"):
        cfg[key] = [n for n in (normalize_url(x) for x in cfg[key]) if n]
    if cfg.get("geo_url"):
        cfg["geo_url"] = normalize_url(cfg["geo_url"])
    return cfg


# --------------------------------------------------------------------------
# subscription parsing -> sing-box outbounds
# --------------------------------------------------------------------------
def b64d(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "replace")


def first_params(u):
    return {k: v[0] for k, v in up.parse_qs(u.query).items()}


def tls_block(p, host, force=False):
    sec = p.get("security", "")
    if sec not in ("tls", "reality") and not force:
        return None
    t = {"enabled": True}
    sni = p.get("sni") or p.get("peer") or host
    if sni:
        t["server_name"] = sni
    if p.get("allowInsecure") in ("1", "true") or p.get("insecure") in ("1", "true"):
        t["insecure"] = True
    if p.get("alpn"):
        t["alpn"] = [x for x in p["alpn"].split(",") if x]
    fp = p.get("fp")
    if fp or sec == "reality":
        t["utls"] = {"enabled": True, "fingerprint": fp or "chrome"}
    if sec == "reality":
        t["reality"] = {"enabled": True, "public_key": p.get("pbk", ""),
                        "short_id": p.get("sid", "")}
    return t


def transport_block(p):
    typ = p.get("type", "tcp")
    host = p.get("host", "")
    path = p.get("path", "") or "/"
    if typ == "ws":
        t = {"type": "ws"}
        m = re.search(r"[?&]ed=(\d+)", path)
        if m:
            t["max_early_data"] = int(m.group(1))
            t["early_data_header_name"] = "Sec-WebSocket-Protocol"
            path = re.sub(r"[?&]ed=\d+", "", path) or "/"
        t["path"] = path
        if host:
            t["headers"] = {"Host": host}
        return t
    if typ == "grpc":
        return {"type": "grpc", "service_name": p.get("serviceName", "")}
    if typ == "httpupgrade":
        t = {"type": "httpupgrade", "path": path}
        if host:
            t["host"] = host
        return t
    if typ in ("h2", "http"):
        t = {"type": "http", "path": path}
        if host:
            t["host"] = [h for h in host.split(",") if h]
        return t
    return None


def parse_node(link):
    link = link.strip()
    try:
        scheme = link.split("://", 1)[0].lower()
        if scheme == "vmess":
            j = json.loads(b64d(link[8:]))
            p = {"security": j.get("tls", ""), "sni": j.get("sni", ""),
                 "alpn": j.get("alpn", ""), "fp": j.get("fp", ""),
                 "type": j.get("net", "tcp"), "host": j.get("host", ""),
                 "path": j.get("path", "/"), "serviceName": j.get("path", "")}
            ob = {"type": "vmess", "server": j["add"], "server_port": int(j["port"]),
                  "uuid": j["id"], "alter_id": int(j.get("aid", 0) or 0),
                  "security": j.get("scy") or "auto"}
            t = tls_block(p, j.get("host") or j["add"])
            if t:
                ob["tls"] = t
            tr = transport_block(p)
            if tr:
                ob["transport"] = tr
            return j.get("ps", j["add"]), ob
        if scheme in ("vless", "trojan"):
            u = up.urlparse(link)
            p = first_params(u)
            name = up.unquote(u.fragment) or u.hostname
            if scheme == "vless":
                ob = {"type": "vless", "server": u.hostname, "server_port": u.port,
                      "uuid": up.unquote(u.username), "packet_encoding": "xudp"}
                if p.get("flow"):
                    ob["flow"] = p["flow"]
                t = tls_block(p, u.hostname)
            else:
                ob = {"type": "trojan", "server": u.hostname, "server_port": u.port,
                      "password": up.unquote(u.username)}
                t = tls_block(p, u.hostname, force=True)
            if t:
                ob["tls"] = t
            tr = transport_block(p)
            if tr:
                ob["transport"] = tr
            return name, ob
        if scheme == "ss":
            body, _, frag = link[5:].partition("#")
            name = up.unquote(frag)
            main, _, query = body.partition("?")
            if "plugin=" in query:
                return None
            if "@" in main:
                userinfo, hostport = main.rsplit("@", 1)
                userinfo = up.unquote(userinfo)
                if ":" not in userinfo:
                    userinfo = b64d(userinfo)
            else:
                dec = b64d(main)
                userinfo, hostport = dec.rsplit("@", 1)
            method, pw = userinfo.split(":", 1)
            host, port = hostport.rsplit(":", 1)
            host = host.strip("[]")
            return name or host, {"type": "shadowsocks", "server": host,
                                  "server_port": int(port.strip("/")),
                                  "method": method, "password": pw}
        if scheme in ("hysteria2", "hy2"):
            u = up.urlparse(link)
            p = first_params(u)
            pw = up.unquote(u.username or "")
            if u.password:
                pw += ":" + up.unquote(u.password)
            ob = {"type": "hysteria2", "server": u.hostname, "server_port": u.port or 443,
                  "password": pw,
                  "tls": {"enabled": True, "server_name": p.get("sni") or u.hostname}}
            if p.get("insecure") in ("1", "true"):
                ob["tls"]["insecure"] = True
            if p.get("obfs") == "salamander":
                ob["obfs"] = {"type": "salamander", "password": p.get("obfs-password", "")}
            return up.unquote(u.fragment) or u.hostname, ob
    except Exception:
        return None
    return None


def node_key(ob):
    return (ob["type"], ob["server"], ob["server_port"],
            ob.get("uuid") or ob.get("password"))


def fetch_nodes(src, label):
    """src: http(s) URL, local file path, or a single node link."""
    body = None
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"{label}.txt"
    if re.match(r"^https?://", src, re.I):
        try:
            req = ur.Request(src, headers={"User-Agent": "v2rayN/6.45"})
            with ur.urlopen(req, timeout=25) as r:
                body = r.read().decode("utf-8", "replace")
            cache.write_text(body, encoding="utf-8")
            log(f"[{label}] subscription downloaded")
        except Exception as e:
            log(f"[{label}] download failed ({e}); trying cache")
            if cache.exists():
                body = cache.read_text(encoding="utf-8")
    elif re.match(r"^[a-z0-9]+://", src, re.I):
        body = src
    elif Path(src).exists():
        body = Path(src).read_text(encoding="utf-8")
    if not body:
        return []
    text = body.strip()
    if not re.search(r"^[a-z0-9]+://", text, re.M | re.I):
        try:
            text = b64d(text)
        except Exception:
            return []
    nodes, seen = [], set()
    for line in text.splitlines():
        n = parse_node(line)
        if n and node_key(n[1]) not in seen:
            seen.add(node_key(n[1]))
            nodes.append(n)
    log(f"[{label}] {len(nodes)} usable nodes")
    return nodes


def load_sources():
    ensure_subs_file()
    if not SUBS_FILE.exists():
        sys.exit("subs.txt not found")
    lines = [l.strip() for l in SUBS_FILE.read_text(encoding="utf-8-sig").splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    if not lines or subs_are_placeholder(lines):
        sys.exit("subs.txt has no real subscription links yet: put the first link on "
                 "line 1 and the second on line 2 (or use Settings in the window)")
    return lines


def ensure_subs_file():
    """First run: subs.txt (never committed, it holds the user's links) is made from the template."""
    example = BASE / "subs.example.txt"
    if not SUBS_FILE.exists() and example.exists():
        try:
            shutil.copyfile(example, SUBS_FILE)
        except OSError:
            pass


def subs_are_placeholder(lines=None):
    if lines is None:
        ensure_subs_file()
        if not SUBS_FILE.exists():
            return True
        lines = [l.strip() for l in SUBS_FILE.read_text(encoding="utf-8-sig").splitlines()]
        lines = [l for l in lines if l and not l.startswith("#")]
    # the template ships a real second link (GeminiRoute best); only the FIRST one must be replaced
    return not lines or "example.com/sub/" in lines[0]


def tcp_ms(ob, timeout):
    if ob["type"] == "hysteria2":      # UDP: cannot TCP-probe
        return 500.0
    t0 = time.time()
    try:
        with socket.create_connection((ob["server"], ob["server_port"]), timeout):
            return (time.time() - t0) * 1000
    except Exception:
        return None


def pick(nodes, k, timeout, prefix, validator=None):
    with ThreadPoolExecutor(64) as ex:
        ms = list(ex.map(lambda n: tcp_ms(n[1], timeout), nodes))
    scored = sorted([(m, n) for m, n in zip(ms, nodes) if m is not None],
                    key=lambda x: x[0])
    ordered = [n for _, n in scored]
    if not ordered:                     # direct TCP probing may be filtered: let the
        ordered = list(nodes)           # end-to-end test decide
    chosen = ordered[:k]
    if validator:                       # drop nodes the sing-box core refuses to load
        pool = ordered[:max(k * 3, k)]
        with ThreadPoolExecutor(4) as ex:
            good = [n for n, ok in zip(pool, ex.map(lambda n: validator(n[1]), pool)) if ok]
        if good:
            chosen = good[:k]
        else:
            log(f"[{prefix}] core check rejected every candidate; using them unvalidated")
    return {f"{prefix}{i + 1}": n for i, n in enumerate(chosen)}


# --------------------------------------------------------------------------
# sing-box config
# --------------------------------------------------------------------------
def build_config(cfg, A, B, modern=True):
    outs = [{"type": "direct", "tag": "direct"}]
    for tag, (_, ob) in list(A.items()) + list(B.items()):
        outs.append({**ob, "tag": tag})
    chains = []
    for ta in A:
        for tb in B:
            tag = f"{ta}-{tb}"
            outs.append({**B[tb][1], "tag": tag, "detour": ta})   # client -> A -> B -> net
            chains.append(tag)
    all_tags = chains + list(B) + list(A)
    outs.append({"type": "selector", "tag": "route", "outbounds": all_tags,
                 "default": all_tags[0]})
    rules = [{"ip_is_private": True, "outbound": "direct"}] if cfg["private_direct"] else []
    if cfg["direct_suffixes"]:
        rules.insert(0, {"domain_suffix": cfg["direct_suffixes"], "outbound": "direct"})
    conf = {
        "log": {"level": cfg["log_level"], "timestamp": True},
        "inbounds": [{"type": "mixed", "tag": "in", "listen": "127.0.0.1",
                      "listen_port": cfg["mixed_port"]}],
        "outbounds": outs,
        "route": {"rules": rules, "final": "route"},
        "experimental": {"clash_api": {"external_controller": f"127.0.0.1:{cfg['api_port']}"}},
    }
    if modern:      # sing-box >= 1.12 wants an explicit resolver for domain server addresses
        conf["dns"] = {"servers": [{"type": "local", "tag": "local"}]}
        conf["route"]["default_domain_resolver"] = "local"
    return conf


def find_core():
    env = os.environ.get("CHAIN_CORE")
    if env and Path(env).exists():
        return env
    for p in (CORE_DIR / "sing-box.exe", CORE_DIR / "sing-box"):
        if p.exists():
            return str(p)
    return shutil.which("sing-box")


def core_cmd():
    """Command prefix that runs the core. A *.py core (the test double) runs under Python."""
    exe = find_core()
    if not exe:
        return None
    return [sys.executable, exe] if exe.lower().endswith(".py") else [exe]


def core_run(args, timeout=20):
    cmd = core_cmd()
    if not cmd:
        return 1, "sing-box not found"
    try:
        r = subprocess.run(cmd + args, capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if IS_WIN else 0)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def core_check(conf):
    """Validate a config dict with `sing-box check`. Returns (ok, message)."""
    RUNTIME_DIR.mkdir(exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".json", dir=RUNTIME_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(conf, f)
        code, out = core_run(["check", "-c", path])
        return code == 0, out
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def node_valid(ob):
    ok, _ = core_check({"outbounds": [{**ob, "tag": "probe"}]})
    return ok


def http_get(url, timeout=30, tries=3, binary=False):
    last = None
    for i in range(tries):
        try:
            with ur.urlopen(ur.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "replace"), r.geturl()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"download failed: {url} ({last})")


def _extract_core(zip_path):
    CORE_DIR.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=CORE_DIR))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for m in zf.namelist():
                if not m.endswith("/"):
                    (stage / Path(m).name).write_bytes(zf.read(m))
        if not any(p.name.startswith("sing-box") for p in stage.iterdir()):
            raise RuntimeError("archive does not contain sing-box")
        for p in stage.iterdir():             # replace only after a clean extraction
            os.replace(p, CORE_DIR / p.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def install_core(force=False):
    if not force and find_core():
        return
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
    tmp = Path(tempfile.mkdtemp())
    z = tmp / "core.zip"
    offline = sorted((BASE / "offline").glob("sing-box*windows*.zip")) if (BASE / "offline").exists() else []
    if offline:
        log("using offline package", offline[-1].name)
        shutil.copy(offline[-1], z)
    else:
        log("sing-box not found: downloading ...")
        name = url = digest = None
        try:
            rel = json.loads(http_get("https://api.github.com/repos/SagerNet/sing-box/releases/latest")[0])
            asset = next(a for a in rel["assets"] if a["name"].endswith(f"windows-{arch}.zip"))
            name, url, digest = asset["name"], asset["browser_download_url"], asset.get("digest")
        except Exception as e:
            log("release API failed, using redirect fallback:", e)
            _, final = http_get("https://github.com/SagerNet/sing-box/releases/latest", tries=3)
            tag = final.rstrip("/").split("/")[-1]
            name = f"sing-box-{tag.lstrip('v')}-windows-{arch}.zip"
            url = f"https://github.com/SagerNet/sing-box/releases/download/{tag}/{name}"
        log("downloading", name)
        data, _ = http_get(url, timeout=120, binary=True)
        if digest and digest.startswith("sha256:"):
            if hashlib.sha256(data).hexdigest() != digest.split(":", 1)[1]:
                raise RuntimeError("sha256 mismatch for the sing-box download - aborting")
            log("sha256 verified")
        else:
            log("(no checksum published for this download; relying on a version self-check)")
        z.write_bytes(data)
    _extract_core(z)
    shutil.rmtree(tmp, ignore_errors=True)
    code, out = core_run(["version"])
    if code != 0:
        raise RuntimeError("installed sing-box does not run: " + out)
    log("sing-box ready:", out.splitlines()[0] if out else "ok")


def ensure_core():
    if find_core():
        code, _ = core_run(["version"])
        if code == 0:
            return
        log("existing sing-box does not run; reinstalling")
        install_core(force=True)
    else:
        install_core()


def port_free(port):
    with socket.socket() as s:
        if not IS_WIN:      # like Go: ignore TIME_WAIT leftovers (never on Windows: it would
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # hide live listeners)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


_JOB = None


def job_attach(proc):
    """Windows: put sing-box into a job object that dies with us, so even `taskkill /F` of
    the app (or a crash) cannot leave an orphan core holding the ports."""
    global _JOB
    if not IS_WIN:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _JOB is None:
            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IoCounters(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in
                            ("r", "w", "o", "rb", "wb", "ob")]

            class Ext(ctypes.Structure):
                _fields_ = [("Basic", Basic), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]
            h = k.CreateJobObjectW(None, None)
            info = Ext()
            info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError("SetInformationJobObject failed")
            _JOB = h
        if not k.AssignProcessToJobObject(_JOB, wintypes.HANDLE(int(proc._handle))):
            raise OSError("AssignProcessToJobObject failed")
    except Exception as e:
        log("could not tie sing-box to this process (job object):", e)


def kill_stale_core():
    """Kill a sing-box left over from a previous run of THIS folder (matched by its config path)."""
    if not IS_WIN:
        return
    cfgp = str(RUNTIME_DIR / "config.json").replace("'", "''")
    script = ("Get-CimInstance Win32_Process -Filter \"Name='sing-box.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*{cfgp}*' }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       creationflags=0x08000000, timeout=30, capture_output=True)
    except Exception as e:
        log("could not look for a stale sing-box:", e)


def pid_alive(pid):
    if IS_WIN:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259                      # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def guard(pid, poll=1.0):
    """Tiny helper process: when the app (pid) disappears without cleaning up - killed from the
    Task Manager, crashed - put the original Windows proxy settings back."""
    while pid_alive(pid):
        time.sleep(poll)
    time.sleep(0.5)
    if STATE_FILE.exists():
        try:
            sys_proxy_restore()
        except Exception:
            pass


def start_guard():
    if not IS_WIN:
        return None
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    try:
        return subprocess.Popen([str(pyw if pyw.exists() else exe), str(BASE / "chain.py"), "guard", str(os.getpid())],
                                creationflags=0x08000000 | 0x00000008, close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log("could not start the crash guard:", e)
        return None


class Core:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.port = cfg["api_port"]

    def _close_log(self):
        f = getattr(self, "logf", None)
        if f:
            try:
                f.close()
            except Exception:
                pass
            self.logf = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, conf):
        self.conf = conf
        RUNTIME_DIR.mkdir(exist_ok=True)
        path = RUNTIME_DIR / "config.json"
        path.write_text(json.dumps(conf, indent=1), encoding="utf-8")
        cmd = core_cmd()
        if not cmd:
            raise RuntimeError("sing-box not found")
        flags = 0x08000000 if IS_WIN else 0     # CREATE_NO_WINDOW
        self._close_log()
        logf = self.logf = open(RUNTIME_DIR / "core.log", "w")
        self.proc = subprocess.Popen(cmd + ["run", "-c", str(path)], stdout=logf,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        job_attach(self.proc)
        for _ in range(60):
            if self.proc.poll() is not None:
                raise RuntimeError("sing-box exited; see runtime/core.log")
            try:
                self.api("GET", "/version", timeout=2)
                return
            except Exception:
                time.sleep(0.25)
        self.stop()          # a half-started core must not stay "alive": the watchdog would never retry
        raise RuntimeError("sing-box API did not come up; see runtime/core.log")

    def api(self, method, path, body=None, timeout=15):
        data = json.dumps(body).encode() if body is not None else None
        req = ur.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                         headers={"Content-Type": "application/json"})
        with NOPROXY.open(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}

    def delay(self, tag, url, timeout_ms):
        q = f"/proxies/{up.quote(tag)}/delay?url={up.quote(url)}&timeout={timeout_ms}"
        try:
            return self.api("GET", q, timeout=timeout_ms / 1000 + 4).get("delay")
        except urllib.error.HTTPError as e:
            e.close()                       # otherwise its temp file is only freed by the GC (ResourceWarning)
            return None
        except Exception:
            return None

    def select(self, tag):
        self.api("PUT", "/proxies/route", {"name": tag})

    def restart(self, tag=None):
        self.stop()
        self.start(self.conf)
        if tag:
            self.select(tag)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except Exception:
                self.proc.kill()
        self._close_log()


# --------------------------------------------------------------------------
# Windows system proxy
# --------------------------------------------------------------------------
def _refresh_inet():
    import ctypes
    wi = ctypes.windll.wininet
    wi.InternetSetOptionW(0, 39, 0, 0)   # SETTINGS_CHANGED
    wi.InternetSetOptionW(0, 37, 0, 0)   # REFRESH


def sys_proxy_set(port, bypass):
    if not IS_WIN:
        log("(not Windows: system proxy not changed)")
        return
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
    if not STATE_FILE.exists():          # keep the ORIGINAL settings across crashes
        saved = {}
        for n in ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL"):
            try:
                v, t = winreg.QueryValueEx(key, n)
                saved[n] = [v, t]
            except FileNotFoundError:
                saved[n] = None
        STATE_FILE.write_text(json.dumps(saved))
    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{port}")
    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass)
    try:
        winreg.DeleteValue(key, "AutoConfigURL")   # a PAC script would override us
    except FileNotFoundError:
        pass
    winreg.CloseKey(key)
    _refresh_inet()


def sys_proxy_restore():
    if not STATE_FILE.exists():
        return
    saved = json.loads(STATE_FILE.read_text())
    if IS_WIN:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
        for n, val in saved.items():
            if val is None:
                try:
                    winreg.DeleteValue(key, n)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, n, 0, val[1], val[0])
        winreg.CloseKey(key)
        _refresh_inet()
    STATE_FILE.unlink()


# --------------------------------------------------------------------------
# verification through the proxy
# --------------------------------------------------------------------------
def via_proxy(url, port, timeout=12):
    px = f"http://127.0.0.1:{port}"
    op = ur.build_opener(ur.ProxyHandler({"http": px, "https": px}))
    try:
        with op.open(ur.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
            return r.status, r.read(65536)
    except urllib.error.HTTPError as e:
        e.close()
        return e.code, b""
    except Exception:
        return None, b""


def parse_geo(body):
    """(ip, country code or None, org) from the JSON of ipinfo.io / api.country.is / ipwho.is ..."""
    j = json.loads(body)
    ip = j.get("ip") or j.get("query")
    cc = j.get("country_code") or j.get("countryCode") or j.get("country")
    cc = cc.upper() if isinstance(cc, str) and len(cc) == 2 else None
    org = j.get("org") or (j.get("connection") or {}).get("org") or j.get("isp") or ""
    if not ip:
        raise ValueError("no ip in the answer")
    return ip, cc, str(org)


def geo_lookup(cfg):
    """Exit IP/country through the active route; the first provider that answers wins."""
    for url in [cfg.get("geo_url")] + list(cfg.get("geo_fallback_urls", [])):
        if not url:
            continue
        st, body = via_proxy(url, cfg["mixed_port"], min(cfg["verify_timeout"], 8))
        if st == 200:
            try:
                return parse_geo(body)
            except Exception:
                pass
    return None


def verify(cfg):
    """Exit-country check + strict sites (in parallel). Returns (ok, info)."""
    port, to = cfg["mixed_port"], cfg["verify_timeout"]
    strict = cfg["strict_urls"]
    with ThreadPoolExecutor(len(strict) + 1) as ex:
        geo_f = ex.submit(geo_lookup, cfg) if cfg.get("geo_url") else None
        site_f = [(u, ex.submit(via_proxy, u, port, to)) for u in strict]
        geo = geo_f.result() if geo_f else None
        sites = [(u, f.result()[0]) for u, f in site_f]
    info = "exit IP unknown"
    if geo:
        ip, cc, org = geo
        info = f"{ip} {cc or '??'} {org}".strip()
        if cc and cc in [c.upper() for c in cfg["blocked_countries"]]:
            return False, f"exit in blocked country ({info})"
    for url, st in sites:
        if st is None or st >= 400:
            return False, f"{url} -> {'no answer' if st is None else st} ({info})"
    return True, info


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------
class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.core = Core(cfg)
        self.names = {}
        self.rank = []          # ordered list of usable tags
        self.delays = {}
        self.idx = -1
        self.stop_evt = threading.Event()
        self.cleaned = False
        self.last_info = ""     # exit-IP info of the active route
        self.srv = None
        self.guard = None

    def label(self, tag):
        parts = tag.split("-")
        return " -> ".join(f"{t}:{self.names[t][:26]}" for t in parts)

    def measure_all(self, tags):
        def one(tag):
            ds = []
            for url in self.cfg["check_urls"]:
                d = self.core.delay(tag, url, self.cfg["delay_timeout_ms"])
                if d is None:
                    return tag, None
                ds.append(d)
            return tag, sum(ds) / len(ds)
        with ThreadPoolExecutor(8) as ex:
            return dict(ex.map(one, tags))

    def build_rank(self, A, B):
        chains = [f"{a}-{b}" for a in A for b in B]
        res = self.measure_all(chains + list(B) + list(A))
        self.delays = res

        def ordered(tags):
            return sorted([t for t in tags if res.get(t) is not None], key=lambda t: res[t])
        # preference: chains (A->B), then B alone, then A alone
        if self.cfg["rank_by_speed"]:
            self.rank = ordered(chains + list(B) + list(A))
        else:
            self.rank = ordered(chains) + ordered(list(B)) + ordered(list(A))
        self.idx = -1
        log(f"{len(self.rank)} routes usable "
            f"({len(ordered(chains))} chains, {len(ordered(list(B)))} B-only, "
            f"{len(ordered(list(A)))} A-only)")

    def go(self, step):
        """Switch to the next/prev suitable route (verified)."""
        with LOCK:
            if not self.rank:
                return "no usable route"
            n = len(self.rank)
            start = self.idx
            for k in range(n):
                if self.stop_evt.is_set():
                    return "stopping"
                if start < 0:
                    i = k if step > 0 else n - 1 - k
                else:
                    i = (start + step * (k + 1)) % n
                tag = self.rank[i]
                try:
                    self.core.select(tag)
                except Exception as e:
                    log("select failed", tag, e)
                    continue
                ok, info = verify(self.cfg)
                if ok:
                    self.idx = i
                    self.last_info = info
                    return (f"[{i + 1}/{n}] {self.label(tag)}  "
                            f"{self.delays[tag]:.0f}ms  exit: {info}")
                log(f"  skip {tag}: {info}")
            if 0 <= start < n:
                self.core.select(self.rank[start])
            return "no route passed verification; run 'rescan' or relax strict_urls"

    def go_to(self, i):
        """Switch to a specific ranked route (verified)."""
        with LOCK:
            if not 0 <= i < len(self.rank):
                return "no such route"
            prev = self.idx
            tag = self.rank[i]
            try:
                self.core.select(tag)
                ok, info = verify(self.cfg)
            except Exception as e:
                ok, info = False, f"select failed: {e}"
            if ok:
                self.idx = i
                self.last_info = info
                return (f"[{i + 1}/{len(self.rank)}] {self.label(tag)}  "
                        f"{self.delays[tag]:.0f}ms  exit: {info}")
            if 0 <= prev < len(self.rank):
                try:
                    self.core.select(self.rank[prev])
                except Exception as e:
                    log("could not go back to the previous route:", e)
            return f"route rejected: {info}"

    def status(self):
        with LOCK:
            if self.idx < 0:
                return "no active route"
            tag = self.rank[self.idx]
            ok, info = verify(self.cfg)
            return (f"[{self.idx + 1}/{len(self.rank)}] {self.label(tag)}  "
                    f"{self.delays[tag]:.0f}ms  exit: {info}")

    def listing(self):
        out = []
        for i, t in enumerate(self.rank):
            out.append(f"{'*' if i == self.idx else ' '} {i + 1:2d}. {self.delays[t]:5.0f}ms  "
                       f"{self.label(t)}")
        return "\n".join(out) or "empty"

    def rescan(self):
        with LOCK:
            A = {t: v for t, v in self.names_src["A"].items()}
            B = {t: v for t, v in self.names_src["B"].items()}
            self.build_rank(A, B)
            return self.go(1)

    def cleanup(self):
        if self.cleaned:
            return
        self.cleaned = True
        self.stop_evt.set()
        if self.srv:
            try:
                self.srv.shutdown()
                self.srv.server_close()
            except Exception:
                pass
        try:
            sys_proxy_restore()
            log("Windows proxy restored")
        except Exception as e:
            log("restore failed:", e)
        if self.guard:
            self.guard.kill()
        self.core.stop()

    # ---- control socket
    def handle(self, cmd):
        cmd = cmd.strip().lower()
        if cmd == "next":
            return self.go(1)
        if cmd == "prev":
            return self.go(-1)
        if cmd == "status":
            return self.status()
        if cmd == "list":
            return self.listing()
        if cmd == "rescan":
            return self.rescan()
        if cmd == "off":
            self.stop_evt.set()
            return "stopping"
        return "commands: next prev status list rescan off"

    def serve_control(self):
        app = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline().decode("utf-8", "replace")
                self.wfile.write(app.handle(line).encode("utf-8"))

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", self.cfg["control_port"]), H)
        srv.daemon_threads = True
        self.srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def watchdog(self):
        """Every 5 s: restart a dead core; every N s: check the route, fail over if dead."""
        secs, limit = max(self.cfg["watchdog_seconds"], 5), self.cfg["watchdog_failures"]
        fails, last_check, crashes = 0, time.time(), []
        while not self.stop_evt.wait(5):
            if not self.core.alive():
                now = time.time()
                crashes = [t for t in crashes if now - t < 300] + [now]
                if len(crashes) > 5:
                    log("sing-box keeps crashing: disabling and restoring the Windows proxy")
                    self.cleanup()
                    return
                log("sing-box stopped unexpectedly: restarting ...")
                try:
                    with LOCK:
                        tag = self.rank[self.idx] if self.idx >= 0 else None
                        self.core.restart(tag)
                    log("sing-box restarted")
                except Exception as e:
                    log("restart failed:", e)
                continue
            if self.cfg["watchdog_seconds"] <= 0 or time.time() - last_check < secs or self.idx < 0:
                continue
            last_check = time.time()
            st, _ = via_proxy(self.cfg["check_urls"][0], self.cfg["mixed_port"], 10)
            fails = 0 if st and st < 400 else fails + 1
            if fails >= limit:
                log("route looks dead, switching ...")
                log(self.go(1))
                fails = 0

    def console(self):
        help_ = "keys: [n]ext  [p]rev  [s]tatus  [l]ist  [r]escan  [q]uit/disable"
        print(help_)
        if IS_WIN:
            import msvcrt
            while not self.stop_evt.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getwch().lower()
                    cmd = {"n": "next", "p": "prev", "s": "status", "l": "list",
                           "r": "rescan", "q": "off"}.get(ch)
                    if cmd:
                        print(self.handle(cmd), flush=True)
                time.sleep(0.1)
        else:
            while not self.stop_evt.is_set():
                try:
                    ln = input().strip()
                except EOFError:
                    self.stop_evt.wait(1)
                    continue
                print(self.handle({"n": "next", "p": "prev", "s": "status", "l": "list",
                                   "r": "rescan", "q": "off"}.get(ln, ln)), flush=True)


def control_send(cfg, cmd, timeout=180):
    try:
        with socket.create_connection(("127.0.0.1", cfg["control_port"]), 3) as s:
            s.settimeout(timeout)
            s.sendall((cmd + "\n").encode())
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            return data.decode("utf-8", "replace")
    except OSError:
        return None


def start_session(cfg):
    """Fetch, test, activate the best route and set the proxy. Returns the App."""
    if control_send(cfg, "status", 5) is not None:
        sys.exit("already running (use: python chain.py off)")
    if STATE_FILE.exists():             # previous crash: bring settings back first
        sys_proxy_restore()
    srcs = load_sources()
    try:
        ensure_core()
    except Exception as e:
        sys.exit(f"cannot get sing-box: {e}\nPut a sing-box windows zip into the 'offline' folder "
                 "and start again.")
    for key in ("mixed_port", "api_port"):
        for _ in range(10):                   # a just-closed instance may need a moment
            if port_free(cfg[key]):
                break
            time.sleep(0.5)
        if not port_free(cfg[key]):
            kill_stale_core()                 # an orphan sing-box of a previous (killed) run?
            time.sleep(1)
        if not port_free(cfg[key]):
            sys.exit(f"port {cfg[key]} ({key}) is already in use; close the other program or "
                     "change it in config.json")
    validator = node_valid
    if not core_run(["version"])[0] == 0:
        validator = None

    A_nodes = fetch_nodes(srcs[0], "A")
    B_nodes = fetch_nodes(srcs[1], "B") if len(srcs) > 1 else []
    if not A_nodes and not B_nodes:
        sys.exit("no usable nodes in either subscription")
    log("probing nodes ...")
    A = pick(A_nodes, cfg["top_k"], cfg["tcp_timeout"], "A", validator) if A_nodes else {}
    B = pick(B_nodes, cfg["top_k"], cfg["tcp_timeout"], "B", validator) if B_nodes else {}

    app = App(cfg)
    app.names_src = {"A": A, "B": B}
    app.names = {t: n for t, (n, _) in {**A, **B}.items()}

    atexit.register(app.cleanup)
    if IS_WIN:
        import ctypes
        HandlerT = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def on_ctrl(_):
            app.cleanup()
            return False
        app._h = HandlerT(on_ctrl)       # keep a reference
        ctypes.windll.kernel32.SetConsoleCtrlHandler(app._h, True)

    try:
        conf = build_config(cfg, A, B, modern=True)
        ok, msg = core_check(conf)
        if not ok:                       # older core: retry without the DNS section
            log("modern config rejected, trying legacy layout:", msg.splitlines()[-1] if msg else "")
            conf = build_config(cfg, A, B, modern=False)
            ok, msg = core_check(conf)
            if not ok:
                raise SystemExit("sing-box rejected the configuration:\n" + msg)
        app.core.start(conf)
        log("sing-box started, testing routes ...")
        app.build_rank(A, B)
        log(app.go(1))
        if app.idx < 0:
            raise SystemExit("no route available")
        sys_proxy_set(cfg["mixed_port"], cfg["bypass"])
        log(f"Windows proxy -> 127.0.0.1:{cfg['mixed_port']}  (Chrome can be used now)")
        app.guard = start_guard()
        app.serve_control()
        if cfg["watchdog_seconds"] > 0:
            threading.Thread(target=app.watchdog, daemon=True).start()
    except BaseException:
        app.cleanup()
        raise
    return app


def serve():
    """Headless mode: no console input; runs until 'chain.py off' (or SIGTERM / Ctrl+C)."""
    cfg = load_cfg()
    app = start_session(cfg)
    try:
        import signal
        signal.signal(signal.SIGTERM, lambda *_: app.stop_evt.set())
    except Exception:
        pass
    log("serving; stop with: python chain.py off")
    try:
        while not app.stop_evt.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        app.cleanup()


def run():
    cfg = load_cfg()
    app = start_session(cfg)
    try:
        app.console()
    except KeyboardInterrupt:
        pass
    finally:
        app.cleanup()


def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "run"
    cfg = load_cfg()
    if cmd == "run":
        run()
    elif cmd == "serve":
        serve()
    elif cmd in ("install-core", "ensure"):
        if cmd == "install-core":
            install_core(force=True)
        else:
            ensure_core()
            print("sing-box OK:", core_run(["version"])[1].splitlines()[0])
    elif cmd == "guard" and len(sys.argv) > 2:
        guard(int(sys.argv[2]))
    elif cmd == "off":
        r = control_send(cfg, "off", 10)
        if r is None:                    # not running: restore settings, remove an orphan core
            sys_proxy_restore()
            kill_stale_core()
            print("not running; proxy settings restored if needed")
        else:
            print(r)
    elif cmd in ("next", "prev", "status", "list", "rescan"):
        r = control_send(cfg, cmd)
        print(r if r is not None else "not running (start with: python chain.py)")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
