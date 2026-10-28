#!/usr/bin/env python3
"""
Hermetic end-to-end lab for chainproxy (runs on the Linux host, needs a real `sing-box`).

It starts ONE sing-box process that plays five subscription nodes and a tiny HTTP server
that plays "the internet":

    node  port        role / exit identity
    A1    base+0      shadowsocks, live   exit source 127.0.0.11
    A2    base+1      shadowsocks, live   exit source 127.0.0.12
    A3    base+2      nothing listens (dead node -> must be filtered out)
    B1    base+3      shadowsocks, live   exit source 127.0.0.21  geo DE  -> the expected exit
    B2    base+4      shadowsocks, live   exit source 127.0.0.22  geo IR  -> blocked country

The client (chain.py) is configured to test against the fake public address LAB_IP
(198.51.100.10, TEST-NET-2). A node that receives a request for LAB_IP rewrites it to
127.0.0.1:<lab_port> and dials from its own loopback source address, so the HTTP server
knows WHICH node the request left from:

    /generate_204   204 (delay tests)
    /whoami         the source address (= exit identity)
    /geo            ipinfo-like JSON; country IR for B2, DE otherwise
    /strict         403 for the A-only exits (A1/A2), 200 otherwise
    /subA, /subB    the two subscriptions (A is base64, B is plain text)

Expected result for chain.py: 8 ranked routes (4 chains, 2 B, 2 A), of which exactly 3 pass
verification (A1-B1, A2-B1, B1); every request leaves through B1 (127.0.0.21).

Manual use:  python3 dev/lab/lab.py --listen 192.168.122.1      (Ctrl+C to stop)
"""
import argparse
import base64
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_client import LAB_IP, client_config  # noqa: E402

