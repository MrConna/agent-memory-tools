"""Install project-local memory wrappers."""

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


def init_project(path: str | os.PathLike[str], *, force: bool = False) -> None:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / "bin").mkdir(exist_ok=True)

    for name in ("learnings.jsonl", "contexts.jsonl"):
        target = root / "memory" / name
        if not target.exists():
            target.write_text("", encoding="utf-8")

    readme = root / "memory" / "README.md"
    if force or not readme.exists():
        readme.write_text(MEMORY_README, encoding="utf-8")

    for name in ("memory", "context", "brain"):
        _write_wrapper(root / "bin" / name, name, force=force)

    print(f"✓ Initialized agent memory in {root}")
    print("  Try: bin/memory list")
    print("  Try: bin/context save --description \"first checkpoint\"")


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
