from __future__ import annotations

import os
import subprocess
import sys
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


def test_init_project_installs_wrappers(tmp_path: Path) -> None:
    result = run_cli("init-project", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "bin" / "memory").exists()
    assert (tmp_path / "bin" / "context").exists()
    assert (tmp_path / "bin" / "brain").exists()
    assert (tmp_path / "memory" / "learnings.jsonl").exists()
    assert (tmp_path / "memory" / "contexts.jsonl").exists()


def test_memory_add_and_apply(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
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
        cwd=tmp_path,
    )
    assert add.returncode == 0, add.stderr

    apply = run_cli("memory", "apply", "--query", "delegated worktree", cwd=tmp_path)
    assert apply.returncode == 0, apply.stderr
    assert "Prior learning applied" in apply.stdout
    assert "scoped worktrees" in apply.stdout


def test_context_save_restore(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    save = run_cli(
        "context",
        "save",
        "--description",
        "checkpoint",
        "--decisions",
        "use jsonl",
        cwd=tmp_path,
    )
    assert save.returncode == 0, save.stderr

    restore = run_cli("context", "restore", cwd=tmp_path)
    assert restore.returncode == 0, restore.stderr
    assert "checkpoint" in restore.stdout
