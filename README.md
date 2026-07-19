# Agent Memory Tools

Standalone tooling for agent project memory and session management.

It provides:

- project-local durable learnings in `memory/learnings.jsonl`
- resumable checkpoints in `memory/contexts.jsonl`
- project-local wiki memory in `memory/wiki/`
- optional cross-project semantic search in `~/.brain`
- **session binding**: stable CLI commands to resume Codex / pi / Claude sessions
- a unified CLI: `agent-memory`
- project wrappers: `bin/memory`, `bin/context`, `bin/brain`, `bin/session`, `bin/wiki`
- a Codex skill and plugin manifest for agent workflows
- **pi Extensions**: auto memory management, cross-session messaging, multi-agent delegation
- a shared lifecycle for Codex, Claude Code, agy, and pi

## One-command automation

```bash
python3 -m pip install -e .
agent-memory install /path/to/project
```

The installer creates native Claude hooks, Codex/Claude lifecycle skills, Antigravity
CLI (`agy`) hooks when detected,
and pi extensions when pi is installed. All adapters use the same commands:

```bash
bin/lifecycle start "task keywords" --agent codex
bin/lifecycle end --agent codex --summary "what changed" \
  --learning "verified reusable lesson" --confidence 8 --tags workflow \
  --decisions "key decisions" --remaining "next steps"
```

Task end saves Context and `HANDOFF.md`, adds an optional verified learning, attempts a
Brain sync, and promotes confidence-7+ learnings to rules/knowledge. A skill is generated
only for confidence-9+ learnings explicitly tagged `skill`.

Low-risk compression and session summaries use the `local-gemma` provider from
`~/.pi/agent/models.json` (for example `gemma-4-12b`). High-impact decisions and durable
Memory/Knowledge/Skill promotion remain the host agent's responsibility. Set
`AGENT_MEMORY_LOCAL_MODEL=off` to disable local inference; failures always degrade to
rule-based storage without blocking the host.

Project policy is stored in `memory/config.json` and can be changed without editing code:

```bash
agent-memory config show
agent-memory config set local_model.timeout_seconds 20
agent-memory config set local_model.observation_compression false
agent-memory config set automation.skill_promotion_min_confidence 10
agent-memory config set automation.brain_sync_on_end false
```

Codex has no required native lifecycle hook: one-command install starts a project-scoped
incremental transcript watcher instead. It tails only Codex sessions whose `session_meta.cwd`
matches the project, persists byte offsets, pairs function calls with outputs, and feeds the
same observation/end lifecycle used by Claude, agy, and pi.

```bash
agent-memory codex-watcher status
agent-memory codex-watcher stop
agent-memory codex-watcher start
```

Every initialized project also receives four conservative common skills—memory recall,
learning capture, session handoff, and knowledge maintenance—and four Wiki seed pages for
memory taxonomy, promotion policy, privacy, and the cross-agent lifecycle. Existing files are
preserved unless `--force` is explicitly supplied.

