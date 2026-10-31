#!/usr/bin/env python3
"""Window + notification-area icon for chainproxy (tkinter, no extra packages). Run: pythonw gui.py"""
import json
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import chain
import tray as tray_mod

# ---- look ------------------------------------------------------------------------------------------
BG, CARD, BORDER = "#f1f5fb", "#ffffff", "#dbe3ee"
TEXT, MUTED = "#172033", "#667389"
ACCENT, ACCENT_DK, ACCENT_LT = "#2563eb", "#1d4ed8", "#e6efff"
OK, OK_LT, WARN, ERR = "#15803d", "#dcfce7", "#c2410c", "#b91c1c"
LOG_BG, LOG_FG = "#0f172a", "#cbd5e1"
FONT = "Segoe UI"
APP_ID = "mhasgari.ChainProxy"

MENU_SHOW, MENU_TOGGLE, MENU_NEXT, MENU_UPDATE, MENU_EXIT = 1, 2, 3, 4, 5


def clean(text):
    """Tk 8.6 on Windows cannot draw characters above U+FFFF (emoji, flags): drop them and the
    joiners that go with them instead of showing empty boxes."""
    out = "".join(c for c in text if ord(c) <= 0xFFFF and c not in "️‍​")
    return " ".join(out.split())


def set_app_identity():
    """Windows groups taskbar buttons / picks their icon by AppUserModelID; without our own id the window
    of pythonw.exe shows the Python logo on some machines."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


class GUI:
    def __init__(self, root):
        self.root = root
        self.app = None
        self.busy = False
        self.q = queue.Queue()
        self.update_info = None
        self.updating = False
        self.tray = None
        self.quitting = False
        chain.LOG_HOOK = lambda line: self.q.put(("log", line))
        self.cfg = chain.load_cfg()

        root.title("Chain Proxy")
        root.geometry("780x700")
        root.minsize(660, 560)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.set_icons()
        self.style()
        self.build()

        self.set_controls(False)
        self.start_tray()
        self.recover_after_crash()
        for stale in (".quit_request",):                         # left over from an installer run
            (chain.BASE / stale).unlink(missing_ok=True)
        self.root.after(150, self.pump)
        self.root.after(1500, self.resume_after_update)
        self.root.after(int(self.cfg.get("update_first_check_seconds", 45)) * 1000, self.update_tick)
        if not chain.sources_configured(self.cfg):               # nothing to try yet: ask for the sources
            self.root.after(500, self.settings)

    # ------------------------------------------------------------------------------- icons / style
    def set_icons(self):
        """PNG icons through iconphoto only. Do NOT also call iconbitmap: with both, Windows shows the Python logo
        in the taskbar and title bar (verified on Windows 11 / Tk 8.6.15)."""
        self.icons = []
        try:                                                    # the taskbar picks the size it needs
            for n in (256, 128, 64, 48, 32, 16):
                self.icons.append(tk.PhotoImage(file=str(chain.BASE / "assets" / f"chainproxy-{n}.png")))
            self.root.iconphoto(True, *self.icons)
        except Exception:
            try:
                self.root.iconbitmap(default=str(chain.BASE / "chainproxy.ico"))      # no PNG support: the ICO
            except Exception:
                pass

    def style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", font=(FONT, 10), background=BG, foreground=TEXT)
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD, relief="flat")
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Card.TLabel", background=CARD)
        st.configure("Muted.TLabel", foreground=MUTED, background=BG)
        st.configure("CardMuted.TLabel", foreground=MUTED, background=CARD)
        st.configure("Title.TLabel", font=(FONT, 17, "bold"), background=CARD)
        st.configure("Route.TLabel", font=(FONT, 11, "bold"), background=CARD)
        st.configure("Section.TLabel", font=(FONT, 10, "bold"), foreground=TEXT, background=BG)
        st.configure("TButton", padding=(14, 7), background=CARD, bordercolor=BORDER, lightcolor=CARD,
                     darkcolor=CARD, focuscolor=CARD, relief="solid", borderwidth=1)
        st.map("TButton", background=[("disabled", "#f3f4f6"), ("active", ACCENT_LT)],
               foreground=[("disabled", "#9aa5b5")], bordercolor=[("active", ACCENT)])
        st.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                     lightcolor=ACCENT, darkcolor=ACCENT, padding=(22, 9), font=(FONT, 10, "bold"))
        st.map("Accent.TButton", background=[("disabled", "#9db8f0"), ("active", ACCENT_DK)],
               foreground=[("disabled", "white")], bordercolor=[("active", ACCENT_DK)])
        st.configure("Stop.TButton", background="#fff1f1", foreground=ERR, bordercolor="#f4b4b4",
                     lightcolor="#fff1f1", darkcolor="#fff1f1", padding=(22, 9), font=(FONT, 10, "bold"))
        st.map("Stop.TButton", background=[("disabled", "#f3f4f6"), ("active", "#ffe0e0")])
        st.configure("Link.TButton", background=CARD, foreground=ACCENT, borderwidth=0, padding=(6, 2),
                     font=(FONT, 10, "underline"))
        st.map("Link.TButton", background=[("active", CARD)])
        st.configure("LinkBg.TButton", background=BG, foreground=ACCENT, borderwidth=0, padding=(6, 2),
                     font=(FONT, 10, "underline"))
        st.map("LinkBg.TButton", background=[("active", BG)])
        st.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=26,
                     borderwidth=0, font=(FONT, 10))
        st.configure("Treeview.Heading", font=(FONT, 9, "bold"), background="#eef2f8", foreground=MUTED,
                     relief="flat", padding=(6, 6))
        st.map("Treeview", background=[("selected", ACCENT_LT)], foreground=[("selected", TEXT)])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", padding=(16, 8), background="#e7edf6", font=(FONT, 10))
        st.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACCENT)])
        st.configure("TCheckbutton", background=CARD, font=(FONT, 10))
        st.configure("TEntry", padding=6, fieldbackground=CARD, bordercolor=BORDER)
        st.configure("Vertical.TScrollbar", background="#e2e8f2", troughcolor=BG, bordercolor=BG,
                     arrowcolor=MUTED, relief="flat")

    def card(self, parent, **pack):
        outer = tk.Frame(parent, bg=BORDER)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=14)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        outer.pack(**pack)
        return inner

    # ------------------------------------------------------------------------------------- layout
    def build(self):
        root = self.root
        wrap = ttk.Frame(root, padding=(16, 14, 16, 12))
        wrap.pack(fill="both", expand=True)

        head = self.card(wrap, fill="x")
        left = ttk.Frame(head, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True)
        try:
            self.logo = tk.PhotoImage(file=str(chain.BASE / "assets" / "chainproxy-48.png"))
            tk.Label(left, image=self.logo, bg=CARD).pack(side="left", padx=(0, 12))
        except Exception:
            pass
        titles = ttk.Frame(left, style="Card.TFrame")
        titles.pack(side="left")
        ttk.Label(titles, text="Chain Proxy", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text=f"Lantern  /  subscriptions  /  v2ray profiles      v{chain.__version__}",
                  style="CardMuted.TLabel").pack(anchor="w")
        right = ttk.Frame(head, style="Card.TFrame")
        right.pack(side="right")
        self.state_var = tk.StringVar(value="Disabled")
        self.state_lbl = tk.Label(right, textvariable=self.state_var, font=(FONT, 10, "bold"), fg="white",
                                  bg="#8a94a6", padx=14, pady=4)
        self.state_lbl.pack(side="left", padx=(0, 12))
        self.toggle_btn = ttk.Button(right, text="Enable", style="Accent.TButton", command=self.toggle)
        self.toggle_btn.pack(side="left")

        info = self.card(wrap, fill="x", pady=(10, 0))
        self.route_var = tk.StringVar(value="No active route")
        self.exit_var = tk.StringVar(value="Press Enable to start")
        self.src_var = tk.StringVar(value="")
        ttk.Label(info, textvariable=self.route_var, style="Route.TLabel", wraplength=700).pack(anchor="w")
        ttk.Label(info, textvariable=self.exit_var, style="Card.TLabel", wraplength=700).pack(anchor="w", pady=(2, 0))
        ttk.Label(info, textvariable=self.src_var, style="CardMuted.TLabel", wraplength=700).pack(anchor="w", pady=(2, 0))
        self.update_row = ttk.Frame(info, style="Card.TFrame")
        self.update_var = tk.StringVar(value="")
        ttk.Label(self.update_row, textvariable=self.update_var, style="Card.TLabel", foreground=WARN).pack(side="left")
        self.update_btn = ttk.Button(self.update_row, text="Install now", style="Link.TButton", command=self.install_update)
        self.update_btn.pack(side="left", padx=8)

        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(10, 8))
        self.prev_btn = ttk.Button(btns, text="Prev", command=lambda: self.run_bg(self.do_step, -1))
        self.next_btn = ttk.Button(btns, text="Next route", command=lambda: self.run_bg(self.do_step, 1))
        self.scan_btn = ttk.Button(btns, text="Rescan", command=lambda: self.run_bg(self.do_rescan))
        for b in (self.prev_btn, self.next_btn, self.scan_btn):
            b.pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Settings", command=self.settings).pack(side="right")

        ttk.Label(wrap, text="Routes   (double-click to switch, green = in use)", style="Section.TLabel").pack(anchor="w")
        box = tk.Frame(wrap, bg=BORDER)
        box.pack(fill="both", expand=True, pady=(4, 10))
        inner = ttk.Frame(box)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        cols = ("n", "ms", "route", "src")
        self.tree = ttk.Treeview(inner, columns=cols, show="headings", selectmode="browse", height=8)
        for c, title, w, anchor in (("n", "#", 46, "center"), ("ms", "ms", 64, "e"),
                                    ("route", "Route", 330, "w"), ("src", "Source", 240, "w")):
            self.tree.heading(c, text=title, anchor="w" if anchor == "w" else "center")
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "route"))
        self.tree.tag_configure("active", background=OK_LT, foreground="#14532d", font=(FONT, 10, "bold"))
        self.tree.tag_configure("odd", background="#f8fafd")
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-Button-1>", self.on_pick)
        self.tree.bind("<Return>", self.on_pick)

        logbar = ttk.Frame(wrap)
        logbar.pack(fill="x")
        ttk.Label(logbar, text="Log", style="Section.TLabel").pack(side="left")
        ttk.Button(logbar, text="Clear", style="LinkBg.TButton", command=self.clear_log).pack(side="right")
        ttk.Button(logbar, text="Copy", style="LinkBg.TButton", command=self.copy_log).pack(side="right")
        gf = tk.Frame(wrap, bg=BORDER)
        gf.pack(fill="both", expand=True, pady=(4, 0))
        gin = tk.Frame(gf, bg=LOG_BG)
        gin.pack(fill="both", expand=True, padx=1, pady=1)
        self.logbox = tk.Text(gin, height=8, state="disabled", wrap="word", font=("Consolas", 9), bg=LOG_BG,
                              fg=LOG_FG, relief="flat", padx=10, pady=8, insertbackground=LOG_FG, borderwidth=0)
        gsb = ttk.Scrollbar(gin, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=gsb.set)
        gsb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------------------------ tray / window
    def tray_menu(self):
        on = self.app is not None
        return [(MENU_SHOW, "Open Chain Proxy", True),
                (MENU_TOGGLE, "Disable" if on else "Enable", not self.busy),
                (MENU_NEXT, "Next route", on and not self.busy),
                None,
                (MENU_UPDATE, "Check for updates", True),
                None,
                (MENU_EXIT, "Exit", True)]

    def start_tray(self):
        ico = chain.BASE / "chainproxy.ico"
        self.tray = tray_mod.Tray(ico, "Chain Proxy - disabled", lambda cmd: self.q.put(("tray", cmd)),
                                  self.tray_menu, self.on_endsession)
        if not (ico.exists() and self.tray.start()):
            self.tray = None

    def show_window(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(250, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def on_close(self):
        """The X button: keep running in the notification area (unless there is none / it is disabled)."""
        if self.tray and self.cfg.get("close_to_tray", True):
            self.root.withdraw()
            if not getattr(self, "_told_tray", False):
                self._told_tray = True
                self.tray.balloon("Chain Proxy is still running",
                                  "Right-click the icon next to the clock and choose Exit to quit.")
            return
        self.exit_app()

    def exit_app(self):
        if self.quitting:
            return
        self.quitting = True
        try:
            if self.app:
                self.app.cleanup()
        except Exception:
            pass
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def on_endsession(self):
        """Windows is logging off / shutting down (called on the tray thread): restore the proxy settings."""
        try:
            if self.app:
                self.app.cleanup()
            chain.sys_proxy_restore()
        except Exception:
            pass

    # ------------------------------------------------------------------------------------ helpers
    def recover_after_crash(self):
        """The previous run was killed: its Windows proxy settings (and maybe a stale core) are
        still in place. Put them back now, not only on the next Enable."""
        try:
            if chain.STATE_FILE.exists() and chain.control_send(self.cfg, "status", 2) is None:
                chain.sys_proxy_restore()
                chain.kill_stale_core()
                self.add_log("previous run did not exit cleanly: Windows proxy settings restored")
        except BaseException as e:
            self.add_log(f"crash recovery failed: {getattr(e, 'code', None) or e}")

    def add_log(self, line):
        self.logbox.config(state="normal")
        self.logbox.insert("end", clean(line) + "\n")
        if int(self.logbox.index("end-1c").split(".")[0]) > 1500:      # keep the box small
            self.logbox.delete("1.0", "300.0")
        self.logbox.see("end")
        self.logbox.config(state="disabled")

    def clear_log(self):
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.config(state="disabled")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.logbox.get("1.0", "end"))

    def set_controls(self, active):
        st = "normal" if active and not self.busy else "disabled"
        for b in (self.prev_btn, self.next_btn, self.scan_btn):
            b.config(state=st)
        self.toggle_btn.config(state="disabled" if self.busy else "normal",
                               text="Disable" if active else "Enable",
                               style="Stop.TButton" if active else "Accent.TButton")

    def set_state(self, text, color):
        self.state_var.set(text)
        self.state_lbl.config(bg=color)

    def run_bg(self, fn, *args):
        if self.busy:
            return
        self.busy = True
        self.set_controls(self.app is not None)

        def work():
            try:
                msg = fn(*args)
            except BaseException as e:           # SystemExit from start_session too
                msg = f"error: {getattr(e, 'code', None) or e}"
            self.q.put(("done", msg))
        threading.Thread(target=work, daemon=True).start()

    def refresh_view(self):
        app = self.app
        top = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        if not app:
            self.set_state("Disabled", "#8a94a6")
            self.route_var.set("No active route")
            self.exit_var.set("Press Enable to start")
            self.src_var.set("")
            self.set_controls(False)
            self.update_tray_tip()
            return
        for i, t in enumerate(app.rank):
            tags = ["active"] if i == app.idx else (["odd"] if i % 2 else [])
            self.tree.insert("", "end", iid=str(i), tags=tags, values=(
                (">" if i == app.idx else "") + str(i + 1), f"{app.delays[t]:.0f}", clean(app.label(t)),
                app.source_label(t)))
        self.tree.yview_moveto(top)
        if app.idx >= 0:
            self.tree.selection_remove(*self.tree.selection())      # the green row is the marker, not a selection
            self.tree.see(str(app.idx))
            t = app.rank[app.idx]
            self.set_state("Active", OK)
            self.route_var.set(clean(f"{app.label(t)}"))
            self.exit_var.set(clean(f"Route {app.idx + 1} of {len(app.rank)}  -  {app.delays[t]:.0f} ms  -  "
                                    f"exit: {app.last_info}"))
            self.src_var.set(self.sources_text())
        self.set_controls(True)
        self.update_tray_tip()

    def sources_text(self):
        app = self.app
        parts = []
        ln = app.lantern if app else None
        if ln is not None:
            parts.append("Lantern: " + ("connected (free plan, best server)" if ln.ready else
                                         f"{ln.status}" + (f" - {ln.error}" if ln.error else "")))
        elif self.cfg.get("lantern_enabled"):
            parts.append("Lantern: off")
        return clean("   |   ".join(parts))

    def update_tray_tip(self):
        if not self.tray:
            return
        app = self.app
        if app and app.idx >= 0:
            tip = clean(f"Chain Proxy - active\n{app.label(app.rank[app.idx])}")
        else:
            tip = "Chain Proxy - disabled"
        self.tray.set_tooltip(tip)

    def pump(self):
        try:
            while True:
                kind, *val = self.q.get_nowait()
                if kind == "log":
                    self.add_log(val[0])
                elif kind == "done":
                    self.busy = False
                    msg = val[0]
                    if msg:
                        self.add_log(msg)
                    if msg and msg.startswith("error:"):
                        self.show_window()
                        messagebox.showerror("Chain Proxy", msg[6:].strip())
                    self.refresh_view()
                elif kind == "tray":
                    self.on_tray(val[0])
                elif kind == "update":
                    self.on_update_result(*val)
                elif kind == "exit":
                    self.exit_app()
                    return
        except queue.Empty:
            pass
        if (chain.BASE / ".quit_request").exists():              # `chain.py quit` (installer / updater)
            (chain.BASE / ".quit_request").unlink(missing_ok=True)
            self.exit_app()
            return
        # `next.bat` / `stop.bat` work too: follow what the control socket did
        if self.app is not None and not self.busy:
            if self.app.stop_evt.is_set():
                self.app.cleanup()
                self.app = None
                self.refresh_view()
            elif self.tree.get_children() and getattr(self, "_seen_idx", None) != self.app.idx:
                self.refresh_view()
            elif self.app.lantern is not None and getattr(self, "_seen_ln", None) != (self.app.lantern.ready,
                                                                                      self.app.lantern.status):
                self.src_var.set(self.sources_text())
        self._seen_idx = self.app.idx if self.app else None
        ln = self.app.lantern if self.app else None
        self._seen_ln = (ln.ready, ln.status) if ln else None
        self.root.after(300, self.pump)

    def on_tray(self, cmd):
        if cmd == "show":
            self.show_window()
        elif cmd == MENU_SHOW:
            self.show_window()
        elif cmd == MENU_TOGGLE:
            if not self.busy:
                self.toggle()
        elif cmd == MENU_NEXT:
            if self.app and not self.busy:
                self.run_bg(self.do_step, 1)
        elif cmd == MENU_UPDATE:
            self.check_updates(manual=True)
        elif cmd == MENU_EXIT:
            self.exit_app()

    # ---------------------------------------------------------------------------------- actions
    def toggle(self):
        if self.app is None:
            self.set_state("Starting ...", WARN)
            self.run_bg(self.do_enable)
        else:
            self.run_bg(self.do_disable)

    def do_enable(self):
        self.cfg = chain.load_cfg()
        self.app = chain.start_session(self.cfg)
        return "enabled"

    def do_disable(self):
        app, self.app = self.app, None
        app.cleanup()
        return "disabled; Windows proxy restored"

    def do_step(self, step):
        return self.app.go(step)

    def do_rescan(self):
        return self.app.rescan()

    def on_pick(self, _=None):
        sel = self.tree.selection()
        if sel and self.app and not self.busy:
            i = int(sel[0])
            self.run_bg(lambda: self.app.go_to(i))

    def resume_after_update(self):
        marker = chain.BASE / ".resume_enabled"
        if marker.exists():
            marker.unlink(missing_ok=True)
            if self.app is None and not self.busy:
                self.add_log("updated: enabling again")
                self.toggle()
        elif "--enable" in sys.argv[1:] and self.app is None and not self.busy \
                and chain.sources_configured(self.cfg):
            self.toggle()

    # ------------------------------------------------------------------------------------ updates
    def update_tick(self):
        if not self.quitting:
            self.check_updates(manual=False)
            hours = max(1, int(self.cfg.get("update_check_hours", 6)))
            self.root.after(hours * 3600 * 1000, self.update_tick)

    def check_updates(self, manual):
        def work():
            try:
                self.q.put(("update", chain.update_available(chain.load_cfg()), manual, None))
            except Exception as e:
                self.q.put(("update", None, manual, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def on_update_result(self, info, manual, error):
        if error:
            if manual:
                self.add_log(f"update check failed: {error}")
            return
        if not info:
            self.update_info = None
            self.update_row.pack_forget()
            if manual:
                self.add_log(f"Chain Proxy {chain.__version__} is up to date")
            return
        self.update_info = info
        self.add_log(f"update available: {info['version']} (installed {chain.__version__})")
        can_auto = chain.installed_by_installer() and info.get("sha256")
        if can_auto and self.cfg.get("auto_update", True):
            self.update_var.set(f"Updating to {info['version']} ...")
            self.update_btn.pack_forget()
            self.update_row.pack(anchor="w", pady=(6, 0))
            self.install_update()
            return
        self.update_var.set(f"Version {info['version']} is available.")
        if can_auto:
            self.update_btn.config(text="Install now", command=self.install_update)
        else:
            self.update_btn.config(text="Open download page", command=self.open_release_page)
        if not self.update_btn.winfo_ismapped():
            self.update_btn.pack(side="left", padx=8)
        self.update_row.pack(anchor="w", pady=(6, 0))

    def open_release_page(self):
        import webbrowser
        webbrowser.open((self.update_info or {}).get("page") or "https://github.com/mhasgari/chainproxy-win/releases")

    def install_update(self):
        info = self.update_info
        if not info or self.updating:
            return
        self.updating = True
        self.add_log(f"downloading Chain Proxy {info['version']} ...")

        def work():
            try:
                path = chain.download_update(info)
                self.q.put(("log", "update downloaded and verified (sha256); installing and restarting ..."))
                chain.apply_update(path, resume=self.app is not None)
                self.q.put(("exit",))
            except Exception as e:
                self.updating = False
                self.q.put(("log", f"update failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------------------------ settings
    def settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.lift()
            return
        win = self._settings = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("700x700")
        win.minsize(620, 600)
        win.configure(bg=BG)
        win.transient(self.root)
        cfg = chain.load_cfg()
        a_sub, b_sub = chain.subscription_sources()
        first_prof = "\n".join(chain.read_lines(chain.FIRST_PROFILES))
        exit_prof = "\n".join(chain.read_lines(chain.EXIT_PROFILES))

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=14, pady=(14, 6))

        def page(title):
            f = ttk.Frame(nb, style="Card.TFrame", padding=16)
            nb.add(f, text=title)
            return f

        def label(parent, text, muted=False, bold=False):
            lb = ttk.Label(parent, text=text, style="CardMuted.TLabel" if muted else "Card.TLabel",
                           wraplength=620, justify="left")
            if bold:
                lb.configure(font=(FONT, 10, "bold"))
            lb.pack(anchor="w", pady=(10, 2))
            return lb

        def textbox(parent, height, content):
            frame = tk.Frame(parent, bg=BORDER)
            frame.pack(fill="x")
            t = tk.Text(frame, height=height, font=("Consolas", 9), relief="flat", padx=8, pady=6, wrap="none",
                        bg="#fbfcfe", fg=TEXT, insertbackground=TEXT, borderwidth=0)
            t.pack(fill="x", padx=1, pady=1)
            t.insert("1.0", content)
            return t

        # ---- Sources
        src = page("Sources")
        label(src, "First hop  -  tried in this order (a lower one is the fallback of the higher ones)", bold=True)
        lantern_var = tk.BooleanVar(value=bool(cfg["lantern_enabled"]))
        ttk.Checkbutton(src, text="1.  Lantern - free plan, the best server is chosen automatically",
                        variable=lantern_var).pack(anchor="w", pady=(4, 0))
        eng = "ready" if chain.engine_exe() else "downloaded once on first use (about 24 MB)"
        ttk.Label(src, text=f"      engine: {eng}", style="CardMuted.TLabel").pack(anchor="w")
        label(src, "2.  Subscription link")
        e1 = ttk.Entry(src)
        e1.insert(0, a_sub or "")
        e1.pack(fill="x")
        label(src, "3.  v2ray profiles - one link per line (vless://  vmess://  trojan://  ss://  hysteria2://)")
        t_first = textbox(src, 4, first_prof)
        label(src, "Exit hop  -  tried in this order", bold=True)
        label(src, "1.  Subscription link")
        e2 = ttk.Entry(src)
        e2.insert(0, b_sub or "")
        e2.pack(fill="x")
        label(src, "2.  v2ray profiles - one link per line")
        t_exit = textbox(src, 4, exit_prof)
        label(src, "Changes to the sources apply the next time you press Enable.", muted=True)

        # ---- Filters
        flt = page("Filters")
        label(flt, "Strict sites - one per line, e.g. gemini.google.com (https:// is added if you "
                                     "omit it; type http:// only if needed). A route must reach each with status < 400:")
        t_strict = textbox(flt, 5, "\n".join(cfg["strict_urls"]))
        label(flt, "Blocked exit countries (comma separated, e.g. IR,RU):")
        e3 = ttk.Entry(flt)
        e3.insert(0, ",".join(cfg["blocked_countries"]))
        e3.pack(fill="x")
        label(flt, "Direct (bypass) domain suffixes (comma separated, e.g. .ir):")
        e4 = ttk.Entry(flt)
        e4.insert(0, ",".join(cfg["direct_suffixes"]))
        e4.pack(fill="x")
        label(flt, "Strict sites and blocked countries apply immediately; direct suffixes on the next Enable.",
              muted=True)

        # ---- General
        gen = page("General")
        tray_var = tk.BooleanVar(value=bool(cfg["close_to_tray"]))
        ttk.Checkbutton(gen, text="Keep running in the notification area when the window is closed "
                                  "(Exit from the icon's menu quits)", variable=tray_var).pack(anchor="w", pady=(4, 0))
        upd_var = tk.BooleanVar(value=bool(cfg["auto_update"]))
        ttk.Checkbutton(gen, text="Install new versions automatically", variable=upd_var).pack(anchor="w", pady=(10, 0))
        mode = "installer build: updates install silently and the app restarts" if chain.installed_by_installer() \
            else "portable/dev copy: new versions are only announced (download them from the release page)"
        label(gen, mode, muted=True)
        row = ttk.Frame(gen, style="Card.TFrame")
        row.pack(anchor="w", pady=6)
        ttk.Button(row, text="Check for updates now", command=lambda: self.check_updates(manual=True)).pack(side="left")
        ttk.Label(row, text=f"  installed: {chain.__version__}", style="CardMuted.TLabel").pack(side="left")

        # ---- About
        about = page("About")
        label(about, f"Chain Proxy {chain.__version__}", bold=True)
        label(about, "Chains two sources of proxies (client -> first hop -> exit hop -> internet) with sing-box, picks "
                     "the best route that passes verification and sets the Windows proxy.")
        label(about, "MIT license.   https://github.com/mhasgari/chainproxy-win", muted=True)
        label(about, "The Lantern engine is Lantern's open-source client backend "
                     "(https://github.com/getlantern/radiance, GPL-3.0) running as a separate program; "
                     f"build {chain.LANTERN_ENGINE['commit']}.", muted=True)
        label(about, "sing-box: https://github.com/SagerNet/sing-box (GPL-3.0 with additional terms).", muted=True)

        def split(s):
            return [x.strip() for x in s.split(",") if x.strip()]

        def lines(widget):
            return [x.strip() for x in widget.get("1.0", "end").splitlines() if x.strip() and not x.startswith("#")]

        def save():
            raw = {}
            if chain.CFG_FILE.exists():
                raw = json.loads(chain.CFG_FILE.read_text(encoding="utf-8-sig"))
            raw["strict_urls"] = [chain.normalize_url(x) for x in lines(t_strict)]
            raw["blocked_countries"] = [x.upper() for x in split(e3.get())]
            raw["direct_suffixes"] = split(e4.get())
            raw["lantern_enabled"] = bool(lantern_var.get())
            raw["close_to_tray"] = bool(tray_var.get())
            raw["auto_update"] = bool(upd_var.get())
            if not (raw["lantern_enabled"] or e1.get().strip() or e2.get().strip() or lines(t_first) or lines(t_exit)):
                messagebox.showerror("Settings", "Enable Lantern or give at least one subscription link / profile.",
                                     parent=win)
                return
            chain.CFG_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            self.cfg = chain.load_cfg()
            if self.app:                                  # live-apply
                for k in ("strict_urls", "blocked_countries", "close_to_tray", "auto_update"):
                    self.app.cfg[k] = self.cfg[k]
            sub_lines = ["# line 1: first-hop subscription   line 2: exit-hop subscription",
                         "# (a link of example.com/sub/ means 'not set')",
                         e1.get().strip() or "https://example.com/sub/first"]
            if e2.get().strip():
                sub_lines.append(e2.get().strip())
            chain.SUBS_FILE.write_text("\n".join(sub_lines) + "\n", encoding="utf-8")
            for path, widget in ((chain.FIRST_PROFILES, t_first), (chain.EXIT_PROFILES, t_exit)):
                items = lines(widget)
                if items:
                    path.write_text("\n".join(items) + "\n", encoding="utf-8")
                else:
                    path.unlink(missing_ok=True)
            self.add_log("settings saved")
            win.destroy()

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=14, pady=(2, 14))
        ttk.Button(bar, text="Save", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)


# ---------------------------------------------------------------------------------- single instance
def single_instance(port):
    """Bind a loopback port. Returns the socket when we are the only window; otherwise asks the running one
    to show itself and returns None."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        s.listen(4)
        return s
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", port), 2) as c:
                c.sendall(b"show\n")
        except OSError:
            pass
        s.close()
        return None


def serve_instance(sock, gui):
    def loop():
        while True:
            try:
                conn, _ = sock.accept()
                with conn:
                    conn.settimeout(1)
                    if conn.recv(16).startswith(b"show"):
                        gui.q.put(("tray", "show"))
            except OSError:
                return
    threading.Thread(target=loop, daemon=True).start()


def main():
    set_app_identity()
    cfg = chain.load_cfg()
    lock = single_instance(cfg["gui_port"])
    if lock is None:
        return                                    # another window lives in the tray: it was asked to show itself
    root = tk.Tk()
    g = GUI(root)
    serve_instance(lock, g)
    if "--tray" in sys.argv[1:]:
        root.after(200, root.withdraw)
    root.mainloop()


if __name__ == "__main__":
    main()
