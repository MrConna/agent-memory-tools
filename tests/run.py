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


def test_graph_edges_and_search_expansion() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        require((root / "memory" / "edges.jsonl").exists(), "edges.jsonl missing")
        require((root / "bin" / "graph").exists(), "graph wrapper missing")
        run_cli("memory", "add", "Alpha uses scoped worktrees for isolation",
                "--confidence", "8", "--source", "t", "--tags", "alpha", cwd=root)
        run_cli("memory", "add", "Beta replaces the old detachment approach entirely",
                "--confidence", "9", "--source", "t", "--tags", "beta", cwd=root)
        learnings = [
            json.loads(line)
            for line in (root / "memory" / "learnings.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        keys = [f"memory:{item['id']}" for item in learnings]
        run_cli("search", "rebuild", cwd=root)

        # Unknown relation is rejected (controlled vocabulary).
        bad_rel = run_cli("graph", "link", keys[1], keys[0], "--relation", "bogus", cwd=root)
        require(bad_rel.returncode != 0, bad_rel.stdout)

        # Unknown node key is rejected without --force (trust-boundary validation).
        bad_key = run_cli("graph", "link", "memory:doesnotexist", keys[0], "--relation", "relates-to", cwd=root)
        require(bad_key.returncode != 0, bad_key.stdout)

        # Valid edge: Beta supersedes Alpha.
        link = run_cli("graph", "link", keys[1], keys[0], "--relation", "supersedes", "--note", "newer", cwd=root)
        require(link.returncode == 0, link.stderr)

        # Idempotent: linking again does not duplicate.
        run_cli("graph", "link", keys[1], keys[0], "--relation", "supersedes", cwd=root)
        edges = [
            line for line in (root / "memory" / "edges.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        require(len(edges) == 1, f"expected 1 edge, got {len(edges)}")

        neighbors = run_cli("graph", "neighbors", keys[1], "--json", cwd=root)
        require(keys[0] in neighbors.stdout, neighbors.stdout)

        # Graph-completion: a query matching only Beta also surfaces Alpha via the edge.
        expanded = run_cli("search", "query", "replaces old detachment approach",
                           "--expand", "1", "--json", cwd=root)
        require(keys[0] in expanded.stdout, expanded.stdout)
        require("expanded_from" in expanded.stdout, expanded.stdout)


def test_graph_doctor_flags_and_fixes_superseded() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_cli("init-project", str(root))
        run_cli("memory", "add", "Old approach uses polling loops",
                "--confidence", "7", "--source", "t", "--tags", "old", cwd=root)
        run_cli("memory", "add", "New approach uses event streams instead",
                "--confidence", "9", "--source", "t", "--tags", "new", cwd=root)
        learnings = [
            json.loads(line)
            for line in (root / "memory" / "learnings.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        old_key = f"memory:{learnings[0]['id']}"
        new_key = f"memory:{learnings[1]['id']}"
        run_cli("search", "rebuild", cwd=root)
        run_cli("graph", "link", new_key, old_key, "--relation", "supersedes", cwd=root)
        # A dangling edge (endpoint removed / never indexed), added with --force.
        run_cli("graph", "link", new_key, "memory:ghost", "--relation", "relates-to", "--force", cwd=root)

        report = run_cli("graph", "doctor", "--json", cwd=root)
        require(report.returncode == 1, "doctor should exit 1 when issues exist")
        payload = json.loads(report.stdout)
        require(any(e["to"] == old_key for e in payload["superseded_active"]), report.stdout)
        require(len(payload["dangling"]) == 0, report.stdout)

        fixed = run_cli("graph", "doctor", "--fix", "--json", cwd=root)
        require(fixed.returncode == 0, fixed.stdout)
        fixed_payload = json.loads(fixed.stdout)
        require(fixed_payload["fixed"]["marked_stale"] == 1, fixed.stdout)
        require(fixed_payload["fixed"]["dangling_removed"] == 0, fixed.stdout)

        # Superseded learning is now stale; explicit external edge is retained.
        after = [
            json.loads(line)
            for line in (root / "memory" / "learnings.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        by_id = {item["id"]: item for item in after}
        require(by_id[learnings[0]["id"]]["stale"] is True, "old learning should be stale")
        require(by_id[learnings[1]["id"]].get("stale") is False, "new learning must stay active")
        edges = [
            line for line in (root / "memory" / "edges.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        require(len(edges) == 2, f"external edge should be retained, got {len(edges)} edges")

        clean = run_cli("graph", "doctor", cwd=root)
        require(clean.returncode == 0, clean.stdout)


def main() -> None:
    tests = [
        test_init_project_installs_wrappers,
        test_memory_add_and_apply,
        test_context_save_restore,
        test_wiki_init_add_page_search_and_sync,
        test_wiki_mutation_fails_on_invalid_sources_jsonl,
        test_wiki_retracking_changed_source_clears_stale_state,
        test_wiki_rejects_external_sources_by_default,
        test_graph_edges_and_search_expansion,
        test_graph_doctor_flags_and_fixes_superseded,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"{len(tests)} checks passed.")


if __name__ == "__main__":
    main()
