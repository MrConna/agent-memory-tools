---
name: recall-project-memory
description: Retrieve relevant project context before coding, debugging, planning, reviewing, or resuming interrupted work. Use when beginning a non-trivial task or when prior decisions and failed approaches may affect the work.
---

# Recall Project Memory

1. Run `./bin/lifecycle start "<task keywords>" --agent "<host>"`.
2. Apply only memories relevant to the current task; ignore stale or weak matches.
3. Treat source files as authoritative when memory conflicts with current code.
4. Mention which prior decision materially changed the plan, if any.

Do not mutate memory during recall except for reference counters maintained by the CLI.
