#!/usr/bin/env python3
"""
End-to-end test on the Linux host with the REAL sing-box (no VM, no Windows registry).

    python3 dev/lab/e2e_local.py            (or: make e2e-local)

Starts the lab on 127.0.0.1, copies the app to a temp folder, runs dev/lab/e2e_client.py
against it with the host's sing-box as the client core, then checks the lab's own logs for
proof that traffic really went client -> A -> B1. Artifacts: dev/artifacts/local-<time>/.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from lab import EXPECT_EXIT, EXPECT_RANKED, EXPECT_VALID, Lab  # noqa: E402

APP_FILES = ["chain.py", "gui.py", "config.json", "subs.txt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--singbox", default=None, help="sing-box binary (default: PATH or dev/bin)")
    ap.add_argument("--lab-port", type=int, default=28080)
    ap.add_argument("--node-base", type=int, default=28101)
    a = ap.parse_args()

    singbox = a.singbox or shutil.which("sing-box") or str(ROOT / "dev" / "bin" / "sing-box")
    if not Path(singbox).exists() and not shutil.which(singbox):
        sys.exit("sing-box not found: run dev/setup-cachyos.sh")
    ver = subprocess.run([singbox, "version"], capture_output=True, text=True).stdout
    print(ver.strip().splitlines()[0] if ver else "sing-box version unknown")
    if "with_clash_api" not in ver:
        sys.exit("this sing-box build lacks with_clash_api (needed by chain.py); "
                 "run: dev/setup-cachyos.sh --official-singbox")

    art = ROOT / "dev" / "artifacts" / time.strftime("local-%Y%m%d-%H%M%S")
    art.mkdir(parents=True)
    app = Path(tempfile.mkdtemp(prefix="chainproxy-app-"))
    for f in APP_FILES:
        shutil.copy(ROOT / f, app / f)

    lab = Lab("127.0.0.1", a.lab_port, a.node_base, singbox, workdir=art / "lab")
    rc = 1
    try:
        lab.start()
        cmd = [sys.executable, str(HERE / "e2e_client.py"), "run", "--app", str(app),
               "--lab-host", "127.0.0.1", "--lab-port", str(a.lab_port),
               "--ports", "28808,28090,28091", "--core", singbox,
               "--expect-exit", EXPECT_EXIT, "--expect-valid", str(EXPECT_VALID),
               "--expect-ranked", str(EXPECT_RANKED)]
        # the test talks to 127.0.0.1 and to the lab's fake address: a desktop proxy from the
        # environment (http_proxy & co.) must not get in the way
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        with open(art / "client.log", "w") as out:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 env=env)
            for line in p.stdout:
                print(line, end="")
                out.write(line)
            rc = p.wait()
        ev = lab.chain_evidence()
        print(f"lab evidence: {ev}")
        ok_chain = bool(ev["a_nodes_forwarding_to_B1"]) and ev["B1_saw_hop_from_A"]
        print(("PASS  " if ok_chain else "FAIL  ") + "lab logs prove client -> A -> B1")
        ok_exit = ev["whoami_sources"] == [EXPECT_EXIT]
        print(("PASS  " if ok_exit else "FAIL  ") + f"all probes left through B1 ({ev['whoami_sources']})")
        if not (ok_chain and ok_exit):
            rc = 1
    finally:
        lab.stop()
        for f in ("runtime/config.json", "runtime/core.log", "runtime/e2e-serve.log"):
            if (app / f).exists():
                shutil.copy(app / f, art / Path(f).name)
        shutil.rmtree(app, ignore_errors=True)
    print(f"artifacts: {art}")
    print("LOCAL E2E:", "PASS" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
