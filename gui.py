#!/usr/bin/env python3
"""Simple window for chainproxy (tkinter, no extra packages). Run: pythonw gui.py"""
import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import chain


def clean(text):
    """Tk 8.6 on Windows cannot draw characters above U+FFFF (emoji, flags): drop them and the
    joiners that go with them instead of showing empty boxes."""
    out = "".join(c for c in text if ord(c) <= 0xFFFF and c not in "\ufe0f\u200d\u200b")
    return " ".join(out.split())


class GUI:
    def __init__(self, root):
        self.root = root
        self.app = None
        self.busy = False
        self.q = queue.Queue()
        chain.LOG_HOOK = lambda line: self.q.put(("log", line))

        root.title("Chain Proxy")
        root.geometry("620x640")
        root.minsize(520, 520)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            root.iconbitmap(str(chain.BASE / "chainproxy.ico"))
        except Exception:
            pass

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        self.state_var = tk.StringVar(value="Disabled")
        self.route_var = tk.StringVar(value="-")
        self.exit_var = tk.StringVar(value="-")
        self.state_lbl = tk.Label(top, textvariable=self.state_var, font=("Segoe UI", 14, "bold"),
                                  fg="#b00020", anchor="w")
        self.state_lbl.pack(fill="x")
        ttk.Label(top, textvariable=self.route_var, wraplength=520).pack(fill="x", anchor="w")
        ttk.Label(top, textvariable=self.exit_var, wraplength=520).pack(fill="x", anchor="w")

        btns = ttk.Frame(root, padding=(10, 0))
        btns.pack(fill="x")
        self.toggle_btn = ttk.Button(btns, text="Enable", command=self.toggle)
        self.toggle_btn.pack(side="left")
        self.prev_btn = ttk.Button(btns, text="< Prev", command=lambda: self.run_bg(self.do_step, -1))
        self.next_btn = ttk.Button(btns, text="Next route >", command=lambda: self.run_bg(self.do_step, 1))
        self.scan_btn = ttk.Button(btns, text="Rescan", command=lambda: self.run_bg(self.do_rescan))
        for b in (self.prev_btn, self.next_btn, self.scan_btn):
            b.pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Settings", command=self.settings).pack(side="right")

        ttk.Label(root, text="Routes (double-click to switch; green = in use):", padding=(10, 8, 10, 0)).pack(anchor="w")
        lf = ttk.Frame(root)
        lf.pack(fill="both", expand=True, padx=10)
        # exportselection=False: selecting text in the log/entries must not clear the active route
        self.lb = tk.Listbox(lf, height=9, activestyle="none", exportselection=False,
                             font=("Consolas", 9), selectbackground="#1b7f2a", selectforeground="white")
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.lb.yview)
        self.lb.config(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.lb.pack(side="left", fill="both", expand=True)
        self.lb.bind("<Double-Button-1>", self.on_pick)

        gf = ttk.Frame(root)
        gf.pack(fill="both", expand=True, padx=10, pady=10)
        self.logbox = tk.Text(gf, height=10, state="disabled", wrap="word", font=("Consolas", 8),
                              bg="#f4f4f4")
        gsb = ttk.Scrollbar(gf, orient="vertical", command=self.logbox.yview)
        self.logbox.config(yscrollcommand=gsb.set)
        gsb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)

        self.set_controls(False)
        self.recover_after_crash()
        self.root.after(150, self.pump)
        if chain.subs_are_placeholder():          # first run: ask for the links
            self.root.after(400, self.settings)

    # ---------------------------------------------------------- helpers
    def recover_after_crash(self):
        """The previous run was killed: its Windows proxy settings (and maybe a stale core) are
        still in place. Put them back now, not only on the next Enable."""
        try:
            if chain.STATE_FILE.exists() and chain.control_send(chain.load_cfg(), "status", 2) is None:
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

    def set_controls(self, active):
        st = "normal" if active and not self.busy else "disabled"
        for b in (self.prev_btn, self.next_btn, self.scan_btn):
            b.config(state=st)
        self.toggle_btn.config(state="disabled" if self.busy else "normal",
                               text="Disable" if active else "Enable")

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
        top = self.lb.yview()[0]
        self.lb.delete(0, "end")
        if not app:
            self.state_var.set("Disabled")
            self.state_lbl.config(fg="#b00020")
            self.route_var.set("-")
            self.exit_var.set("-")
            self.set_controls(False)
            return
        for i, t in enumerate(app.rank):
            self.lb.insert("end", clean(f"{'>' if i == app.idx else ' '} {i + 1:2d}. "
                                        f"{app.delays[t]:5.0f}ms  {app.label(t)}"))
        self.lb.yview_moveto(top)
        if app.idx >= 0:
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(app.idx)          # green row = the route in use
            self.lb.activate(app.idx)
            self.lb.see(app.idx)
            t = app.rank[app.idx]
            self.state_var.set("Active")
            self.state_lbl.config(fg="#1b7f2a")
            self.route_var.set(clean(f"Route {app.idx + 1}/{len(app.rank)}: {app.label(t)}  "
                                     f"({app.delays[t]:.0f} ms)"))
            self.exit_var.set(clean(f"Exit: {app.last_info}"))
        self.set_controls(True)

    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.add_log(val)
                elif kind == "done":
                    self.busy = False
                    if val:
                        self.add_log(val)
                    if val and val.startswith("error:"):
                        messagebox.showerror("Chain Proxy", val[6:].strip())
                    self.refresh_view()
        except queue.Empty:
            pass
        # `next.bat` / `stop.bat` work too: follow what the control socket did
        if self.app is not None and not self.busy:
            if self.app.stop_evt.is_set():
                self.app.cleanup()
                self.app = None
                self.refresh_view()
            elif self.lb.size() and getattr(self, "_seen_idx", None) != self.app.idx:
                self.refresh_view()
        self._seen_idx = self.app.idx if self.app else None
        self.root.after(300, self.pump)

    # ---------------------------------------------------------- actions
    def toggle(self):
        if self.app is None:
            self.state_var.set("Starting ...")
            self.state_lbl.config(fg="#b36b00")
            self.run_bg(self.do_enable)
        else:
            self.run_bg(self.do_disable)

    def do_enable(self):
        cfg = chain.load_cfg()
        self.app = chain.start_session(cfg)
        return "enabled"

    def do_disable(self):
        app, self.app = self.app, None
        app.cleanup()
        return "disabled; Windows proxy restored"

    def do_step(self, step):
        return self.app.go(step)

    def do_rescan(self):
        return self.app.rescan()

    def on_pick(self, _):
        sel = self.lb.curselection()
        if sel and self.app and not self.busy:
            self.run_bg(lambda: self.app.go_to(sel[0]))

    def on_close(self):
        if self.app:
            try:
                self.app.cleanup()
            except Exception:
                pass
        self.root.destroy()

    # ---------------------------------------------------------- settings
    def settings(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("600x470")
        win.transient(self.root)
        cfg = chain.load_cfg()
        srcs = chain.SUBS_FILE.read_text(encoding="utf-8-sig").splitlines() if chain.SUBS_FILE.exists() else []
        srcs = [l.strip() for l in srcs if l.strip() and not l.startswith("#")] + ["", ""]
        if "example.com/sub/" in srcs[0]:         # the template's placeholder: show an empty field
            srcs[0] = ""

        def row(label):
            ttk.Label(win, text=label, justify="left").pack(anchor="w", padx=10, pady=(8, 0))

        row("Subscription 1 (first hop):")
        e1 = ttk.Entry(win)
        e1.insert(0, srcs[0])
        e1.pack(fill="x", padx=10)
        row("Subscription 2 (exit hop) - default: GeminiRoute \"best\" (github.com/alizn7/GeminiRoute):")
        e2 = ttk.Entry(win)
        e2.insert(0, srcs[1])
        e2.pack(fill="x", padx=10)
        row("Strict sites - one per line, e.g. gemini.google.com (https:// is added if you omit it;\n"
            "type http:// only if needed). A route must reach each with status < 400:")
        t = tk.Text(win, height=5)
        t.insert("1.0", "\n".join(cfg["strict_urls"]))
        t.pack(fill="x", padx=10)
        row("Blocked exit countries (comma separated, e.g. IR,RU):")
        e3 = ttk.Entry(win)
        e3.insert(0, ",".join(cfg["blocked_countries"]))
        e3.pack(fill="x", padx=10)
        row("Direct (bypass) domain suffixes (comma separated, e.g. .ir):")
        e4 = ttk.Entry(win)
        e4.insert(0, ",".join(cfg["direct_suffixes"]))
        e4.pack(fill="x", padx=10)
        ttk.Label(win, text="Subscriptions and direct suffixes apply on the next Enable; "
                            "strict sites / countries apply immediately.",
                  foreground="#666").pack(anchor="w", padx=10, pady=8)

        def save():
            raw = {}
            if chain.CFG_FILE.exists():
                raw = json.loads(chain.CFG_FILE.read_text(encoding="utf-8-sig"))
            split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
            raw["strict_urls"] = [chain.normalize_url(x) for x in t.get("1.0", "end").splitlines() if x.strip()]
            raw["blocked_countries"] = [x.upper() for x in split(e3.get())]
            raw["direct_suffixes"] = split(e4.get())
            chain.CFG_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            if self.app:                                  # live-apply
                self.app.cfg["strict_urls"] = raw["strict_urls"]
                self.app.cfg["blocked_countries"] = raw["blocked_countries"]
            if not e1.get().strip():
                messagebox.showerror("Settings", "Subscription 1 is required", parent=win)
                return
            lines = ["# line 1: first subscription (first hop)",
                     "# line 2: second subscription (exit hop)", e1.get().strip()]
            if e2.get().strip():
                lines.append(e2.get().strip())
            chain.SUBS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
            win.destroy()

        ttk.Button(win, text="Save", command=save).pack(pady=6)


def main():
    root = tk.Tk()
    g = GUI(root)
    if "--enable" in sys.argv[1:] and not chain.subs_are_placeholder():
        root.after(500, g.toggle)            # start enabled (used by tests / autostart)
    root.mainloop()


if __name__ == "__main__":
    main()
