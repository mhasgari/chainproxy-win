"""
GUI smoke test (tkinter) against the mock core.

    python tests/gui_smoke.py                 Windows / any desktop
    xvfb-run -a python tests/gui_smoke.py     Linux without a display

Drives the real window: Enable -> Next -> pick a route -> follow a CLI 'next' ->
Disable -> Enable again -> close. Message boxes are captured instead of shown.
"""
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_tests import Env  # noqa: E402

FAIL = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg, flush=True)
    if not cond:
        FAIL.append(msg)


def main():
    env = Env()
    dialogs = []
    messagebox.showerror = lambda title, msg, **k: dialogs.append(msg)
    sys.modules.pop("gui", None)
    import gui                                   # imports the env's chain module
    root = tk.Tk()
    g = gui.GUI(root)
    cfg = env.chain.load_cfg()

    def wait_idle(then, delay=300, deadline=None):
        deadline = deadline or time.time() + 60

        def poll():
            if g.busy and time.time() < deadline:
                root.after(200, poll)
            else:
                then()
        root.after(delay, poll)

    def s_enable():
        g.toggle()
        wait_idle(s_after_enable, 600)

    def s_after_enable():
        check(g.state_var.get() == "Active", f"enabled (state={g.state_var.get()!r}, dialogs={dialogs})")
        check(len(g.tree.get_children()) >= 3, f"route list filled ({len(g.tree.get_children())} rows)")
        check(bool(g.route_var.get()) and "->" in g.route_var.get(), f"route label shown ({g.route_var.get()!r})")
        g.next_btn.invoke()
        wait_idle(s_after_next, 600)

    def s_after_next():
        check(g.exit_var.get().startswith("Route 2 of"), f"next -> {g.exit_var.get()!r}")
        g.tree.selection_set("2")
        g.on_pick(None)
        wait_idle(s_after_pick, 600)

    def s_after_pick():
        check(g.exit_var.get().startswith("Route 3 of"), f"double-click pick -> {g.exit_var.get()!r}")
        check(g.tree.set("2", "n").startswith(">") and "active" in g.tree.item("2", "tags")
              and "active" not in g.tree.item("0", "tags"),
              f"picked route is marked in the list ({g.tree.set('2', 'n')!r}, {g.tree.item('2', 'tags')})")
        check(bool(g.tree.set("2", "src")), f"source column filled ({g.tree.set('2', 'src')!r})")
        r = gui.rejected_short("https://gemini.google.com -> no answer (1.2.3.4 JP)")
        check(r == "gemini: no answer", f"short reject reason ({r!r})")
        r = gui.rejected_short("https://gemini.google.com -> Google places this exit in IR (location not supported) (x)")
        check(r == "Google sees exit in IR", f"short Google reason ({r!r})")
        g.logbox.tag_add("sel", "1.0", "end")                  # selecting log text must not clear it
        g.root.update()
        check("active" in g.tree.item("2", "tags"), "the active-route marker survives selecting log text")
        check(bool(g.logbox.get("1.0", "end").strip()), "log box has content")
        reply = env.chain.control_send(cfg, "next", 30)
        check(bool(reply) and reply.startswith("["), f"CLI next while window open -> {reply!r}")
        root.after(1500, s_follow)

    def s_follow():
        check(g.exit_var.get().startswith("Route 1 of"), f"window follows CLI -> {g.exit_var.get()!r}")
        g.toggle()
        wait_idle(s_after_disable, 600)

    def s_after_disable():
        check(g.state_var.get() == "Disabled" and not g.tree.get_children(), "disabled, list cleared")
        check(env.chain.port_free(cfg["api_port"]), "core stopped after disable")
        g.toggle()
        wait_idle(s_after_reenable, 600)

    def s_after_reenable():
        check(g.state_var.get() == "Active", "re-enabled in the same process")
        # update banner: a portable copy only announces a new version
        info = {"version": "9.9.9", "page": "https://example.invalid/r", "sha256": "", "url": None}
        g.cfg["auto_update"] = True
        g.on_update_result(info, False, None)
        check("9.9.9" in g.update_var.get() and g.update_row.winfo_ismapped() is not None, f"update banner ({g.update_var.get()!r})")
        check(g.update_btn.cget("text") == "Open download page", "portable copy gets a download link, not an auto install")
        g.on_update_result(None, True, None)
        check(not g.update_row.winfo_ismapped(), "banner hidden when up to date")
        # closing the window with a tray icon present keeps everything running
        told = []

        class FakeTray:
            ok = True

            def balloon(self, t, m):
                told.append(t)

            def set_tooltip(self, t):
                pass

            def stop(self):
                told.append("stopped")
        if g.tray:                                              # Windows: the real icon is registered
            check(g.tray.ok, "real notification-area icon is registered")
            g.tray.stop()
        g.tray = FakeTray()
        g.on_close()
        root.update()
        check(root.state() == "withdrawn" and g.app is not None, f"X hides the window, the session keeps running ({root.state()})")
        check(bool(told), "first close shows the 'still running' balloon")
        g.on_tray("show")
        root.update()
        check(root.state() == "normal", "tray 'show' brings the window back")
        menu = [m for m in g.tray_menu() if m]
        check([m[1] for m in menu] == ["Open Chain Proxy", "Disable", "Next route", "Check for updates", "Exit"],
              f"tray menu reflects the state ({[m[1] for m in menu]})")
        # single instance: the second start asks the first one to show itself
        port = 29192
        lock = gui.single_instance(port)
        gui.serve_instance(lock, g)
        check(gui.single_instance(port) is None, "second window instance is refused")
        root.after(500, s_quit)

    def s_quit():
        (env.proj / ".quit_request").write_text("1")           # what `chain.py quit` does: the window exits
        root.after(1500, lambda: check(False, "window did not quit on .quit_request") or root.destroy())

    root.after(300, s_enable)
    root.mainloop()
    check(env.chain.port_free(cfg["api_port"]), "core stopped after the window quit")
    check(not dialogs, f"no error dialogs ({dialogs})")
    env.close()
    print("GUI SMOKE:", "FAIL" if FAIL else "PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
