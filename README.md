# Agent Memory Tools

Standalone tooling for agent project memory.

It provides:

- project-local durable learnings in `memory/learnings.jsonl`
- resumable checkpoints in `memory/contexts.jsonl`
- optional cross-project semantic search in `~/.brain`
- a unified CLI: `agent-memory`
- project wrappers: `bin/memory`, `bin/context`, `bin/brain`
- a Codex skill and plugin manifest for agent workflows

## Install

From this checkout:

```bash
python3 -m pip install -e .
```

Initialize a project:

```bash
agent-memory init-project /path/to/project
```

Then inside that project:

```bash
bin/memory apply --query "task keywords"
bin/memory add "Durable lesson" --confidence 8 --source implementation --tags workflow
bin/context save --description "Implemented feature" --decisions "d1|d2" --remaining "r1|r2"
bin/context restore
```

## CLI

```bash
agent-memory memory list
agent-memory context list
agent-memory brain status
```

Short alias:

```bash
amt memory search "routing"
```

Direct entry points are also installed:

```bash
agent-memory-memory list
agent-memory-context restore
agent-memory-brain status
```

## Optional Brain

Semantic cross-project search requires the optional dependencies:

```bash
python3 -m pip install -e ".[brain]"
agent-memory brain init
agent-memory brain register /path/to/project
agent-memory brain sync
agent-memory brain search "agent routing rules"
```

## Codex Skill

The bundled skill lives at:

```text
skills/agent-memory/SKILL.md
```

Use it when an agent needs to retrieve project learnings, save context, add durable memories, or sync cross-project memory.

## Plugin

This repository is also a Codex plugin root through:

```text
.codex-plugin/plugin.json
```

Install it as a local plugin from this repository when you want the skill to be discoverable in Codex.

## Validation

```bash
python3 tests/run.py
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/agent-memory --help
```
