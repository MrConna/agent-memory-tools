/**
 * delegate — 多 Agent 协作 Extension
 *
 * 让当前 session 通过 RPC 协议直接控制子 pi 进程。
 *
 * 工具：
 *   delegate        — 一次性派活：spawn → send → wait → return → cleanup
 *   delegate_start  — 启动持久子 agent，返回 ID
 *   delegate_send   — 向子 agent 发送任务（可等待/后台）
 *   delegate_abort  — 中止子 agent
 *   delegate_list   — 列出所有子 agent 状态
 *
 * 原理：
 *   pi --mode rpc 启动子进程，通过 stdin/stdout JSONL 协议通信。
 *   子 agent 拥有完整工具能力（读文件、写代码、跑命令），但有独立的对话上下文。
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn, ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";

// ---------------------------------------------------------------------------
// Sub-agent management
// ---------------------------------------------------------------------------

interface SubAgent {
  id: string;
  process: ChildProcess;
  cwd: string;
  model?: string;
  status: "idle" | "running" | "done" | "error" | "aborted";
  lastResult: string;
  events: EventEmitter; // emits "rpc" for each RPC event
}

const agents = new Map<string, SubAgent>();
let agentCounter = 0;

// ---------------------------------------------------------------------------
// JSONL reader — split on \n only, per RPC spec
// ---------------------------------------------------------------------------

function attachReader(
  stream: NodeJS.ReadableStream,
  onLine: (line: string) => void
) {
  let buffer = "";
  stream.on("data", (chunk: Buffer | string) => {
    buffer += typeof chunk === "string" ? chunk : chunk.toString("utf8");
    while (true) {
      const idx = buffer.indexOf("\n");
      if (idx === -1) break;
      let line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (line) onLine(line);
    }
  });
  stream.on("end", () => {
    if (buffer.length > 0) {
      let line = buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer;
      if (line) onLine(line);
    }
  });
}

// ---------------------------------------------------------------------------
// RPC helpers
// ---------------------------------------------------------------------------

function rpcSend(proc: ChildProcess, cmd: object) {
  if (!proc.stdin?.writable) throw new Error("Sub-agent stdin not writable");
  proc.stdin.write(JSON.stringify(cmd) + "\n");
}

function extractAssistantText(messages: any[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === "assistant") {
      const parts: string[] = [];
      const content = Array.isArray(m.content)
        ? m.content
        : [{ type: "text", text: String(m.content ?? "") }];
      for (const c of content) {
        if (c.type === "text" && c.text) parts.push(c.text);
      }
      if (parts.length > 0) return parts.join("\n");
    }
  }
  return "";
}

// ---------------------------------------------------------------------------
// Sub-agent lifecycle
// ---------------------------------------------------------------------------

function createAgent(
  cwd: string,
  model?: string,
  noSession = true
): SubAgent {
  const id = `agent-${++agentCounter}`;
  const args = ["--mode", "rpc"];
  if (noSession) args.push("--no-session");
  if (model) args.push("--model", model);

  const proc = spawn("pi", args, {
    cwd,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env },
  });

  const agent: SubAgent = {
    id,
    process: proc,
    cwd,
    model,
    status: "idle",
    lastResult: "",
    events: new EventEmitter(),
  };

  // Single reader, re-emit via EventEmitter
  attachReader(proc.stdout!, (line) => {
    try {
      const event = JSON.parse(line);
      agent.events.emit("rpc", event);

      if (event.type === "agent_end") {
        agent.lastResult = extractAssistantText(event.messages || []);
        agent.status = "idle";
      }
      if (event.type === "agent_start") {
        agent.status = "running";
      }
    } catch {
      // ignore non-JSON lines
    }
  });

  proc.on("exit", (code) => {
    if (agent.status !== "aborted") {
      agent.status = code === 0 ? "done" : "error";
    }
    agent.events.emit("exit", code);
  });

  proc.on("error", (err) => {
    agent.status = "error";
    agent.events.emit("error", err);
  });

  agents.set(id, agent);
  return agent;
}

function killAgent(id: string): boolean {
  const agent = agents.get(id);
  if (!agent) return false;
  try {
    agent.process.kill("SIGTERM");
    setTimeout(() => {
      try { agent.process.kill("SIGKILL"); } catch {}
    }, 3000);
  } catch {
    try { agent.process.kill("SIGKILL"); } catch {}
  }
  agent.status = "aborted";
  agents.delete(id);
  return true;
}

// ---------------------------------------------------------------------------
// Wait for agent_end with timeout and optional progress streaming
// ---------------------------------------------------------------------------

function waitForResult(
  agent: SubAgent,
  timeoutMs: number,
  onUpdate?: (text: string) => void,
  signal?: AbortSignal
): Promise<{ text: string; timedOut: boolean; aborted: boolean }> {
  return new Promise((resolve) => {
    let resolved = false;
    let streamingText = "";

    const done = (result: { text: string; timedOut: boolean; aborted: boolean }) => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timer);
      clearInterval(poll);
      agent.events.removeListener("rpc", onEvent);
      resolve(result);
    };

    const timer = setTimeout(() => {
      done({ text: streamingText || agent.lastResult || "（无结果）", timedOut: true, aborted: false });
    }, timeoutMs);

    const onEvent = (event: any) => {
      if (event.type === "agent_end") {
        const text = extractAssistantText(event.messages || []);
        done({ text: text || "（子 agent 无文本输出）", timedOut: false, aborted: false });
      }
      if (event.type === "message_update") {
        const delta = event.assistantMessageEvent;
        if (delta?.type === "text_delta") {
          streamingText += delta.delta;
          onUpdate?.(streamingText);
        }
      }
      if (event.type === "tool_execution_start") {
        const args = JSON.stringify(event.args || {}).slice(0, 80);
        onUpdate?.(`${streamingText}\n🔧 ${event.toolName}(${args})`);
      }
    };

    agent.events.on("rpc", onEvent);

    // Also poll for status changes from the persistent reader
    const poll = setInterval(() => {
      if (agent.status === "idle" && agent.lastResult && !resolved) {
        done({ text: agent.lastResult, timedOut: false, aborted: false });
      }
    }, 2000);

    signal?.addEventListener("abort", () => {
      done({ text: streamingText || "（已中止）", timedOut: false, aborted: true });
    });
  });
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  // Cleanup on shutdown
  pi.on("session_shutdown", async () => {
    for (const id of [...agents.keys()]) {
      killAgent(id);
    }
  });

  // -----------------------------------------------------------------------
  // delegate — One-shot: spawn, send, wait, return, cleanup
  // -----------------------------------------------------------------------

  pi.registerTool({
    name: "delegate",
    label: "Delegate Task",
    description:
      "派一个独立任务给子 agent 执行，等待结果返回。" +
      "子 agent 是独立的 pi 进程，拥有完整工具能力（读文件、写代码、跑命令），但无当前对话上下文。" +
      "任务描述要清晰完整，包含所有必要背景信息。",
    promptSnippet: "Delegate a self-contained task to a sub-agent",
    promptGuidelines: [
      "Use delegate for self-contained tasks that don't require back-and-forth with the user",
      "Provide complete context in the task description — the sub-agent has no knowledge of this conversation",
      "Good for: analyzing a file, running tests, generating boilerplate, researching a topic",
      "Not for: tasks needing user confirmation, multi-step workflows with dependencies",
    ],
    parameters: Type.Object({
      task: Type.String({
        description: "要派给子 agent 执行的任务描述。要清晰完整，包含所有必要上下文，因为子 agent 看不到当前对话",
      }),
      cwd: Type.Optional(
        Type.String({ description: "子 agent 工作目录，默认当前目录" })
      ),
      model: Type.Optional(
        Type.String({ description: "子 agent 使用的模型，如 claude-sonnet-4-20250514" })
      ),
      timeout: Type.Optional(
        Type.Number({ description: "超时秒数，默认 120", minimum: 10, maximum: 600 })
      ),
    }),
    async execute(_toolCallId, params, signal, onUpdate, _ctx) {
      const cwd = params.cwd || process.cwd();
      const timeoutMs = (params.timeout || 120) * 1000;

      onUpdate?.({ content: [{ type: "text", text: `🔄 启动子 agent (cwd: ${cwd})...` }] });

      let agent: SubAgent;
      try {
        agent = createAgent(cwd, params.model, true);
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `❌ 启动失败: ${err.message}` }],
          isError: true,
        };
      }

      // Send the task
      rpcSend(agent.process, { type: "prompt", message: params.task });

      const result = await waitForResult(
        agent,
        timeoutMs,
        (text) => {
          const preview = text.length > 300 ? text.slice(-300) : text;
          onUpdate?.({ content: [{ type: "text", text: `📝 ${preview}` }] });
        },
        signal
      );

      // Cleanup
      agents.delete(agent.id);
      try { agent.process.kill(); } catch {}

      if (result.aborted) {
        return { content: [{ type: "text", text: "🛑 子 agent 已中止" }] };
      }

      const prefix = result.timedOut ? `⏰ 超时（${params.timeout || 120}s），部分结果:\n\n` : "";
      return {
        content: [{ type: "text", text: prefix + result.text }],
        details: { timedOut: result.timedOut },
      };
    },
  });

  // -----------------------------------------------------------------------
  // delegate_start — Start persistent sub-agent
  // -----------------------------------------------------------------------

  pi.registerTool({
    name: "delegate_start",
    label: "Start Sub-Agent",
    description:
      "启动一个持久的子 agent 进程，返回 agent ID。" +
      "后续用 delegate_send 发送任务、delegate_abort 中止。" +
      "适合需要多轮交互的场景。子 agent 保留会话历史，有上下文记忆。",
    parameters: Type.Object({
      cwd: Type.Optional(Type.String({ description: "工作目录" })),
      model: Type.Optional(Type.String({ description: "模型" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const cwd = params.cwd || process.cwd();
      try {
        const agent = createAgent(cwd, params.model, false);
        return {
          content: [
            {
              type: "text",
              text: `✅ 子 agent 已启动\nID: ${agent.id}\nCWD: ${cwd}${params.model ? `\nModel: ${params.model}` : ""}\n\n用 delegate_send 发送任务，delegate_abort 中止，delegate_list 查看状态`,
            },
          ],
          details: { agentId: agent.id, cwd },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `❌ 启动失败: ${err.message}` }],
          isError: true,
        };
      }
    },
  });

  // -----------------------------------------------------------------------
  // delegate_send — Send task to persistent sub-agent
  // -----------------------------------------------------------------------

  pi.registerTool({
    name: "delegate_send",
    label: "Send to Sub-Agent",
    description:
      "向运行中的子 agent 发送任务。wait=true（默认）等待结果返回，wait=false 后台执行后用 delegate_list 查看结果。",
    parameters: Type.Object({
      agent_id: Type.String({ description: "子 agent ID" }),
      task: Type.String({ description: "任务描述" }),
      wait: Type.Optional(
        Type.Boolean({ description: "是否等待结果，默认 true" })
      ),
      timeout: Type.Optional(
        Type.Number({ description: "等待超时秒数，默认 120", minimum: 10, maximum: 600 })
      ),
    }),
    async execute(_toolCallId, params, signal, onUpdate, _ctx) {
      const agent = agents.get(params.agent_id);
      if (!agent) {
        return {
          content: [{ type: "text", text: `❌ 未找到子 agent: ${params.agent_id}\n用 delegate_list 查看可用 agent` }],
        };
      }

      rpcSend(agent.process, { type: "prompt", message: params.task });

      const wait = params.wait !== false;
      if (!wait) {
        return {
          content: [{ type: "text", text: `📤 任务已发送到 ${agent.id}（后台执行）\n用 delegate_list 查看结果` }],
        };
      }

      // Wait for result
      const timeoutMs = (params.timeout || 120) * 1000;
      const result = await waitForResult(
        agent,
        timeoutMs,
        (text) => {
          const preview = text.length > 300 ? text.slice(-300) : text;
          onUpdate?.({ content: [{ type: "text", text: `📝 ${preview}` }] });
        },
        signal
      );

      if (result.aborted) {
        return { content: [{ type: "text", text: "🛑 已中止" }] };
      }

      const prefix = result.timedOut ? `⏰ 超时，部分结果:\n\n` : "";
      return {
        content: [{ type: "text", text: prefix + result.text }],
        details: { timedOut: result.timedOut },
      };
    },
  });

  // -----------------------------------------------------------------------
  // delegate_abort — Abort sub-agent
  // -----------------------------------------------------------------------

  pi.registerTool({
    name: "delegate_abort",
    label: "Abort Sub-Agent",
    description: "中止一个运行中的子 agent 进程。",
    parameters: Type.Object({
      agent_id: Type.String({ description: "子 agent ID" }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const ok = killAgent(params.agent_id);
      return {
        content: [
          {
            type: "text",
            text: ok
              ? `🛑 子 agent ${params.agent_id} 已中止`
              : `❌ 未找到子 agent: ${params.agent_id}`,
          },
        ],
      };
    },
  });

  // -----------------------------------------------------------------------
  // delegate_list — List all sub-agents
  // -----------------------------------------------------------------------

  pi.registerTool({
    name: "delegate_list",
    label: "List Sub-Agents",
    description: "列出所有子 agent 的状态和最近结果摘要。",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, _signal, _onUpdate, _ctx) {
      if (agents.size === 0) {
        return { content: [{ type: "text", text: "无运行中的子 agent" }] };
      }

      const lines: string[] = ["## 子 Agent 列表\n"];
      for (const [id, agent] of agents) {
        const statusEmoji = { idle: "💤", running: "🔄", done: "✅", error: "❌", aborted: "🛑" }[agent.status] || "❓";
        lines.push(`**${id}** ${statusEmoji} ${agent.status} | cwd: \`${agent.cwd}\`${agent.model ? ` | model: ${agent.model}` : ""}`);
        if (agent.lastResult) {
          const preview = agent.lastResult.slice(0, 200).replace(/\n/g, " ");
          lines.push(`  > ${preview}${agent.lastResult.length > 200 ? "..." : ""}`);
        }
        lines.push("");
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  });
}
