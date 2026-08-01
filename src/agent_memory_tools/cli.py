#!/usr/bin/env python3
"""Unified CLI for agent memory tooling."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from . import automation, brain, codex_watcher, config, context, governance, health, memory, patterns, progress, search, session, wiki, workbench
from .installer import init_project, install_all


def _delegate(label: str, fn: Callable[[], int], argv: Sequence[str]) -> int:
    original = sys.argv[:]
    try:
        sys.argv = [f"agent-memory {label}", *argv]
        return fn()
    finally:
        sys.argv = original


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    command, rest = args[0], args[1:]
    if command == "memory":
        sys.exit(_delegate("memory", memory.main, rest))
    elif command == "context":
        sys.exit(_delegate("context", context.main, rest))
    elif command == "brain":
        sys.exit(_delegate("brain", brain.main, rest))
    elif command == "session":
        sys.exit(_delegate("session", session.main, rest))
    elif command == "wiki":
        sys.exit(_delegate("wiki", wiki.main, rest))
    elif command == "health":
        sys.exit(_delegate("health", health.main, rest))
    elif command == "lifecycle":
        sys.exit(automation.main(rest))
    elif command == "config":
        sys.exit(config.main(rest))
    elif command == "codex-watcher":
        sys.exit(codex_watcher.main(rest))
    elif command == "progress":
        sys.exit(progress.main(rest))
    elif command == "workbench":
        sys.exit(workbench.main(rest))
    elif command == "search":
        sys.exit(search.main(rest))
    elif command == "patterns":
        sys.exit(patterns.main(rest))
    elif command == "governance":
        sys.exit(governance.main(rest))
    elif command == "init-project":
        parser = argparse.ArgumentParser(
            prog="agent-memory init-project",
            description="Install project-local memory wrappers and empty JSONL files.",
        )
        parser.add_argument("path", nargs="?", default=".", help="Project root to initialize")
        parser.add_argument("--force", action="store_true", help="Overwrite existing bin wrappers")
        parsed = parser.parse_args(rest)
        init_project(parsed.path, force=parsed.force)
    elif command == "install":
        parser = argparse.ArgumentParser(prog="agent-memory install")
        parser.add_argument("path", nargs="?", default=".")
        parser.add_argument("--force", action="store_true")
        parsed = parser.parse_args(rest)
        install_all(parsed.path, force=parsed.force)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        _print_help(file=sys.stderr)
        sys.exit(2)


def _print_help(file=sys.stdout) -> None:
    print(
        """agent-memory — project memory tooling for coding agents

Usage:
  agent-memory memory <add|search|list|check|prune|export|apply> ...
  agent-memory context <save|restore|list|show> ...
  agent-memory wiki <init|add-source|add-page|search|sync> ...
  agent-memory brain <init|register|sync|search|status> ...
  agent-memory session <scan|bind|run|list|show|unbind> ...
  agent-memory health check [--session-id <id>]
  agent-memory lifecycle <start|end> ...
  agent-memory config <show|set> ...
  agent-memory codex-watcher <start|stop|status|once> ...
  agent-memory progress <start|update|list> ...
  agent-memory workbench [--port 8765] [--no-open]
  agent-memory search <rebuild|query> ...
  agent-memory patterns <record|status> ...
  agent-memory governance <status|verify|graduate|reject|withdraw|migrate> ...
  agent-memory init-project [path] [--force]
  agent-memory install [path] [--force]

Short alias:
  amt memory list
""",
        file=file,
    )


if __name__ == "__main__":
    main()
