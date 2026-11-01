#!/usr/bin/env python3
"""Emulator test of the whole Android session flow with the lab: sources (v2ray profiles), probing, config, TUN,
ranking, verification, next/prev, traffic through the chain.

    python3 dev/android/emu_session_test.py     (emulator running: dev/android/emu.sh start; debug APK installed)
"""
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "dev" / "lab"))
from lab import EXPECT_EXIT, METHOD, Lab  # noqa: E402
from e2e_client import LAB_IP  # noqa: E402

PKG = "app.chainproxy"
HOST = "10.0.2.2"
LAB_PORT, NODE_BASE = 38080, 38101


def adb(*args, check=True, timeout=60):
    r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f"adb {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout.strip()


def ok(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg, flush=True)
    return cond


def request(path):
    cmd = f"(printf 'GET {path} HTTP/1.0\\r\\nHost: x\\r\\n\\r\\n'; sleep 3) | toybox nc -w 5 {LAB_IP} {LAB_PORT}"
    return adb("shell", cmd, check=False, timeout=20)


def session_log():
    return adb("logcat", "-d", "-s", "ChainSession:*", check=False)


def wait_log(pattern, seconds, more_than=0):
    """First match once the log holds more than `more_than` matches (to wait for a NEW line)."""
    end = time.time() + seconds
    while time.time() < end:
        found = list(re.finditer(pattern, session_log()))
        if len(found) > more_than:
            return found[-1]
        time.sleep(1)
    return None


def link(lab, tag, host):
    userinfo = base64.b64encode(f"{METHOD}:{lab.password(tag)}".encode()).decode()
    return f"ss://{userinfo}@{host}:{lab.port(tag)}#lab-{tag}"


def main():
    lab = Lab("127.0.0.1", LAB_PORT, NODE_BASE, "/usr/bin/sing-box", workdir=ROOT / "dev" / "artifacts" / "android-lab")
    lab.start()
    passed = True
    try:
        base = f"http://{LAB_IP}:{LAB_PORT}"
        cfg = {"check_urls": [f"{base}/generate_204"], "geo_url": f"{base}/geo", "strict_urls": [f"{base}/strict"],
               "geo_fallback_urls": [], "lantern_enabled": False, "blocked_countries": ["IR"], "direct_suffixes": [],
               "private_direct": False, "watchdog_seconds": 0, "tcp_timeout": 1.5, "exit_subscription": "",
               # A nodes are dialed by the phone (10.0.2.2 = host), B nodes by the A node (127.0.0.1 = host)
               "first_profiles": link(lab, "A1", HOST) + "\n" + link(lab, "A2", HOST),
               "exit_profiles": link(lab, "B1", "127.0.0.1") + "\n" + link(lab, "B2", "127.0.0.1")}
        tmp = ROOT / "dev" / "artifacts" / "android-session-config.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(cfg, indent=1))
        adb("shell", f"run-as {PKG} mkdir -p files")
        adb("push", str(tmp), "/data/local/tmp/chain-config.json")
        adb("shell", f"run-as {PKG} sh -c 'cp /data/local/tmp/chain-config.json files/chain-config.json'")
        adb("shell", f"cmd appops set {PKG} ACTIVATE_VPN allow", check=False)
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action stop", check=False)
        time.sleep(3)
        adb("logcat", "-c")
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action start")
        m = wait_log(r"\[\d+/\d+\] .*exit: .*", 90)
        passed &= ok(bool(m), f"session reached a verified route ({m.group(0)[:110] if m else session_log()[-600:]!r})")
        time.sleep(2)
        body = request("/whoami")
        passed &= ok(EXPECT_EXIT in body, f"traffic from the phone leaves through a chain ({body.strip()[-40:]!r})")
        ev = lab.chain_evidence()
        passed &= ok(bool(ev["a_nodes_forwarding_to_B1"]) and ev["B1_saw_hop_from_A"], f"lab logs prove phone -> A -> B1 ({ev})")
        log = session_log()
        passed &= ok("skip " in log and "B2" in log or "[2/" in log or "routes usable" in log, "ranking happened (routes usable line)")
        pat = r"\[\d+/\d+\] .*exit: .*"
        before = len(re.findall(pat, session_log()))
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action next")
        m2 = wait_log(pat, 60, before)
        passed &= ok(bool(m2) and m2.group(0) != m.group(0), f"next activated another verified route ({m2.group(0)[:90] if m2 else None!r})")
        time.sleep(2)
        body = request("/whoami")
        passed &= ok(EXPECT_EXIT in body, f"traffic after next still leaves through B1 ({body.strip()[-40:]!r})")
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action stop")
        time.sleep(4)
        gone = adb("shell", "ip addr show | grep -c 172.19.0.1 || true", check=False).strip() in ("", "0")
        passed &= ok(gone, "TUN interface removed after stop")
    finally:
        lab.stop()
        (ROOT / "dev" / "artifacts" / "android-session-test.log").write_text(
            adb("logcat", "-d", "-s", "ChainSession:*", "ChainVpnService:*", "ChainPlatform:*", "AndroidRuntime:E", check=False))
    print("ANDROID SESSION RESULT: " + ("PASS" if passed else "FAIL"))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
