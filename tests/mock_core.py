"""
Fake `sing-box` for tests. Speaks just enough of the CLI and the Clash API for chain.py:

  mock_core.py version              -> prints a version line
  mock_core.py check -c cfg.json    -> exit 1 when the config contains the server "a3.test"
                                       (simulates an outbound the core refuses to load) or,
                                       with MOCK_OLD=1, a "dns" section (simulates an old core)
  mock_core.py run   -c cfg.json    -> serves GET /version, GET /proxies/<tag>/delay,
                                       PUT /proxies/route on experimental.clash_api
Delay rules: any tag containing "A2" fails (HTTP 503), others get a deterministic delay.
"""
import json
import os
import re
import sys
import urllib.parse as up
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if sys.argv[1] == "version":
    print("sing-box version 1.99.0-mock")
    sys.exit(0)

cfg_path = sys.argv[sys.argv.index("-c") + 1]
cfg = json.load(open(cfg_path, encoding="utf-8"))

if sys.argv[1] == "check":
    if os.environ.get("MOCK_OLD") and "dns" in cfg:
        print("unknown field dns", file=sys.stderr)
        sys.exit(1)
    if any(o.get("server") == "a3.test" for o in cfg.get("outbounds", [])):
        print("outbound rejected: a3.test", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

port = int(cfg["experimental"]["clash_api"]["external_controller"].split(":")[1])
STATE = {"selected": None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = up.urlparse(self.path).path
        if path == "/version":
            return self._json(200, {"version": "mock"})
        m = re.match(r"/proxies/(.+)/delay", path)
        if m:
            tag = up.unquote(m.group(1))
            if "A2" in tag:
                return self._json(503, {"message": "timeout"})
            return self._json(200, {"delay": 50 + 10 * sum(map(ord, tag)) % 300})
        self._json(404, {})

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        STATE["selected"] = json.loads(self.rfile.read(n))["name"]
        self.send_response(204)
        self.end_headers()


ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
