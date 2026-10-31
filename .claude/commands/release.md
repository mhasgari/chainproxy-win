---
description: Prepare and publish a release (checks, VM tests, artifacts, GitHub release)
---
Version: $ARGUMENTS (bump `__version__` in chain.py; if empty, ask).
1. `make -j1 check`; stop if anything fails.
2. `make -j1 vm-all`; then `make -j1 vm-clean`, `make -j1 vm-installer-full`, `make -j1 vm-clean`
   (also `vm-installer`, `--python full|notk` when the setup/installer changed). Report what passed.
3. `make pdf package installer` (PDF first); copy `dist/chainproxy-X.Y.Z.zip` to `dist/Chain-Proxy-X.Y.Z.zip`.
4. Docs updated for the change (docs/*.md, README, CLAUDE.md, the ADR)? Show me the diff summary.
5. ASK before committing/pushing/tagging/publishing: `git commit`, `git push`, `git tag vX.Y.Z`, then
   `gh release create vX.Y.Z` with ChainProxy-Setup-X.Y.Z.exe, ChainProxy-Setup-Full-X.Y.Z.exe,
   Chain-Proxy-X.Y.Z.zip and docs/Chain-Proxy-Quick-Start-fa.pdf (notes: changes, tested/not tested).
Never include subs.txt. Leave the VM clean (`make vm-clean`) at the end.
