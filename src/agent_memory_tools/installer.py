"""Install project-local memory wrappers."""

from __future__ import annotations

import os
from pathlib import Path


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


def init_project(path: str | os.PathLike[str], *, force: bool = False) -> None:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / "memory" / "wiki" / "pages").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(exist_ok=True)

    for name in ("learnings.jsonl", "contexts.jsonl"):
        target = root / "memory" / name
        if not target.exists():
            target.write_text("", encoding="utf-8")

    readme = root / "memory" / "README.md"
    if force or not readme.exists():
        readme.write_text(MEMORY_README, encoding="utf-8")

    wiki_index = root / "memory" / "wiki" / "index.md"
    if force or not wiki_index.exists():
        wiki_index.write_text("# Wiki Memory\n\nNo wiki pages yet.\n", encoding="utf-8")

    wiki_sources = root / "memory" / "wiki" / "sources.jsonl"
    if not wiki_sources.exists():
        wiki_sources.write_text("", encoding="utf-8")

    for name in ("memory", "context", "brain", "wiki"):
        _write_wrapper(root / "bin" / name, name, force=force)

    # Install pi extensions
    _install_pi_extensions()

    # Install pi packages (subagents + intercom)
    _install_pi_packages()

    print(f"\n✓ Initialized agent memory in {root}")
    print("  Try: bin/memory list")
    print("  Try: bin/context save --description \"first checkpoint\"")


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
