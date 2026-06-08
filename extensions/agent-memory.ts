/**
 * agent-memory — 自动记忆管理 + 跨 session 通信 Extension (pi)
 *
 * 钩子：
 *   session_start       → 恢复上下文 + 启动全局信箱监听
 *   before_agent_start  → 注入恢复的上下文 + 相关 learnings
 *   agent_end           → 自动保存 context
 *
 * 注册工具：
 *   memory_add / memory_search / memory_list / context_save
 *   session_send  → 跨 session 发消息（全局信箱）
 *   session_list  → 列出所有项目下的 pi session
 *
 * 依赖：
 *   pip install agent-memory-tools  （提供 agent-memory / memory / context / brain CLI）
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execSync } from "node:child_process";
import * as path from "node:path";
import * as fs from "node:fs";
import * as os from "node:os";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PI_HOME = path.join(os.homedir(), ".pi", "agent");
const GLOBAL_MAILBOX = path.join(PI_HOME, "mailbox");
const SESSIONS_ROOT = path.join(PI_HOME, "sessions");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function run(command: string, cwd?: string): string {
  try {
    return execSync(command, {
      cwd: cwd || process.cwd(),
      encoding: "utf-8",
      timeout: 15_000,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch (e: any) {
    return `[error] ${e.message?.split("\n")?.[0] ?? e}`;
  }
}

function extractSessionId(sessionFile?: string): string {
  if (!sessionFile) return "unknown";
  const m = sessionFile.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/);
  return m?.[0] ?? "unknown";
}

function dirToProjectPath(dirName: string): string {
  return dirName.replace(/^--/, "/").replace(/--$/, "").replace(/-/g, "/");
}

function scanAllSessions(currentSessionId: string) {
  const results: Array<{
    id: string; shortId: string; project: string;
    model: string; firstMsg: string; mtime: string; isCurrent: boolean;
  }> = [];
  if (!fs.existsSync(SESSIONS_ROOT)) return results;

  for (const pDir of fs.readdirSync(SESSIONS_ROOT)) {
    const projectName = dirToProjectPath(pDir).split("/").filter(Boolean).pop() ?? pDir;
    const fullDir = path.join(SESSIONS_ROOT, pDir);
    let files: string[];
    try { files = fs.readdirSync(fullDir).filter(f => f.endsWith(".jsonl")); } catch { continue; }

    for (const file of files) {
      const sessionId = extractSessionId(file);
      const isCurrent = sessionId === currentSessionId;
      const shortId = sessionId.slice(0, 8);
      let model = "?", firstMsg = "(空)", mtime = "?";
      try {
        const stat = fs.statSync(path.join(fullDir, file));
        const d = new Date(stat.mtimeMs);
        mtime = `${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
      } catch {}
      try {
        const content = fs.readFileSync(path.join(fullDir, file), "utf8");
        for (const line of content.split("\n")) {
          if (!line.trim()) continue;
          try {
            const d = JSON.parse(line);
            if (d.type === "model_change") model = `${d.provider}/${d.modelId}`;
            if (d.type === "message" && d.message?.role === "user") {
              const c = d.message.content;
              if (Array.isArray(c)) { for (const x of c) { if (x.type === "text") { firstMsg = x.text.slice(0, 50); break; } } }
              else if (typeof c === "string") { firstMsg = c.slice(0, 50); }
              break;
            }
          } catch {}
        }
      } catch {}
      results.push({ id: sessionId, shortId, project: projectName, model, firstMsg, mtime, isCurrent });
    }
  }
  results.sort((a, b) => b.mtime.localeCompare(a.mtime));
  return results;
}

function resolveSessionId(shortId: string): string | null {
  if (shortId.length >= 32) return shortId;
  if (!fs.existsSync(SESSIONS_ROOT)) return null;
  for (const pDir of fs.readdirSync(SESSIONS_ROOT)) {
    try {
      for (const file of fs.readdirSync(path.join(SESSIONS_ROOT, pDir))) {
        if (file.includes(shortId)) { const full = extractSessionId(file); if (full !== "unknown") return full; }
      }
    } catch {}
  }
  return null;
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  const cwd = process.cwd();
  let restoredContext: string | null = null;
  let contextInjected = false;

  // -----------------------------------------------------------------------
  // Session start: 恢复上下文 + 启动全局信箱监听
  // -----------------------------------------------------------------------
  pi.on("session_start", async (_event, ctx) => {
    const currentSessionId = extractSessionId(ctx.sessionManager.getSessionFile());

    const restored = run("context restore --latest", cwd);
    if (!restored.startsWith("[error]") && !restored.includes("No saved contexts")) {
      restoredContext = restored;
    }

    // 全局信箱监听
    fs.mkdirSync(GLOBAL_MAILBOX, { recursive: true });
    const deliveredIds = new Set<string>();
    const mailboxTimer = setInterval(() => {
      try {
        for (const file of fs.readdirSync(GLOBAL_MAILBOX).filter(f => f.endsWith(".json")).sort()) {
          if (deliveredIds.has(file)) continue;
          try {
            const msg = JSON.parse(fs.readFileSync(path.join(GLOBAL_MAILBOX, file), "utf8"));
            deliveredIds.add(file);
            if (msg.to === currentSessionId || msg.to === "*") {
              const prefix = msg.from ? `[来自 session ${msg.from.slice(0, 8)}] ` : "";
              pi.sendUserMessage(`${prefix}${msg.message}`, { deliverAs: "followUp" });
              const deliveredDir = path.join(GLOBAL_MAILBOX, "delivered");
              fs.mkdirSync(deliveredDir, { recursive: true });
              try { fs.renameSync(path.join(GLOBAL_MAILBOX, file), path.join(deliveredDir, file)); } catch {}
            }
          } catch {}
        }
      } catch {}
    }, 2000);

    pi.on("session_shutdown", async () => { clearInterval(mailboxTimer); });
  });

  // -----------------------------------------------------------------------
  // Before agent start: 注入恢复的上下文 + 相关 learnings
  // -----------------------------------------------------------------------
  pi.on("before_agent_start", async (event, _ctx) => {
    if (contextInjected) return;
    contextInjected = true;
    const blocks: string[] = [];
    if (restoredContext) blocks.push("## 上次会话恢复\n" + restoredContext);
    const query = event.prompt?.slice(0, 200) ?? "";
    if (query) {
      const learnings = run(`memory apply --query "${query.replace(/"/g, '\\"')}"`, cwd);
      if (learnings && !learnings.startsWith("[error]") && learnings.trim()) {
        blocks.push("## 相关项目记忆\n" + learnings);
      }
    }
    if (blocks.length > 0) return { systemPrompt: event.systemPrompt + "\n\n" + blocks.join("\n\n") };
  });

  // -----------------------------------------------------------------------
  // Agent end: 自动保存 context
  // -----------------------------------------------------------------------
  pi.on("agent_end", async (event, _ctx) => {
    const messages = event.messages;
    if (!messages || messages.length === 0) return;
    const userTexts = messages
      .filter((m: any) => m.role === "user")
      .map((m: any) => {
        if (Array.isArray(m.content)) return m.content.filter((c: any) => c.type === "text").map((c: any) => c.text).join(" ");
        return typeof m.content === "string" ? m.content : "";
      }).filter(Boolean);
    const description = userTexts.join("; ").slice(0, 200) || "agent session";
    run(`context save --description "${description.replace(/"/g, '\\"')}" --decisions "" --remaining ""`, cwd);
  });

  // =====================================================================
  // Tools
  // =====================================================================

  pi.registerTool({
    name: "memory_add",
    label: "Add Memory",
    description:
      "添加一条结构化项目记忆(learning)。用于记录确认过的模式、决策、经验教训。" +
      "置信度7-10为高置信度(自动推荐)，4-6为中等，0-3为待验证。",
    promptSnippet: "Add structured project memory",
    promptGuidelines: [
      "Use memory_add when you discover an important pattern, make a key decision, or learn something worth remembering",
      "Use memory_search when starting work on a topic to recall relevant past learnings",
      "Use context_save when ending a significant work session to preserve state",
    ],
    parameters: Type.Object({
      pattern: Type.String({ description: "要记录的模式/决策/经验" }),
      confidence: Type.Number({ description: "置信度 0-10", minimum: 0, maximum: 10 }),
      source: Type.Optional(Type.String({ description: "来源：review/discussion/meeting/practice/correction/manual" })),
      tags: Type.Optional(Type.String({ description: "逗号分隔的标签" })),
      context: Type.Optional(Type.String({ description: "补充说明" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const args = ["add", `"${params.pattern.replace(/"/g, '\\"')}"`, "--confidence", String(params.confidence)];
      if (params.source) args.push("--source", params.source);
      if (params.tags) args.push("--tags", params.tags);
      if (params.context) args.push("--context", `"${params.context.replace(/"/g, '\\"')}"`);
      return { content: [{ type: "text", text: run(`memory ${args.join(" ")}`, cwd) || "Learning added." }] };
    },
  });

  pi.registerTool({
    name: "memory_search",
    label: "Search Memory",
    description: "搜索项目记忆(learnings)。按关键词搜索，返回匹配的结构化记忆。",
    parameters: Type.Object({ query: Type.String({ description: "搜索关键词" }) }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      return { content: [{ type: "text", text: run(`memory search "${params.query.replace(/"/g, '\\"')}"`, cwd) || "No results found." }] };
    },
  });

  pi.registerTool({
    name: "context_save",
    label: "Save Context",
    description: "保存当前会话上下文。记录关键决策、未完成工作和失败方案。",
    parameters: Type.Object({
      description: Type.String({ description: "本次会话做了什么" }),
      decisions: Type.Optional(Type.String({ description: "关键决策，|分隔" })),
      remaining: Type.Optional(Type.String({ description: "未完成工作，|分隔" })),
      failed: Type.Optional(Type.String({ description: "失败方案，|分隔" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const args = ["save", "--description", `"${params.description.replace(/"/g, '\\"')}"`];
      if (params.decisions) args.push("--decisions", `"${params.decisions.replace(/"/g, '\\"')}"`);
      if (params.remaining) args.push("--remaining", `"${params.remaining.replace(/"/g, '\\"')}"`);
      if (params.failed) args.push("--failed", `"${params.failed.replace(/"/g, '\\"')}"`);
      return { content: [{ type: "text", text: run(`context ${args.join(" ")}`, cwd) || "Context saved." }] };
    },
  });

  pi.registerTool({
    name: "memory_list",
    label: "List Memory",
    description: "列出所有项目记忆(learnings)。可按置信度、标签过滤。",
    parameters: Type.Object({
      confidenceMin: Type.Optional(Type.Number({ description: "最低置信度", minimum: 0, maximum: 10 })),
      tag: Type.Optional(Type.String({ description: "按标签过滤" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const args = ["list"];
      if (params.confidenceMin) args.push("--confidence-min", String(params.confidenceMin));
      if (params.tag) args.push("--tag", params.tag);
      return { content: [{ type: "text", text: run(`memory ${args.join(" ")}`, cwd) || "No learnings found." }] };
    },
  });

  // -----------------------------------------------------------------------
  // session_send — 跨 session 发消息（全局信箱）
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "session_send",
    label: "Send to Session",
    description:
      "向另一个 pi session 发送消息（跨项目）。" +
      "to 填目标 session ID（8位简写或完整UUID），to=* 表示广播。",
    promptSnippet: "Send a message to another session (cross-project)",
    promptGuidelines: ["Use session_list to discover available session IDs first"],
    parameters: Type.Object({
      to: Type.String({ description: "目标 session ID（8位简写或完整 UUID），* 表示广播" }),
      message: Type.String({ description: "要发送的消息内容" }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      fs.mkdirSync(GLOBAL_MAILBOX, { recursive: true });
      const fromSession = extractSessionId(ctx.sessionManager.getSessionFile());
      let toId = params.to;
      if (toId !== "*") {
        const resolved = resolveSessionId(toId);
        if (resolved) toId = resolved;
        else return { content: [{ type: "text", text: `❌ 未找到 session: ${params.to}\n用 session_list 查看可用 session` }] };
      }
      const id = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 6);
      fs.writeFileSync(path.join(GLOBAL_MAILBOX, `${id}.json`), JSON.stringify({
        id, from: fromSession, to: toId, message: params.message, timestamp: new Date().toISOString(),
      }, null, 2));
      return {
        content: [{ type: "text", text: `✉️ 已发送\n  从: ${fromSession.slice(0, 8)}...\n  到: ${toId === "*" ? "所有 session" : toId.slice(0, 8) + "..."}\n  消息: ${params.message.slice(0, 100)}` }],
        details: { from: fromSession, to: toId, messageId: id },
      };
    },
  });

  // -----------------------------------------------------------------------
  // session_list — 列出所有项目下的 session
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "session_list",
    label: "List Sessions",
    description: "列出所有项目下的 pi session，显示 ID、模型、项目、首条消息。",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      const currentSessionId = extractSessionId(ctx.sessionManager.getSessionFile());
      const sessions = scanAllSessions(currentSessionId);
      if (sessions.length === 0) return { content: [{ type: "text", text: "未找到任何 session" }] };
      const lines: string[] = ["## 所有项目 Sessions\n"];
      lines.push("| ID | 模型 | 项目 | 时间 | 首条消息 |");
      lines.push("|---|---|---|---|---|");
      for (const s of sessions.slice(0, 30)) {
        const tag = s.isCurrent ? " **←**" : "";
        lines.push(`| \`${s.shortId}\`${tag} | ${s.model} | ${s.project} | ${s.mtime} | ${s.firstMsg} |`);
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  });
}
