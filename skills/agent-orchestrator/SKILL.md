---
name: agent-orchestrator
description: Use when the agent has a task list or multi-step plan. Enforces the principle that the leader agent must not execute tasks itself — it must delegate, monitor, review, and iterate. Triggers on "task list", "plan", "delegate", "orchestrate", "assign", "任务列表", "分工", "派发".
---

# Agent Orchestrator

When there is a task list or multi-step plan, the leader agent acts as **orchestrator**, not executor.

## Core Principle

**Leader does not execute. Leader orchestrates.**

```
任务列表存在？
│
├─ 是 → Leader 进入编排循环：
│   │
│   │   ┌─ 规划 ──► 派发 ──► 监控 ──► Review ──► 整理 ─┐
│   │   │                                                │
│   │   └────────────── 未完成？继续 ─────────────────────┘
│   │
│   └─ 否 → Leader 自己干活（单任务场景）
```

## The Loop

### 1. 规划

- 把目标拆成可独立执行的任务
- 每个任务有明确的输入、输出、验收标准
- 确定依赖关系和执行顺序

### 2. 派发

根据任务性质选择执行方式：

| 任务类型 | 派发方式 | 何时用 |
|---------|---------|--------|
| 代码分析、搜索 | `pi-subagents` (scout) | 快速侦察，用便宜模型 |
| 代码实现 | `pi-subagents` (worker) | 需要完整工具集 |
| 代码审查 | `pi-subagents` (reviewer) | 需要审查视角 |
| 多步实现 | `pi-subagents` (chain) | scout→planner→worker |
| 简单一次性任务 | `delegate` | 无需预定义 agent |
| 需要已有 session 的上下文 | `pi-intercom` | 对方 session 有项目知识 |
| 并行独立任务 | `pi-subagents` (parallel) | 多个任务无依赖 |

**禁止**：Leader 自己写代码、自己跑测试、自己分析文件。Leader 只做拆解和派发。

### 3. 监控

- 用 `subagent({ action: "status" })` 查看子 agent 进度
- 用 `intercom({ action: "pending" })` 查看待处理消息
- 子 agent 遇到阻塞时（`contact_supervisor`），及时回复决策
- 超时未返回的任务，主动检查或 `delegate_abort`

### 4. Review

每个子任务返回后，Leader 必须：

- **验收**：输出是否满足预期？验收标准是否达成？
- **判断**：结果质量如何？需要返工还是接受？
- **返工**：质量不达标时，带上具体反馈重新派发，而不是自己改
- **合并**：多个子任务的结果如何整合？

### 5. 整理

- 更新任务列表状态（待做 → 进行中 → 已完成/已返工）
- 用 `memory_add` 记录重要发现和决策
- 用 `context_save` 保存当前进度
- 汇报整体进度给用户

## Anti-Patterns

| 反模式 | 正确做法 |
|--------|---------|
| Leader 自己写代码 | 派给 worker subagent |
| Leader 自己读文件分析 | 派给 scout subagent |
| 所有任务串行一个个做 | 并行派发无依赖的任务 |
| 子任务失败后 Leader 接手 | 带反馈重新派发 |
| 等所有任务完成才汇报 | 每个任务完成后汇报增量进展 |
| 任务描述模糊 | 明确输入/输出/验收标准 |

## Example

用户说："帮我重构 PRISM 项目的 knowledge 模块，太大了需要拆分"

**错误做法**：Leader 自己 `read` 文件 → 自己分析 → 自己 `edit` 改代码

**正确做法**：

```
Leader 规划：
  Task 1: scout 分析 knowledge 模块结构，列出所有类和依赖
  Task 2: planner 基于 Task 1 结果制定拆分方案
  Task 3: worker 按 Task 2 方案执行拆分
  Task 4: reviewer 审查 Task 3 的改动

Leader 派发 Task 1 → scout 返回分析结果
Leader Review Task 1 → 验收通过

Leader 派发 Task 2（附带 Task 1 结果）→ planner 返回方案
Leader Review Task 2 → 方案合理，继续

Leader 派发 Task 3（附带 Task 2 方案）→ worker 返回改动
Leader Review Task 3 → 发现遗漏，带反馈重新派发

Leader 派发 Task 3（retry）→ worker 返回改动
Leader Review Task 3 → 验收通过

Leader 派发 Task 4 → reviewer 返回审查意见
Leader Review Task 4 → 两个小问题，派 worker 修

Leader 整理：memory_add + context_save + 汇报用户
```

## When Leader Can Execute

Leader 只在以下情况自己动手：

- **单任务场景**：没有任务列表，只有一个简单问题
- **轻量操作**：memory_add、context_save、session_send 等元操作
- **紧急决策**：子 agent 阻塞等回复时，Leader 必须立刻回应
- **最终汇报**：整合结果、总结进度
