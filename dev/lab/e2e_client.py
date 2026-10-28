#!/usr/bin/env python3
"""
Client half of the end-to-end test. Runs where chain.py runs (the Linux host for
`make e2e-local`, or inside the Windows VM for `make vm-e2e`), against a running lab
(dev/lab/lab.py) on --lab-host.

    e2e_client.py run      full CLI flow: start `chain.py serve`, check ranking, exit IP,
                           next/prev/rescan, Windows registry handling, `off`, restoration
    e2e_client.py prepare  only write subs.txt + config.json for the lab (used by the GUI test)
    e2e_client.py probe    one request through the local proxy; checks the exit identity
    e2e_client.py reg      Windows only: reg save | sentinel | check-active | check-sentinel | restore

Only the standard library is used, so it runs on a fresh Windows Python.
Prints PASS/FAIL lines and a final line `E2E_RESULT {json}`; exit code 0 = all passed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request as ur
from pathlib import Path

LAB_IP = "198.51.100.10"         # TEST-NET-2: never routed; only lab nodes rewrite it
IS_WIN = os.name == "nt"
ROOT = Path(__file__).resolve().parents[2]
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
REG_NAMES = ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL")
REG_SAVE = Path(tempfile.gettempdir()) / "chainproxy-e2e-registry.json"
SENTINEL = {"ProxyEnable": [0, 4], "ProxyServer": ["10.9.9.9:9", 1],
            "ProxyOverride": ["sentinel.example", 1],
            "AutoConfigURL": ["http://sentinel.example/proxy.pac", 1]}   # [value, REG_* type]

RESULTS = []


def check(ok, msg):
    RESULTS.append((bool(ok), msg))
    print(("PASS  " if ok else "FAIL  ") + msg, flush=True)
    return ok


def client_config(lab_port, **extra):
    """config.json overrides that point chain.py at the lab."""
    base = f"http://{LAB_IP}:{lab_port}"
    cfg = {
        "check_urls": [f"{base}/generate_204"],
        "geo_url": f"{base}/geo",
        "strict_urls": [f"{base}/strict"],
        "geo_fallback_urls": [],
        "blocked_countries": ["IR"],
        "direct_suffixes": [],
        "private_direct": False,
        "watchdog_seconds": 0,
        "top_k": 5,
        "tcp_timeout": 1.5,
        "delay_timeout_ms": 5000,
        "log_level": "info",
    }
    cfg.update(extra)
    return cfg


# ---------------------------------------------------------------- app helpers
def load_chain(app):
    sys.path.insert(0, str(app))
    import chain                     # noqa: E402  (the app under test)
    return chain


def prepare(a):
    app = Path(a.app)
    (app / "subs.txt").write_text(
        "# written by dev/lab/e2e_client.py\n"
        f"http://{a.lab_host}:{a.lab_port}/subA\nhttp://{a.lab_host}:{a.lab_port}/subB\n",
        encoding="utf-8")
    extra = {}
    if a.ports:
        m, api, ctl = (int(x) for x in a.ports.split(","))
        extra = {"mixed_port": m, "api_port": api, "control_port": ctl}
    (app / "config.json").write_text(json.dumps(client_config(a.lab_port, **extra), indent=2),
                                     encoding="utf-8")
    print(f"prepared {app} for lab http://{a.lab_host}:{a.lab_port}", flush=True)


def probe(port, lab_port, timeout=15):
    """GET /whoami through the local mixed proxy -> exit identity seen by the lab."""
    px = f"http://127.0.0.1:{port}"
    op = ur.build_opener(ur.ProxyHandler({"http": px, "https": px}))
    try:
        with op.open(f"http://{LAB_IP}:{lab_port}/whoami", timeout=timeout) as r:
            return r.read().decode().strip()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"error: {e}"


# ---------------------------------------------------------------- registry (Windows)
def reg_read():
    import winreg
    out = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
        for n in REG_NAMES:
            try:
                v, t = winreg.QueryValueEx(k, n)
                out[n] = [v, t]
            except FileNotFoundError:
                out[n] = None
    return out


def reg_write(values):
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS) as k:
        for n, val in values.items():
            if val is None:
                try:
                    winreg.DeleteValue(k, n)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, n, 0, val[1], val[0])
    ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
    ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)


def reg_cmd(action, mixed_port=10808):
    if not IS_WIN:
        return check(True, f"reg {action}: skipped (not Windows)")
    if action == "save":
        if not REG_SAVE.exists():                 # never overwrite the real original
            REG_SAVE.write_text(json.dumps(reg_read()))
        return check(True, f"registry original saved to {REG_SAVE}")
    if action == "sentinel":
        reg_write(SENTINEL)
        return check(reg_read() == SENTINEL, "sentinel proxy settings written")
    if action == "check-active":
        cur = reg_read()
        return check(cur["ProxyEnable"] == [1, 4]
                     and cur["ProxyServer"] == [f"127.0.0.1:{mixed_port}", 1]
                     and cur["AutoConfigURL"] is None,
                     f"Windows proxy points at 127.0.0.1:{mixed_port}, PAC removed ({cur})")
    if action == "check-sentinel":
        cur = reg_read()
        return check(cur == SENTINEL, f"original proxy settings restored exactly ({cur})")
    if action == "restore":
        if REG_SAVE.exists():
            reg_write(json.loads(REG_SAVE.read_text()))
            REG_SAVE.unlink()
        return check(True, "registry restored to the pre-test state")
    raise SystemExit(f"unknown reg action {action}")


# ---------------------------------------------------------------- full flow
def run(a):
    app = Path(a.app).resolve()
    prepare(a)
    chain = load_chain(app)
    cfg = chain.load_cfg()
    port = cfg["mixed_port"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if a.core:
        env["CHAIN_CORE"] = a.core
    log_path = app / "runtime" / "e2e-serve.log"
    log_path.parent.mkdir(exist_ok=True)
    proc = None
    if IS_WIN:
        reg_cmd("save")
        reg_cmd("sentinel")
    try:
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen([sys.executable, "-X", "utf8", str(app / "chain.py"), "serve"],
                                    cwd=app, env=env, stdout=logf, stderr=subprocess.STDOUT)
            status = None
            deadline = time.time() + a.start_timeout
            while time.time() < deadline and proc.poll() is None:
                status = chain.control_send(cfg, "status", 5)
                if status and status.startswith("["):
                    break
                time.sleep(1)
            if not check(status and status.startswith("["), f"chain.py serve came up: {status!r}"):
                print("---- serve log ----\n" + log_path.read_text(errors="replace")[-4000:])
                return

            check(re.search(r"\] A\d:\S+ -> B\d:lab-B1\b", status), f"first active route is an A->B1 chain ({status})")
            check(" DE " in status + " ", "exit country shown as DE (geo lookup through the route)")
            if IS_WIN:
                reg_cmd("check-active", port)
            ip = probe(port, a.lab_port)
            check(ip == a.expect_exit, f"traffic exits through B1: whoami={ip!r}")

            lst = chain.control_send(cfg, "list", 10) or ""
            rows = [l for l in lst.splitlines() if l.strip()]
            check(len(rows) == a.expect_ranked, f"{len(rows)} ranked routes (expected {a.expect_ranked})")
            check(not any("A3" in r for r in rows), "dead node A3 filtered out")
            chains = [r for r in rows if "->" in r]
            check(len(chains) == 4 and rows[:4] == chains, "chains are ranked first")

            first = int(re.match(r"\[(\d+)/", status).group(1))
            seen = [first]
            for i in range(a.expect_valid):
                r = chain.control_send(cfg, "next", 120) or ""
                m = re.match(r"\[(\d+)/", r)
                check(m, f"next #{i + 1}: {r!r}")
                if m:
                    seen.append(int(m.group(1)))
                    check("lab-B2" not in r.split("exit:")[0], "route via lab-B2 (blocked country) skipped")
                ip = probe(port, a.lab_port)
                check(ip == a.expect_exit, f"after next #{i + 1}: exit {ip!r}")
            check(len(set(seen[:-1])) == a.expect_valid and seen[-1] == first,
                  f"next cycles through exactly {a.expect_valid} valid routes and wraps ({seen})")

            r = chain.control_send(cfg, "prev", 120) or ""
            check(r.startswith("[") and probe(port, a.lab_port) == a.expect_exit, f"prev: {r!r}")
            r = chain.control_send(cfg, "rescan", 300) or ""
            check(r.startswith("[") and probe(port, a.lab_port) == a.expect_exit, f"rescan: {r!r}")

            r = chain.control_send(cfg, "off", 10)
            check(r == "stopping", f"off acknowledged: {r!r}")
            try:
                proc.wait(30)
                check(True, "chain.py exited after off")
            except subprocess.TimeoutExpired:
                check(False, "chain.py exited after off")
            check(chain.control_send(cfg, "status", 3) is None, "control socket closed")
            check(chain.port_free(port), f"proxy port {port} released")
            if IS_WIN:
                reg_cmd("check-sentinel")
                check(not (app / ".proxy_state.json").exists(), "saved-state file removed")
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        if IS_WIN:
            try:
                reg_cmd("restore")
            except Exception as e:
                print("registry restore failed:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["run", "prepare", "probe", "reg"])
    ap.add_argument("reg_action", nargs="?")
    ap.add_argument("--app", default=str(ROOT))
    ap.add_argument("--lab-host", default="127.0.0.1")
    ap.add_argument("--lab-port", type=int, default=18080)
    ap.add_argument("--ports", default="", help="mixed,api,control for chain.py (default: its own)")
    ap.add_argument("--core", default="", help="sing-box binary to use (sets CHAIN_CORE)")
    ap.add_argument("--expect-exit", default="127.0.0.21")
    ap.add_argument("--expect-valid", type=int, default=3)
    ap.add_argument("--expect-ranked", type=int, default=8)
    ap.add_argument("--start-timeout", type=int, default=240)
    ap.add_argument("--mixed-port", type=int, default=0, help="for probe / reg check-active")
    a = ap.parse_args()

    if a.action == "prepare":
        prepare(a)
        return 0
    if a.action == "probe":
        port = a.mixed_port or load_chain(Path(a.app)).load_cfg()["mixed_port"]
        ip = probe(port, a.lab_port)
        check(ip == a.expect_exit, f"exit {ip!r} (expected {a.expect_exit})")
    elif a.action == "reg":
        port = a.mixed_port or load_chain(Path(a.app)).load_cfg()["mixed_port"]
        reg_cmd(a.reg_action, port)
    else:
        run(a)
    failed = [m for ok, m in RESULTS if not ok]
    print("E2E_RESULT " + json.dumps({"passed": len(RESULTS) - len(failed), "failed": failed}), flush=True)
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
