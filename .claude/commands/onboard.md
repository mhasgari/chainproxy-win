---
description: Load the project context in a new conversation (ADR, architecture, state), then wait for the task
---
Get fully oriented before I describe the work. Do not change anything.
1. `index_status` for project `home-hadi-projects-chainproxy-win`; if it is missing or stale, run
   `index_repository(repo_path="/home/hadi/projects/chainproxy-win", mode="full")`.
2. `manage_adr(project, mode="get")` and read it: architecture, decisions, workflows, release recipe.
3. `get_architecture(project, aspects=["overview","entry_points","hotspots"])`.
4. Read `CLAUDE.md` rules/gotchas (already in context) and skim `docs/DEVELOPER.md` headings only.
5. `git status --short`, `git log --oneline -5`, `gh release list --limit 3`, and
   `python3 dev/vm/vmtest.py doctor` to see whether the Windows VM is reachable and what state it is in.
6. Reply in Persian with: what the project is (3 lines), the current version/branch/dirty files, VM state,
   and the commands you will use (make test/check, vm-*). Then ask what we are changing.
