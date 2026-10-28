"""
Automated tests for chainproxy. No real sing-box, no network, no Windows needed.

    python tests/run_tests.py            (from the project folder)

Each run copies the project into a temporary folder, writes sample subscriptions, and points
chain.py at tests/mock_core.py instead of the real core (via the CHAIN_CORE variable).
Ports 20808/20090/20091 are used so a running instance of the real tool is not disturbed.
"""
import base64
import hashlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"
UUID = "11111111-2222-3333-4444-555555555555"


def b64(s):
    return base64.b64encode(s.encode()).decode()


def vmess(name, host):
    return "vmess://" + b64(json.dumps({
        "v": "2", "ps": name, "add": host, "port": "443", "id": UUID, "aid": "0", "net": "ws",
        "host": host, "path": "/ws?ed=2048", "tls": "tls", "sni": host}))


SUB_A = "\n".join([
    f"vless://{UUID}@a1.test:443?security=reality&sni=x.com&fp=chrome&pbk=KEY&sid=ab&type=tcp"
    "&flow=xtls-rprx-vision#A-reality",
    vmess("A-vmess", "a2.test"),
    "trojan://pass@a3.test:443?type=grpc&serviceName=g#A-trojan",
])
SUB_B = "\n".join([
    "ss://" + b64("aes-256-gcm:pw") + "@b1.test:8388#B-ss",
    "hysteria2://pw@b2.test:443?sni=b2.test&obfs=salamander&obfs-password=x#B-hy2",
    f"vless://{UUID}@b3.test:443?security=tls&type=ws&path=%2Fp&host=b3.test#B-vless",
])


class Env:
    """A throw-away copy of the project wired to the mock core."""

    def __init__(self, old_core=False):
        self.dir = Path(tempfile.mkdtemp(prefix="chainproxy-test-"))
        self.proj = self.dir / "proj"
        shutil.copytree(PROJECT, self.proj, ignore=shutil.ignore_patterns(
            "__pycache__", "cache", "runtime", "core", ".proxy_state.json", ".shortcuts_done",
            ".git", "dev", "dist", "artifacts", ".claude",
            # installers a VM deploy puts into offline/ must not leak into the installer tests
            "*.zip", "*.exe", "*.msi"))
        (self.dir / "subA.txt").write_text(b64(SUB_A))          # base64 body
        (self.dir / "subB.txt").write_text(SUB_B)               # plain body
        (self.proj / "subs.txt").write_text(f"{self.dir / 'subA.txt'}\n{self.dir / 'subB.txt'}\n")
        (self.proj / "config.json").write_text(json.dumps({
            "mixed_port": 20808, "api_port": 20090, "control_port": 20091,
            "top_k": 5, "tcp_timeout": 0.3, "watchdog_seconds": 0}))
        # a *.py core is run with the current Python by chain.core_cmd() on every OS
        os.environ["CHAIN_CORE"] = str(self.proj / "tests" / "mock_core.py")
        if old_core:
            os.environ["MOCK_OLD"] = "1"
        else:
            os.environ.pop("MOCK_OLD", None)
        sys.path.insert(0, str(self.proj))
        sys.modules.pop("chain", None)
        self.chain = importlib.import_module("chain")

    def close(self):
        try:
            sys.path.remove(str(self.proj))
        except ValueError:
            pass
        sys.modules.pop("chain", None)
        os.environ.pop("CHAIN_CORE", None)
        os.environ.pop("MOCK_OLD", None)
        shutil.rmtree(self.dir, ignore_errors=True)


class ParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.chain = cls.env.chain

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def test_vless_reality(self):
        name, ob = self.chain.parse_node(SUB_A.splitlines()[0])
        self.assertEqual((name, ob["type"], ob["server"], ob["server_port"]), ("A-reality", "vless", "a1.test", 443))
        self.assertEqual(ob["flow"], "xtls-rprx-vision")
        self.assertTrue(ob["tls"]["reality"]["enabled"])
        self.assertEqual(ob["tls"]["reality"]["public_key"], "KEY")
        self.assertEqual(ob["tls"]["utls"]["fingerprint"], "chrome")

    def test_vmess_ws_early_data(self):
        _, ob = self.chain.parse_node(SUB_A.splitlines()[1])
        self.assertEqual(ob["type"], "vmess")
        self.assertEqual(ob["transport"]["type"], "ws")
        self.assertEqual(ob["transport"]["path"], "/ws")
        self.assertEqual(ob["transport"]["max_early_data"], 2048)

    def test_trojan_grpc_forces_tls(self):
        _, ob = self.chain.parse_node(SUB_A.splitlines()[2])
        self.assertEqual(ob["transport"], {"type": "grpc", "service_name": "g"})
        self.assertTrue(ob["tls"]["enabled"])

    def test_shadowsocks_sip002_and_legacy(self):
        _, ob = self.chain.parse_node(SUB_B.splitlines()[0])
        self.assertEqual((ob["method"], ob["password"], ob["server_port"]), ("aes-256-gcm", "pw", 8388))
        legacy = "ss://" + b64("chacha20-ietf-poly1305:secret@legacy.test:443") + "#L"
        _, ob = self.chain.parse_node(legacy)
        self.assertEqual((ob["server"], ob["password"]), ("legacy.test", "secret"))

    def test_hysteria2(self):
        _, ob = self.chain.parse_node(SUB_B.splitlines()[1])
        self.assertEqual(ob["type"], "hysteria2")
        self.assertEqual(ob["obfs"]["type"], "salamander")

    def test_garbage_is_ignored(self):
        for bad in ("", "nonsense", "vmess://!!!", "vless://", "ss://x#y", "http://example.com"):
            self.assertIsNone(self.chain.parse_node(bad), bad)

    def test_subscription_bodies_base64_and_plain(self):
        a = self.chain.fetch_nodes(str(self.env.dir / "subA.txt"), "tA")
        b = self.chain.fetch_nodes(str(self.env.dir / "subB.txt"), "tB")
        self.assertEqual((len(a), len(b)), (3, 3))

    def test_placeholder_detection(self):
        self.assertTrue(self.chain.subs_are_placeholder(["https://example.com/sub/first"]))
        self.assertFalse(self.chain.subs_are_placeholder(["https://real.host/x"]))


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.chain = cls.env.chain

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def test_chain_structure(self):
        c = self.chain
        A = c.pick(c.fetch_nodes(str(self.env.dir / "subA.txt"), "cA"), 2, 0.1, "A")
        B = c.pick(c.fetch_nodes(str(self.env.dir / "subB.txt"), "cB"), 2, 0.1, "B")
        conf = c.build_config(c.load_cfg(), A, B)
        outs = {o["tag"]: o for o in conf["outbounds"]}
        for ta in A:
            for tb in B:                                   # B dialled THROUGH A
                self.assertEqual(outs[f"{ta}-{tb}"]["detour"], ta)
                self.assertEqual(outs[f"{ta}-{tb}"]["server"], B[tb][1]["server"])
        self.assertNotIn("detour", outs["A1"])
        sel = outs["route"]
        self.assertEqual(sel["type"], "selector")
        self.assertTrue(sel["outbounds"][0].count("-") == 1)            # chains come first
        self.assertEqual(conf["route"]["final"], "route")
        self.assertIn({"domain_suffix": [".ir"], "outbound": "direct"}, conf["route"]["rules"])
        self.assertEqual(conf["inbounds"][0]["listen"], "127.0.0.1")    # never exposed to the LAN

    def test_private_direct_switch(self):
        c = self.chain
        A = {"A1": ("n", {"type": "direct"})}
        cfg = c.load_cfg()
        on = c.build_config(cfg, A, {})
        self.assertIn({"ip_is_private": True, "outbound": "direct"}, on["route"]["rules"])
        cfg["private_direct"] = False
        off = c.build_config(cfg, A, {})
        self.assertFalse(any("ip_is_private" in r for r in off["route"]["rules"]))

    def test_core_cmd_runs_python_doubles(self):
        cmd = self.chain.core_cmd()
        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(cmd[1].endswith("mock_core.py"))
        self.assertEqual(self.chain.core_run(["version"])[0], 0)

    def test_modern_vs_legacy_dns(self):
        c = self.chain
        A = {"A1": ("n", {"type": "direct"})}
        modern = c.build_config(c.load_cfg(), A, {}, modern=True)
        legacy = c.build_config(c.load_cfg(), A, {}, modern=False)
        self.assertIn("dns", modern)
        self.assertEqual(modern["route"]["default_domain_resolver"], "local")
        self.assertNotIn("dns", legacy)
        self.assertNotIn("default_domain_resolver", legacy["route"])


