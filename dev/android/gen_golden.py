#!/usr/bin/env python3
"""Golden vectors for the Kotlin port of the chain logic.

chain.py is the reference implementation. This script feeds it fixed inputs and writes inputs + outputs to
android/app/src/test/resources/golden.json; the Kotlin unit tests (ChainGoldenTest) must produce the same
results. Run it again whenever chain.py's parsing, config, ranking or verification rules change:

    python3 dev/android/gen_golden.py
"""
import base64
import json
import sys
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import chain  # noqa: E402

OUT = ROOT / "android" / "app" / "src" / "test" / "resources" / "golden.json"


def b64(s, urlsafe=False, pad=True):
    raw = s.encode() if isinstance(s, str) else s
    out = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(raw).decode()
    return out if pad else out.rstrip("=")


def vmess(**kw):
    j = {"v": "2", "ps": "vm", "add": "vm.example.com", "port": "443", "id": "11111111-2222-3333-4444-555555555555",
         "aid": "0", "net": "tcp", "type": "none", "host": "", "path": "", "tls": ""}
    j.update(kw)
    return "vmess://" + b64(json.dumps(j))


LINKS = [
    vmess(),
    vmess(ps="vm ws tls", net="ws", host="cdn.example.com", path="/ws?ed=2048", tls="tls", sni="sni.example.com",
          alpn="h2,http/1.1", fp="chrome", scy="aes-128-gcm", port=8443, aid=2),
    vmess(ps="vm grpc", net="grpc", path="svc", tls="tls"),
    vmess(ps="vm h2", net="h2", host="a.example.com,b.example.com", path="/h2", tls="tls"),
    vmess(ps="vm httpupgrade", net="httpupgrade", host="h.example.com", path="/up"),
    vmess(ps="", add="noname.example.com"),
    "vmess://" + b64("not json"),
    "vmess://###",
    "vless://aaaa-bbbb@v.example.com:443?encryption=none&security=reality&sni=www.microsoft.com&fp=chrome&pbk=PUBKEY&sid=ab12&type=tcp&flow=xtls-rprx-vision#Reality%20Node",
    "vless://uuid-1@V.Example.COM:2053?security=tls&type=ws&host=ws.example.com&path=%2Fpath%3Fed%3D2560&sni=s.example.com&alpn=h2%2Chttp%2F1.1&allowInsecure=1#WS+TLS",
    "vless://uuid-2@[2001:db8::1]:443?security=tls&type=grpc&serviceName=grpcsvc&fp=firefox#v6",
    "vless://uuid-3@plain.example.com:80?type=httpupgrade&host=hu.example.com&path=%2Fhu#plain",
    "vless://uuid-4@h2.example.com:443?security=tls&type=h2&host=a.com,b.com&path=/x&peer=peer.example.com#h2",
    "vless://uuid-5@host.example.com:443?security=tls&sni=&fp=#%F0%9F%87%A9%F0%9F%87%AA%20Germany",
    "vless://uuid-6@noport.example.com?security=tls",
    "trojan://pass%40word@t.example.com:443?sni=t.example.com&type=ws&path=/t&host=t.example.com#Trojan",
    "trojan://secret@t2.example.com:8443?allowInsecure=true&alpn=h2#T2",
    "trojan://secret@t3.example.com:443?security=none#forced-tls",
    "ss://" + b64("aes-256-gcm:pw123", urlsafe=True, pad=False) + "@ss.example.com:8388#SS%20Node",
    "ss://aes-128-gcm:plainpw@ss2.example.com:443#plain",
    "ss://" + b64("chacha20-ietf-poly1305:pw@ss3.example.com:9999", urlsafe=True, pad=False) + "#whole",
    "ss://" + b64("aes-256-gcm:pw") + "@[2001:db8::2]:8388/#v6ss",
    "ss://" + b64("aes-256-gcm:pw") + "@plug.example.com:8388/?plugin=obfs-local%3Bobfs%3Dhttp#plugin",
    "hysteria2://hy2pass@hy.example.com:8443?sni=hy.example.com&insecure=1&obfs=salamander&obfs-password=ob#HY2",
    "hy2://user:pass@hy2.example.com?sni=custom.example.com#hy2 userpass",
    "hysteria2://nopass.example.com#bare",
    "http://example.com/not-a-node",
    "",
    "garbage",
    "vless://",
]

NORMALIZE = ["gemini.google.com", "https://gemini.google.com", "  http://a.b  ", "", "   ", "ftp://x", "a.b/c?d=1"]

