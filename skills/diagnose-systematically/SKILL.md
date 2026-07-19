---
name: diagnose-systematically
description: Diagnose bugs, regressions, failures, and unexpected behavior with reproducible evidence and falsifiable hypotheses. Use before proposing or implementing a non-obvious fix.
---

# Diagnose Systematically

1. State expected versus actual behavior and reproduce the smallest failing case.
2. Gather direct evidence from code, logs, tests, configuration, and recent changes.
3. Rank three to five falsifiable hypotheses. For each, name the observation that would confirm or reject it.
4. Run the cheapest discriminating check first and update the ranking from evidence.
5. Identify the root cause before changing behavior. If reproduction is impossible, say what remains uncertain.
6. Add a regression test, make the smallest causal fix, rerun relevant verification, and remove temporary instrumentation.
7. Save a reusable bug pattern only after verification.
