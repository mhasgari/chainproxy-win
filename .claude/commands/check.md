---
description: Run every local check (no VM) and summarise
---
Run `make check` (lint, unit tests, dev-tool tests, GUI smoke under Xvfb, local end-to-end with
the real sing-box). Summarise PASS/FAIL per part; for failures show the relevant output and
the likely cause. If `e2e-local` fails because sing-box is missing or lacks with_clash_api,
point to `dev/setup-cachyos.sh --official-singbox` instead of debugging the app.
