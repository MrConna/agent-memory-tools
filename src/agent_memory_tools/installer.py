"""Install project-local memory wrappers and LLM Wiki scaffolding."""

from __future__ import annotations

import os
import json
import shutil
from datetime import date
from pathlib import Path

from .config import write_default


MEMORY_README = """# Agent Memory

Project-local memory for coding agents.

- `learnings.jsonl`: durable rules, decisions, bug patterns, and failed approaches.
- `contexts.jsonl`: resumable checkpoints for interrupted work.
- `wiki/`: Markdown working knowledge generated from tracked sources.

Typical workflow:

```bash
bin/memory apply --query "<task keywords>"
bin/memory add "Durable lesson" --confidence 8 --source implementation --tags workflow
bin/context save --description "Checkpoint" --decisions "d1|d2" --remaining "r1|r2"
bin/context restore
bin/wiki add-source README.md AGENTS.md
bin/wiki add-page project-overview --summary "Durable project knowledge for agents." --source README.md
```

Do not store secrets, raw logs, ordinary progress updates, or low-confidence guesses as high-confidence memory.
"""

# ---- LLM Wiki scaffolding (from remote) -----------------------------------

KNOWLEDGE_INDEX_TEMPLATE = """# Knowledge Index

Content-oriented catalog of the `knowledge/` directory.

Maintain this file as the wiki grows:
- Add a one-line summary for each new long-term knowledge page.
- Organize by topic/domain.
- Update after every ingest or promotion.

## Topics

| Page | Summary |
|------|---------|
|  |  |
"""

KNOWLEDGE_LOG_TEMPLATE = """# Knowledge Log

Chronological record of ingests, queries, lint passes, and promotions.

Use a consistent prefix so the log is parseable with simple tools:

```text
## [YYYY-MM-DD] ingest | Source Title
## [YYYY-MM-DD] query | Question asked
## [YYYY-MM-DD] lint | Health check summary
## [YYYY-MM-DD] promote | Draft -> knowledge
```
"""

RAW_README = """# Raw Sources

Place original, immutable source materials here:
- meeting transcripts
- clipped articles
- design drafts
- exported chat logs
- reference documents

The LLM reads from these during **ingest**, but never modifies them.
Processed, synthesized knowledge belongs in `knowledge/`.
"""

DOCS_KNOWLEDGE_MANAGEMENT = """# Knowledge Management

This project follows the LLM Wiki pattern:

- `raw/` — immutable source materials
- `knowledge/` — LLM-maintained markdown wiki (index + log + topic pages)
- `AGENTS.md` / this doc — schema and conventions

## Lifecycle

1. **Ingest**: add a source to `raw/`, then ask the agent to integrate it into `knowledge/`.
2. **Query**: ask questions against `knowledge/`. File valuable answers back into the wiki.
3. **Lint**: periodically check for contradictions, orphan pages, stale claims, missing cross-references.

## Tools

- `bin/memory` — durable project learnings
- `bin/context` — resumable session checkpoints
- `bin/brain` — optional cross-project semantic search
- `bin/session` — bind agent sessions to stable commands for resume
"""

AGENTS_TEMPLATE = """# {project_name} — Agent Notes

This file is the schema for the project's LLM Wiki and agent memory.
Update it as conventions evolve.

## Project Memory

- Use `bin/memory add` for durable decisions, bug patterns, and preferences.
- Use `bin/context save` at important checkpoints or before handing off work.
- Use `bin/brain search` for cross-project semantic retrieval.
- Use `bin/session bind` to create stable resume commands for long-running agent sessions.

## Knowledge Workflow

1. **Ingest**: raw sources go to `raw/`; synthesized knowledge goes to `knowledge/`.
2. **Update `knowledge/index.md`** when adding or promoting a knowledge page.
3. **Append `knowledge/log.md`** for every ingest, query, lint, or promotion.
4. **Lint weekly**: check for stale claims, orphan pages, and missing cross-references.

## Directory Quick Reference

| Directory | Purpose |
|-----------|---------|
| `memory/` | Structured JSONL learnings + contexts |
| `knowledge/` | LLM-maintained markdown wiki |
| `raw/` | Immutable source materials |
| `docs/` | Stable process and convention docs |
| `bin/` | Project-local agent tool wrappers |
"""

