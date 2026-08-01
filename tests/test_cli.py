from __future__ import annotations

import os
import json
import subprocess
import sys
import types
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
    assert (tmp_path / "bin" / "patterns").exists()
    assert (tmp_path / "bin" / "governance").exists()
    assert (tmp_path / "bin" / "config").exists()
    assert (tmp_path / "bin" / "codex-watcher").exists()
    assert (tmp_path / "bin" / "progress").exists()
    assert (tmp_path / "bin" / "workbench").exists()
    assert (tmp_path / "bin" / "search").exists()
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


def test_workbench_new_entry_has_real_editor() -> None:
    source = (ROOT / "web" / "src" / "app.js").read_text(encoding="utf-8")
    markup = (ROOT / "web" / "src" / "index.html").read_text(encoding="utf-8")
    assert "window.alert" not in source
    assert 'id="entry-dialog"' in markup
    assert 'id="entry-form"' in markup
    assert 'fetch("/api/entry"' in source
    assert "contentOf(entry)" in source


def test_workbench_state_preserves_full_original_content(tmp_path: Path) -> None:
    from agent_memory_tools import workbench

    original = "# Long knowledge\n\n" + "full-content-line\n" * 100
    page = tmp_path / "wiki" / "concepts" / "long.md"
    page.parent.mkdir(parents=True)
    page.write_text(original, encoding="utf-8")
    previous = os.environ.get("PROJECT_ROOT")
    os.environ["PROJECT_ROOT"] = str(tmp_path)
    try:
        entry = workbench.state()["knowledge"][0]
    finally:
        if previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = previous
    assert entry["content"] == original
    assert len(entry["summary"]) < len(entry["content"])


def test_lifecycle_end_saves_and_promotes(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    result = run_cli(
        "lifecycle", "end", "--agent", "codex", "--summary", "Implemented lifecycle",
        "--learning", "Use one lifecycle command across coding agents",
        "--confidence", "9", "--tags", "workflow,skill,verified", "--decisions", "share the core",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "HANDOFF.md").exists()
    assert (tmp_path / "memory" / "lifecycle.jsonl").exists()
    assert not list((tmp_path / "memory" / "rules").glob("*.md"))
    assert not list((tmp_path / "wiki" / "concepts").glob("use-one-lifecycle*.md"))
    assert not list((tmp_path / "skills").glob("*/SKILL.md"))
    learning = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text().splitlines()[-1])
    assert learning["lifecycle_status"] == "candidate"
    assert learning["scope"] == "project"


def test_governance_candidate_can_be_verified_and_graduated(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    run_cli("memory", "add", "Prefer focused tests", "--tags", "verified", cwd=tmp_path)
    item = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text().splitlines()[0])

    verified = run_cli("governance", "verify", item["id"], "--by", "reviewer", "--targets", "knowledge,skill", cwd=tmp_path)
    assert verified.returncode == 0, verified.stderr
    graduated = run_cli("governance", "graduate", item["id"], "--by", "owner", cwd=tmp_path)
    assert graduated.returncode == 0, graduated.stderr

    current = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text().splitlines()[0])
    assert current["lifecycle_status"] == "graduated"
    assert current["scope"] == "cross_project"
    assert current["desired_targets"] == ["knowledge", "skill"]
    assert current["provenance"]["verified_by"] == ["reviewer"]
    assert current["provenance"]["graduated_by"] == ["owner"]
    assert list((tmp_path / "wiki" / "concepts").glob("prefer-focused-tests*.md"))
    assert list((tmp_path / "skills").glob("prefer-focused-tests*/SKILL.md"))
    events = [json.loads(line)["event"] for line in (tmp_path / "memory" / "lifecycle.jsonl").read_text().splitlines()]
    assert events[-2:] == ["governance_verified", "governance_graduated"]


