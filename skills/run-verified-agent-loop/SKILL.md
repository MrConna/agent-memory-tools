---
name: run-verified-agent-loop
description: Run bounded autonomous iteration for repetitive engineering tasks with objective success criteria. Use for test repair, lint cleanup, dependency upgrades, flaky reproduction, benchmarks, or other tasks with deterministic verification; do not use for subjective architecture or high-risk business decisions.
---

# Run Verified Agent Loop

1. Define one measurable target and a deterministic verifier command before changing files.
2. Set hard caps for attempts, elapsed time, and cost. Stop when any cap is reached.
3. Persist each attempt, result, and failed approach outside chat context.
4. Make the smallest next change informed by the previous verifier output.
5. Accept success only when the verifier exits successfully; an Agent's claim is not proof.
6. Preserve human review for security, payments, architecture, and other high-impact changes.
7. Report accepted changes, total attempts, elapsed cost, and remaining comprehension risk.

Never weaken tests or redefine the target merely to make the loop pass.
