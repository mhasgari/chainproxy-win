"""
Notification-area ("system tray") icon for Chain Proxy - Windows only, ctypes only (no extra packages).

A hidden window on its own thread owns the icon and the right-click menu. Menu choices and clicks are
handed to `on_command(name)`; the GUI turns them into Tk actions (nothing here touches Tk).
It also receives the session-end messages: when Windows logs off / shuts down, `on_endsession()` runs
so the system proxy is restored even though no window was ever closed.

    t = Tray(icon_path, "Chain Proxy", on_command, get_menu, on_endsession)
    if t.start(): ...                # False -> no tray available: closing the window must exit
"""
import ctypes
import os
import threading
from ctypes import wintypes

IS_WIN = os.name == "nt"

WM_NULL, WM_DESTROY, WM_COMMAND = 0x0000, 0x0002, 0x0111
WM_QUERYENDSESSION, WM_ENDSESSION = 0x0011, 0x0016
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_APP = 0x8000
WM_TRAY, WM_REFRESH, WM_BALLOON, WM_STOP = WM_APP + 1, WM_APP + 2, WM_APP + 3, WM_APP + 4
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_BOTTOMALIGN, TPM_RETURNCMD = 0x2, 0x20, 0x100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON = 49


if IS_WIN:
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                    ("szInfo", ctypes.c_wchar * 256), ("uTimeout", wintypes.UINT),
                    ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.LPVOID]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class Tray:
    def __init__(self, icon_path, tooltip, on_command, get_menu, on_endsession=None):
        self.icon_path = str(icon_path)
        self.tip = tooltip
        self.on_command = on_command
        self.get_menu = get_menu            # -> [(id, label, enabled), ...] with None = separator
        self.on_endsession = on_endsession
        self.ok = False
        self.hwnd = None
        self._balloon = None
        self._ready = threading.Event()
        self._thread = None
        self._wndproc = None                # keep the callback alive
        self._hicon = None
        self._created_msg = 0
        self._nid = None

    # ---------------------------------------------------------------- public
    def start(self, timeout=5.0):
        if not IS_WIN:
            return False
        self._thread = threading.Thread(target=self._run, daemon=True, name="tray")
        self._thread.start()
        self._ready.wait(timeout)
        return self.ok

    def set_tooltip(self, text):
        if self.ok and text != self.tip:
            self.tip = text
            user32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)

    def balloon(self, title, text):
        if self.ok:
            self._balloon = (title, text)
            user32.PostMessageW(self.hwnd, WM_BALLOON, 0, 0)

    def stop(self):
        if self.ok and self.hwnd:
            user32.PostMessageW(self.hwnd, WM_STOP, 0, 0)
            if self._thread:
                self._thread.join(3)
        self.ok = False

    # ---------------------------------------------------------------- thread
    def _data(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self.tip[:127]
        return nid

    def _add(self):
        return bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP))))

    def _popup(self):
        menu = user32.CreatePopupMenu()
        for item in self.get_menu():
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                ident, label, enabled = item
                user32.AppendMenuW(menu, MF_STRING | (0 if enabled else MF_GRAYED), ident, label)
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)          # otherwise the menu does not close when clicking away
        chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD, pt.x, pt.y, 0,
                                       self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if chosen:
            self.on_command(chosen)

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                if lparam in (WM_LBUTTONDBLCLK, WM_LBUTTONUP):
                    self.on_command("show")
                elif lparam == WM_RBUTTONUP:
                    self._popup()
                return 0
            if msg == WM_REFRESH:
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data(NIF_TIP)))
                return 0
            if msg == WM_BALLOON and self._balloon:
                nid = self._data(NIF_INFO)
                nid.szInfoTitle, nid.szInfo = self._balloon[0][:63], self._balloon[1][:255]
                nid.dwInfoFlags = NIIF_INFO
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
                return 0
            if msg == self._created_msg and self._created_msg:      # explorer.exe restarted: put the icon back
                self._add()
                return 0
            if msg == WM_QUERYENDSESSION:
                return 1
            if msg == WM_ENDSESSION and wparam and self.on_endsession:
                self.on_endsession()                                # logoff / shutdown: restore the proxy now
                return 0
            if msg == WM_STOP:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc = WNDPROC(self._proc)
            cls = WNDCLASSW()
            cls.lpfnWndProc = self._wndproc
            cls.hInstance = hinst
            cls.lpszClassName = "ChainProxyTrayWindow"
            user32.RegisterClassW(ctypes.byref(cls))
            self.hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "Chain Proxy tray", 0, 0, 0, 0, 0, None, None,
                                               hinst, None)
            if not self.hwnd:
                return
            size = user32.GetSystemMetrics(SM_CXSMICON) or 16
            self._hicon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            self._created_msg = user32.RegisterWindowMessageW("TaskbarCreated")
            self.ok = self._add()
        except Exception:
            self.ok = False
        finally:
            self._ready.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._hicon:
            user32.DestroyIcon(self._hicon)
        self.ok = False
