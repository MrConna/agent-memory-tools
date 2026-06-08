# Agent Memory Tools

Standalone tooling for agent project memory.

It provides:

- project-local durable learnings in `memory/learnings.jsonl`
- resumable checkpoints in `memory/contexts.jsonl`
- optional cross-project semantic search in `~/.brain`
- a unified CLI: `agent-memory`
- project wrappers: `bin/memory`, `bin/context`, `bin/brain`
- a Codex skill and plugin manifest for agent workflows
- **pi Extensions**: auto memory management, cross-session messaging, multi-agent delegation

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

## pi Extensions

Two pi extensions are bundled in `extensions/`. Copy them to `~/.pi/agent/extensions/` to use.

### agent-memory.ts — Memory + Cross-Session Messaging

**Automatic (lifecycle hooks, no agent action needed):**

| Hook | When | What |
|------|------|------|
| `session_start` | Session begins | `context restore` + start mailbox listener |
| `before_agent_start` | First turn | Inject restored context + relevant learnings into system prompt |
| `agent_end` | Session ends | Auto `context save` |

**Agent tools (LLM calls on demand):**

| Tool | Purpose |
|------|---------|
| `memory_add` | Record a learning |
| `memory_search` | Search learnings |
| `memory_list` | List learnings |
| `context_save` | Save session context |
| `session_send` | Send message to another session (cross-project) |
| `session_list` | List all sessions across projects |

**Cross-session messaging** works via a global mailbox at `~/.pi/agent/mailbox/`. Any session can send a message to any other session by session ID. The receiving session's extension polls the mailbox every 2 seconds and injects matching messages via `pi.sendUserMessage()`.

```typescript
// Send from any session
session_send(to: "019e8b7c", message: "hi")

// Broadcast to all sessions
session_send(to: "*", message: " heads up")
```

### delegate.ts — Multi-Agent Delegation

Spawn sub-agents via pi's RPC protocol and control them directly.

**Tools:**

| Tool | Purpose |
|------|---------|
| `delegate` | One-shot: spawn, send task, wait for result, cleanup |
| `delegate_start` | Start persistent sub-agent, returns ID |
| `delegate_send` | Send task to persistent sub-agent |
| `delegate_abort` | Abort a sub-agent |
| `delegate_list` | List all sub-agents |

```typescript
// One-shot delegation
delegate(task: "Analyze the architecture of src/api.ts", cwd: "/path/to/project")

// Persistent sub-agent for multi-step work
delegate_start(cwd: "/path/to/project", model: "deepseek/deepseek-v4-flash")
delegate_send(agent_id: "agent-1", task: "First do X")
delegate_send(agent_id: "agent-1", task: "Now do Y")
delegate_abort(agent_id: "agent-1")
```

### Install Extensions

```bash
cp extensions/agent-memory.ts ~/.pi/agent/extensions/
cp extensions/delegate.ts ~/.pi/agent/extensions/
```

Then `/reload` in any running pi session.

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

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Brain（跨项目语义检索）                              │
│  ~/.brain/  向量索引 + 多项目 learnings               │
│  命令: brain init / search / sync / register         │
├─────────────────────────────────────────────────────┤
│  Memory（项目内结构化记忆）                            │
│  memory/learnings.jsonl  模式/决策/经验               │
│  命令: memory add / search / list / apply / prune     │
├─────────────────────────────────────────────────────┤
│  Context（会话级状态）                                │
│  memory/contexts.jsonl   决策/待办/失败方案            │
│  命令: context save / restore / list / show           │
└─────────────────────────────────────────────────────┘

         ┌──────────────────────────────────┐
         │  pi Extensions（自动化 + 通信）    │
         │  ~/.pi/agent/extensions/          │
         │  agent-memory.ts — 钩子 + 信箱     │
         │  delegate.ts — 多 agent 协作       │
         └──────────────────────────────────┘
```

## License

MIT
