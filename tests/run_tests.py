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
import threading
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
            "__pycache__", "cache", "runtime", "core", "engine", ".proxy_state.json", ".shortcuts_done",
            ".git", "dev", "dist", "artifacts", ".claude",
            # installers a VM deploy puts into offline/ must not leak into the installer tests
            "*.zip", "*.exe", "*.msi"))
        (self.dir / "subA.txt").write_text(b64(SUB_A))          # base64 body
        (self.dir / "subB.txt").write_text(SUB_B)               # plain body
        (self.proj / "subs.txt").write_text(f"{self.dir / 'subA.txt'}\n{self.dir / 'subB.txt'}\n")
        (self.proj / "config.json").write_text(json.dumps({
            "mixed_port": 20808, "api_port": 20090, "control_port": 20091,
            "top_k": 5, "tcp_timeout": 0.3, "watchdog_seconds": 0,
            "lantern_enabled": False, "strict_urls": []}))
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
        # the template: placeholder first link + the default (real) second link
        self.assertTrue(self.chain.subs_are_placeholder(["https://example.com/sub/first", "https://alizn7.github.io/GeminiRoute/sub/best.txt"]))
        self.assertFalse(self.chain.subs_are_placeholder(["https://real.host/x", "https://example.com/sub/second"]))


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
        # the new process is "alive" before its API answers; cleanup() must not race the
        # restart (it killed the core mid-start and logged "restart failed" in the next test)
        while time.time() < deadline:
            try:
                app.core.api("GET", "/version", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        with env.chain.LOCK:                                   # restart() is done
            pass

    def test_placeholder_subs_give_clear_error(self):
        env = Env()
        self.addCleanup(env.close)
        (env.proj / "subs.txt").write_text("https://example.com/sub/first\n")
        with self.assertRaises(SystemExit) as cm:
            env.chain.start_session(env.chain.load_cfg())
        self.assertIn("no source configured", str(cm.exception))


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)          # registered first = runs last, after app.cleanup()
        self.chain = self.env.chain

    def test_bare_hosts_become_urls(self):
        n = self.chain.normalize_url
        self.assertEqual(n("gemini.google.com"), "https://gemini.google.com")
        self.assertEqual(n(" http://x.test/a "), "http://x.test/a")
        self.assertEqual(n(""), "")
        (self.env.proj / "config.json").write_text(json.dumps({"strict_urls": ["gemini.google.com", ""]}))
        self.assertEqual(self.chain.load_cfg()["strict_urls"], ["https://gemini.google.com"])

    def test_expired_certificate_falls_back_to_the_os_tls_stack(self):
        import ssl
        import urllib.error
        c = self.chain
        real = c.ur.urlopen

        def boom(*a, **k):
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired"))
        c.ur.urlopen = boom
        self.addCleanup(setattr, c.ur, "urlopen", real)
        c.native_get = lambda url, timeout=30, ua=None: (b"vless://x#n", "https://final.test/sub")
        self.assertEqual(c.http_get("https://sub.test/a", tries=3), ("vless://x#n", "https://final.test/sub"))
        self.assertEqual(c.http_get("https://sub.test/a", binary=True)[0], b"vless://x#n")

        def fail(url, timeout=30, ua=None):
            raise RuntimeError("curl: (60) SSL certificate problem")
        c.native_get = fail
        with self.assertRaises(RuntimeError) as cm:
            c.http_get("https://sub.test/a")
        self.assertIn("Windows Update", str(cm.exception))
        # an ordinary network error is NOT sent to the OS stack
        c.ur.urlopen = lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused"))
        c.native_get = lambda *a, **k: self.fail("native_get must not run for a plain network error")
        with self.assertRaises(RuntimeError):
            c.http_get("https://sub.test/a", tries=1)

    def test_native_get_follows_redirects(self):
        import http.server
        import shutil as sh
        if not sh.which("curl"):
            self.skipTest("curl not installed")

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/a":
                    self.send_response(302)
                    self.send_header("Location", "/b")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"body-" + self.headers.get("User-Agent", "").encode())

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        data, final = self.chain.native_get(f"http://127.0.0.1:{srv.server_port}/a", 10)
        self.assertTrue(data.startswith(b"body-"))
        self.assertTrue(final.endswith("/b"))

    def test_subscription_download_also_uses_the_os_tls_stack(self):
        """The bug of 1.2.1/1.2.2: only http_get had the fallback, fetch_nodes called urlopen itself."""
        import ssl
        import urllib.error
        c = self.chain
        real = c.ur.urlopen

        def boom(*a, **k):
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate has expired"))
        c.ur.urlopen = boom
        self.addCleanup(setattr, c.ur, "urlopen", real)
        seen = {}

        def native(url, timeout=30, ua=None):
            seen["ua"] = ua
            return (SUB_B.encode(), url)
        c.native_get = native
        nodes = c.fetch_nodes("https://sub.test/b", "TLS")
        self.assertEqual(len(nodes), 3)
        self.assertEqual(seen["ua"], "v2rayN/6.45")

    def test_defaults_for_new_features(self):
        d = self.chain.DEFAULTS
        self.assertEqual(d["strict_urls"], ["https://gemini.google.com"])
        self.assertTrue(d["lantern_enabled"])
        self.assertTrue(d["auto_update"])
        self.assertTrue(d["close_to_tray"])

    def test_ports_avoid_common_tools_and_legacy_values_move(self):
        d = self.chain.DEFAULTS
        common = {1080, 1081, 7890, 7891, 7892, 7893, 8080, 8118, 8888, 9090, 10808, 10809, 10810,
                  19090, 19091, 19092, 18080}
        ports = [d[k] for k in ("mixed_port", "api_port", "control_port", "gui_port", "lantern_port")]
        self.assertEqual(len(set(ports)), 5)
        self.assertFalse(set(ports) & common, ports)
        self.chain.CFG_FILE.write_text(json.dumps({"mixed_port": 10808, "api_port": 19090,
                                                   "gui_port": 31337}))
        cfg = self.chain.load_cfg()
        self.assertEqual(cfg["mixed_port"], d["mixed_port"])
        self.assertEqual(cfg["api_port"], d["api_port"])
        self.assertEqual(cfg["gui_port"], 31337)         # a deliberate custom value stays

    def test_geo_lookup_does_not_wait_for_a_slow_provider(self):
        chain = self.chain
        orig = chain.via_proxy

        def fake(url, port, timeout):
            if "slow" in url:
                time.sleep(3)
                return None, b""
            return 200, b'{"ip": "9.9.9.9", "country": "DE", "org": "X"}'
        chain.via_proxy = fake
        self.addCleanup(setattr, chain, "via_proxy", orig)
        cfg = dict(chain.DEFAULTS, geo_url="https://slow.test/", geo_fallback_urls=["https://ok.test/"])
        t0 = time.time()
        geo = chain.geo_lookup(cfg)
        self.assertLess(time.time() - t0, 2)
        self.assertEqual(geo[0], "9.9.9.9")

    def test_gemini_page_with_unsupported_country_is_rejected(self):
        chain = self.chain
        page = b'x' * 70000 + b'"vXmutd":"%.@.\\"IR\\",\\"ZZ\\",\\"o3vBBw\\\\u003d\\"]"'
        self.assertEqual(chain.google_country(page), "IR")
        self.assertEqual(chain.google_country(page.replace(b"IR", b"DE")), "DE")
        self.assertIsNone(chain.google_country(b"<html>no country</html>"))
        orig = chain.via_proxy
        seen = {}

        def fake(url, port, timeout=12, limit=65536, until=None):
            seen["limit"] = limit
            return 200, page
        chain.via_proxy = fake
        self.addCleanup(setattr, chain, "via_proxy", orig)
        cfg = dict(chain.DEFAULTS, geo_url="", strict_urls=["https://gemini.google.com"],
                   blocked_countries=["IR"])
        ok, info = chain.verify(cfg)
        self.assertFalse(ok)
        self.assertIn("Google places this exit in IR", info)
        self.assertGreater(seen["limit"], 135000)            # the country sits ~135 KB into the page
        page = page.replace(b"IR", b"DE")
        self.assertTrue(chain.verify(cfg)[0])

    def test_via_proxy_stops_reading_at_the_marker(self):
        import http.server
        body = b"a" * 100000 + b'%.@.\\"DE\\",\\"ZZ\\"' + b"b" * 400000

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        st, got = self.chain.via_proxy("http://x.test/", srv.server_address[1], 5, 300000, self.chain.GOOGLE_COUNTRY)
        self.assertEqual(st, 200)
        self.assertLess(len(got), 200000)
        self.assertEqual(self.chain.google_country(got), "DE")

    def test_profiles_and_source_priority_tiers(self):
        env = self.env
        (env.proj / "profiles_first.txt").write_text(
            "# one link per line\n" + f"vless://{UUID}@p1.test:443?security=tls&type=ws&path=%2Fp&host=p1.test#P-first\n")
        (env.proj / "profiles_exit.txt").write_text(
            f"vless://{UUID}@q1.test:443?security=tls&type=ws&path=%2Fp&host=q1.test#Q-exit\nnot a link\n")
        app = self.chain.start_session(self.chain.load_cfg())
        self.addCleanup(app.cleanup)
        self.addCleanup(lambda: [(env.proj / f).unlink() for f in ("profiles_first.txt", "profiles_exit.txt")])
        tiers = {t: app.tier_of(t) for t in app.names}
        self.assertEqual(tiers["A101"], 3)                     # first-hop profile: lowest priority
        self.assertEqual(tiers["B101"], 2)                     # exit-hop profile: second priority
        self.assertEqual(tiers["A1"], 2)                       # subscription A: middle
        self.assertEqual(tiers["B1"], 1)
        chains = [t for t in app.rank if "-" in t]
        keys = [(app.tier_of(t.split("-")[0]), app.tier_of(t.split("-")[1])) for t in chains]
        self.assertEqual(keys, sorted(keys), "chains must be ordered by first-hop tier, then exit-hop tier")
        self.assertIn((3, 2), keys)                            # the profile -> profile chain exists
        self.assertEqual(app.source_label("A101-B101"), "Profile + Profile")
        self.assertEqual(app.source_label("A1-B1"), "Subscription + Subscription")

    def test_lantern_engine_is_the_first_priority(self):
        import subprocess
        env = self.env
        (env.proj / "config.json").write_text(json.dumps({
            "mixed_port": 20808, "api_port": 20090, "control_port": 20091, "top_k": 5, "tcp_timeout": 0.3,
            "watchdog_seconds": 0, "lantern_enabled": True, "lantern_port": 28090, "lantern_timeout": 20,
            "strict_urls": []}))
        os.environ["CHAIN_LANTERN"] = str(env.proj / "tests" / "mock_lantern.py")
        self.addCleanup(os.environ.pop, "CHAIN_LANTERN", None)
        app = self.chain.start_session(self.chain.load_cfg())
        self.addCleanup(app.cleanup)
        self.assertEqual(app.tier_of("A0"), 1)
        self.assertEqual(app.names["A0"], "Lantern (auto)")
        self.assertTrue(app.rank[0].startswith("A0-"), app.rank)     # Lantern chains come first
        self.assertEqual(app.source_label(app.rank[0]), "Lantern + Subscription")
        proc = app.lantern.proc
        self.assertTrue(app.lantern.alive())
        app.cleanup()                                                # closes the engine's stdin
        proc.wait(10)
        self.assertIsNotNone(proc.poll())

    def test_session_goes_on_without_lantern_when_it_cannot_start(self):
        env = self.env
        (env.proj / "config.json").write_text(json.dumps({
            "mixed_port": 20808, "api_port": 20090, "control_port": 20091, "top_k": 5, "tcp_timeout": 0.3,
            "watchdog_seconds": 0, "lantern_enabled": True, "lantern_port": 28091, "lantern_timeout": 4,
            "strict_urls": []}))
        os.environ["CHAIN_LANTERN"] = str(env.proj / "tests" / "mock_lantern.py")
        os.environ["MOCK_LANTERN"] = "fail"
        self.addCleanup(os.environ.pop, "CHAIN_LANTERN", None)
        self.addCleanup(os.environ.pop, "MOCK_LANTERN", None)
        app = self.chain.start_session(self.chain.load_cfg())
        self.addCleanup(app.cleanup)
        self.assertNotIn("A0", app.names)
        self.assertTrue(app.rank)                                    # the subscriptions still work
        self.assertIn("no free server", app.lantern.error)

    def test_engine_package_must_match_the_pinned_hash(self):
        import zipfile
        (self.env.proj / "offline").mkdir(exist_ok=True)
        with zipfile.ZipFile(self.env.proj / "offline" / "chainlantern-72fe1e9-windows-amd64.zip", "w") as z:
            z.writestr("chainlantern.exe", "MZ-evil")
        with self.assertRaises(RuntimeError) as cm:
            self.chain.install_engine()
        self.assertIn("sha256", str(cm.exception))
        self.assertFalse((self.chain.ENGINE_DIR / "chainlantern.exe").exists())

    def test_update_check_and_download(self):
        import hashlib
        c = self.chain
        self.assertGreater(c.parse_version("v1.10.0"), c.parse_version("1.9.9"))
        self.assertEqual(c.parse_version("garbage"), (0, 0, 0))
        installer = b"MZ-installer-bytes"
        digest = hashlib.sha256(installer).hexdigest()
        release = {"tag_name": "v9.9.9", "html_url": "https://x/releases/v9.9.9", "body": "notes",
                   "assets": [{"name": "ChainProxy-Setup-Full-9.9.9.exe", "browser_download_url": "https://x/full", "digest": "sha256:" + "0" * 64},
                              {"name": "ChainProxy-Setup-9.9.9.exe", "browser_download_url": "https://x/light",
                               "size": len(installer), "digest": "sha256:" + digest}]}
        calls = []

        def fake(url, timeout=30, tries=3, binary=False, ua=None):
            calls.append(url)
            return (json.dumps(release), url) if "api" in url or "releases" in url else (installer, url)
        c.http_get = fake
        cfg = c.load_cfg()
        info = c.update_available(cfg)
        self.assertEqual((info["version"], info["url"], info["sha256"]), ("9.9.9", "https://x/light", digest))
        path = c.download_update(info)
        self.assertEqual(path.read_bytes(), installer)
        self.assertEqual(path.name, "ChainProxy-Setup-9.9.9.exe")
        with self.assertRaises(RuntimeError):                        # wrong hash is refused
            c.download_update({**info, "sha256": "1" * 64})
        with self.assertRaises(RuntimeError):                        # no digest: never installed automatically
            c.download_update({**info, "sha256": ""})
        release["tag_name"] = "v0.0.1"
        self.assertIsNone(c.update_available(cfg))                   # not newer
        release["tag_name"] = "engine-72fe1e9"
        self.assertIsNone(c.update_available(cfg))                   # non-app release ignored

    def test_subs_txt_is_created_from_the_template(self):
        (self.env.proj / "subs.txt").unlink()
        self.assertTrue(self.chain.subs_are_placeholder())          # recreated, still the placeholder
        self.assertTrue((self.env.proj / "subs.txt").exists())

    def test_release_zip_never_contains_the_users_subs(self):
        import subprocess
        import zipfile
        root = Path(__file__).resolve().parents[1]
        out = subprocess.run([sys.executable, str(root / "dev" / "package.py")], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        z = sorted((root / "dist").glob("chainproxy-*.zip"))[-1]
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(zf.read("chainproxy/subs.txt"), (root / "subs.example.txt").read_bytes())

    def test_files_saved_by_notepad_with_a_bom(self):
        (self.env.proj / "config.json").write_bytes(b'\xef\xbb\xbf{"top_k": 3}')
        self.assertEqual(self.chain.load_cfg()["top_k"], 3)

    def test_geo_answers_of_different_providers(self):
        pg = self.chain.parse_geo
        self.assertEqual(pg('{"ip":"1.2.3.4","country":"NL","org":"AS1 X"}'), ("1.2.3.4", "NL", "AS1 X"))
        self.assertEqual(pg('{"ip":"1.2.3.4","country":"NL"}')[1], "NL")                    # api.country.is
        self.assertEqual(pg('{"ip":"1.2.3.4","country":"Iran","country_code":"IR",'
                            '"connection":{"org":"Z"}}'), ("1.2.3.4", "IR", "Z"))           # ipwho.is
        with self.assertRaises(Exception):
            pg('{"error":"rate limited"}')

    def test_verify_uses_fallback_geo_and_reports_errors(self):
        c = self.chain
        cfg = c.load_cfg()
        cfg["strict_urls"] = ["https://ok.test/", "https://down.test/"]
        calls = []

        def fake(url, port, timeout=12):
            calls.append(url)
            if "ipinfo" in url:
                return 429, b"rate limited"
            if "country.is" in url:
                return 200, b'{"ip":"5.6.7.8","country":"DE"}'
            return (None, b"") if "down" in url else (200, b"x")
        c.via_proxy = fake
        ok, info = c.verify(cfg)
        self.assertFalse(ok)
        self.assertIn("https://down.test/ -> no answer", info)
        self.assertIn("5.6.7.8 DE", info)                      # the fallback provider was used
        cfg["strict_urls"] = []
        cfg["blocked_countries"] = ["DE"]
        self.assertEqual(c.verify(cfg), (False, "exit in blocked country (5.6.7.8 DE)"))

    def test_rank_by_speed_option(self):
        c = self.chain
        cfg = c.load_cfg()
        cfg["rank_by_speed"] = True
        app = c.start_session(cfg)
        self.addCleanup(app.cleanup)
        d = [app.delays[t] for t in app.rank]
        self.assertEqual(d, sorted(d))

    def test_guard_restores_when_the_app_dies(self):
        c = self.chain
        import subprocess
        restored = []
        c.sys_proxy_restore = lambda: restored.append(1)
        c.STATE_FILE.write_text("{}")
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        t0 = time.time()
        threading_guard = c.guard
        p_wait = threading.Thread(target=p.wait)
        p_wait.start()                                          # reap it, so the pid really vanishes
        threading_guard(p.pid, poll=0.1)
        p_wait.join()
        self.assertEqual(restored, [1])
        self.assertLess(time.time() - t0, 10)
        c.STATE_FILE.unlink()
        restored.clear()
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        c.guard(p.pid, poll=0.1)                                # clean exit: state file gone -> nothing
        self.assertEqual(restored, [])


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
