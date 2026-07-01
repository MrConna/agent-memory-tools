"""Install project-local memory wrappers and LLM Wiki scaffolding."""

from __future__ import annotations

import os
from pathlib import Path


MEMORY_README = """# Agent Memory

Project-local memory for coding agents.

- `learnings.jsonl`: durable rules, decisions, bug patterns, and failed approaches.
- `contexts.jsonl`: resumable checkpoints for interrupted work.

Typical workflow:

```bash
bin/memory apply --query "<task keywords>"
bin/memory add "Durable lesson" --confidence 8 --source implementation --tags workflow
bin/context save --description "Checkpoint" --decisions "d1|d2" --remaining "r1|r2"
bin/context restore
```

Do not store secrets, raw logs, ordinary progress updates, or low-confidence guesses as high-confidence memory.
"""

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


def init_project(path: str | os.PathLike[str], *, force: bool = False) -> None:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    # Core memory dirs
    (root / "memory").mkdir(exist_ok=True)
    (root / "bin").mkdir(exist_ok=True)

    # LLM Wiki dirs
    (root / "knowledge").mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)

    # Memory JSONL files
    for name in ("learnings.jsonl", "contexts.jsonl"):
        target = root / "memory" / name
        if not target.exists():
            target.write_text("", encoding="utf-8")

    # Memory README
    readme = root / "memory" / "README.md"
    if force or not readme.exists():
        readme.write_text(MEMORY_README, encoding="utf-8")

    # LLM Wiki scaffolding
    _write_if_missing(root / "knowledge" / "index.md", KNOWLEDGE_INDEX_TEMPLATE, force=force)
    _write_if_missing(root / "knowledge" / "log.md", KNOWLEDGE_LOG_TEMPLATE, force=force)
    _write_if_missing(root / "raw" / "README.md", RAW_README, force=force)
    _write_if_missing(root / "docs" / "knowledge-management.md", DOCS_KNOWLEDGE_MANAGEMENT, force=force)

    # AGENTS.md with project name
    agents = root / "AGENTS.md"
    if force or not agents.exists():
        project_name = root.name or "Project"
        agents.write_text(AGENTS_TEMPLATE.format(project_name=project_name), encoding="utf-8")

    # Bin wrappers
    for name in ("memory", "context", "brain", "session", "health"):
        _write_wrapper(root / "bin" / name, name, force=force)

    # Install pi extensions
    _install_pi_extensions()

    # Install pi packages (subagents + intercom)
    _install_pi_packages()

    print(f"\n✓ Initialized agent memory + LLM Wiki scaffolding in {root}")
    print("  Try: bin/memory list")
    print("  Try: bin/context save --description \"first checkpoint\"")
    print("  Try: bin/session bind my-task --runtime pi --session-id <id> --cwd .")


def _write_if_missing(path: Path, content: str, *, force: bool) -> None:
    if force or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


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
                # Already installed or other issue
                if "already" in result.stderr.lower() or "already" in result.stdout.lower():
                    print(f"  → {name} already installed")
                else:
                    print(f"  → {name} install skipped: {result.stderr.strip()[:80]}")
        except subprocess.TimeoutExpired:
            print(f"  → {name} install timed out")
        except Exception as e:
            print(f"  → {name} install failed: {e}")

    print("    → /reload in pi to activate")


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