# ---- Memory scaffolding (hooks + index + manifest) -------------------------

HOT_MD = """# Hot Memory

High-confidence learnings are cached here by `hooks/post-task.sh`.
"""

INDEX_MD = """# Memory Index

- `hot.md`: frequently useful, high-confidence learnings.
- `rules/`: durable project rules.
- `concepts/`: project concepts and terminology.
- `entities/`: important people, systems, and components.
- `snapshots/`: point-in-time memory snapshots.
"""

WIKI_INDEX = """# Wiki

Knowledge base for this project, following the [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern:
agents ingest sources, distill them into durable pages, and query the wiki before doing work.

## Structure

- `entities/`  — important people, systems, services, and components.
- `concepts/`  — project terminology, patterns, and mental models.
- `sources/`   — raw ingested material (transcripts, docs, links) awaiting distillation.

## Workflow

1. Drop raw material into `sources/`.
2. Distill it into `entities/` and `concepts/` pages, cross-linking with `[[wikilinks]]`.
3. Query these pages before starting related work; file new answers back in.

Keep pages short, factual, and cross-linked. Prefer editing an existing page over adding a duplicate.
"""

WIKI_SUBDIRS = {
    "entities": "# Entities\n\nPeople, systems, services, and components. One page per entity.\n",
    "concepts": "# Concepts\n\nTerminology, patterns, and mental models. One page per concept.\n",
    "sources": "# Sources\n\nRaw ingested material awaiting distillation into `entities/` and `concepts/`.\n",
}

COMMON_SKILLS = {
    "recall-project-memory": """---
name: recall-project-memory
description: Retrieve relevant project context before coding, debugging, planning, reviewing, or resuming interrupted work. Use when beginning a non-trivial task or when prior decisions and failed approaches may affect the work.
---

# Recall Project Memory

1. Run `./bin/lifecycle start "<task keywords>" --agent "<host>"`.
2. Apply only relevant memory and treat current source files as authoritative.
3. Mention any prior decision that materially changes the plan.
""",
    "capture-project-learning": """---
name: capture-project-learning
description: Record verified, reusable lessons after implementation, debugging, review, correction, or incident work. Use when a discovery will change how similar future work should be performed.
---

# Capture Project Learning

1. Search existing memory before adding.
2. Record one reusable pattern, not progress or raw logs.
3. Use confidence 7 for verified once, 8 for repeated evidence, and 9+ for stable workflows.
4. Add tag `skill` only for an executable repeatable workflow.
5. Never store secrets, private blocks, or unsupported guesses.
""",
    "handoff-session": """---
name: handoff-session
description: Preserve resumable task state before ending, pausing, compressing, or transferring a long-running session. Use for cross-day work, context limits, agent changes, or unresolved blockers.
---

# Handoff Session

Run `./bin/lifecycle end` with summary, decisions, remaining work, and failed approaches.
Verify `HANDOFF.md` is understandable without chat history. Keep task state separate from durable learning.
""",
    "maintain-project-knowledge": """---
name: maintain-project-knowledge
description: Curate project Wiki concepts, entities, and source-linked summaries after architecture changes, terminology changes, source updates, or repeated memory patterns.
---

# Maintain Project Knowledge

Search before creating, verify against current sources, update rather than duplicate, keep one topic per page, and run `./bin/wiki sync`. Never promote transient or unverified claims.
""",
}

COMMON_KNOWLEDGE = {
    "memory-taxonomy.md": """# Memory Taxonomy

- Observation: factual event captured from agent/tool activity.
- Context: resumable task state for the next session.
- Learning: verified reusable lesson with confidence and provenance.
- Rule: imperative project constraint promoted from reliable learning.
- Knowledge: source-backed concept or entity explanation.
- Skill: repeatable executable workflow, not merely advice.

Keep each fact in the lowest sufficient layer and avoid duplicating the same content across layers.
""",
    "promotion-policy.md": """# Promotion Policy

Promote only verified reusable information. Default thresholds are confidence 7 for Rule and Knowledge, and confidence 9 plus an explicit `skill` tag for Skill. Current source files override stale memory. Update existing assets instead of creating synonyms.
""",
    "privacy-and-safety.md": """# Privacy and Safety

Never persist secrets, credentials, raw private conversations, or `<private>` blocks. Observations are evidence, not authority. Local-model output is a compression aid and must not independently establish high-impact rules or skills.
""",
    "cross-agent-lifecycle.md": """# Cross-Agent Lifecycle

All hosts use the same start, observe, and end lifecycle. Claude and agy use native hooks, pi uses its extension, and Codex uses a project-scoped transcript watcher. Every adapter must degrade without blocking the host.
""",
}

