"""
Fake `chainlantern` engine for tests: speaks the same stdout protocol and listens on --listen.

  mock_lantern.py --data-path D --listen 127.0.0.1:PORT [--log-level L]

MOCK_LANTERN=fail     -> prints an ERROR and never becomes ready
MOCK_LANTERN=die      -> becomes ready, then exits after 2 s (crash)
Exits when stdin is closed, like the real engine.
"""
import os
import socket
import sys
import threading
import time

args = sys.argv[1:]
addr = args[args.index("--listen") + 1]
host, port = addr.rsplit(":", 1)
mode = os.environ.get("MOCK_LANTERN", "")


def say(text):
    print("CHAINLANTERN " + text, flush=True)


say("STATUS connecting")
if mode == "fail":
    say("ERROR connect: no free server reachable")
    time.sleep(30)
    sys.exit(1)
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((host, int(port)))
srv.listen(8)
threading.Thread(target=lambda: [srv.accept() for _ in iter(int, 1)], daemon=True).start()
say("READY " + addr)
if mode == "die":
    time.sleep(2)
    sys.exit(3)
threading.Thread(target=lambda: [(say("STATUS connected"), time.sleep(1)) for _ in iter(int, 1)], daemon=True).start()
sys.stdin.read()                 # returns at EOF: the parent closed our stdin
