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
    "AGENT_MEMORY_LOCAL_MODEL": "off",
}


def run_cli(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_memory_tools.cli", *args],
        cwd=str(cwd or ROOT),
        env={**ENV, **(env or {})},
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
    assert (tmp_path / "bin" / "lifecycle").exists()
    assert (tmp_path / "bin" / "config").exists()
    assert (tmp_path / "bin" / "codex-watcher").exists()
    assert (tmp_path / "bin" / "progress").exists()
    assert (tmp_path / "bin" / "workbench").exists()
    assert (tmp_path / "progress" / "README.md").exists()
    assert (tmp_path / "memory" / "learnings.jsonl").exists()
    assert (tmp_path / "memory" / "contexts.jsonl").exists()
    assert (tmp_path / "knowledge" / "index.md").exists()
    assert (tmp_path / "knowledge" / "log.md").exists()
    assert (tmp_path / "raw" / "README.md").exists()
    assert (tmp_path / "docs" / "knowledge-management.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "memory" / "wiki" / "pages").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".codex" / "skills" / "agent-memory-lifecycle" / "SKILL.md").exists()
    assert (tmp_path / ".agy" / "AGENTS.md").exists()
    assert (tmp_path / "memory" / "config.json").exists()
    assert (tmp_path / ".codex" / "skills" / "recall-project-memory" / "SKILL.md").exists()
    assert (tmp_path / ".codex" / "skills" / "run-verified-agent-loop" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "handoff-session" / "SKILL.md").exists()
    for target in (".codex", ".claude", ".pi", ".agy", ".gemini"):
        assert (tmp_path / target / "skills" / "teach" / "SKILL.md").exists()
        assert (tmp_path / target / "skills" / "diagnose-systematically" / "SKILL.md").exists()
        assert (tmp_path / target / "skills" / "develop-test-first" / "SKILL.md").exists()
        assert (tmp_path / target / "skills" / "verify-before-completion" / "SKILL.md").exists()
        assert (tmp_path / target / "skills" / "plan-and-execute" / "SKILL.md").exists()
    assert (tmp_path / "wiki" / "concepts" / "memory-taxonomy.md").exists()
    assert (tmp_path / "wiki" / "concepts" / "privacy-and-safety.md").exists()
    assert (tmp_path / "wiki" / "concepts" / "loop-engineering.md").exists()

    configured = run_cli("config", "set", "automation.brain_sync_on_end", "false", cwd=tmp_path)
    assert configured.returncode == 0, configured.stderr
    shown = run_cli("config", "show", cwd=tmp_path)
    assert shown.returncode == 0
    assert json.loads(shown.stdout)["automation"]["brain_sync_on_end"] is False


def test_common_skill_install_is_configurable(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "config.json").write_text(
        json.dumps({"skills": {"enabled": ["teach"], "targets": ["pi"]}}),
        encoding="utf-8",
    )
    result = run_cli("init-project", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".pi" / "skills" / "teach" / "SKILL.md").exists()
    assert not (tmp_path / ".codex" / "skills" / "teach" / "SKILL.md").exists()


def test_init_uses_local_git_exclude_without_modifying_gitignore(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("dist/\n", encoding="utf-8")
    result = run_cli("init-project", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert gitignore.read_text(encoding="utf-8") == "dist/\n"
    exclude = Path(subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--git-path", "info/exclude"],
        text=True, capture_output=True, check=True,
    ).stdout.strip())
    if not exclude.is_absolute():
        exclude = tmp_path / exclude
    text = exclude.read_text(encoding="utf-8")
    assert text.count("agent-memory-tools generated files >>>") == 1
    assert "/memory/" in text
    assert "/.codex/" in text
    assert "/bin/workbench" in text
    ignored = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", "memory/config.json", ".codex/skills/teach/SKILL.md", "bin/workbench"],
        text=True, capture_output=True, check=False,
    )
    assert ignored.returncode == 0, ignored.stderr
    assert len(ignored.stdout.splitlines()) == 3

    second = run_cli("init-project", str(tmp_path))
    assert second.returncode == 0, second.stderr
    assert exclude.read_text(encoding="utf-8").count("agent-memory-tools generated files >>>") == 1


def test_complex_lifecycle_creates_and_updates_progress(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    started = run_cli(
        "lifecycle", "start", "build workbench", "--agent", "codex", "--complex",
        "--outcome", "Manage project knowledge", "--acceptance", "API returns state",
        "--plan", "scaffold | implement | verify", cwd=tmp_path,
    )
    assert started.returncode == 0, started.stderr
    records = list((tmp_path / "progress").glob("*.json"))
    assert len(records) == 1
    updated = run_cli("progress", "update", "--message", "API implemented", "--artifact", "src/api.py", cwd=tmp_path)
    assert updated.returncode == 0, updated.stderr
    data = json.loads(records[0].read_text(encoding="utf-8"))
    assert "src/api.py" in data["artifacts"]
    markdown = records[0].with_suffix(".md").read_text(encoding="utf-8")
    assert "API implemented" in markdown
    assert "src/api.py" in markdown

    from agent_memory_tools import workbench
    previous = os.environ.get("PROJECT_ROOT")
    os.environ["PROJECT_ROOT"] = str(tmp_path)
    try:
        snapshot = workbench.state()
    finally:
        if previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = previous
    assert snapshot["progress"][0]["title"] == "build workbench"


def test_lifecycle_end_saves_and_promotes(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    result = run_cli(
        "lifecycle", "end", "--agent", "codex", "--summary", "Implemented lifecycle",
        "--learning", "Use one lifecycle command across coding agents",
        "--confidence", "9", "--tags", "workflow,skill", "--decisions", "share the core",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "HANDOFF.md").exists()
    assert (tmp_path / "memory" / "lifecycle.jsonl").exists()
    assert list((tmp_path / "memory" / "rules").glob("*.md"))
    assert list((tmp_path / "wiki" / "concepts").glob("use-one-lifecycle*.md"))
    assert list((tmp_path / "skills").glob("*/SKILL.md"))

    first = run_cli("lifecycle", "observe", "--agent", "codex", "--text", "updated auth routing", cwd=tmp_path)
    second = run_cli("lifecycle", "observe", "--agent", "codex", "--text", "updated auth routing", cwd=tmp_path)
    private = run_cli("lifecycle", "observe", "--agent", "codex", "--text", "<private>secret</private>", cwd=tmp_path)
    assert first.returncode == second.returncode == private.returncode == 0
    observations = (tmp_path / "memory" / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(observations) == 1


def test_codex_watcher_ingests_project_transcript(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    fake_home = tmp_path / "home"
    transcript = fake_home / ".codex" / "sessions" / "2026" / "07" / "19" / "rollout-test.jsonl"
    transcript.parent.mkdir(parents=True)
    events = [
        {"type": "session_meta", "payload": {"cwd": str(tmp_path), "id": "session-1"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "fix auth"}},
        {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "apply_patch", "arguments": "{}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "done"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "Auth fixed"}},
    ]
    transcript.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = run_cli(
        "codex-watcher", "once", cwd=tmp_path,
        env={"HOME": str(fake_home), "PROJECT_ROOT": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert "apply_patch" in (tmp_path / "memory" / "observations.jsonl").read_text(encoding="utf-8")
    assert "Auth fixed" in (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")


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