CODEX_MD = """# Agent Memory — Codex Instructions

Codex-compatible memory workflow. Same discipline as `CLAUDE.md`, framed for Codex.

## Before a task: retrieve learnings

```bash
./bin/memory apply --query "<task keywords>"
./memory/hooks/pre-task.sh "<task keywords>"
```

## After a task: record durable learnings

```bash
./memory/hooks/post-task.sh "<task name>" "<pattern description>" [confidence] [tags]
./bin/memory add "<pattern>" --confidence 7 --source "task" --tags "<tags>"
```

## Session state: save / restore

```bash
./bin/context save --description "What I did" --decisions "d1|d2" --remaining "r1|r2"
./bin/context restore
```

Do not store secrets, raw logs, ordinary progress updates, or low-confidence guesses as high-confidence memory.
"""

CLAUDE_MD = """# Agent Memory — Claude Code Hooks

## Pre-task: retrieve relevant learnings

Run this before starting any non-trivial work:

```bash
./bin/memory apply --query "<task keywords>"
./memory/hooks/pre-task.sh "<task keywords>"
```

## Post-task: extract durable learnings

After completing a task, record what was learned:

```bash
./memory/hooks/post-task.sh "<task name>" "<pattern description>" [confidence] [tags]
./bin/memory add "<pattern>" --confidence 7 --source "task" --tags "<tags>"
```

## Context: save/restore session state

```bash
./bin/context save --description "What I did" --decisions "d1|d2" --remaining "r1|r2"
./bin/context restore
```
"""

UNIVERSAL_AGENT_MD = """# Automated Agent Memory Lifecycle

Use the shared lifecycle for every non-trivial task.

Before work:
`./bin/lifecycle start "<task keywords>" --agent "<agent name>"`

Before the final response:
`./bin/lifecycle end --agent "<agent name>" --summary "<completed work>" --learning "<verified reusable lesson, or empty>" --confidence 7 --tags "<tags>" --decisions "<decisions>" --remaining "<remaining work>" --failed "<failed approaches>"`

Only verified reusable patterns belong in `--learning`. Use tag `skill` with confidence
9+ only for a repeatable workflow suitable for promotion. Never store secrets or raw logs.
"""

