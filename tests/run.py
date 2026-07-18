from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV = {
    **os.environ,
    "PYTHONPATH": str(ROOT / "src"),
}


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_memory_tools.cli", *args],
        cwd=str(cwd or ROOT),
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_init_project_installs_wrappers() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        result = run_cli("init-project", str(root))
        require(result.returncode == 0, result.stderr)
        require((root / "bin" / "memory").exists(), "memory wrapper missing")
        require((root / "bin" / "context").exists(), "context wrapper missing")
        require((root / "bin" / "brain").exists(), "brain wrapper missing")
        require((root / "memory" / "learnings.jsonl").exists(), "learnings missing")
        require((root / "memory" / "contexts.jsonl").exists(), "contexts missing")
        # Cross-agent support files
        require((root / "CLAUDE.md").exists(), "CLAUDE.md missing")
        require((root / ".codex" / "CLAUDE.md").exists(), ".codex/CLAUDE.md missing")
        require((root / ".codex-plugin" / "plugin.json").exists(), "codex plugin missing")
        require((root / "wiki" / "index.md").exists(), "wiki/index.md missing")
        require((root / "wiki" / "entities").is_dir(), "wiki/entities missing")
        require((root / "wiki" / "concepts").is_dir(), "wiki/concepts missing")
        require((root / "wiki" / "sources").is_dir(), "wiki/sources missing")


def test_memory_add_and_apply() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        add = run_cli(
            "memory",
            "add",
            "Use scoped worktrees for delegated agents",
            "--confidence",
            "9",
            "--source",
            "test",
            "--tags",
            "agents,worktree",
            cwd=root,
        )
        require(add.returncode == 0, add.stderr)

        apply = run_cli("memory", "apply", "--query", "delegated worktree", cwd=root)
        require(apply.returncode == 0, apply.stderr)
        require("Prior learning applied" in apply.stdout, apply.stdout)
        require("scoped worktrees" in apply.stdout, apply.stdout)


def test_context_save_restore() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        save = run_cli(
            "context",
            "save",
            "--description",
            "checkpoint",
            "--decisions",
            "use jsonl",
            cwd=root,
        )
        require(save.returncode == 0, save.stderr)

        restore = run_cli("context", "restore", cwd=root)
        require(restore.returncode == 0, restore.stderr)
        require("checkpoint" in restore.stdout, restore.stdout)


def main() -> None:
    tests = [
        test_init_project_installs_wrappers,
        test_memory_add_and_apply,
        test_context_save_restore,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"{len(tests)} checks passed.")


if __name__ == "__main__":
    main()
