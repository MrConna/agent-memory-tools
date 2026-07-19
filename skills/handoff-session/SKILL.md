---
name: handoff-session
description: Preserve resumable task state before ending, pausing, compressing, or transferring a long-running session. Use for cross-day work, context limits, agent changes, or unresolved blockers.
---

# Handoff Session

Run `./bin/lifecycle end` with:

- `--summary`: completed work and current state.
- `--decisions`: decisions that constrain the next session.
- `--remaining`: concrete next actions.
- `--failed`: attempts and pitfalls that must not be repeated.
- `--learning`: only a separate reusable lesson, otherwise leave empty.

Verify that `HANDOFF.md` is understandable without chat history. Keep task state out of durable learning records.
