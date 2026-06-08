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

Initialize a project (also installs pi extensions and packages if pi is available):

```bash
agent-memory init-project /path/to/project
```

This will:
1. Create `memory/` and `bin/` in the target project
2. If **pi** is detected: install extensions (`agent-memory.ts`, `delegate.ts`) to `~/.pi/agent/extensions/`
3. If **pi** is detected: install `pi-subagents` and `pi-intercom` via `pi install`
4. If **pi** is not found: skip pi-related steps silently

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

pi 生态有三种 agent 交互机制，加上本项目的跨 session 信箱，共四层：

| | pi-subagents | pi-intercom | Cross-Session (Mailbox) | delegate (RPC) |
|---|---|---|---|---|
| **安装** | `pi install npm:pi-subagents` | `pi install npm:pi-intercom` | 本项目 Extension | 本项目 Extension |
| **工具名** | `subagent` | `intercom` | `session_send` / `session_list` | `delegate` / `delegate_start` |
| **传输** | 子进程 + 事件流 | 本地 IPC Broker | 文件轮询 (`~/.pi/agent/mailbox/`) | RPC stdin/stdout JSONL |
| **拓扑** | Parent → Child（新建子进程） | Peer-to-Peer（已有 session 间） | Peer-to-Peer（已有 session 间） | Parent → Child（新建子进程） |
| **延迟** | 实时流式 | 实时 | ~2s 轮询 | 实时流式 |
| **方向** | 双向（可 intercom 回传） | 双向（send/ask/reply） | 单向通知 | 双向（发任务→拿结果） |
| **生命周期** | 按需创建子进程 | 双方 session 必须已存在 | 双方 session 必须已存在 | 按需创建子进程 |
| **上下文** | 独立上下文 + 自定义 system prompt | 复用已有 session 上下文 | 复用已有 session 上下文 | 全新上下文，无对话历史 |
| **模型** | 可指定（scout=Haiku, worker=Sonnet） | 跟随各 session | 跟随各 session | 可指定 |
| **Agent 定义** | `.md` 文件（scout/planner/reviewer/worker） | — | — | — |
| **工作流** | 单/并行/链式/异步/循环 | — | — | 单次/持久 |
| **子 agent 回调** | ✅ contact_supervisor / intercom bridge | — | ❌ | ❌ |
| **UI** | 内嵌渲染 + 展开视图 | Alt+M / `/intercom` 覆盖层 | — | 进度流式 onUpdate |

### Decision Tree

```
需要和其他 agent 交互？
│
├─ 需要新起一个 agent 干活？
│   ├─ 是 → 需要专业 agent（scout/reviewer/...）？
│   │   ├─ 是 → pi-subagents（预定义 agent + 工作流）
│   │   └─ 否，只需简单派活拿结果 → delegate（轻量 RPC）
│   └─ 否，对方是已存在的 session →
│       ├─ 需要双向对话/拿返回结果？
│       │   ├─ 是 → pi-intercom（send/ask/reply）
│       │   └─ 否，只需单向通知 → session_send（文件信箱）
│
└─ 不需要交互，只需要记住经验？
    └─ memory_add / context_save
```

### Use Cases

**pi-subagents** — 专业 agent + 工作流编排

```bash
pi install npm:pi-subagents
```

- "用 scout 扫一遍代码库，找到所有认证相关代码"
- "并行跑 3 个 reviewer：正确性、测试覆盖、复杂度"
- "scout → planner → worker 链式工作流实现功能"
- "后台跑 worker，完了通知我"
- 子 agent 执行中可通过 `contact_supervisor` 回调父 session 问决策
- 预定义 agent 模板：scout（快速侦察）、planner（规划）、reviewer（审查）、worker（通用实现）、oracle（决策咨询）
- 自定义 agent：`~/.pi/agent/agents/*.md` 或 `.pi/agents/*.md`
- 工作流 prompt：`/implement`、`/scout-and-plan`、`/implement-and-review`

**pi-intercom** — 已有 session 间实时双向通信

```bash
pi install npm:pi-intercom
```

- "让 PRISM 那个 session 帮我查一下它项目里 datacheck 的 checker 列表"
- 两个 session 协作完成一个跨项目任务
- `intercom({ action: "send", to: "session-name", message: "..." })` 发送
- `intercom({ action: "ask", to: "session-name", message: "..." })` 提问并等待回复
- `intercom({ action: "reply", message: "..." })` 回复
- Alt+M 或 `/intercom` 打开 UI 选择目标 session
- 与 pi-subagents 联动：子 agent 可通过 intercom bridge 回调父 session

**session_send（本项目）** — pi-intercom 的轻量 fallback

- 当 pi-intercom 未安装时的降级方案
- 文件信箱，无额外依赖，不依赖 broker 进程
- 单向通知，~2s 延迟
- 支持广播（`to: "*"`），pi-intercom 不支持
- 推荐优先使用 pi-intercom，session_send 仅作兜底

**delegate（本项目）** — 轻量级子 agent 派活

- "帮我分析一下这个文件的架构" → `delegate(task: "分析架构")`
- "用便宜模型跑个搜索" → `delegate(task: "...", model: "deepseek/deepseek-v4-flash")`
- 无需预定义 agent 模板，直接描述任务
- 适合简单的一次性任务，不需要专业 agent 角色

### Recommendation

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| 专业代码审查 | pi-subagents (reviewer) | 预定义审查 prompt，支持并行多维度 |
| 快速代码侦察 | pi-subagents (scout) | Haiku 模型 + 限制工具集，快且省 |
| 复杂多步实现 | pi-subagents (chain) | scout→planner→worker 自动串联 |
| 简单一次性任务 | delegate | 无需定义 agent，直接描述任务 |
| 跨项目实时协作 | pi-intercom | 双向通信，ask/reply 模式 |
| 跨项目通知 | pi-intercom 或 session_send | pi-intercom 优先；session_send 仅作 fallback（无 broker 时） |
| 子 agent 需要回调父 | pi-subagents + pi-intercom | intercom bridge 自动配置 |

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