class SessionTests(unittest.TestCase):
    """Whole flow: fetch -> validate -> start core -> rank -> select -> control -> stop."""

    def run_session(self, old_core=False):
        env = Env(old_core)
        self.addCleanup(env.close)
        app = env.chain.start_session(env.chain.load_cfg())
        self.addCleanup(app.cleanup)
        return env, app

    def test_ranking_validation_and_switching(self):
        env, app = self.run_session()
        self.assertTrue(app.core.alive())
        tags = set(app.rank)
        self.assertNotIn("A2", " ".join(tags))                  # delay test fails for A2
        self.assertFalse(any("A3" in t for t in tags))          # core check rejected a3.test
        kinds = [("-" in t, t[0]) for t in app.rank]            # chains, then B only, then A only
        self.assertEqual(kinds, sorted(kinds, key=lambda k: (not k[0], k[1] != "B")))
        self.assertEqual(app.idx, 0)
        first = app.rank[0]
        self.assertIn("-", first)
        app.go(1)
        self.assertEqual(app.idx, 1)
        app.go(-1)
        self.assertEqual(app.idx, 0)
        app.go(-1)                                              # wraps around
        self.assertEqual(app.idx, len(app.rank) - 1)
        self.assertEqual(app.go_to(99), "no such route")

    def test_control_socket(self):
        env, app = self.run_session()
        cfg = env.chain.load_cfg()
        self.assertTrue(env.chain.control_send(cfg, "status", 10).startswith("[1/"))
        self.assertTrue(env.chain.control_send(cfg, "next", 30).startswith("[2/"))
        self.assertIn("1.", env.chain.control_send(cfg, "list", 10))
        self.assertEqual(env.chain.control_send(cfg, "off", 10), "stopping")
        self.assertTrue(app.stop_evt.is_set())
        app.cleanup()
        self.assertIsNone(env.chain.control_send(cfg, "status", 2))      # socket closed
        self.assertTrue(env.chain.port_free(cfg["api_port"]))            # core stopped

    def test_legacy_layout_when_core_is_old(self):
        env, app = self.run_session(old_core=True)
        conf = json.loads((env.chain.RUNTIME_DIR / "config.json").read_text())
        self.assertNotIn("dns", conf)
        self.assertTrue(app.core.alive())

    def test_core_crash_is_repaired(self):
        env, app = self.run_session()
        app.cfg["watchdog_seconds"] = 0
        import threading
        threading.Thread(target=app.watchdog, daemon=True).start()
        old_pid = app.core.proc.pid
        app.core.proc.kill()
        deadline = time.time() + 20
        while time.time() < deadline and not (app.core.alive() and app.core.proc.pid != old_pid):
            time.sleep(0.3)
        self.assertTrue(app.core.alive(), "watchdog did not restart the core")
        self.assertNotEqual(app.core.proc.pid, old_pid)

    def test_placeholder_subs_give_clear_error(self):
        env = Env()
        self.addCleanup(env.close)
        (env.proj / "subs.txt").write_text("https://example.com/sub/first\n")
        with self.assertRaises(SystemExit) as cm:
            env.chain.start_session(env.chain.load_cfg())
        self.assertIn("no real subscription", str(cm.exception))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CHAIN_CORE", None)
        self.env = Env()
        os.environ.pop("CHAIN_CORE", None)           # use the real lookup in ./core
        self.chain = self.env.chain
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("pkg/sing-box.exe", "#!/bin/sh\necho 'sing-box version 9.9.9'\n")
            z.writestr("pkg/libcronet.dll", "x")
        self.zip = buf.getvalue()

    def tearDown(self):
        self.env.close()

    def fake_http(self, digest, calls=None, api_fails=False):
        rel = {"assets": [{"name": "sing-box-9.9.9-windows-amd64.zip",
                           "browser_download_url": "http://x/a.zip", "digest": digest}]}

        def fake(url, timeout=30, tries=3, binary=False):
            if calls is not None:
                calls.append(url)
            if "api.github.com" in url:
                if api_fails:
                    raise RuntimeError("blocked")
                return json.dumps(rel), url
            if url.endswith("/releases/latest"):
                return "", "https://github.com/SagerNet/sing-box/releases/tag/v1.2.3"
            return self.zip, url
        return fake

    def test_checksum_mismatch_installs_nothing(self):
        self.chain.http_get = self.fake_http("sha256:" + "0" * 64)
        with self.assertRaises(RuntimeError) as cm:
            self.chain.install_core(force=True)
        self.assertIn("sha256 mismatch", str(cm.exception))
        self.assertFalse(self.chain.CORE_DIR.exists() and any(self.chain.CORE_DIR.iterdir()))

    def test_good_checksum_extracts_files(self):
        self.chain.http_get = self.fake_http("sha256:" + hashlib.sha256(self.zip).hexdigest())
        try:
            self.chain.install_core(force=True)          # may fail the run-check on non-Windows
        except RuntimeError as e:
            self.assertIn("does not run", str(e))
        names = sorted(p.name for p in self.chain.CORE_DIR.iterdir())
        self.assertEqual(names, ["libcronet.dll", "sing-box.exe"])

    def test_redirect_fallback_when_api_blocked(self):
        calls = []
        self.chain.http_get = self.fake_http(None, calls, api_fails=True)
        try:
            self.chain.install_core(force=True)
        except RuntimeError:
            pass
        self.assertEqual(calls[-1], "https://github.com/SagerNet/sing-box/releases/download/"
                                    "v1.2.3/sing-box-1.2.3-windows-amd64.zip")

    def test_offline_zip_is_preferred_and_needs_no_network(self):
        off = self.chain.BASE / "offline"
        off.mkdir(exist_ok=True)
        (off / "sing-box-9.9.9-windows-amd64.zip").write_bytes(self.zip)
        calls = []
        self.chain.http_get = self.fake_http(None, calls)
        try:
            self.chain.install_core(force=True)
        except RuntimeError:
            pass
        self.assertEqual(calls, [])
        self.assertTrue((self.chain.CORE_DIR / "sing-box.exe").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
