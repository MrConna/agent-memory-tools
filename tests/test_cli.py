from __future__ import annotations

import os
import json
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
    assert (tmp_path / "bin" / "session").exists()
    assert (tmp_path / "bin" / "wiki").exists()
    assert (tmp_path / "memory" / "learnings.jsonl").exists()
    assert (tmp_path / "memory" / "contexts.jsonl").exists()
    assert (tmp_path / "knowledge" / "index.md").exists()
    assert (tmp_path / "knowledge" / "log.md").exists()
    assert (tmp_path / "raw" / "README.md").exists()
    assert (tmp_path / "docs" / "knowledge-management.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "memory" / "wiki" / "pages").exists()


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


def test_session_bind_run_unbind(tmp_path: Path) -> None:
    registry = tmp_path / "session-commands.json"
    bin_dir = tmp_path / "bin"
    run_cli(
        "session",
        "bind",
        "test-cmd",
        "--runtime",
        "pi",
        "--session-id",
        "019ec97f-f34d-770d-9187-e88abc54c9b8",
        "--cwd",
        str(tmp_path),
        "--registry",
        str(registry),
        "--bin-dir",
        str(bin_dir),
        "--backend",
        "native",
    )

    run = run_cli(
        "session",
        "run",
        "test-cmd",
        "--dry-run",
        "--registry",
        str(registry),
    )
    assert run.returncode == 0, run.stderr
    assert "pi --session-id" in run.stdout

    list_result = run_cli("session", "list", "--registry", str(registry))
    assert list_result.returncode == 0, list_result.stderr
    assert "test-cmd" in list_result.stdout

    unbind = run_cli(
        "session",
        "unbind",
        "test-cmd",
        "--registry",
        str(registry),
        "--bin-dir",
        str(bin_dir),
    )
    assert unbind.returncode == 0, unbind.stderr


def test_session_tmux_backend_dry_run(tmp_path: Path) -> None:
    registry = tmp_path / "session-commands.json"
    bin_dir = tmp_path / "bin"
    run_cli(
        "session",
        "bind",
        "test-tmux",
        "--runtime",
        "pi",
        "--session-id",
        "019ec97f-f34d-770d-9187-e88abc54c9b8",
        "--cwd",
        str(tmp_path),
        "--registry",
        str(registry),
        "--bin-dir",
        str(bin_dir),
        "--backend",
        "tmux",
    )

    run = run_cli(
        "session",
        "run",
        "test-tmux",
        "--dry-run",
        "--registry",
        str(registry),
    )
    assert run.returncode == 0, run.stderr
    assert "tmux new-session" in run.stdout or "tmux attach" in run.stdout

    unbind = run_cli(
        "session",
        "unbind",
        "test-tmux",
        "--registry",
        str(registry),
        "--bin-dir",
        str(bin_dir),
    )
    assert unbind.returncode == 0, unbind.stderr


def test_wiki_init_add_page_search_and_sync(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    source = tmp_path / "README.md"
    source.write_text("Project memory uses wiki pages for durable domain knowledge.\n", encoding="utf-8")

    add_source = run_cli("wiki", "add-source", "README.md", cwd=tmp_path)
    assert add_source.returncode == 0, add_source.stderr
    assert "README.md" in add_source.stdout

    add_page = run_cli(
        "wiki",
        "add-page",
        "project-overview",
        "--title",
        "Project Overview",
        "--summary",
        "Wiki pages compress durable project knowledge for agents.",
        "--source",
        "README.md",
        cwd=tmp_path,
    )
    assert add_page.returncode == 0, add_page.stderr

    page = tmp_path / "memory" / "wiki" / "pages" / "project-overview.md"
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    assert "Project Overview" in text
    assert "README.md" in text

    search = run_cli("wiki", "search", "durable agents", cwd=tmp_path)
    assert search.returncode == 0, search.stderr
    assert "project-overview" in search.stdout

    source.write_text("Project memory source changed.\n", encoding="utf-8")
    sync = run_cli("wiki", "sync", cwd=tmp_path)
    assert sync.returncode == 0, sync.stderr
    assert "stale" in sync.stdout.lower()


def test_wiki_mutation_fails_on_invalid_sources_jsonl(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    sources = tmp_path / "memory" / "wiki" / "sources.jsonl"
    sources.write_text('{"path": "README.md"}\nnot-json\n', encoding="utf-8")
    before = sources.read_text(encoding="utf-8")
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")

    result = run_cli("wiki", "add-source", "README.md", cwd=tmp_path)

    assert result.returncode != 0
    assert "invalid JSON" in result.stderr
    assert sources.read_text(encoding="utf-8") == before


def test_wiki_retracking_changed_source_clears_stale_state(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    source = tmp_path / "README.md"
    source.write_text("original source\n", encoding="utf-8")
    run_cli(
        "wiki",
        "add-page",
        "project-overview",
        "--summary",
        "Original summary.",
        "--source",
        "README.md",
        cwd=tmp_path,
    )
    source.write_text("changed source\n", encoding="utf-8")
    run_cli("wiki", "sync", cwd=tmp_path)

    add_source = run_cli("wiki", "add-source", "README.md", cwd=tmp_path)
    assert add_source.returncode == 0, add_source.stderr
    sync = run_cli("wiki", "sync", cwd=tmp_path)
    assert sync.returncode == 0, sync.stderr
    assert "up to date" in sync.stdout

    records = [
        json.loads(line)
        for line in (tmp_path / "memory" / "wiki" / "sources.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0].get("stale") is False
    assert "current_sha256" not in records[0]


def test_wiki_rejects_external_sources_by_default(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    outside = tmp_path.parent / "outside-source.md"
    outside.write_text("outside\n", encoding="utf-8")

    result = run_cli("wiki", "add-source", str(outside), cwd=tmp_path)

    assert result.returncode != 0
    assert "outside project" in result.stderr


def test_health_check_missing_session(tmp_path: Path) -> None:
    result = run_cli(
        "health",
        "check",
        "--session-id",
        "00000000-0000-0000-0000-000000000000",
        cwd=tmp_path,
    )
    assert result.returncode == 1, result.stderr
    assert "Session file not found" in result.stdout