METHOD = "aes-128-gcm"
NODES = {           # tag: (port offset, exit source or None for a dead node)
    "A1": (0, "127.0.0.11"),
    "A2": (1, "127.0.0.12"),
    "A3": (2, None),
    "B1": (3, "127.0.0.21"),
    "B2": (4, "127.0.0.22"),
}
GEO = {"127.0.0.22": "IR"}                       # everything else: DE
STRICT_BLOCKED = {"127.0.0.11", "127.0.0.12"}    # A-only exits fail the strict site
EXPECT_EXIT = "127.0.0.21"
EXPECT_VALID = 3
EXPECT_RANKED = 8
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def port_free(host, port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class Lab:
    def __init__(self, listen="127.0.0.1", lab_port=18080, node_base=18101,
                 singbox=None, workdir=None):
        self.listen = listen
        self.lab_port = lab_port
        self.node_base = node_base
        self.singbox = singbox or shutil.which("sing-box")
        self.dir = Path(workdir or tempfile.mkdtemp(prefix="chainproxy-lab-"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc = None
        self.servers = []
        self.requests = []                      # (source, path) seen by the HTTP server
        self.logf = None

    # ------------------------------------------------------------ description
    def port(self, tag):
        return self.node_base + NODES[tag][0]

    def password(self, tag):
        return f"lab-{tag}-secret"

    def link(self, tag):
        userinfo = base64.b64encode(f"{METHOD}:{self.password(tag)}".encode()).decode()
        return f"ss://{userinfo}@{self.listen}:{self.port(tag)}#lab-{tag}"

    def sub_a(self):
        return base64.b64encode("\n".join(self.link(t) for t in ("A1", "A2", "A3")).encode()).decode()

    def sub_b(self):
        return "\n".join(self.link(t) for t in ("B1", "B2")) + "\n"

    def client_config(self, **extra):
        return client_config(self.lab_port, **extra)

    def server_config(self):
        live = [t for t, (_, src) in NODES.items() if src]
        inbounds = [{"type": "shadowsocks", "tag": t, "listen": self.listen,
                     "listen_port": self.port(t), "method": METHOD,
                     "password": self.password(t)} for t in live]
        outbounds = [{"type": "direct", "tag": "plain"}]
        rules = []
        for t in live:
            outbounds.append({"type": "direct", "tag": f"exit-{t}",
                              "inet4_bind_address": NODES[t][1]})
            rules.append({"inbound": [t], "ip_cidr": [f"{LAB_IP}/32"], "action": "route",
                          "outbound": f"exit-{t}", "override_address": "127.0.0.1"})
        return {"log": {"level": "info", "timestamp": True},
                "inbounds": inbounds, "outbounds": outbounds,
                "route": {"rules": rules, "final": "plain"}}

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if not self.singbox:
            raise RuntimeError("sing-box not found on this host (run dev/setup-cachyos.sh)")
        hosts = {self.listen, "127.0.0.1"}
        busy = [f"{h}:{p}" for h in hosts for p in [self.lab_port]] + \
               [f"{self.listen}:{self.port(t)}" for t in NODES]
        busy = [hp for hp in busy if not port_free(hp.rsplit(":", 1)[0], int(hp.rsplit(":", 1)[1]))]
        if busy:
            raise RuntimeError(f"lab ports already in use: {', '.join(busy)}")

        cfg = self.dir / "server.json"
        cfg.write_text(json.dumps(self.server_config(), indent=1))
        chk = subprocess.run([self.singbox, "check", "-c", str(cfg)], capture_output=True, text=True)
        if chk.returncode != 0:
            raise RuntimeError("host sing-box rejected the lab config:\n" + chk.stdout + chk.stderr)

        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="text/plain"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):
                src = self.client_address[0]
                path = self.path.split("?")[0]
                lab.requests.append((src, path))
                if path == "/generate_204":
                    return self._send(204)
                if path == "/whoami":
                    return self._send(200, src.encode())
                if path == "/geo":
                    body = json.dumps({"ip": src, "country": GEO.get(src, "DE"), "org": "chainproxy-lab"})
                    return self._send(200, body.encode(), "application/json")
                if path == "/strict":
                    return self._send(403 if src in STRICT_BLOCKED else 200, b"strict")
                if path == "/subA":
                    return self._send(200, lab.sub_a().encode())
                if path == "/subB":
                    return self._send(200, lab.sub_b().encode())
                self._send(404)

        for host in sorted(hosts):
            srv = ThreadingHTTPServer((host, self.lab_port), Handler)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers.append(srv)

        self.logf = open(self.dir / "lab-singbox.log", "w")
        self.proc = subprocess.Popen([self.singbox, "run", "-c", str(cfg)],
                                     stdout=self.logf, stderr=subprocess.STDOUT)
        deadline = time.time() + 15
        pending = [t for t, (_, src) in NODES.items() if src]
        while pending and time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("lab sing-box exited:\n" + self.log_text())
            pending = [t for t in pending if port_free(self.listen, self.port(t))]
            time.sleep(0.2)
        if pending:
            raise RuntimeError(f"lab nodes did not start: {pending}\n" + self.log_text())
        return self

    def stop(self):
        for srv in self.servers:
            srv.shutdown()
            srv.server_close()
        self.servers = []
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.logf:
            self.logf.close()
            self.logf = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ------------------------------------------------------------ evidence
    def log_text(self):
        p = self.dir / "lab-singbox.log"
        return ANSI.sub("", p.read_text(errors="replace")) if p.exists() else ""

    def forwarded(self, tag, host, port):
        """Did node <tag> receive a request for host:port (i.e. was it a hop toward it)?"""
        pat = re.compile(rf"inbound/shadowsocks\[{tag}\]: inbound connection to {re.escape(host)}:{port}\b")
        return bool(pat.search(self.log_text()))

    def seen_from(self, tag, ip):
        pat = re.compile(rf"inbound/shadowsocks\[{tag}\]: inbound connection from \[?{re.escape(ip)}\]?:")
        return bool(pat.search(self.log_text()))

    def chain_evidence(self, a_src_host=None):
        """Both halves of 'client -> A -> B1': an A node dialled B1, and B1 saw that hop."""
        via_a = [t for t in ("A1", "A2") if self.forwarded(t, self.listen, self.port("B1"))]
        b1_from_a = self.seen_from("B1", self.listen) if a_src_host is None else self.seen_from("B1", a_src_host)
        exits = sorted({src for src, path in self.requests if path == "/whoami"})
        return {"a_nodes_forwarding_to_B1": via_a, "B1_saw_hop_from_A": b1_from_a,
                "whoami_sources": exits}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--listen", default="127.0.0.1", help="address the nodes/subscriptions listen on")
    ap.add_argument("--lab-port", type=int, default=18080)
    ap.add_argument("--node-base", type=int, default=18101)
    ap.add_argument("--singbox", default=None)
    a = ap.parse_args()
    lab = Lab(a.listen, a.lab_port, a.node_base, a.singbox)
    lab.start()
    print(f"lab running in {lab.dir}")
    print(f"  subscriptions: http://{a.listen}:{a.lab_port}/subA   http://{a.listen}:{a.lab_port}/subB")
    print("  client config.json for chain.py:")
    print(json.dumps(lab.client_config(), indent=2))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        lab.stop()


if __name__ == "__main__":
    main()
