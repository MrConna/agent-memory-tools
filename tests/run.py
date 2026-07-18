from __future__ import annotations

import os
import json
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
        require((root / "bin" / "wiki").exists(), "wiki wrapper missing")
        require((root / "memory" / "learnings.jsonl").exists(), "learnings missing")
        require((root / "memory" / "contexts.jsonl").exists(), "contexts missing")
        require((root / "memory" / "wiki" / "pages").exists(), "wiki pages missing")
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


def test_wiki_init_add_page_search_and_sync() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        source = root / "README.md"
        source.write_text("Project memory uses wiki pages for durable domain knowledge.\n", encoding="utf-8")

        add_source = run_cli("wiki", "add-source", "README.md", cwd=root)
        require(add_source.returncode == 0, add_source.stderr)
        require("README.md" in add_source.stdout, add_source.stdout)

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
            cwd=root,
        )
        require(add_page.returncode == 0, add_page.stderr)

        page = root / "memory" / "wiki" / "pages" / "project-overview.md"
        require(page.exists(), "wiki page missing")
        text = page.read_text(encoding="utf-8")
        require("Project Overview" in text, text)
        require("README.md" in text, text)

        search = run_cli("wiki", "search", "durable agents", cwd=root)
        require(search.returncode == 0, search.stderr)
        require("project-overview" in search.stdout, search.stdout)

        source.write_text("Project memory source changed.\n", encoding="utf-8")
        sync = run_cli("wiki", "sync", cwd=root)
        require(sync.returncode == 0, sync.stderr)
        require("stale" in sync.stdout.lower(), sync.stdout)


def test_wiki_mutation_fails_on_invalid_sources_jsonl() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        sources = root / "memory" / "wiki" / "sources.jsonl"
        sources.write_text('{"path": "README.md"}\nnot-json\n', encoding="utf-8")
        before = sources.read_text(encoding="utf-8")
        (root / "README.md").write_text("source\n", encoding="utf-8")

        result = run_cli("wiki", "add-source", "README.md", cwd=root)

        require(result.returncode != 0, result.stdout)
        require("invalid JSON" in result.stderr, result.stderr)
        require(sources.read_text(encoding="utf-8") == before, "sources.jsonl was modified")


def test_wiki_retracking_changed_source_clears_stale_state() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        source = root / "README.md"
        source.write_text("original source\n", encoding="utf-8")
        run_cli(
            "wiki",
            "add-page",
            "project-overview",
            "--summary",
            "Original summary.",
            "--source",
            "README.md",
            cwd=root,
        )
        source.write_text("changed source\n", encoding="utf-8")
        run_cli("wiki", "sync", cwd=root)

        add_source = run_cli("wiki", "add-source", "README.md", cwd=root)
        require(add_source.returncode == 0, add_source.stderr)
        sync = run_cli("wiki", "sync", cwd=root)
        require(sync.returncode == 0, sync.stderr)
        require("up to date" in sync.stdout, sync.stdout)

        records = [
            json.loads(line)
            for line in (root / "memory" / "wiki" / "sources.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        require(records[0].get("stale") is False, str(records[0]))
        require("current_sha256" not in records[0], str(records[0]))


def test_wiki_rejects_external_sources_by_default() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        outside = root.parent / "outside-source.md"
        outside.write_text("outside\n", encoding="utf-8")

        result = run_cli("wiki", "add-source", str(outside), cwd=root)

        require(result.returncode != 0, result.stdout)
        require("outside project" in result.stderr, result.stderr)


def main() -> None:
    tests = [
        test_init_project_installs_wrappers,
        test_memory_add_and_apply,
        test_context_save_restore,
        test_wiki_init_add_page_search_and_sync,
        test_wiki_mutation_fails_on_invalid_sources_jsonl,
        test_wiki_retracking_changed_source_clears_stale_state,
        test_wiki_rejects_external_sources_by_default,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"{len(tests)} checks passed.")


if __name__ == "__main__":
    main()
