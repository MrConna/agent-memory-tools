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
// Assignments — 任务分配持久化（跨 compaction 不丢失）
// ---------------------------------------------------------------------------

interface Assignment {
  id: string;
  task: string;
  sessionId: string;
  role: string;         // executor, reviewer, scout, etc.
  status: "active" | "done" | "failed" | "revoked" | "session_gone" | "timeout";
  assignedBy: string;   // leader session ID
  timeoutMinutes?: number;  // 超时时间（分钟），0=不限
  createdAt: string;
  updatedAt: string;
  result?: string;      // 完成时的摘要
}

function assignmentsFile(cwd: string): string {
  const dir = path.join(cwd, "memory");
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, "assignments.jsonl");
}

function loadAssignments(cwd: string): Assignment[] {
  const file = assignmentsFile(cwd);
  if (!fs.existsSync(file)) return [];
  const records: Assignment[] = [];
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try { records.push(JSON.parse(line)); } catch {}
  }
  return records;
}

function saveAssignment(cwd: string, a: Assignment): void {
  const file = assignmentsFile(cwd);
  fs.appendFileSync(file, JSON.stringify(a) + "\n", "utf8");
}

function updateAssignment(cwd: string, id: string, updates: Partial<Assignment>): Assignment | null {
  const file = assignmentsFile(cwd);
  const records = loadAssignments(cwd);
  let found: Assignment | null = null;
  for (const r of records) {
    if (r.id === id) {
      Object.assign(r, updates, { updatedAt: new Date().toISOString() });
      found = r;
    }
  }
  if (found) fs.writeFileSync(file, records.map(r => JSON.stringify(r)).join("\n") + "\n", "utf8");
  return found;
}

/** 检查 session 文件是否还存在 */
function sessionExists(sessionId: string): boolean {
  return findSessionFile(sessionId) !== null;
}

/** 找到 session 文件路径，不存在返回 null */
function findSessionFile(sessionId: string): string | null {
  if (!fs.existsSync(SESSIONS_ROOT)) return null;
  const shortId = sessionId.slice(0, 8);
  for (const pDir of fs.readdirSync(SESSIONS_ROOT)) {
    try {
      for (const file of fs.readdirSync(path.join(SESSIONS_ROOT, pDir))) {
        if (file.includes(shortId)) return path.join(SESSIONS_ROOT, pDir, file);
      }
    } catch {}
  }
  return null;
}

/** 返回 session 文件多少分钟没更新 */
function getStaleMinutes(sessionFile: string): number {
  try {
    const stat = fs.statSync(sessionFile);
    return (Date.now() - stat.mtimeMs) / 60_000;
  } catch {
    return 999; // 文件读不到，视为严重卡住
  }
}

