"""
Tests for the developer tooling itself (lab, e2e client, VM driver) - no VM, no real sing-box.

    python3 dev/tests/test_devtools.py      (make test-dev)

A fake `sing-box` (only binds the inbound ports) and fake `virsh`/`ssh`/`scp` executables are
put on PATH so the plumbing can be exercised end to end on Linux.
"""
import base64
import importlib
import json
import os
import socket
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "dev" / "lab"), str(ROOT / "dev" / "vm")]
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

FAKE_SINGBOX = r'''#!/usr/bin/env python3
import json, socket, sys, time
cmd = sys.argv[1]
if cmd == "version":
    print("sing-box version 0.0.0-fake\nTags: with_clash_api"); sys.exit(0)
cfg = json.load(open(sys.argv[sys.argv.index("-c") + 1]))
if cmd == "check":
    sys.exit(0)
socks = []
for ib in cfg["inbounds"]:
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((ib["listen"], ib["listen_port"])); s.listen(5); socks.append(s)
print("INFO started", flush=True)
while True:
    time.sleep(1)
'''

FAKE_VIRSH = r'''#!/usr/bin/env python3
import sys
args = sys.argv[3:]          # skip: -c URI
if args[0] == "domstate": print("running")
elif args[0] == "domifaddr":
    print(" Name       MAC address          Protocol     Address")
    print("-------------------------------------------------------------------------------")
    print(" vnet0      52:54:00:aa:bb:cc    ipv4         192.168.122.57/24")
elif args[0] == "net-dumpxml":
    print("<network><name>default</name><ip address='192.168.122.1' netmask='255.255.255.0'/></network>")
else: sys.exit(1)
'''

FAKE_SSH = r'''#!/usr/bin/env python3
import base64, os, sys
log = os.environ["FAKE_LOG"]
script = ""
if "-EncodedCommand" in sys.argv[-1]:
    script = base64.b64decode(sys.argv[-1].split()[-1]).decode("utf-16-le")
with open(log, "a") as f:
    f.write("SSH " + sys.argv[-2] + "\n" + script + "\n----\n")
if "echo chainproxy-ok" in sys.argv[-1]: print("chainproxy-ok")
if "tar -xzf" in script: print("deployed to C:\\Users\\tester\\chainproxy-test\\repo")
'''