A fifth `run-verified-agent-loop` skill and Loop Engineering Wiki page define safe autonomous
iteration: deterministic verification, external state, hard attempt/time/cost caps, and human
review for high-impact changes.

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
2. Create **LLM Wiki scaffolding**: `knowledge/`, `raw/`, `docs/`, and `AGENTS.md`, following the [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern
3. Create **cross-agent support files** so the same memory workflow works across Claude Code, Codex, and pi (see below)
4. If **pi** is detected: install extensions (`agent-memory.ts`, `delegate.ts`) to `~/.pi/agent/extensions/`
5. If **pi** is detected: install `pi-subagents` and `pi-intercom` via `pi install`
6. If **pi** is not found: skip pi-related steps silently

Then inside that project:

```bash
bin/memory apply --query "task keywords"
bin/memory add "Durable lesson" --confidence 8 --source implementation --tags workflow
bin/context save --description "Implemented feature" --decisions "d1|d2" --remaining "r1|r2"
bin/context restore
bin/session bind my-task --runtime pi --session-id <id> --cwd .
bin/wiki add-source README.md AGENTS.md
bin/wiki add-page project-overview --summary "Durable project knowledge for agents." --source README.md
```

The generated `AGENTS.md` and `docs/knowledge-management.md` describe how to maintain the wiki: ingest sources into `raw/` and `knowledge/`, query against the wiki, and file answers back into it.

## Cross-Agent Support

`init-project` writes one memory workflow that three coding agents can all follow, so learnings and context carry over regardless of which agent is driving:

| Agent | Entry point | Purpose |
|-------|-------------|---------|
| **Claude Code** | `CLAUDE.md` | Pre/post-task hook instructions (`memory apply` → work → `memory add` / `context save`) |
| **Codex** | `.codex/CLAUDE.md` + `.codex-plugin/plugin.json` | Same workflow framed for Codex; the plugin's `skills` path resolves to `.codex/` |
| **pi** | `~/.pi/agent/extensions/*.ts` | Lifecycle hooks auto-restore context and inject learnings (installed only if pi is present) |

All three call the same `bin/memory`, `bin/context`, and `memory/hooks/*.sh` wrappers, so there is a single source of truth. A cross-agent knowledge base is scaffolded under `wiki/` (`index.md` + `entities/`, `concepts/`, `sources/`) for durable, hand-authored pages that complement the append-only `memory/` store.

## CLI

```bash
agent-memory memory list
agent-memory context list
agent-memory wiki search "routing"
agent-memory brain status
agent-memory session list
```

Short alias:

```bash
amt memory search "routing"
amt session scan --runtime pi --cwd . --limit 5
```

Direct entry points are also installed:

```bash
agent-memory-memory list
agent-memory-context restore
agent-memory-brain status
agent-memory-session bind talkwithai-main --runtime pi --session-id <id> --cwd .
agent-memory-wiki search "routing"
agent-memory-health check --session-id <id>
```

## Wiki Memory

Wiki memory is a small Markdown working-knowledge layer for agents. It does not replace
`learnings.jsonl`, `contexts.jsonl`, or your source documents:

- source documents remain the source of truth
- `learnings.jsonl` stores durable rules and bug patterns
- `contexts.jsonl` stores resumable session checkpoints
- `memory/wiki/` stores human-readable summaries that agents can reuse across sessions

```bash
agent-memory wiki init
agent-memory wiki add-source README.md AGENTS.md
agent-memory wiki add-page project-overview \
  --summary "This project provides CLI tools for agent memory." \
  --source README.md
agent-memory wiki search "agent memory"
agent-memory wiki sync
```

Tracked sources are recorded in `memory/wiki/sources.jsonl` with content hashes. When a
source changes, `wiki sync` marks dependent pages stale so an agent can rebuild only the
affected knowledge instead of rereading the whole project.

## Long-Session Closeout: Handoff, Reflection, Memory

长任务、跨天协作或复杂 Agent 工作流结束前，用三层信息解决新会话“失忆”：

| Layer | Stores | Does not store |
|------|--------|----------------|
| `HANDOFF.md` | 当前任务、进度、阻塞、下一步、已验证的坑 | 可复用经验的长期堆积 |
| Reflection | 本轮被纠正的内容、归因、下次如何改进输入 | 普通进度流水账 |
| `memory` | 经验证、以后仍有用的纠错与方法 | 已有规则、重复条目、低置信猜测 |

### 1. `HANDOFF.md`: hand work to a fresh session

Use this before ending a long session or pausing a complex task overnight:

```text
这个会话要结束了。请写一份交接文档存到 `HANDOFF.md`：我们在做什么任务、已经完成了什么、当前卡在哪、下一步计划是什么、有哪些踩过的坑绝对不要再踩。写给一个完全没有上下文的新会话看。
```

Start the next session with:

```text
请先读取 `HANDOFF.md`，了解项目上下文，再继续推进。
```

`HANDOFF.md` is the human-readable handoff. `context save` is its structured,
searchable counterpart; projects may use either or both, but task progress should not
be mixed into durable learnings.

### 2. Reflection: turn corrections into better next-session input

Run this after the user has corrected important output:

```text
回顾我们这次协作，你的输出里，哪些内容是我给你纠正的，逐条列出，判断是我给的信息不够导致你判断缺失，还是信息够了但你的判断逻辑有问题，思考如果下次做同样的任务，我在开头多说哪几句话，你就能避开这些问题？复盘结果用表格输出三列，包括我修改的内容，归因，下次的开头指令建议。
```

The reflection separates missing context from faulty reasoning, producing concrete
opening instructions instead of a vague retrospective.

### 3. Memory: turn reusable corrections into durable assets

Use this whenever a correction, review order, or questioning technique is likely to
help again:

```text
把我们刚才的经验录入错题本/系统记忆，只记纠错与有效方法，错题本里已有类似记录的，更新旧条目，不新建，审查规则或提示词模板里已经明确写了的内容，不重复记录。
```

With Agent Memory Tools, search before adding so similar entries can be updated or
left alone instead of duplicated:

```bash
bin/memory search "<correction or method keywords>"
bin/memory add "<reusable lesson>" --confidence 8 --source reflection --tags workflow
```

Recommended order:

1. At long-session closeout, write `HANDOFF.md` with task state only.
2. When a meaningful deviation is found, run the reflection and review its table.
3. Record only reusable corrections and effective methods in project memory.
4. When repeated entries reveal a general rule, promote the smallest stable version
   to always-on instructions or sync it to the cross-project Brain.

## Optional Brain

Semantic cross-project search requires the optional dependencies:

```bash
python3 -m pip install -e ".[brain]"
agent-memory brain init
agent-memory brain register /path/to/project
agent-memory brain sync
agent-memory brain search "agent routing rules"
```

## Session Commands

Bind agent sessions to stable commands so you can resume after an accidental close.

In **tmux** environments, session management prefers tmux: the bound command
attaches to an existing tmux session or creates a new detached tmux session
running the agent resume command. Outside tmux, it falls back to the native
agent CLI resume command.

```bash
# Scan recent sessions
agent-memory session scan --runtime pi --cwd . --limit 5
agent-memory session scan --runtime codex --limit 5

# Bind a command (auto-detects tmux if $TMUX is set)
agent-memory session bind talkwithai-main \
  --runtime pi \
  --session-id 019ec97f-f34d-770d-9187-e88abc54c9b8 \
  --cwd /path/to/project

# Force native backend
agent-memory session bind talkwithai-main \
  --runtime pi \
  --session-id <id> \
  --cwd /path/to/project \
  --backend native

# Resume via the generated command
talkwithai-main

# Preview what it will run
agent-memory session run talkwithai-main --dry-run

# Manage bindings
agent-memory session list
agent-memory session show talkwithai-main
agent-memory session unbind talkwithai-main
```

Supported runtimes:

| Runtime | Resume command |
|---------|---------------|
| Codex | `codex resume -C <cwd> [--profile <p>] <thread-id>` |
| pi | `pi --session-id <session-id>` |
| Claude | `claude --continue --cwd <cwd> [--name <name>]` |

Backends:

| Backend | Behavior |
|---------|----------|
| `native` | Run the agent's own resume command directly |
| `tmux` | Attach to existing tmux session, or create a new detached tmux session running the resume command |

The default backend is `tmux` when `$TMUX` is present, otherwise `native`.

## Health Checks

Detect loop patterns in agent sessions so interrupted work can be diagnosed on resume:

```bash
agent-memory health check --session-id <pi-session-id>
agent-memory health check --recent-turns 10 --loop-threshold 3
```

Detected patterns include:
- Repeated identical tool calls
- Consecutive tool errors
- Assistant turns with no text response (only tool calls)

When used inside the pi extension, the `before_agent_start` hook can run this check automatically and inject a recovery hint if a loop is detected.

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

## Orchestration Principle

When there is a task list or multi-step plan, the **leader agent does not execute** — it orchestrates.

```
规划 → 派发 → 监控 → Review → 整理 → 未完成？继续
```

| Role | Does | Does Not |
|------|-------|----------|
| Leader | Plan, delegate, monitor, review, summarize | Write code, analyze files, run tests |
| Sub-agent | Execute tasks, return results | Make architectural decisions |

See `skills/agent-orchestrator/SKILL.md` for the full guide.

## License

MIT
