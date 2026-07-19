---
name: verify-before-completion
description: Require fresh objective evidence before claiming work is complete, fixed, passing, or ready to ship. Use before final responses, commits, pushes, merge requests, releases, or handoffs.
---

# Verify Before Completion

1. Translate every completion claim into a command, inspection, or observable acceptance check.
2. Run the checks after the final change, not from memory or an earlier run.
3. Read exit status and relevant output; distinguish skipped, partial, flaky, and fully passing checks.
4. Check the diff and repository status for accidental or missing changes.
5. Report exactly what was verified and disclose anything not run or still uncertain.
6. Never treat an agent's confidence, a code review glance, or absence of errors as proof.