GEO = [
    '{"ip":"1.2.3.4","country":"DE","org":"AS1 Foo"}',
    '{"ip":"5.6.7.8","country":"nl"}',
    '{"query":"9.9.9.9","countryCode":"US","isp":"ISP Inc"}',
    '{"ip":"2.2.2.2","country_code":"FR","connection":{"org":"Conn Org"}}',
    '{"ip":"3.3.3.3","country":"Germany"}',
    '{"country":"DE"}',
    '{"ip":"4.4.4.4","country":"IR","org":null}',
    'not json',
]


def marker(cc):
    return '...x%.@.\\"' + cc + '\\",\\"ZZ\\"...'


GOOGLE = [marker("IR"), marker("US"), "no marker here", '%.@.\\"ir\\",\\"ZZ\\"', "", marker("DE") + marker("IR")]


def parse_cases():
    out = []
    for link in LINKS:
        r = chain.parse_node(link)
        out.append({"link": link, "expect": None if r is None else {"name": r[0], "ob": r[1]}})
    return out


def subscription_cases():
    lines = [vmess(ps="one"), "vless://u@dup.example.com:443?security=tls#first", "vless://u@dup.example.com:443?security=tls#second",
             "bad line", "trojan://p@t.example.com:443#t", "ss://aes-128-gcm:p@s.example.com:1#s"]
    plain = "\n".join(lines)
    cases = []

    def run(body):
        with mock.patch.object(chain, "CACHE_DIR", Path("/nonexistent-cache")), \
             mock.patch.object(chain, "log", lambda *a: None):
            nodes, seen = [], set()
            text = body.strip()
            import re
            if not re.search(r"^[a-z0-9]+://", text, re.M | re.I):
                try:
                    text = chain.b64d(text)
                except Exception:
                    return []
            for line in text.splitlines():
                n = chain.parse_node(line)
                if n and chain.node_key(n[1]) not in seen:
                    seen.add(chain.node_key(n[1]))
                    nodes.append(n)
            return [{"name": n, "ob": o} for n, o in nodes]
    for label, body in (("plain", plain), ("base64", b64(plain)), ("base64-urlsafe-nopad", b64(plain, True, False)),
                        ("empty", ""), ("junk", "!!!not base64 and no links")):
        cases.append({"label": label, "body": body, "expect": run(body)})
    return cases


def node_set(prefix, specs, start=1):
    out = {}
    for i, (name, host) in enumerate(specs):
        out[f"{prefix}{start + i}"] = (name, {"type": "shadowsocks", "server": host, "server_port": 8388 + i,
                                               "method": "aes-128-gcm", "password": f"pw-{prefix}{start + i}"})
    return out


def config_cases():
    cases = []
    A = {**node_set("A", [("first", "a1.example.com"), ("second", "a2.example.com")]),
         "A0": ("Lantern", {"type": "socks", "server": "127.0.0.1", "server_port": 42819, "version": "5"})}
    B = node_set("B", [("exit1", "b1.example.com"), ("exit2", "b2.example.com")])
    base = {k: chain.DEFAULTS[k] for k in ("mixed_port", "api_port", "private_direct", "direct_suffixes", "log_level")}
    for label, over in (("defaults", {}), ("no-private", {"private_direct": False}),
                        ("no-suffix", {"direct_suffixes": []}), ("two-suffix", {"direct_suffixes": [".ir", ".local"]})):
        cfg = {**chain.DEFAULTS, **over}
        for modern in (True, False):
            conf = chain.build_config(cfg, A, B, modern=modern)
            cases.append({"label": f"{label}/modern={modern}", "cfg": {k: cfg[k] for k in base}, "modern": modern,
                          "A": {t: {"name": n, "ob": o} for t, (n, o) in A.items()},
                          "B": {t: {"name": n, "ob": o} for t, (n, o) in B.items()},
                          "expect": conf})
    return cases


