#!/usr/bin/env python3
"""Unified CLI for agent memory tooling."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from . import brain, context, memory, wiki
from .installer import init_project


def _delegate(label: str, fn: Callable[[], None], argv: Sequence[str]) -> None:
    original = sys.argv[:]
    try:
        sys.argv = [f"agent-memory {label}", *argv]
        fn()
    finally:
        sys.argv = original


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    command, rest = args[0], args[1:]
    if command == "memory":
        _delegate("memory", memory.main, rest)
    elif command == "context":
        _delegate("context", context.main, rest)
    elif command == "brain":
        _delegate("brain", brain.main, rest)
    elif command == "wiki":
        _delegate("wiki", wiki.main, rest)
    elif command == "init-project":
        parser = argparse.ArgumentParser(
            prog="agent-memory init-project",
            description="Install project-local memory wrappers and empty JSONL files.",
        )
        parser.add_argument("path", nargs="?", default=".", help="Project root to initialize")
        parser.add_argument("--force", action="store_true", help="Overwrite existing bin wrappers")
        parsed = parser.parse_args(rest)
        init_project(parsed.path, force=parsed.force)
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
  agent-memory init-project [path] [--force]

Short alias:
  amt memory list
""",
        file=file,
    )


if __name__ == "__main__":
    main()
