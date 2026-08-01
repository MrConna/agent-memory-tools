from __future__ import annotations

import json
from pathlib import Path
import hashlib
import pytest

from agent_memory_tools import audit
from agent_memory_tools import governance
from agent_memory_tools import patterns


def _setup(root: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    (root / "memory" / "wiki" / "pages").mkdir(parents=True)
    (root / "progress").mkdir()
    (root / "memory" / "learnings.jsonl").write_text("", encoding="utf-8")
    (root / "memory" / "wiki" / "sources.jsonl").write_text("", encoding="utf-8")


def test_clean_json_report(tmp_path: Path, monkeypatch, capsys) -> None:
    _setup(tmp_path, monkeypatch)
    assert audit.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == 1
    assert report["summary"] == {"total": 0, "unresolved": 0, "errors": 0, "warnings": 0}


def test_aggregates_governance_progress_and_graph(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    (tmp_path / "memory" / "learnings.jsonl").write_text(
        json.dumps({"id": "one", "schema_version": 2, "lifecycle_status": "candidate", "scope": "project"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "progress" / "active").write_text("gone\n", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text(
        json.dumps({"from": "memory:one", "to": "memory:gone", "relation": "contradicts"}) + "\n",
        encoding="utf-8",
    )
    report = audit.run()
    codes = {f["code"] for f in report["findings"]}
    assert {"GOVERNANCE_CANDIDATE", "PROGRESS_ACTIVE_DANGLING", "GRAPH_DANGLING", "GRAPH_CONTRADICTION"} <= codes


def test_graph_supersedes_legacy_learning_key(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    legacy = {"pattern": "old legacy method", "stale": False}
    replacement = {"id": "new", "pattern": "new method", "stale": False}
    learnings = tmp_path / "memory" / "learnings.jsonl"
    learnings.write_text(json.dumps(legacy) + "\n" + json.dumps(replacement) + "\n", encoding="utf-8")
    legacy_key = "memory:" + hashlib.sha1(legacy["pattern"].encode()).hexdigest()[:12]
    edge = {"from": "memory:new", "to": legacy_key, "relation": "supersedes", "external_nodes": []}
    (tmp_path / "memory" / "edges.jsonl").write_text(json.dumps(edge) + "\n", encoding="utf-8")

    report = audit.run(fix_safe=True)

    assert any(f["code"] == "GRAPH_SUPERSEDED_ACTIVE" and f["fixed"] for f in report["findings"])
    current = [json.loads(line) for line in learnings.read_text(encoding="utf-8").splitlines()]
    assert current[0]["stale"] is True


def test_malformed_core_never_writes(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    learnings = tmp_path / "memory" / "learnings.jsonl"
    learnings.write_text("{broken\n", encoding="utf-8")
    edges = tmp_path / "memory" / "edges.jsonl"
    original = json.dumps({"from": "ghost:a", "to": "ghost:b", "relation": "relates-to"}) + "\n"
    edges.write_text(original, encoding="utf-8")
    active = tmp_path / "progress" / "active"
    active.write_text("gone\n", encoding="utf-8")
    report = audit.run(fix_safe=True)
    assert any(f["code"] == "LEARNINGS_MALFORMED" for f in report["findings"])
    assert edges.read_text(encoding="utf-8") == original
    assert active.read_text(encoding="utf-8") == "gone\n"


def test_fix_safe_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    (tmp_path / "progress" / "active").write_text("gone\n", encoding="utf-8")
    first = audit.run(fix_safe=True)
    second = audit.run(fix_safe=True)
    assert first["fix_safe"]["applied"] == 1
    assert second["fix_safe"]["applied"] == 0
    assert second["summary"]["unresolved"] == 0


def test_repeated_pattern_requires_canonical_learning(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    assert governance.verify_repeated_pattern("missing", evidence=["task:a", "task:b"], targets=["knowledge"]) is False
    assert not list((tmp_path / "wiki" / "concepts").glob("missing.md"))


def test_real_patterns_dict_schema_and_missing_promoted_path(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    (tmp_path / "memory" / "patterns.json").write_text(json.dumps({"key": {
        "text": "Always test then review", "promoted": ["knowledge"],
        "knowledge_path": "wiki/concepts/missing.md",
    }}), encoding="utf-8")
    report = audit.run()
    codes = {finding["code"] for finding in report["findings"]}
    assert "PATTERNS_MALFORMED" not in codes
    assert "PATTERN_PROMOTED_MISSING" in codes


@pytest.mark.parametrize("broken", ["patterns", "sources", "edges"])
def test_any_malformed_ledger_makes_all_fixes_zero_write(tmp_path: Path, monkeypatch, broken: str) -> None:
    _setup(tmp_path, monkeypatch)
    (tmp_path / "progress" / "active").write_text("gone\n", encoding="utf-8")
    paths = {
        "patterns": tmp_path / "memory" / "patterns.json",
        "sources": tmp_path / "memory" / "wiki" / "sources.jsonl",
        "edges": tmp_path / "memory" / "edges.jsonl",
    }
    paths[broken].write_text("{broken\n", encoding="utf-8")
    watched = [path for path in tmp_path.rglob("*") if path.is_file()]
    before = {path: path.read_bytes() for path in watched}
    report = audit.run(fix_safe=True)
    assert report["fix_safe"]["applied"] == 0
    assert {path: path.read_bytes() for path in watched} == before


def test_wiki_source_remains_unresolved_after_stale_propagation(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    source = tmp_path / "README.md"; source.write_text("new", encoding="utf-8")
    page = tmp_path / "memory" / "wiki" / "pages" / "topic.md"
    page.write_text('---\nslug: "topic"\nstale: "false"\n---\n\n# Topic\n', encoding="utf-8")
    record = {"path": "README.md", "sha256": hashlib.sha256(b"old").hexdigest(), "pages": ["topic"]}
    (tmp_path / "memory" / "wiki" / "sources.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    first = audit.run(fix_safe=True); second = audit.run(fix_safe=True)
    assert first["fix_safe"]["applied"] == 1
    assert second["fix_safe"]["applied"] == 0
    assert any(f["code"] == "WIKI_SOURCE_CHANGED" and not f["fixed"] for f in second["findings"])


def test_repeated_summary_creates_and_verifies_canonical_learning(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    text = "Always inspect generated migrations before running deployment"
    for number in range(3):
        result = patterns.record(text, source=f"task-{number}", tags="workflow", confidence=7)
    learning = json.loads((tmp_path / "memory" / "learnings.jsonl").read_text(encoding="utf-8"))
    assert learning["lifecycle_status"] == "project_verified"
    assert result and result.get("knowledge_path")
    assert (tmp_path / str(result["knowledge_path"])).exists()
