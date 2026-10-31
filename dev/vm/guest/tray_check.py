"""Run on the VM desktop by `vmtest.py gui`: the real notification-area icon, its menu and session-end hook."""
import ctypes
import sys
import time
from pathlib import Path

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo))
import tray

out = open(repo / "runtime" / "tray-check.log", "w", buffering=1)


def say(text):
    print(text, file=out)


cmds = []
MENU = lambda: [(1, "Open Chain Proxy", True), (2, "Enable", True), (3, "Next route", False), None,
                (4, "Check for updates", True), None, (5, "Exit", True)]
t = tray.Tray(repo / "chainproxy.ico", "Chain Proxy - tray check", cmds.append, MENU, lambda: cmds.append("endsession"))
say(f"TRAY_OK {t.ok}")
u = ctypes.WinDLL("user32")
u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
if t.start():
    say(f"TRAY_OK {t.ok}")
    u.PostMessageW(t.hwnd, tray.WM_TRAY, 0, tray.WM_LBUTTONDBLCLK)
    time.sleep(1)
    say(f"DBLCLICK_SHOW {'show' in cmds}")
    say(f"QUERYEND {u.SendMessageW(t.hwnd, tray.WM_QUERYENDSESSION, 0, 0)}")
    u.SendMessageW(t.hwnd, tray.WM_ENDSESSION, 1, 0)
    say(f"ENDSESSION_HOOK {'endsession' in cmds}")
    t.balloon("Chain Proxy is still running", "Right-click the icon next to the clock and choose Exit to quit.")
    t.set_tooltip("Chain Proxy - active\nA0:Lantern (auto) -> B1:test")
    time.sleep(1)
    u.PostMessageW(t.hwnd, tray.WM_TRAY, 0, tray.WM_RBUTTONUP)      # opens the menu (blocks the tray thread)
    say("MENU_OPEN")
    time.sleep(7)                                                    # the host takes a screenshot meanwhile
    u.keybd_event = ctypes.windll.user32.keybd_event
    ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)                  # Esc closes the menu
    ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
    time.sleep(1)
    u.PostMessageW(t.hwnd, tray.WM_TRAY, 0, tray.WM_LBUTTONUP)
    time.sleep(1)
    say(f"STILL_RESPONDING {cmds.count('show') >= 2}")
    t.stop()
    say(f"STOPPED {not t.ok}")
say("TRAY_DONE")
