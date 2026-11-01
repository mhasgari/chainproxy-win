#!/usr/bin/env python3
"""Emulator test of the TUN path: lab (A1 -> B1 shadowsocks nodes + fake internet) on this host, a fixed chain config
pushed to the app, VPN started, then a request from the adb shell (which goes through the TUN) must leave through B1.

    python3 dev/android/emu_vpn_test.py        (emulator must be running: dev/android/emu.sh start; APK installed)
"""
import json
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
HOST = "10.0.2.2"            # the host as seen from the emulator
LAB_PORT, NODE_BASE = 38080, 38101


def adb(*args, check=True, timeout=60):
    r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f"adb {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout.strip()


def ok(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg, flush=True)
    return cond


def request(path, timeout=8):
    # sleep keeps stdin open so nc waits for the answer instead of quitting at EOF
    cmd = f"(printf 'GET {path} HTTP/1.0\\r\\nHost: x\\r\\n\\r\\n'; sleep 3) | toybox nc -w 5 {LAB_IP} {LAB_PORT}"
    return adb("shell", cmd, check=False, timeout=timeout + 10)


def main():
    lab = Lab("127.0.0.1", LAB_PORT, NODE_BASE, "/usr/bin/sing-box", workdir=ROOT / "dev" / "artifacts" / "android-lab")
    lab.start()
    passed = True
    try:
        def ss(tag, host=HOST, **extra):
            return {"type": "shadowsocks", "tag": tag, "server": host, "server_port": lab.port(tag),
                    "method": METHOD, "password": lab.password(tag), **extra}
        config = {"log": {"level": "debug", "output": "box.log", "timestamp": True},
                  "inbounds": [{"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30"], "mtu": 1400,
                                "auto_route": True, "stack": "gvisor"}],
                  "outbounds": [ss("A1"), ss("B1", host="127.0.0.1", detour="A1"),   # B1 is dialed BY the A node, i.e. from the host
                               {"type": "direct", "tag": "direct"}],
                  "route": {"auto_detect_interface": True, "final": "B1"}}
        tmp = HERE.parent.parent / "dev" / "artifacts" / "android-config.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(config, indent=1))
        adb("shell", f"run-as {PKG} mkdir -p files")
        adb("push", str(tmp), "/data/local/tmp/config.json")
        adb("shell", f"run-as {PKG} sh -c 'cp /data/local/tmp/config.json files/config.json'")
        adb("shell", f"cmd appops set {PKG} ACTIVATE_VPN allow", check=False)
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action stop", check=False)   # a leftover session would ignore the new config
        time.sleep(3)
        adb("shell", f"run-as {PKG} rm -f files/core/box.log", check=False)
        adb("logcat", "-c")
        before = request("/whoami")
        passed &= ok(before.strip() == "" or "127.0.0.21" not in before, f"before the VPN the fake address is unreachable ({before!r})")
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action start_config")
        up = False
        for _ in range(30):
            time.sleep(1)
            if adb("shell", "ip addr show | grep -c 172.19.0.1 || true", check=False).strip() not in ("", "0"):
                up = True
                break
        passed &= ok(up, "TUN interface 172.19.0.1 exists")
        time.sleep(2)
        body = request("/whoami")
        passed &= ok(EXPECT_EXIT in body, f"traffic from the shell leaves through B1 ({body.strip()[-60:]!r})")
        ev = lab.chain_evidence()
        passed &= ok(bool(ev["a_nodes_forwarding_to_B1"]) and ev["B1_saw_hop_from_A"], f"lab logs prove phone -> A -> B1 ({ev})")
        adb("shell", f"am start -n {PKG}/.MainActivity --es debug_action stop")
        time.sleep(3)
        gone = adb("shell", "ip addr show | grep -c 172.19.0.1 || true", check=False).strip() in ("", "0")
        passed &= ok(gone, "TUN interface removed after stop")
    finally:
        lab.stop()
        logs = adb("logcat", "-d", "-s", "ChainVpnService:*", "ChainPlatform:*", "AndroidRuntime:E", check=False)
        (ROOT / "dev" / "artifacts" / "android-vpn-test.log").write_text(logs)
    print("ANDROID VPN RESULT: " + ("PASS" if passed else "FAIL"))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
