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

## When to Use What: Communication & Delegation Guide

Three mechanisms for agent-to-agent interaction, each for different scenarios:

| | Cross-Session (Mailbox) | Sub-Agent (RPC) | Intercom (TBD) |
|---|---|---|---|
| **Extension** | `agent-memory.ts` | `delegate.ts` | — |
| **Tool** | `session_send` / `session_list` | `delegate` / `delegate_start` / `delegate_send` | — |
| **Transport** | File-based mailbox (`~/.pi/agent/mailbox/`) | RPC stdin/stdout JSONL | — |
| **Topology** | Peer-to-peer (existing sessions) | Parent → Child (spawn new process) | Peer-to-peer (real-time) |
| **Latency** | ~2s polling | Real-time (streaming) | Real-time |
| **Direction** | One-way message | Bidirectional (send task → get result) | Bidirectional |
| **Lifecycle** | Sessions must already exist | Sub-agent created on demand | Sessions must already exist |
| **Result** | No return value | Returns result text | Returns result text |
| **Model** | Each session has its own model | Can specify different model per sub-agent | Each session has its own model |
| **Context** | Full session context (AGENTS.md, skills, etc.) | Fresh context, no conversation history | Full session context |

### Decision Tree

```
需要和其他 agent 交互？
│
├─ 对方是已存在的 session？
│   ├─ 是 → 需要拿到返回结果？
│   │   ├─ 否，只需通知/触发 → Cross-Session (session_send)
│   │   └─ 是，需要对方处理并返回 → Intercom (TBD)
│   └─ 否，需要新起一个 agent 干活 → Sub-Agent (delegate)
│
└─ 不需要交互，只需要记住经验？
    └─ memory_add / context_save
```

### Use Cases

**Cross-Session (`session_send`)** — 通知已存在的 session

- "告诉 PRISM 项目那个 session，datacheck 新增了 2 个 checker"
- "广播：飞书文档模板更新了，大家注意"
- "给那个跑测试的 session 发个消息，让它也跑一下新用例"
- 跨项目知识推送
- 团队协作通知

**Sub-Agent (`delegate`)** — 派活给新进程拿结果

- "帮我分析一下这个文件的架构问题" → `delegate(task: "分析架构", cwd: "/path")`
- "用便宜模型跑个搜索" → `delegate(task: "搜索...", model: "deepseek/deepseek-v4-flash")`
- "后台跑测试，完了告诉我" → `delegate_start()` + `delegate_send(wait: false)`
- 并行子任务（多个 delegate 同时跑）
- 用不同模型处理不同子任务
- 长时间运行的后台任务

**Intercom (TBD)** — 已有 session 间的双向协作

- "让那个 session 帮我查一下它项目里的 X，我需要结果"
- 两个 session 协作完成一个跨项目任务
- 需要：请求-响应模式、超时控制、结果回传

### Why Not Just One Mechanism?

| 需求 | Mailbox 不够 | Delegate 不够 | 需要 Intercom |
|------|-------------|--------------|-------------|
| 发消息给已有 session | ✅ 够用 | ❌ 只能创新进程 | — |
| 拿到返回结果 | ❌ 单向 | ✅ 有结果 | ✅ 需要 |
| 复用已有上下文 | ✅ session 已有 | ❌ 全新上下文 | ✅ 需要 |
| 指定模型 | ❌ 跟随 session | ✅ 可指定 | ❌ 跟随 session |
| 实时流式输出 | ❌ 轮询 2s | ✅ RPC 流式 | ✅ 需要 |

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
