---
description: Prepare a release zip after all checks pass
---
1. Run `make check`. Stop if anything fails.
2. Run `python3 dev/vm/vmtest.py all` (ask me first if the VM is not reachable).
3. Bump `__version__` in chain.py if I gave a version: $ARGUMENTS
4. Run `make package` and report the zip path, its size and the file list.
Do not commit or push.
