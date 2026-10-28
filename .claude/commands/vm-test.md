---
description: Run the Windows VM test suite and analyse the result
argument-hint: "[all|install|unit|e2e|gui] (default: all)"
---
Run the Windows VM tests for chainproxy and report what happened.

1. Run `make vm-doctor`. If it reports a FAIL, stop and explain the fix it suggests
   (do not run sudo yourself).
2. Run `python3 dev/vm/vmtest.py <stage>` where <stage> is "$ARGUMENTS" (use `all` when it is empty).
3. Read `dev/artifacts/vm-latest/summary.json` and the logs of every FAIL stage in
   `dev/artifacts/vm-latest/` (install.log, unit.log, e2e.log, gui.log, e2e-core.log,
   lab/lab-singbox.log, lab-evidence.json). Look at the gui-*.png screenshots if the GUI
   stage ran.
4. For each failure: the failing check, the most likely cause in the code (file + function),
   and a proposed fix. Do not change code unless I ask.
