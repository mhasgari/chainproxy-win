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
        check(g.lb.size() >= 3, f"route list filled ({g.lb.size()} rows)")
        g.next_btn.invoke()
        wait_idle(s_after_next, 600)

    def s_after_next():
        check(g.route_var.get().startswith("Route 2/"), f"next -> {g.route_var.get()!r}")
        g.lb.selection_clear(0, "end")
        g.lb.selection_set(2)
        g.on_pick(None)
        wait_idle(s_after_pick, 600)

    def s_after_pick():
        check(g.route_var.get().startswith("Route 3/"), f"double-click pick -> {g.route_var.get()!r}")
        check(g.lb.curselection() == (2,) and g.lb.get(2).lstrip().startswith(">"),
              f"picked route is marked in the list ({g.lb.curselection()}, {g.lb.get(2)!r})")
        g.logbox.tag_add("sel", "1.0", "end")                  # selecting log text must not clear it
        g.root.update()
        check(g.lb.curselection() == (2,), "list selection survives selecting log text")
        check(bool(g.logbox.get("1.0", "end").strip()), "log box has content")
        reply = env.chain.control_send(cfg, "next", 30)
        check(bool(reply) and reply.startswith("["), f"CLI next while window open -> {reply!r}")
        root.after(1500, s_follow)

    def s_follow():
        check(g.route_var.get().startswith("Route 1/"), f"window follows CLI -> {g.route_var.get()!r}")
        g.toggle()
        wait_idle(s_after_disable, 600)

    def s_after_disable():
        check(g.state_var.get() == "Disabled" and g.lb.size() == 0, "disabled, list cleared")
        check(env.chain.port_free(cfg["api_port"]), "core stopped after disable")
        g.toggle()
        wait_idle(s_after_reenable, 600)

    def s_after_reenable():
        check(g.state_var.get() == "Active", "re-enabled in the same process")
        g.on_close()

    root.after(300, s_enable)
    root.mainloop()
    check(env.chain.port_free(cfg["api_port"]), "core stopped after closing the window")
    check(not dialogs, f"no error dialogs ({dialogs})")
    env.close()
    print("GUI SMOKE:", "FAIL" if FAIL else "PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