/** 通过 tmux send-keys 向终端窗口投递消息 */
function sendToTerminal(target: string, message: string): { content: Array<{ type: string; text: string }>; details: Record<string, string> } {
  // 检测 tmux
  try {
    execSync("which tmux", { timeout: 3_000 });
  } catch {
    return { content: [{ type: "text", text: "❌ tmux 未安装。安装: brew install tmux" }], details: {} };
  }

  const sessionName = target.includes(":") ? target.split(":")[0] : target;

  // 检测 session 是否存在
  try {
    const sessions = execSync("tmux list-sessions -F '#{session_name}'", { encoding: "utf-8", timeout: 3_000 }).trim();
    if (!sessions.split("\n").includes(sessionName)) {
      return {
        content: [{ type: "text", text: `❌ tmux session '${sessionName}' 不存在。\n可用: ${sessions.split("\n").join(", ")}\n创建: tmux new -s ${sessionName}` }],
        details: {},
      };
    }
  } catch {
    return { content: [{ type: "text", text: "❌ 没有运行中的 tmux session。\n启动: tmux new -s worker" }], details: {} };
  }

  // 投递：输入消息 + Enter
  try {
    const escaped = message.replace("'", "'\\''");
    execSync(`tmux send-keys -t ${target} '${escaped}' Enter`, { timeout: 5_000 });
    return {
      content: [{ type: "text", text: `✉️ 已投递到终端（tmux）\n  目标: ${target}\n  消息: ${message.slice(0, 100)}` }],
      details: { target, via: "terminal" },
    };
  } catch (e: any) {
    return { content: [{ type: "text", text: `❌ 投递失败: ${e.message}` }], details: {} };
  }
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

    pi.on("session_shutdown", async () => { clearInterval(mailboxTimer); clearInterval(assignmentWatchTimer); });

    // 分配巡检：每 60 秒检查 active 分配
    // 1. session 文件是否还存在（进程退出）
    // 2. session 是否还在活跃工作（文件长时间未更新 = 可能卡住）
    // 3. 是否超时（分配时指定了 timeoutMinutes）
    const notifiedStale = new Set<string>(); // 已通知过的 stale assignment，避免重复通知
    const assignmentWatchTimer = setInterval(() => {
      try {
        const assignments = loadAssignments(cwd).filter(a => a.status === "active");
        if (assignments.length === 0) { notifiedStale.clear(); return; }
        const now = Date.now();
        const STALE_MINUTES = 10;

        for (const a of assignments) {
          // 检测 1：session 是否还存在
          const sessionFile = findSessionFile(a.sessionId);
          if (!sessionFile) {
            updateAssignment(cwd, a.id, { status: "session_gone" });
            notifiedStale.delete(a.id); // 已自动标记，不再通知
            pi.sendUserMessage(
              `⚠️ 任务「${a.task.slice(0, 60)}」的执行 session \`${a.sessionId.slice(0, 8)}\` 已不可用（进程已退出）。` +
              `请用 task_assign 重新分配，或 delegate 派给新子 agent。`,
              { deliverAs: "followUp" }
            );
            continue;
          }

          // 检测 2：session 是否还在活跃工作（只通知一次）
          const staleMin = getStaleMinutes(sessionFile);
          if (staleMin > STALE_MINUTES && !notifiedStale.has(a.id)) {
            notifiedStale.add(a.id); // 标记已通知，后续不再重复
            pi.sendUserMessage(
              `⏳ 任务「${a.task.slice(0, 60)}」的执行 session \`${a.sessionId.slice(0, 8)}\` 已 ${Math.round(staleMin)} 分钟无活动，可能卡住了。` +
              `用 task_update(status: "failed") 取消，或 session_send 询问进度。`,
              { deliverAs: "followUp" }
            );
          }
          // 如果恢复活跃了，清除已通知标记（下次卡住再通知）
          if (staleMin <= STALE_MINUTES) notifiedStale.delete(a.id);

          // 检测 3：是否超时
          if (a.timeoutMinutes && a.timeoutMinutes > 0) {
            const elapsedMin = (now - new Date(a.createdAt).getTime()) / 60_000;
            if (elapsedMin > a.timeoutMinutes) {
              updateAssignment(cwd, a.id, { status: "timeout" });
              notifiedStale.delete(a.id);
              pi.sendUserMessage(
                `⏰ 任务「${a.task.slice(0, 60)}」已超时（${a.timeoutMinutes}分钟），session \`${a.sessionId.slice(0, 8)}\`。` +
                `已自动标记为 timeout，请用 task_assign 重新分配。`,
                { deliverAs: "followUp" }
              );
            }
          }
        }
      } catch {}
    }, 60_000);
  });

  // -----------------------------------------------------------------------
  // Before agent start: 注入恢复的上下文 + learnings + 活跃分配
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
    // 注入活跃的任务分配（跨 compaction 持久化）
    // 检测分配的 session 是否还存在，不存在则自动标记 + 告警
    const activeAssignments = loadAssignments(cwd).filter(a => a.status === "active");
    if (activeAssignments.length > 0) {
      const lines = ["## 任务分配（跨会话持久化，context 压缩不会丢失）\n"];
      const goneLines: string[] = [];
      for (const a of activeAssignments) {
        const exists = sessionExists(a.sessionId);
        if (!exists) {
          // Session 已不存在，自动标记
          updateAssignment(cwd, a.id, { status: "session_gone" });
          goneLines.push(`- ~~${a.task.slice(0, 60)}~~ → session \`${a.sessionId.slice(0, 8)}\` **已不可用**，需重新分配`);
        } else {
          lines.push(`- **${a.task.slice(0, 80)}** → session \`${a.sessionId.slice(0, 8)}\` (${a.role ?? "executor"}) [${a.status}]`);
        }
      }
      if (lines.length > 1) blocks.push(lines.join("\n"));
      if (goneLines.length > 0) {
        blocks.push("## ⚠️ 以下任务的执行 session 已不可用，需重新分配\n" + goneLines.join("\n"));
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
  // task_assign — 记录任务分配（跨 compaction 持久化）
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "task_assign",
    label: "Assign Task to Session",
    description:
      "记录一条任务分配关系。当用户指定了某个 session 负责某项任务时，必须调用此工具持久化记录，" +
      "防止 context 压缩后丢失分配信息。分配关系会在每次会话开始时自动注入到 system prompt。",
    promptSnippet: "Persist a task-to-session assignment",
    promptGuidelines: [
      "Use task_assign whenever the user specifies which session should handle a task",
      "Assignments survive context compaction — they are injected into system prompt on each session start",
    ],
    parameters: Type.Object({
      task: Type.String({ description: "任务描述，清晰具体，包含验收标准" }),
      sessionId: Type.String({ description: "执行方 session ID（8位简写或完整 UUID）" }),
      role: Type.Optional(Type.String({ description: "角色：executor / reviewer / scout / planner / worker", default: "executor" })),
      timeoutMinutes: Type.Optional(Type.Number({ description: "超时时间（分钟），超时自动标记 timeout。0 或不填=不限", minimum: 0 })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const fromSession = extractSessionId(ctx.sessionManager.getSessionFile());
      // 短 ID 补全
      let toId = params.sessionId;
      const resolved = resolveSessionId(toId);
      if (resolved) toId = resolved;

      // 检测 session 是否存在
      if (!sessionExists(toId)) {
        return {
          content: [{ type: "text", text: `❌ session \`${toId.slice(0, 8)}\` 不存在或已关闭\n\n请用 session_list 查看可用 session，或用 delegate 派发给新子 agent` }],
        };
      }

      const id = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 6);
      const now = new Date().toISOString();
      const assignment: Assignment = {
        id, task: params.task, sessionId: toId,
        role: params.role ?? "executor",
        timeoutMinutes: params.timeoutMinutes,
        status: "active", assignedBy: fromSession,
        createdAt: now, updatedAt: now,
      };
      saveAssignment(cwd, assignment);

      return {
        content: [{
          type: "text",
          text: `📌 任务已分配（持久化，compaction 不会丢失）\n  任务: ${params.task.slice(0, 100)}\n  执行: ${toId.slice(0, 8)}... (${params.role ?? "executor"})\n  超时: ${params.timeoutMinutes ? params.timeoutMinutes + "分钟" : "不限"}\n  状态: active\n\n下次会话开始时，此分配会自动注入到 system prompt。\n巡检每 10 秒检测 session 存活和活跃度。`,
        }],
        details: { assignmentId: id, sessionId: toId },
      };
    },
  });

  // -----------------------------------------------------------------------
  // task_list — 列出任务分配
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "task_list",
    label: "List Task Assignments",
    description: "列出所有任务分配关系。按状态过滤，查看哪些任务已分配、已完成、需返工。",
    parameters: Type.Object({
      status: Type.Optional(Type.String({ description: "过滤状态：active / done / failed / revoked" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const assignments = loadAssignments(cwd);
      const filtered = params.status ? assignments.filter(a => a.status === params.status) : assignments;
      if (filtered.length === 0) {
        return { content: [{ type: "text", text: params.status ? `无 ${params.status} 状态的任务分配` : "无任务分配" }] };
      }
      const lines: string[] = ["## 任务分配\n"];
      lines.push("| 任务 | Session | 角色 | 状态 | 活跃度 | 超时 | 分配时间 |");
      lines.push("|---|---|---|---|---|---|---|");
      for (const a of filtered) {
        const statusEmoji: Record<string, string> = { active: "🔵", done: "✅", failed: "❌", revoked: "🚫", session_gone: "💀", timeout: "⏰" };
        const emoji = statusEmoji[a.status] ?? "❓";
        let activity = "—";
        if (a.status === "active") {
          const sf = findSessionFile(a.sessionId);
          if (!sf) activity = "💀 已退出";
          else {
            const stale = Math.round(getStaleMinutes(sf));
            activity = stale < 1 ? "🟢 活跃" : stale < 10 ? `🟡 ${stale}min前` : `🔴 ${stale}min前`;
          }
        }
        const timeout = a.timeoutMinutes ? `${a.timeoutMinutes}min` : "不限";
        lines.push(`| ${a.task.slice(0, 30)} | \`${a.sessionId.slice(0, 8)}\` | ${a.role} | ${emoji} ${a.status} | ${activity} | ${timeout} | ${a.createdAt.slice(5, 16)} |`);
      }
      if (filtered.some(a => a.result)) {
        lines.push("");
        for (const a of filtered.filter(a => a.result)) {
          lines.push(`**${a.task.slice(0, 40)}** → ${a.result!.slice(0, 100)}`);
        }
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  });

  // -----------------------------------------------------------------------
  // task_update — 更新任务状态
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "task_update",
    label: "Update Task Assignment",
    description: "更新任务分配的状态和结果。子 agent 完成后由 leader 调用，或任务失败时标记。",
    parameters: Type.Object({
      assignmentId: Type.String({ description: "分配 ID（task_assign 返回的 assignmentId）" }),
      status: Type.String({ description: "新状态：done / failed / revoked" }),
      result: Type.Optional(Type.String({ description: "结果摘要" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const updated = updateAssignment(cwd, params.assignmentId, {
        status: params.status as Assignment["status"],
        ...(params.result ? { result: params.result } : {}),
      });
      if (!updated) {
        return { content: [{ type: "text", text: `❌ 未找到分配: ${params.assignmentId}` }] };
      }
      return {
        content: [{ type: "text", text: `✅ 任务更新\n  ${updated.task.slice(0, 60)}\n  状态: ${updated.status}${updated.result ? "\n  结果: " + updated.result.slice(0, 100) : ""}` }],
      };
    },
  });

  // -----------------------------------------------------------------------
  // session_send — 跨 session/终端 发消息
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "session_send",
    label: "Send to Session",
    description:
      "向另一个 agent session 发送消息。" +
      "via=mailbox（默认）：通过全局信箱，对方需有 agent-memory Extension。" +
      "via=terminal：通过 tmux send-keys 直接往终端窗口打字，适用于任何交互式 agent（pi/Codex/Claude Code/其他）。",
    promptSnippet: "Send a message to another session or terminal",
    promptGuidelines: ["Use session_list to discover pi sessions", "Use terminal_list to discover terminal windows for via=terminal"],
    parameters: Type.Object({
      to: Type.String({ description: "目标：pi session ID（8位简写/UUID），或终端窗口名（如 my-worker），* 广播所有 pi session" }),
      message: Type.String({ description: "要发送的消息内容" }),
      via: Type.Optional(Type.String({ description: "投递方式：mailbox（默认，pi 信箱）/ terminal（tmux 终端打字）", default: "mailbox" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const via = params.via ?? "mailbox";

      // ---- via=terminal: tmux send-keys ----
      if (via === "terminal") {
        return sendToTerminal(params.to, params.message);
      }

      // ---- via=mailbox: 全局信箱 ----
      fs.mkdirSync(GLOBAL_MAILBOX, { recursive: true });
      const fromSession = extractSessionId(ctx.sessionManager.getSessionFile());
      let toId = params.to;
      if (toId !== "*") {
        const resolved = resolveSessionId(toId);
        if (resolved) toId = resolved;
        else return { content: [{ type: "text", text: `❌ 未找到 session: ${params.to}\n用 session_list 查看可用 pi session\n如果是非 pi session，用 via=terminal 通过 tmux 投递` }] };
      }
      const id = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 6);
      fs.writeFileSync(path.join(GLOBAL_MAILBOX, `${id}.json`), JSON.stringify({
        id, from: fromSession, to: toId, message: params.message, timestamp: new Date().toISOString(),
      }, null, 2));
      return {
        content: [{ type: "text", text: `✉️ 已发送（mailbox）\n  从: ${fromSession.slice(0, 8)}...\n  到: ${toId === "*" ? "所有 session" : toId.slice(0, 8) + "..."}\n  消息: ${params.message.slice(0, 100)}` }],
        details: { from: fromSession, to: toId, messageId: id, via: "mailbox" },
      };
    },
  });

  // -----------------------------------------------------------------------
  // -----------------------------------------------------------------------
  // terminal_list — 发现可投递的终端窗口
  // -----------------------------------------------------------------------
  pi.registerTool({
    name: "terminal_list",
    label: "List Terminals",
    description: "列出所有可投递的终端窗口（tmux sessions/windows），用于 session_send via=terminal。",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, _signal, _onUpdate, _ctx) {
      try {
        execSync("which tmux", { timeout: 3_000 });
      } catch {
        return { content: [{ type: "text", text: "tmux 未安装或未运行。\n安装: brew install tmux\n启动: tmux new -s worker" }] };
      }

      const lines: string[] = ["## 终端窗口（tmux）\n"];
      try {
        const sessions = run("tmux list-sessions -F '#{session_name} #{session_windows}' 2>/dev/null || true");
        if (!sessions || sessions.startsWith("[error]")) {
          return { content: [{ type: "text", text: "无 tmux session 运行。\n启动: tmux new -s worker" }] };
        }
        for (const line of sessions.split("\n").filter(Boolean)) {
          const [name, windows] = line.split(" ");
          lines.push(`- **${name}** (${windows} windows)`);
          try {
            const wins = run(`tmux list-windows -t ${name} -F '#{window_index}:#{window_name} #{pane_current_command}' 2>/dev/null || true`);
            if (wins && !wins.startsWith("[error]")) {
              for (const w of wins.split("\n").filter(Boolean)) lines.push(`  - ${w}`);
            }
          } catch {}
        }
        lines.push("");
        lines.push("发送: session_send(to: 'worker', message: 'hi', via: 'terminal')");
      } catch (e: any) {
        lines.push(`检测失败: ${e.message}`);
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  });

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