CLAUDE_SETTINGS_HOOKS = {
    "SessionStart": [{"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR/memory/hooks/session-start.sh" claude'}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": 'PROJECT_ROOT="$CLAUDE_PROJECT_DIR" agent-memory lifecycle observe --agent claude --kind tool'}]}],
    "Stop": [{"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR/memory/hooks/session-end.sh" claude'}]}],
}

AGY_HOOKS = {
    "SessionStart": "agent-memory lifecycle start session --agent agy",
    "BeforeAgent": "agent-memory lifecycle observe --agent agy --kind prompt",
    "AfterAgent": "agent-memory lifecycle observe --agent agy --kind response",
    "BeforeTool": "agent-memory lifecycle observe --agent agy --kind before-tool",
    "AfterTool": "agent-memory lifecycle observe --agent agy --kind tool",
    "Notification": "agent-memory lifecycle observe --agent agy --kind notification",
    "PreCompress": "agent-memory lifecycle end --agent agy --summary 'agy pre-compress checkpoint'",
    "SessionEnd": "agent-memory lifecycle end --agent agy --summary 'agy session completed'",
}

HOOKS = {
    "pre-task.sh": r"""#!/usr/bin/env bash
# pre-task.sh - retrieve memory before tasks
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
Q="${1:-}"
if [ -z "$Q" ]; then echo "Usage: pre-task.sh <query>"; exit 1; fi
echo "[pre-task] searching: $Q"
if [ -f "$ROOT/memory/hot.md" ]; then head -40 "$ROOT/memory/hot.md"; fi
"$ROOT/bin/memory" apply --query "$Q" 2>/dev/null || true
echo "[pre-task] done"
""",
    "post-task.sh": r"""#!/usr/bin/env bash
# post-task.sh - extract knowledge after tasks
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK="${1:-}"; PATTERN="${2:-}"; CONF="${3:-7}"; TAGS="${4:-general}"
if [ -z "$TASK" ] || [ -z "$PATTERN" ]; then
  echo "Usage: post-task.sh <task> <pattern> [confidence] [tags]"; exit 1
fi
echo "[post-task] extracting: $PATTERN"
"$ROOT/bin/memory" add "$PATTERN" --confidence "$CONF" --source "task: $TASK" --tags "$TAGS"
if [ "$CONF" -ge 7 ] && [ -f "$ROOT/memory/hot.md" ]; then
  echo "- $PATTERN [confidence:$CONF tags:$TAGS]" >> "$ROOT/memory/hot.md"
fi
python3 - "$ROOT/memory/manifest.json" "$CONF" <<'PYEOF'
import datetime, json, sys
path, confidence = sys.argv[1], int(sys.argv[2])
with open(path) as f: manifest = json.load(f)
s = manifest["stats"]
s["last_post_task"] = datetime.datetime.now().isoformat()
s["total_learnings"] = s.get("total_learnings", 0) + 1
if confidence >= 7: s["high_confidence"] = s.get("high_confidence", 0) + 1
with open(path, "w") as f: json.dump(manifest, f, indent=2); f.write("\n")
PYEOF
if [ "$CONF" -ge 7 ] && [ -f "$ROOT/bin/brain-sync" ]; then
  python3 "$ROOT/bin/brain-sync"
fi
echo "[post-task] done (confidence=$CONF tags=$TAGS)"
""",
    "self-review.sh": r"""#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LF="$ROOT/memory/learnings.jsonl"
echo "[self-review] starting..."
if [ ! -f "$LF" ]; then echo "no learnings file"; exit 0; fi
python3 - "$LF" "$ROOT/memory/manifest.json" <<'PYEOF'
import datetime, json, sys
lp, mp = sys.argv[1:]
lines = [json.loads(l) for l in open(lp) if l.strip()]
total = len(lines)
high = sum(1 for l in lines if l.get("confidence", 0) >= 7)
med = sum(1 for l in lines if 4 <= l.get("confidence", 0) < 7)
low = sum(1 for l in lines if l.get("confidence", 0) < 4)
tags = {}
for l in lines:
    for t in (l.get("tags","") if isinstance(l.get("tags"), list) else l.get("tags","").split(",")):
        t = t.strip()
        if t: tags[t] = tags.get(t, 0) + 1
print(f"total={total} high={high} med={med} low={low}")
print(f"top_tags={sorted(tags.items(), key=lambda p:-p[1])[:5]}")
seen = {}
for l in lines:
    k = l.get("pattern","").strip().lower()[:50]
    if k in seen: print(f"DUP: {l.get('pattern','')[:60]} <-> {seen[k][:60]}")
    else: seen[k] = l.get("pattern","")
with open(mp) as f:
    m = json.load(f)
m["stats"]["self_reviews"] = m["stats"].get("self_reviews", 0) + 1
m["stats"]["last_self_review"] = datetime.datetime.now().isoformat()
with open(mp, "w") as f: json.dump(m, f, indent=2); f.write("\n")
print(f'review #{m["stats"]["self_reviews"]} complete')
PYEOF
echo "[self-review] done"
""",
    "session-start.sh": r"""#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT="${1:-unknown}"
INPUT="$(cat 2>/dev/null || true)"
PROJECT_ROOT="$ROOT" "$ROOT/bin/lifecycle" start "${INPUT:-session start}" --agent "$AGENT" || true
""",
    "session-end.sh": r"""#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT="${1:-unknown}"
PROJECT_ROOT="$ROOT" "$ROOT/bin/lifecycle" end --agent "$AGENT" --summary "$AGENT session completed" || true
""",
}


# ---- Helpers -----------------------------------------------------------------

def _write_if_missing(path: Path, content: str, *, force: bool) -> None:
    """Write content if file doesn't exist or force is True."""
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _new_manifest() -> dict[str, object]:
    return {
        "version": "1.0.0",
        "system": "AgentTeam Self-Evolving Knowledge System",
        "pattern": "Karpathy LLM Wiki + claude-obsidian",
        "created": date.today().isoformat(),
        "stats": {
            "total_learnings": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
            "self_reviews": 0,
            "last_self_review": None,
            "last_pre_task": None,
            "last_post_task": None,
        },
        "hooks": {
            "pre_task": "hooks/pre-task.sh",
            "post_task": "hooks/post-task.sh",
            "self_review": "hooks/self-review.sh",
            "auto_commit": True,
            "auto_push": False,
        },
        "thresholds": {
            "high_confidence_min": 7,
            "medium_confidence_min": 4,
            "self_review_interval_tasks": 3,
            "hot_cache_max_lines": 50,
            "max_learning_age_days": 180,
        },
        "history": [{
            "event": "system_init",
            "date": date.today().isoformat(),
            "note": "Created self-evolving knowledge system based on Karpathy LLM Wiki pattern",
        }],
    }


def _install_codex_bridge(root: Path, *, force: bool) -> None:
    """Install .codex-plugin for Codex CLI compatibility."""
    codex_dir = root / ".codex-plugin"
    codex_dir.mkdir(exist_ok=True)
    plugin_file = codex_dir / "plugin.json"
    if not plugin_file.exists() or force:
        plugin = {
            "name": "agent-memory",
            "version": "1.0.0",
            "description": "Durable learnings and resumable context for coding agents",
            "skills": "../.codex/",
            "interface": {
                "displayName": "Agent Memory",
                "shortDescription": "Retrieve learnings and save agent context",
                "category": "Developer Tools",
                "capabilities": ["Read", "Write"],
                "brandColor": "#2563EB",
            },
        }
        plugin_file.write_text(json.dumps(plugin, indent=2) + "\n")

    # The plugin points `skills` at ../.codex/ — create it so the reference resolves.
    _write_if_missing(root / ".codex" / "CLAUDE.md", CODEX_MD, force=force)


def _merge_claude_hooks(root: Path) -> None:
    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings: dict[str, object] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("  → invalid .claude/settings.json; native hooks skipped")
            return
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print("  → invalid hooks value in .claude/settings.json; native hooks skipped")
        return
    for event, entries in CLAUDE_SETTINGS_HOOKS.items():
        current = hooks.setdefault(event, [])
        if not isinstance(current, list):
            continue
        serialized = json.dumps(current)
        for entry in entries:
            command = entry["hooks"][0]["command"]
            if command not in serialized:
                current.append(entry)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _install_agent_integrations(root: Path, *, force: bool) -> None:
    skill = """---
name: agent-memory-lifecycle
description: Retrieve project memory before work and persist context, handoff, knowledge, and verified learnings after work.
---

""" + UNIVERSAL_AGENT_MD
    _write_if_missing(root / ".codex" / "skills" / "agent-memory-lifecycle" / "SKILL.md", skill, force=force)
    _write_if_missing(root / ".claude" / "skills" / "agent-memory-lifecycle" / "SKILL.md", skill, force=force)
    _write_if_missing(root / ".agy" / "AGENTS.md", UNIVERSAL_AGENT_MD.replace("<agent name>", "agy"), force=force)
    _write_if_missing(root / "AGY.md", UNIVERSAL_AGENT_MD.replace("<agent name>", "agy"), force=force)
    _merge_claude_hooks(root)
    for name, content in COMMON_SKILLS.items():
        _write_if_missing(root / ".codex" / "skills" / name / "SKILL.md", content, force=force)
        _write_if_missing(root / ".claude" / "skills" / name / "SKILL.md", content, force=force)


def _install_common_knowledge(root: Path, *, force: bool) -> None:
    for name, content in COMMON_KNOWLEDGE.items():
        _write_if_missing(root / "wiki" / "concepts" / name, content, force=force)


def _install_agy_global_hooks() -> None:
    if not shutil.which("agy"):
        print("  → agy not found, skipping Antigravity global hooks")
        return
    path = Path.home() / ".gemini" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    settings: dict[str, object] = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("  → invalid ~/.gemini/settings.json; agy hooks skipped")
            return
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print("  → invalid hooks in ~/.gemini/settings.json; agy hooks skipped")
        return
    for event, command in AGY_HOOKS.items():
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            continue
        if command not in json.dumps(entries):
            entries.append({"hooks": [{"name": "agent-memory", "type": "command", "command": command, "timeout": 30}]})
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print("  ✓ agy global hooks → ~/.gemini/settings.json")


def install_all(path: str | os.PathLike[str], *, force: bool = False) -> None:
    """One-command project setup plus all detected host integrations."""
    init_project(path, force=force)
    _install_agy_global_hooks()
    from .codex_watcher import cmd_start
    from .config import load_config
    root = Path(path).expanduser().resolve()
    if load_config(root).get("codex", {}).get("watcher_enabled", True):
        previous = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(root)
        try:
            cmd_start()
        finally:
            if previous is None:
                os.environ.pop("PROJECT_ROOT", None)
            else:
                os.environ["PROJECT_ROOT"] = previous


# ---- init_project ---------------------------------------------------------

def init_project(path: str | os.PathLike[str], *, force: bool = False) -> None:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    # Core dirs
    (root / "memory").mkdir(exist_ok=True)
    (root / "memory" / "wiki" / "pages").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(exist_ok=True)

    # Memory sub-dirs
    for name in ("hooks", "rules", "concepts", "entities", "snapshots"):
        (root / "memory" / name).mkdir(exist_ok=True)

    # LLM Wiki dirs (from remote)
    (root / "knowledge").mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)

    # Wiki dir (cross-agent knowledge)
    (root / "wiki").mkdir(exist_ok=True)

    # Memory data files
    for name in ("learnings.jsonl", "contexts.jsonl"):
        target = root / "memory" / name
        if not target.exists():
            target.write_text("", encoding="utf-8")

    # Memory README
    _write_if_missing(root / "memory" / "README.md", MEMORY_README, force=force)
    write_default(root, force=force)

    # Memory hot cache + index + manifest
    _write_if_missing(root / "memory" / "hot.md", HOT_MD, force=force)
    _write_if_missing(root / "memory" / "index.md", INDEX_MD, force=force)
    manifest = root / "memory" / "manifest.json"
    if not manifest.exists() or force:
        manifest.write_text(json.dumps(_new_manifest(), indent=2) + "\n", encoding="utf-8")

    # Hook scripts
    for name, content in HOOKS.items():
        target = root / "memory" / "hooks" / name
        if not target.exists() or force:
            target.write_text(content.strip() + "\n", encoding="utf-8")
            target.chmod(0o755)

    # LLM Wiki scaffolding (from remote)
    _write_if_missing(root / "knowledge" / "index.md", KNOWLEDGE_INDEX_TEMPLATE, force=force)
    _write_if_missing(root / "knowledge" / "log.md", KNOWLEDGE_LOG_TEMPLATE, force=force)
    _write_if_missing(root / "raw" / "README.md", RAW_README, force=force)
    _write_if_missing(root / "docs" / "knowledge-management.md", DOCS_KNOWLEDGE_MANAGEMENT, force=force)

    # AGENTS.md with project name
    agents = root / "AGENTS.md"
    if not agents.exists() or force:
        project_name = root.name or "Project"
        agents.write_text(AGENTS_TEMPLATE.format(project_name=project_name), encoding="utf-8")

    wiki_index = root / "memory" / "wiki" / "index.md"
    if force or not wiki_index.exists():
        wiki_index.write_text("# Wiki Memory\n\nNo wiki pages yet.\n", encoding="utf-8")

    wiki_sources = root / "memory" / "wiki" / "sources.jsonl"
    if not wiki_sources.exists():
        wiki_sources.write_text("", encoding="utf-8")

    # Wiki (cross-agent knowledge base template)
    _write_if_missing(root / "wiki" / "index.md", WIKI_INDEX, force=force)
    for name, content in WIKI_SUBDIRS.items():
        (root / "wiki" / name).mkdir(exist_ok=True)
        _write_if_missing(root / "wiki" / name / "README.md", content, force=force)

    # Cross-agent CLAUDE.md + .codex-plugin
    _write_if_missing(root / "CLAUDE.md", CLAUDE_MD, force=force)
    _install_codex_bridge(root, force=force)

    # Bin wrappers
    for name in ("memory", "context", "brain", "session", "wiki", "health", "lifecycle", "config", "codex-watcher"):
        _write_wrapper(root / "bin" / name, name, force=force)

    _install_agent_integrations(root, force=force)
    _install_common_knowledge(root, force=force)

    # Install pi extensions + packages
    _install_pi_extensions()
    _install_pi_packages()

    # Summary
    print()
    if (root / "CLAUDE.md").exists():
        print("  🤖 Claude Code  → CLAUDE.md (hooks config)")
    if (root / ".codex-plugin" / "plugin.json").exists():
        print("  🤖 Codex CLI    → .codex-plugin/ + .codex/CLAUDE.md (skill bridge)")
    if (root / ".agy" / "AGENTS.md").exists():
        print("  🤖 agy          → .agy/AGENTS.md (lifecycle bridge)")
    if _has_pi():
        print("  🤖 pi           → Extensions installed")
    print(f"  ✓ Initialized agent memory + LLM Wiki scaffolding in {root}")
    print("  Try: bin/memory list")
    print('  Try: bin/context save --description "first checkpoint"')
    print('  Try: hooks/pre-task.sh "<task keywords>"')


# ---- Pi integration --------------------------------------------------------

def _has_pi() -> bool:
    """Check if pi is available in PATH."""
    import subprocess
    try:
        subprocess.run(["pi", "--version"], capture_output=True, timeout=5, check=True)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False


def _install_pi_extensions() -> None:
    """Copy pi extensions to ~/.pi/agent/extensions/."""
    if not _has_pi():
        print("  → pi not found, skipping pi extensions")
        return

    import shutil
    src_dir = Path(__file__).parent.parent.parent / "extensions"
    dst_dir = Path.home() / ".pi" / "agent" / "extensions"

    if not src_dir.exists():
        print("  → pi extensions source not found, skipping")
        return

    dst_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for ext_file in src_dir.glob("*.ts"):
        dst = dst_dir / ext_file.name
        if dst.exists():
            print(f"  → {ext_file.name} already installed, skipping")
        else:
            shutil.copy2(ext_file, dst)
            installed.append(ext_file.name)

    if installed:
        print(f"  ✓ pi extensions: {', '.join(installed)}")
        print("    → /reload in pi to activate")
    else:
        print("  → pi extensions: all already installed")


def _install_pi_packages() -> None:
    """Install pi-subagents and pi-intercom via pi install."""
    if not _has_pi():
        print("  → pi not found, skipping pi packages")
        return

    import subprocess

    packages = [
        ("pi-subagents", "Delegate tasks to specialized child agents"),
        ("pi-intercom", "Direct 1:1 messaging between pi sessions"),
    ]

    for name, desc in packages:
        try:
            result = subprocess.run(
                ["pi", "install", f"npm:{name}"],
                capture_output=True, timeout=30, text=True,
            )
            if result.returncode == 0:
                print(f"  ✓ {name} — {desc}")
            else:
                if "already" in result.stderr.lower() or "already" in result.stdout.lower():
                    print(f"  → {name} already installed")
                else:
                    print(f"  → {name} install skipped: {result.stderr.strip()[:80]}")
        except subprocess.TimeoutExpired:
            print(f"  → {name} install timed out")
        except Exception as e:
            print(f"  → {name} install failed: {e}")

    print("    → /reload in pi to activate")


# ---- Bin wrapper ----------------------------------------------------------

def _write_wrapper(path: Path, command: str, *, force: bool) -> None:
    if path.exists() and not force:
        return
    script = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
export PROJECT_ROOT="${{PROJECT_ROOT:-$ROOT}}"
if command -v agent-memory >/dev/null 2>&1; then
  exec agent-memory {command} "$@"
fi
exec python3 -m agent_memory_tools.cli {command} "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
