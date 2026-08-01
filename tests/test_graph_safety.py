from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_memory_tools import graph


def test_malformed_edges_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    path = tmp_path / "memory" / "edges.jsonl"
    path.parent.mkdir(parents=True)
    original = b'{"from":"a"}\n{broken\n'
    path.write_bytes(original)
    with pytest.raises(ValueError):
        graph.add_edge("a", "b", "relates-to", force=True)
    assert path.read_bytes() == original


def test_force_records_external_nodes_and_doctor_retains_them(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    edge = graph.add_edge("external:a", "external:b", "relates-to", force=True)
    assert edge["external_nodes"] == ["external:a", "external:b"]
    report = graph.doctor(fix=True)
    assert report["dangling"] == []
    assert report["ambiguous_dangling"] == []
    assert graph.list_edges() == [edge]


def test_legacy_unknown_edge_is_ambiguous_and_not_deleted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    path = tmp_path / "memory" / "edges.jsonl"
    path.parent.mkdir(parents=True)
    edge = {"from": "external:a", "to": "external:b", "relation": "relates-to"}
    path.write_text(json.dumps(edge) + "\n", encoding="utf-8")
    report = graph.doctor(fix=True)
    assert report["ambiguous_dangling"] == [edge]
    assert json.loads(path.read_text(encoding="utf-8")) == edge
    upgraded = graph.add_edge("external:a", "external:b", "relates-to", force=True)
    assert upgraded["external_nodes"] == ["external:a", "external:b"]
    assert graph.doctor()["ambiguous_dangling"] == []


def test_doctor_marks_legacy_learning_key_under_shared_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    learnings = tmp_path / "memory" / "learnings.jsonl"
    learnings.parent.mkdir(parents=True)
    old = {"pattern": "old legacy method", "stale": False}
    new = {"id": "new", "pattern": "new method", "stale": False}
    learnings.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n", encoding="utf-8")
    old_key = "memory:" + hashlib.sha1(old["pattern"].encode()).hexdigest()[:12]
    edge = {"from": "memory:new", "to": old_key, "relation": "supersedes", "external_nodes": []}
    (tmp_path / "memory" / "edges.jsonl").write_text(json.dumps(edge) + "\n", encoding="utf-8")
    report = graph.doctor(fix=True)
    assert report["fixed"]["marked_stale"] == 1
    current = [json.loads(line) for line in learnings.read_text(encoding="utf-8").splitlines()]
    assert current[0]["stale"] is True


def test_multihop_neighbor_reports_immediate_predecessor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    graph.add_edge("external:a", "external:b", "depends-on", force=True)
    graph.add_edge("external:b", "external:c", "implements", force=True)

    reached = {item["key"]: item for item in graph.neighbors("external:a", hops=2)}
    assert reached["external:b"]["via"] == "external:a"
    assert reached["external:c"]["via"] == "external:b"
    assert reached["external:c"]["relation"] == "implements"


def test_edge_rewrite_is_atomic_on_replace_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    original = graph.add_edge("external:a", "external:b", "relates-to", force=True)
    path = tmp_path / "memory" / "edges.jsonl"
    before = path.read_bytes()

    def fail_replace(*_args, **_kwargs) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        graph.add_edge("external:c", "external:d", "relates-to", force=True)

    assert graph.list_edges() == [original]
    assert path.read_bytes() == before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX advisory-lock regression")
def test_doctor_waits_for_learning_lock_and_preserves_concurrent_append(tmp_path: Path, monkeypatch) -> None:
    import fcntl

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    learnings = tmp_path / "memory" / "learnings.jsonl"
    learnings.parent.mkdir(parents=True)
    old = {"id": "old", "pattern": "old", "stale": False}
    new = {"id": "new", "pattern": "new", "stale": False}
    concurrent = {"id": "concurrent", "pattern": "must survive", "stale": False}
    learnings.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n", encoding="utf-8")
    graph.add_edge("memory:new", "memory:old", "supersedes", force=True)

    env = {
        **os.environ,
        "PROJECT_ROOT": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "AGENT_MEMORY_LOCAL_MODEL": "off",
    }
    lock_path = learnings.with_suffix(learnings.suffix + ".lock")
    lock_path.touch()
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        process = subprocess.Popen(
            [sys.executable, "-m", "agent_memory_tools.cli", "graph", "doctor", "--fix", "--json"],
            cwd=tmp_path,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        assert process.poll() is None, "doctor must take the shared lock before read-modify-write"
        with learnings.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(concurrent) + "\n")
        fcntl.flock(lock, fcntl.LOCK_UN)

    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr or stdout
    records = [json.loads(line) for line in learnings.read_text(encoding="utf-8").splitlines()]
    by_id = {record.get("id"): record for record in records}
    assert by_id["old"]["stale"] is True
    assert by_id["concurrent"]["pattern"] == "must survive"
