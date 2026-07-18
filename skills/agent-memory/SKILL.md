---
name: agent-memory
description: Use when working in a repository with Agent Memory Tools, including retrieving durable project learnings, adding high-confidence memory, saving or restoring context checkpoints, initializing project memory, or syncing cross-project brain memory.
---

# Agent Memory

Use this skill for project-local memory discipline.

## Required Workflow

Before non-trivial work:

```bash
bin/memory apply --query "<task keywords>"
```

When resuming after interruption:

```bash
bin/context restore
```

After durable discoveries:

```bash
bin/memory add "<reusable lesson>" \
  --confidence 8 \
  --source implementation \
  --tags workflow,agents \
  --context "<why future agents need this>"
```

After meaningful milestones or before handoff:

```bash
bin/context save \
  --description "<checkpoint>" \
  --decisions "<d1>|<d2>" \
  --remaining "<r1>|<r2>" \
  --failed "<failed approach>"
```

## What Belongs In Memory

Add high-confidence memory for:

- project rules future agents must follow
- architecture decisions
- recurring bug patterns
- validated command shapes
- failed approaches to avoid
- model-routing or delegation lessons

Do not store:

- secrets
- raw logs
- ordinary progress updates
- guesses as high-confidence rules
- large pasted artifacts

## Tooling

If wrappers are missing, initialize the repository:

```bash
agent-memory init-project .
```

Unified CLI:

```bash
agent-memory memory list
agent-memory context list
agent-memory brain status
```

Optional cross-project sync:

```bash
bin/brain register "$(pwd)"
bin/brain sync
```

## Handoff

For a long or cross-day task, keep task state separate from durable experience:

1. Write `HANDOFF.md` for a completely fresh session: task, completed work, current
   blocker, next steps, and failed approaches that must not be repeated.
2. Use `context save` when a structured, searchable checkpoint is also useful.
3. Reflect on user corrections and classify each as missing input or faulty reasoning.
4. Search existing memory before adding only the reusable corrections and effective
   methods; do not duplicate rules already present in instructions or templates.
5. Promote a lesson to cross-project Brain only after repeated evidence shows it is
   general rather than project-specific.

Do not turn `HANDOFF.md` into a memory dump: it records resumable task state, while
`memory` records durable lessons.

At handoff, explicitly state:

- which memory entries influenced the plan, or that none matched
- whether durable memory was added
- whether a context checkpoint was saved
- whether cross-project `bin/brain sync` would be useful