FAKE_SCP = r'''#!/usr/bin/env python3
import os, shutil, sys
src, dst = sys.argv[-2], sys.argv[-1]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(f"SCP {src} -> {dst}\n")
shutil.copy(src, os.path.join(os.environ["FAKE_DROP"], os.path.basename(dst.split(":", 1)[1])))
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url, src=None):
    if src:                                             # request from a specific loopback source
        host, rest = url.split("//", 1)[1].split("/", 1)
        h, p = host.split(":")
        with socket.create_connection((h, int(p)), source_address=(src, 0)) as s:
            s.sendall(f"GET /{rest} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            data = b""
            while chunk := s.recv(4096):
                data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        return int(head.split()[1]), body.decode()
    try:
        with NOPROXY.open(url, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def write_exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class LabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        write_exe(cls.tmp / "sing-box", FAKE_SINGBOX)
        import lab
        cls.labmod = lab
        base = free_port()
        cls.lab = lab.Lab("127.0.0.1", free_port(), base if base < 60000 else 40000,
                          singbox=str(cls.tmp / "sing-box"), workdir=cls.tmp / "lab")
        cls.lab.start()
        cls.url = f"http://127.0.0.1:{cls.lab.lab_port}"

    @classmethod
    def tearDownClass(cls):
        cls.lab.stop()

    def test_subscriptions_parse_with_the_app_parser(self):
        import chain
        st, a = get(self.url + "/subA")
        st2, b = get(self.url + "/subB")
        self.assertEqual((st, st2), (200, 200))
        a_text = base64.b64decode(a).decode()            # list A is served base64-encoded
        nodes = [chain.parse_node(l) for l in a_text.splitlines() + b.splitlines()]
        self.assertTrue(all(nodes))
        self.assertEqual([n[0] for n in nodes], ["lab-A1", "lab-A2", "lab-A3", "lab-B1", "lab-B2"])
        self.assertEqual(nodes[3][1]["server_port"], self.lab.port("B1"))
        self.assertEqual(nodes[3][1]["password"], self.lab.password("B1"))

    def test_identity_endpoints(self):
        self.assertEqual(get(self.url + "/generate_204")[0], 204)
        self.assertEqual(get(self.url + "/whoami", "127.0.0.21"), (200, "127.0.0.21"))
        self.assertEqual(json.loads(get(self.url + "/geo", "127.0.0.21")[1])["country"], "DE")
        self.assertEqual(json.loads(get(self.url + "/geo", "127.0.0.22")[1])["country"], "IR")
        self.assertEqual(get(self.url + "/strict", "127.0.0.11")[0], 403)
        self.assertEqual(get(self.url + "/strict", "127.0.0.21")[0], 200)

    def test_server_config_shape(self):
        cfg = self.lab.server_config()
        tags = [i["tag"] for i in cfg["inbounds"]]
        self.assertEqual(tags, ["A1", "A2", "B1", "B2"])            # A3 is the dead node
        exits = {o["tag"]: o.get("inet4_bind_address") for o in cfg["outbounds"]}
        self.assertEqual(exits["exit-B1"], "127.0.0.21")
        r = cfg["route"]["rules"][0]
        self.assertEqual((r["action"], r["override_address"], r["ip_cidr"]),
                         ("route", "127.0.0.1", ["198.51.100.10/32"]))
        self.assertEqual(cfg["route"]["final"], "plain")

    def test_log_evidence_parsing(self):
        lab = self.labmod.Lab("192.168.122.1", 18080, 18101, singbox="x", workdir=self.tmp / "ev")
        (lab.dir / "lab-singbox.log").write_text(
            "\x1b[36mINFO\x1b[0m [1 0ms] inbound/shadowsocks[A2]: inbound connection from 192.168.122.57:50001\n"
            "INFO [1 0ms] inbound/shadowsocks[A2]: inbound connection to 192.168.122.1:18104\n"
            "INFO [2 0ms] inbound/shadowsocks[B1]: inbound connection from 192.168.122.1:41000\n")
        self.assertTrue(lab.forwarded("A2", "192.168.122.1", 18104))
        self.assertFalse(lab.forwarded("A1", "192.168.122.1", 18104))
        self.assertTrue(lab.seen_from("B1", "192.168.122.1"))
        self.assertFalse(lab.seen_from("B1", "192.168.122.57"))
        ev = lab.chain_evidence()
        self.assertEqual(ev["a_nodes_forwarding_to_B1"], ["A2"])

    def test_client_config_only_uses_real_app_keys(self):
        import chain
        import e2e_client
        unknown = set(e2e_client.client_config(18080)) - set(chain.DEFAULTS)
        self.assertEqual(unknown, set(), "e2e_client sets keys chain.py does not know")


class VmToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        for name, text in (("virsh", FAKE_VIRSH), ("ssh", FAKE_SSH), ("scp", FAKE_SCP)):
            write_exe(cls.bin / name, text)
        cls.drop = cls.tmp / "drop"
        cls.drop.mkdir()
        cls.log = cls.tmp / "fake.log"
        os.environ.update(PATH=f"{cls.bin}:{os.environ['PATH']}", FAKE_LOG=str(cls.log),
                          FAKE_DROP=str(cls.drop), VM_NAME="win-test", WIN_USER="tester")
        sys.modules.pop("vmtest", None)
        cls.vm = importlib.import_module("vmtest")
        cls.vm.CACHE = cls.tmp / "cache"
        cls.vm.CACHE.mkdir()
        (cls.vm.CACHE / "python-3.12.10-amd64.exe").write_bytes(b"MZ-fake")
        (cls.vm.CACHE / "sing-box-1.99.0-windows-amd64.zip").write_bytes(b"PK-fake")

    def test_clixml_keeps_host_text_and_errors(self):
        info = ('<Obj S="information" RefId="0"><TN RefId="0"><T>X</T></TN><ToString>PASS  a &lt;b&gt;</ToString><Props>'
                '<Obj N="MessageData" RefId="1"><Props><S N="Message">PASS  a &lt;b&gt;</S><B N="NoNewLine">false</B>'
                '</Props></Obj><S N="Source">x.ps1</S></Props></Obj>')
        err = '<S S="Error">boom_x000D__x000A_</S>'
        raw = ("plain line\n#< CLIXML\n<Objs Version=\"1.1.0.1\">" + info + err + info.replace("PASS  a", "CLEAN RESULT: PASS  a")
               + "</Objs>")
        out = self.vm.clean_clixml(raw)
        self.assertIn("plain line", out)
        self.assertIn("PASS  a <b>\n", out)
        self.assertIn("boom\n", out)
        self.assertIn("CLEAN RESULT: PASS", out)
        self.assertNotIn("<Obj", out)
        self.assertNotIn("CLIXML", out)

    def test_addresses_from_virsh(self):
        self.assertEqual(self.vm.vm_ip(), "192.168.122.57")
        self.assertEqual(self.vm.host_ip(), "192.168.122.1")
        self.assertEqual(self.vm.vm_state(), "running")

    def test_encoded_command_roundtrip(self):
        enc = self.vm.encode_ps("Write-Host 'hi ä'")
        text = base64.b64decode(enc).decode("utf-16-le")
        self.assertIn("$ProgressPreference='SilentlyContinue'", text)
        self.assertTrue(text.endswith("Write-Host 'hi ä'"))

    def test_tar_contents(self):
        data, staged = self.vm.build_tar(online=False)
        names = tarfile.open(fileobj=__import__("io").BytesIO(data)).getnames()
        self.assertIn("repo/chain.py", names)
        self.assertIn("repo/dev/vm/guest/common.ps1", names)
        self.assertIn("repo/dev/lab/e2e_client.py", names)
        self.assertIn("repo/offline/python-3.12.10-amd64.exe", names)
        self.assertEqual(len([n for n in staged if not n.startswith("chainlantern")]), 2)   # + the engine zip if built
        self.assertNotIn("repo/dev/vm/vm.conf", names)               # local settings stay home
        for bad in ("/.ssh/", "/cache/", "/artifacts/", "__pycache__", "/.git/"):
            self.assertFalse(any(bad in n for n in names), f"{bad} must not be deployed")
        _, staged_online = self.vm.build_tar(online=True)
        self.assertEqual([n for n in staged_online if not n.startswith("chainlantern")], [])

    def test_deploy_plumbing(self):
        self.log.write_text("")
        self.assertEqual(self.vm.cmd_deploy(type("A", (), {"online": False})()), 0)
        log = self.log.read_text()
        self.assertIn("SSH tester@192.168.122.57", log)
        self.assertIn("SCP ", log)
        self.assertIn("tester@192.168.122.57:chainproxy-test.tar.gz", log)
        self.assertIn("Stop-TestProcesses", log)                      # pre-clean ran first
        self.assertLess(log.index("Stop-TestProcesses"), log.index("tar -xzf"))
        self.assertTrue((self.drop / "chainproxy-test.tar.gz").exists())

    def test_ppm_to_png(self):
        w, h = 3, 2
        ppm = b"P6\n# comment\n3 2\n255\n" + bytes(range(18))
        png = self.vm.ppm_to_png(ppm)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", png[16:24]), (w, h))
        idat = png[png.index(b"IDAT") + 4:]
        raw = zlib.decompressobj().decompress(idat)
        self.assertEqual(raw[:10], b"\x00" + bytes(range(9)))
        self.assertEqual(self.vm.ppm_to_png(b"\x89PNGxyz"), b"\x89PNGxyz")

    def test_guest_scripts_follow_windows_rules(self):
        for p in (ROOT / "dev" / "vm" / "guest").glob("*.ps1"):
            data = p.read_bytes()
            self.assertFalse(any(b > 127 for b in data), f"{p.name} must be ASCII")
            self.assertNotRegex(data.decode(), r"(?<!\r)\n", f"{p.name} must use CRLF")

    def test_bootstrap_placeholders(self):
        text = (ROOT / "dev" / "vm" / "guest" / "bootstrap.ps1").read_text()
        for ph in ("__PUBKEY__", "__WIN_USER__", "__MSI_URL__", "__AUTOLOGON_PASSWORD__"):
            self.assertEqual(text.count(ph), 1, ph)


if __name__ == "__main__":
    unittest.main(verbosity=2)