def test_governance_invalid_transition_preserves_learning_bytes(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    run_cli("memory", "add", "Keep writes atomic", cwd=tmp_path)
    path = tmp_path / "memory" / "learnings.jsonl"
    item = json.loads(path.read_text().splitlines()[0])
    before = path.read_bytes()
    result = run_cli("governance", "graduate", item["id"], "--by", "owner", cwd=tmp_path)
    assert result.returncode != 0
    assert path.read_bytes() == before


def test_governance_legacy_requires_migration_and_targets_are_validated(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "learnings.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"id": "legacy", "pattern": "old"}) + "\n")
    before = path.read_bytes()
    blocked = run_cli("governance", "reject", "legacy", "--by", "owner", "--reason", "old", cwd=tmp_path)
    assert blocked.returncode != 0
    assert path.read_bytes() == before
    run_cli("governance", "migrate", "--apply", cwd=tmp_path)
    invalid = run_cli("governance", "graduate", "legacy", "--by", "owner", cwd=tmp_path)
    assert invalid.returncode == 0  # migrated legacy is project_verified

    run_cli("memory", "add", "new", cwd=tmp_path)
    current = json.loads(path.read_text().splitlines()[-1])
    before = path.read_bytes()
    invalid = run_cli("governance", "verify", current["id"], "--by", "owner", "--targets", "database", cwd=tmp_path)
    assert invalid.returncode != 0
    assert path.read_bytes() == before


def test_concurrent_memory_rmw_preserves_governance_and_reference_updates(tmp_path: Path) -> None:
    run_cli("memory", "add", "Concurrent governance memory", "--confidence", "9", cwd=tmp_path)
    path = tmp_path / "memory" / "learnings.jsonl"
    item = json.loads(path.read_text().splitlines()[0])
    searches = [
        subprocess.Popen(
            [sys.executable, "-m", "agent_memory_tools.cli", "memory", "search", "concurrent"],
            cwd=tmp_path, env=ENV, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for _ in range(6)
    ]
    verified = run_cli("governance", "verify", item["id"], "--by", "reviewer", cwd=tmp_path)
    assert verified.returncode == 0, verified.stderr
    assert all(process.wait(timeout=20) == 0 for process in searches)
    current = json.loads(path.read_text().splitlines()[0])
    assert current["lifecycle_status"] == "project_verified"
    assert current["provenance"]["verified_by"] == ["reviewer"]
    assert current["reference_count"] == 6


def test_brain_sync_evicts_withdrawn_learning(tmp_path: Path, monkeypatch) -> None:
    from argparse import Namespace
    from agent_memory_tools import brain

    brain_home = tmp_path / "brain"
    monkeypatch.setattr(brain, "BRAIN_HOME", brain_home)
    monkeypatch.setattr(brain, "CONFIG_FILE", brain_home / "config.json")
    monkeypatch.setattr(brain, "INDEX_FILE", brain_home / "index.jsonl")
    monkeypatch.setattr(brain, "EMBEDDINGS_FILE", brain_home / "embeddings.npy")
    brain._save_config({"model": "fake", "projects": [str(tmp_path)]})
    run_cli("memory", "add", "shared", cwd=tmp_path)
    item = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text().splitlines()[0])
    run_cli("governance", "verify", item["id"], "--by", "reviewer", cwd=tmp_path)
    run_cli("governance", "graduate", item["id"], "--by", "owner", cwd=tmp_path)

    class Embedding:
        shape = (1, 1)
        def astype(self, _kind):
            return self
    class Model:
        def __init__(self, _name):
            pass
        def encode(self, *_args, **_kwargs):
            return Embedding()
    fake_numpy = types.SimpleNamespace(float32="float32", save=lambda path, _value: Path(path).write_bytes(b"embedding"))
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Model))
    brain.cmd_sync(Namespace())
    assert len(brain._load_index()) == 1

    run_cli("governance", "withdraw", item["id"], "--by", "owner", "--reason", "superseded", cwd=tmp_path)
    brain.cmd_sync(Namespace())
    assert brain._load_index() == []
    assert not brain.EMBEDDINGS_FILE.exists()
    assert brain._load_config()["indexed_count"] == 0

    first = run_cli("lifecycle", "observe", "--agent", "codex", "--text", "updated auth routing", cwd=tmp_path)
    second = run_cli("lifecycle", "observe", "--agent", "codex", "--text", "updated auth routing", cwd=tmp_path)
    private = run_cli("lifecycle", "observe", "--agent", "codex", "--text", "<private>secret</private>", cwd=tmp_path)
    assert first.returncode == second.returncode == private.returncode == 0
    observations = (tmp_path / "memory" / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(observations) == 1


def test_repeated_lifecycle_learning_auto_promotes_to_knowledge(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    learning = "Always run the focused authentication test before the full suite"

    for occurrence in range(1, 4):
        result = run_cli(
            "lifecycle", "end", "--agent", f"agent-{occurrence}",
            "--summary", f"Authentication task {occurrence} completed",
            "--learning", learning, "--confidence", "5", "--tags", "testing,workflow",
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        pages = list((tmp_path / "wiki" / "concepts").glob("always-run-the-focused*.md"))
        assert bool(pages) is (occurrence == 3)

    status = run_cli("patterns", "status", cwd=tmp_path)
    assert status.returncode == 0, status.stderr
    assert "3 occurrences" in status.stdout
    assert "knowledge" in status.stdout


def test_rejected_learning_is_not_reverified_by_repeated_pattern(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    text = "Always validate generated schemas before publishing them"
    run_cli("lifecycle", "end", "--agent", "agent-1", "--learning", text, "--tags", "workflow", cwd=tmp_path)
    item = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text().splitlines()[0])
    run_cli("governance", "reject", item["id"], "--by", "reviewer", "--reason", "unsafe", cwd=tmp_path)
    for number in (2, 3):
        run_cli("lifecycle", "end", "--agent", f"agent-{number}", "--learning", text, "--tags", "workflow", cwd=tmp_path)
    current = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text().splitlines()[0])
    assert current["lifecycle_status"] == "rejected"
    assert not list((tmp_path / "wiki" / "concepts").glob("always-validate-generated*.md"))
    events = [json.loads(line)["event"] for line in (tmp_path / "memory" / "lifecycle.jsonl").read_text().splitlines()]
    assert events.count("governance_rejected") == 1
    assert "governance_verified" not in events


def test_malformed_learnings_prevent_pattern_asset_writes(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "learnings.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{broken\n")
    text = "Always validate memory before creating knowledge assets"
    for number in (1, 2):
        assert run_cli("patterns", "record", text, "--source", f"task-{number}", cwd=tmp_path).returncode == 0
    third = run_cli("patterns", "record", text, "--source", "task-3", cwd=tmp_path)
    assert third.returncode != 0
    assert not list((tmp_path / "wiki" / "concepts").glob("*.md"))


def test_semantically_similar_pattern_wording_accumulates_as_one_candidate(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    variants = [
        "Always run focused tests before the full suite",
        "Always run the focused tests before running the full suite",
        "Always run focused tests before full suite",
    ]
    for index, text in enumerate(variants):
        run_cli("patterns", "record", text, "--source", f"task-{index}", "--tags", "workflow", cwd=tmp_path)
    status = run_cli("patterns", "status", cwd=tmp_path)
    assert status.stdout.count("occurrences") == 1
    assert "3 occurrences" in status.stdout


def test_repeated_workflow_auto_promotes_to_skill_without_duplicate_evidence(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    workflow = "Run focused tests, inspect the diff, then run the full suite before committing"

    duplicate = run_cli(
        "patterns", "record", workflow, "--source", "task-1", "--tags", "workflow",
        cwd=tmp_path,
    )
    assert duplicate.returncode == 0, duplicate.stderr
    run_cli("patterns", "record", workflow, "--source", "task-1", "--tags", "workflow", cwd=tmp_path)
    run_cli("patterns", "record", "<private>personal workflow</private>", "--source", "task-private", cwd=tmp_path)
    for occurrence in range(2, 6):
        run_cli(
            "patterns", "record", workflow, "--source", f"task-{occurrence}", "--tags", "workflow",
            cwd=tmp_path,
        )

    skills = list((tmp_path / "skills").glob("run-focused-tests-inspect-the-diff*/SKILL.md"))
    assert len(skills) == 1
    skill = skills[0]
    content = skill.read_text(encoding="utf-8")
    assert "description:" in content
    assert "## Workflow" in content
    assert "5 distinct lifecycle events" in content
    status = run_cli("patterns", "status", cwd=tmp_path)
    assert "5 occurrences" in status.stdout
    assert "skill" in status.stdout
    assert "personal workflow" not in status.stdout


def test_lifecycle_auto_captures_procedural_summaries_but_ignores_generic_completion(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    procedure = "Always inspect generated migrations before running the deployment"
    for occurrence in range(1, 4):
        run_cli("lifecycle", "start", f"deployment {occurrence}", "--agent", "codex", cwd=tmp_path)
        result = run_cli(
            "lifecycle", "end", "--agent", "codex", "--summary", procedure,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
    run_cli("lifecycle", "end", "--agent", "host-4", "--summary", "Deployment task completed", cwd=tmp_path)

    pages = list((tmp_path / "wiki" / "concepts").glob("always-inspect-generated-migrations*.md"))
    assert len(pages) == 1
    status = run_cli("patterns", "status", cwd=tmp_path)
    assert procedure in status.stdout
    assert "Deployment task completed" not in status.stdout
    found = run_cli("search", "query", "generated migrations", "--type", "pattern", cwd=tmp_path)
    assert found.returncode == 0, found.stderr
    assert procedure in found.stdout


def test_repeated_observed_action_sequence_auto_promotes_without_learning_or_summary_cue(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    for occurrence in range(1, 4):
        run_cli("lifecycle", "start", f"task {occurrence}", "--agent", "codex", cwd=tmp_path)
        run_cli("lifecycle", "observe", "--agent", "codex", "--kind", "tool", "--text", "run focused tests", cwd=tmp_path)
        run_cli("lifecycle", "observe", "--agent", "codex", "--kind", "tool", "--text", "inspect git diff", cwd=tmp_path)
        ended = run_cli(
            "lifecycle", "end", "--agent", "codex", "--summary", f"Task {occurrence} completed",
            cwd=tmp_path,
        )
        assert ended.returncode == 0, ended.stderr

    status = run_cli("patterns", "status", cwd=tmp_path)
    assert "3 occurrences" in status.stdout
    assert "run focused tests then inspect git diff" in status.stdout
    assert list((tmp_path / "wiki" / "concepts").glob("run-focused-tests-then-inspect-git-diff*.md"))


def test_native_hook_payloads_keep_session_identity_privacy_and_repeated_steps(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    for occurrence in range(3):
        session_id = f"claude-session-{occurrence}"
        run_cli(
            "lifecycle", "start", f"task {occurrence}", "--agent", "claude",
            "--session-id", session_id, cwd=tmp_path,
        )
        for tool_name in ("pytest", "apply_patch", "pytest"):
            payload = json.dumps({"session_id": session_id, "tool_name": tool_name, "tool_input": {}})
            run_cli("lifecycle", "observe", "--agent", "claude", "--kind", "tool", "--text", payload, cwd=tmp_path)
        run_cli(
            "lifecycle", "observe", "--agent", "claude", "--kind", "tool",
            "--text", "<PRIVATE reason='secret'>do not store</PRIVATE>", cwd=tmp_path,
        )
        run_cli(
            "lifecycle", "end", "--agent", "claude", "--session-id", session_id,
            "--summary", f"Task {occurrence} completed", cwd=tmp_path,
        )
    status = run_cli("patterns", "status", cwd=tmp_path)
    assert "pytest then apply_patch then pytest" in status.stdout
    observations = (tmp_path / "memory" / "observations.jsonl").read_text(encoding="utf-8")
    assert "do not store" not in observations


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


def test_codex_watcher_learns_repeated_tool_sequence(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    fake_home = tmp_path / "home"
    transcript = fake_home / ".codex" / "sessions" / "2026" / "07" / "23" / "rollout-pattern.jsonl"
    transcript.parent.mkdir(parents=True)
    events: list[dict[str, object]] = [
        {"type": "session_meta", "payload": {"cwd": str(tmp_path), "id": "codex-session-pattern"}},
    ]
    for task in range(3):
        events.extend([
            {"type": "event_msg", "payload": {"type": "user_message", "message": f"task {task}"}},
            {"type": "response_item", "payload": {"type": "function_call", "call_id": f"exec-{task}", "name": "exec_command", "arguments": '{"cmd":"pytest focused"}'}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": f"exec-{task}", "output": f"{task} passed"}},
            {"type": "response_item", "payload": {"type": "function_call", "call_id": f"patch-{task}", "name": "apply_patch", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": f"patch-{task}", "output": f"patch {task} done"}},
            {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": f"task {task} completed"}},
        ])
    transcript.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    result = run_cli(
        "codex-watcher", "once", cwd=tmp_path,
        env={"HOME": str(fake_home), "PROJECT_ROOT": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    status = run_cli("patterns", "status", cwd=tmp_path)
    assert "3 occurrences" in status.stdout
    assert "exec_command pytest then apply_patch" in status.stdout


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


def test_unified_search_rebuilds_and_finds_project_sources(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    run_cli(
        "memory", "add", "鉴权中间件必须先于路由初始化",
        "--confidence", "9", "--tags", "鉴权,架构", cwd=tmp_path,
    )
    run_cli(
        "context", "save", "--description", "正在迁移身份验证模块",
        "--decisions", "继续兼容旧登录接口", cwd=tmp_path,
    )
    concept = tmp_path / "wiki" / "concepts" / "authentication.md"
    concept.write_text("# 身份验证规范\n\n所有鉴权失败返回统一错误结构。\n", encoding="utf-8")
    (tmp_path / "wiki" / "concepts" / "deployment.md").write_text(
        "# 部署规范\n\n上线前检查发布清单。\n", encoding="utf-8",
    )

    rebuilt = run_cli("search", "rebuild", cwd=tmp_path)
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert "Indexed" in rebuilt.stdout
    assert (tmp_path / "memory" / "index.db").exists()

    result = run_cli("search", "query", "鉴权", "--top", "10", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "鉴权中间件" in result.stdout
    assert "身份验证规范" in result.stdout
    precise = run_cli("search", "query", "鉴权规范", "--type", "knowledge", "--top", "1", cwd=tmp_path)
    assert "身份验证规范" in precise.stdout
    assert "部署规范" not in precise.stdout

    contexts = run_cli("search", "query", "迁移 身份验证", "--type", "context", cwd=tmp_path)
    assert contexts.returncode == 0, contexts.stderr
    assert "正在迁移身份验证模块" in contexts.stdout
    assert "[context]" in contexts.stdout

    skills = run_cli("search", "query", "learning objective", "--type", "skill", cwd=tmp_path)
    assert skills.returncode == 0, skills.stderr
    assert "Teach" in skills.stdout
    assert skills.stdout.count("[skill] Teach") == 1


def test_unified_search_refreshes_changed_sources_and_filters(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    run_cli("search", "rebuild", cwd=tmp_path)
    run_cli(
        "memory", "add", "Database migrations require a rollback plan",
        "--confidence", "9", "--tags", "database", cwd=tmp_path,
    )

    refreshed = run_cli(
        "search", "query", "rollback", "--type", "memory",
        "--confidence-min", "8", cwd=tmp_path,
    )
    assert refreshed.returncode == 0, refreshed.stderr
    assert "Database migrations" in refreshed.stdout

    excluded = run_cli(
        "search", "query", "rollback", "--type", "memory",
        "--confidence-min", "10", cwd=tmp_path,
    )
    assert excluded.returncode == 0, excluded.stderr
    assert "No indexed entries" in excluded.stdout


def test_lifecycle_start_uses_relevant_unified_context(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    run_cli(
        "context", "save", "--description", "Authentication migration checkpoint",
        "--remaining", "replace legacy token validator", cwd=tmp_path,
    )
    run_cli(
        "context", "save", "--description", "Unrelated CSS cleanup",
        "--remaining", "adjust footer spacing", cwd=tmp_path,
    )
    run_cli(
        "memory", "add", "Legacy token authentication guess",
        "--confidence", "2", cwd=tmp_path,
    )

    started = run_cli("lifecycle", "start", "legacy token authentication", "--agent", "codex", cwd=tmp_path)
    assert started.returncode == 0, started.stderr
    assert "Authentication migration checkpoint" in started.stdout
    assert "Unrelated CSS cleanup" not in started.stdout
    assert "Legacy token authentication guess" not in started.stdout
    assert "[context]" in started.stdout
    assert "replace legacy token validator" in started.stdout


def test_unified_search_rebuild_is_concurrent_and_validates_limits(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "agent_memory_tools.cli", "search", "rebuild"],
            cwd=tmp_path, env=ENV, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for _ in range(4)
    ]
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stdout + stderr
    query = run_cli("search", "query", "memory", cwd=tmp_path)
    assert query.returncode == 0, query.stderr

    bad_top = run_cli("search", "query", "memory", "--top", "0", cwd=tmp_path)
    assert bad_top.returncode == 2
    assert "greater than zero" in bad_top.stderr
    bad_confidence = run_cli("search", "query", "memory", "--confidence-min", "-1", cwd=tmp_path)
    assert bad_confidence.returncode == 2
    assert "zero or greater" in bad_confidence.stderr


def test_unified_search_detects_same_size_preserved_mtime_changes(tmp_path: Path) -> None:
    run_cli("init-project", str(tmp_path))
    run_cli("config", "set", "search.deep_freshness_check_seconds", "0", cwd=tmp_path)
    page = tmp_path / "wiki" / "concepts" / "mutable.md"
    page.write_text("# Mutable\n\noldtoken\n", encoding="utf-8")
    run_cli("search", "rebuild", cwd=tmp_path)
    stat = page.stat()
    page.write_text("# Mutable\n\nnewtoken\n", encoding="utf-8")
    os.utime(page, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    result = run_cli("search", "query", "newtoken", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Mutable" in result.stdout


def test_semantic_vector_generation_signature_is_reused(tmp_path: Path) -> None:
    import numpy as np
    from agent_memory_tools import search

    previous = os.environ.get("PROJECT_ROOT")
    os.environ["PROJECT_ROOT"] = str(tmp_path)
    try:
        vector = tmp_path / "memory" / "index-vectors.npz"
        vector.parent.mkdir(parents=True)
        np.savez(vector, vectors=np.zeros((1, 2)), keys=np.asarray(["memory:1"]), signature=np.asarray("generation-1"))
        assert search._vector_generation_matches("generation-1") is True
        assert search._vector_generation_matches("generation-2") is False
    finally:
        if previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = previous


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