def rank_cases():
    cases = []

    def run(cfg_over, tiers, delays, A, B):
        cfg = {**chain.DEFAULTS, **cfg_over}
        app = chain.App(cfg)
        app.tier = tiers
        app.core = mock.Mock()
        app.core.delay = lambda tag, url, to: delays.get(tag)
        with mock.patch.object(chain, "log", lambda *a: None):
            app.build_rank(A, B)
        return app.rank

    A = ["A0", "A1", "A2", "A101"]
    B = ["B1", "B2", "B3", "B101"]
    tiers = {"A0": 1, "A1": 2, "A2": 2, "A101": 3, "B1": 1, "B2": 1, "B3": 1, "B101": 2}
    import random
    rnd = random.Random(7)
    chains = [f"{a}-{b}" for a in A for b in B]
    delays = {t: round(rnd.uniform(80, 900), 1) for t in chains + A + B}
    delays["A1-B2"] = None
    delays["B3"] = None
    delays["A101"] = None
    for label, over in (("tiers", {}), ("speed", {"rank_by_speed": True})):
        a = {t: None for t in A}
        b = {t: None for t in B}
        cases.append({"label": label, "rank_by_speed": over.get("rank_by_speed", False), "tiers": tiers,
                      "A": A, "B": B, "delays": delays, "expect": run(over, tiers, delays, a, b)})
    only_a = {t: None for t in ["A1", "A2"]}
    d2 = {"A1": 300.0, "A2": 120.0}
    cases.append({"label": "only-A", "rank_by_speed": False, "tiers": {"A1": 2, "A2": 2}, "A": ["A1", "A2"], "B": [],
                  "delays": d2, "expect": run({}, {"A1": 2, "A2": 2}, d2, only_a, {})})
    return cases


def verify_cases():
    cases = []
    gem = "https://gemini.google.com"

    def run(cfg_over, geo, sites):
        cfg = {**chain.DEFAULTS, **cfg_over}

        def fake_via(url, port, timeout=12, limit=65536, until=None):
            st, body = sites[url]
            return st, body.encode("latin-1")
        with mock.patch.object(chain, "geo_lookup", lambda c: tuple(geo) if geo else None), \
             mock.patch.object(chain, "via_proxy", fake_via):
            return list(chain.verify(cfg))
    scenarios = [
        ("all-good", {}, ["1.2.3.4", "DE", "AS1 Foo"], {gem: [200, marker("DE")]}),
        ("blocked-exit", {}, ["5.6.7.8", "IR", "AS2"], {gem: [200, ""]}),
        ("gemini-403", {}, ["1.2.3.4", "DE", ""], {gem: [403, ""]}),
        ("gemini-none", {}, ["1.2.3.4", "DE", ""], {gem: [None, ""]}),
        ("google-says-IR", {}, ["1.2.3.4", "DE", "x"], {gem: [200, marker("IR")]}),
        ("google-says-US", {}, ["1.2.3.4", "NL", "x"], {gem: [200, marker("US")]}),
        ("no-geo", {}, None, {gem: [200, "ok"]}),
        ("geo-no-country", {}, ["1.2.3.4", None, "org"], {gem: [200, "ok"]}),
        ("two-sites", {"strict_urls": [gem, "https://example.com"]}, ["1.2.3.4", "DE", ""],
         {gem: [200, marker("DE")], "https://example.com": [500, ""]}),
        ("lowercase-blocked", {"blocked_countries": ["ir", "ru"]}, ["1.1.1.1", "RU", "o"], {gem: [200, ""]}),
        ("no-strict", {"strict_urls": []}, ["1.2.3.4", "DE", "o"], {}),
        ("non-gemini-with-marker", {"strict_urls": ["https://example.com"]}, ["1.2.3.4", "DE", "o"],
         {"https://example.com": [200, marker("IR")]}),
    ]
    for label, over, geo, sites in scenarios:
        cases.append({"label": label, "blocked_countries": over.get("blocked_countries", chain.DEFAULTS["blocked_countries"]),
                      "strict_urls": over.get("strict_urls", chain.DEFAULTS["strict_urls"]), "geo": geo,
                      "sites": {u: {"status": s, "body": b} for u, (s, b) in sites.items()},
                      "expect": run(over, geo, sites)})
    return cases


def main():
    golden = {
        "normalize": [{"in": u, "out": chain.normalize_url(u)} for u in NORMALIZE],
        "parse": parse_cases(),
        "subscription": subscription_cases(),
        "config": config_cases(),
        "geo": [{"body": b, "expect": (lambda r: r)(_geo(b))} for b in GEO],
        "google": [{"body": g, "expect": chain.google_country(g.encode("latin-1"))} for g in GOOGLE],
        "rank": rank_cases(),
        "verify": verify_cases(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(golden, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: " + ", ".join(f"{k}={len(v)}" for k, v in golden.items()))


def _geo(body):
    try:
        ip, cc, org = chain.parse_geo(body)
        return {"ip": ip, "cc": cc, "org": org}
    except Exception:
        return None


if __name__ == "__main__":
    main()
