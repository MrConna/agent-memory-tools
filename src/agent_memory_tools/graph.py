"""Directed relationship graph over indexed project knowledge nodes.

A lightweight edge layer (``memory/edges.jsonl``) on top of the flat search
index. Each node is an existing search ``entry_key`` — ``memory:<id>``,
``knowledge:<path>``, ``entity:<name>``, ``context:<id>``, ``progress:<id>``,
``skill:<name>`` — so edges reuse ids the index already assigns.

This is the one thing a knowledge graph gives you that plain vector/lexical
search does not: retrieval can *follow relationships* instead of only ranking
isolated hits. It intentionally stays file-based (one JSONL, no graph DB),
matching this project's zero-infrastructure design.

CLI:
    graph link <from> <to> --relation <r> [--note N] [--force]
    graph unlink <from> <to> [--relation <r>]
    graph neighbors <key> [--hops N] [--relation R ...] [--direction both|out|in]
    graph list [--key K]
    graph nodes [pattern]
    graph relations
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .learning_store import atomic_write, locked

# Controlled vocabulary (ontology-lite). Directional edges point new -> old /
# dependent -> dependency; ``contradicts``/``relates-to`` read as symmetric.
RELATIONS: dict[str, str] = {
    "relates-to": "generic association between two nodes",
    "depends-on": "<from> requires <to> to hold",
    "implements": "<from> realizes/carries out <to>",
    "contradicts": "<from> conflicts with <to>",
    "supersedes": "<from> replaces <to> (<to> is now outdated)",
}


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _edges_file() -> Path:
    path = _root() / "memory" / "edges.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_edges() -> list[dict]:
    path = _edges_file()
    if not path.exists():
        return []
    edges = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"edges.jsonl line {i} invalid JSON: {exc.msg}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"edges.jsonl line {i}: expected object")
        if not all(isinstance(item.get(field), str) and item[field].strip() for field in ("from", "to", "relation")):
            raise ValueError(f"edges.jsonl line {i}: from, to, and relation must be non-empty strings")
        if item["relation"] not in RELATIONS:
            raise ValueError(f"edges.jsonl line {i}: unknown relation {item['relation']!r}")
        if "external_nodes" in item:
            external = item["external_nodes"]
            if not isinstance(external, list) or not all(isinstance(value, str) for value in external):
                raise ValueError(f"edges.jsonl line {i}: external_nodes must be an array of strings")
            invalid = set(external) - {item["from"], item["to"]}
            if invalid:
                raise ValueError(f"edges.jsonl line {i}: external_nodes must be edge endpoints")
        edges.append(item)
    return edges


def _save_edges(edges: list[dict]) -> None:
    atomic_write(_edges_file(), "".join(json.dumps(edge, ensure_ascii=False) + "\n" for edge in edges))


def _load_learnings_strict(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"learnings.jsonl line {number} invalid JSON: {exc.msg}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"learnings.jsonl line {number}: expected object")
        records.append(item)
    return records


def _learning_key(item: dict) -> str | None:
    if item.get("id"):
        return f"memory:{item['id']}"
    pattern = str(item.get("pattern", ""))
    return f"memory:{hashlib.sha1(pattern.encode()).hexdigest()[:12]}" if pattern else None


def known_keys() -> set[str]:
    """Node keys the search index would assign for the current project files."""
    from . import search  # lazy: avoids import cycle

    return {entry.key for entry in search.collect_entries()}


def add_edge(frm: str, to: str, relation: str, note: str = "", *, force: bool = False) -> dict:
    relation = relation.strip().lower()
    if relation not in RELATIONS:
        raise ValueError(f"unknown relation '{relation}'; choose one of: {', '.join(sorted(RELATIONS))}")
    frm, to = frm.strip(), to.strip()
    if not frm or not to:
        raise ValueError("both <from> and <to> node keys are required")
    if frm == to:
        raise ValueError("a node cannot link to itself")
    keys = known_keys()
    missing = [k for k in (frm, to) if k not in keys]
    if not force:
        if missing:
            raise ValueError(
                "unknown node key(s): " + ", ".join(missing)
                + " — run `search rebuild` / `graph nodes` to see valid keys, or pass --force"
            )
    path = _edges_file()
    with locked(path):
        edges = _load_edges()
        for edge in edges:
            if edge["from"] == frm and edge["to"] == to and edge["relation"] == relation:
                if force:
                    declared = list(edge.get("external_nodes", []))
                    upgraded = list(dict.fromkeys([*declared, *missing]))
                    if "external_nodes" not in edge or upgraded != declared:
                        edge["external_nodes"] = upgraded
                        _save_edges(edges)
                return edge  # idempotent
        record = {
            "from": frm, "to": to, "relation": relation, "note": note,
            "created_at": datetime.now(timezone.utc).isoformat(), "external_nodes": missing,
        }
        edges.append(record)
        _save_edges(edges)
        return record


def remove_edge(frm: str, to: str, relation: str | None = None) -> int:
    frm, to = frm.strip(), to.strip()
    relation = relation.strip().lower() if relation else None
    path = _edges_file()
    with locked(path):
        edges = _load_edges()
        kept = [e for e in edges if not (
            e["from"] == frm and e["to"] == to and (relation is None or e["relation"] == relation)
        )]
        removed = len(edges) - len(kept)
        if removed:
            _save_edges(kept)
        return removed


def neighbors(
    key: str, *, hops: int = 1, relations: list[str] | None = None, direction: str = "both",
) -> list[dict]:
    """BFS over edges from ``key``. Returns dicts with neighbor key, relation,
    direction ('out'/'in'), and distance. Directed edges, but ``direction`` can
    walk them either way for undirected reachability."""
    if hops < 1:
        raise ValueError("hops must be greater than zero")
    if direction not in {"both", "out", "in"}:
        raise ValueError("direction must be 'both', 'out', or 'in'")
    wanted = {r.strip().lower() for r in relations} if relations else None
    edges = _load_edges()
    seen = {key}
    frontier: deque[tuple[str, int]] = deque([(key, 0)])
    found: list[dict] = []
    while frontier:
        node, distance = frontier.popleft()
        if distance >= hops:
            continue
        for edge in edges:
            if wanted and edge["relation"] not in wanted:
                continue
            nxt = way = None
            if direction in {"both", "out"} and edge["from"] == node:
                nxt, way = edge["to"], "out"
            elif direction in {"both", "in"} and edge["to"] == node:
                nxt, way = edge["from"], "in"
            if nxt is None or nxt in seen:
                continue
            seen.add(nxt)
            found.append({
                "key": nxt,
                "relation": edge["relation"],
                "direction": way,
                "distance": distance + 1,
                "via": node,
            })
            frontier.append((nxt, distance + 1))
    return found


def list_edges(key: str | None = None) -> list[dict]:
    edges = _load_edges()
    if key is None:
        return edges
    key = key.strip()
    return [e for e in edges if e["from"] == key or e["to"] == key]


def doctor(*, fix: bool = False) -> dict:
    """Audit memory hygiene using the relation graph.

    Reports three classes of issue and, with ``fix``, resolves the two safe ones:
      - dangling edges  → endpoint no longer in the index (source deleted)  [fixable]
      - superseded-active → a learning is the target of a `supersedes` edge  [fixable]
        but not yet flagged stale
      - contradictions   → `contradicts` edges surfaced for human review     [advisory]
    """
    edges = _load_edges()
    keys = known_keys()
    learnings_path = _root() / "memory" / "learnings.jsonl"
    learnings = _load_learnings_strict(learnings_path)
    by_key = {key: item for item in learnings if (key := _learning_key(item))}

    dangling, ambiguous = [], []
    for edge in edges:
        missing = {node for node in (edge["from"], edge["to"]) if node not in keys}
        undeclared = missing - set(edge.get("external_nodes", []))
        if not undeclared:
            continue
        (dangling if "external_nodes" in edge else ambiguous).append(edge)
    superseded = [
        e for e in edges
        if e["relation"] == "supersedes" and e["to"] in by_key and not by_key[e["to"]].get("stale")
    ]
    contradictions = [e for e in edges if e["relation"] == "contradicts"]

    result = {
        "dangling": dangling,
        "ambiguous_dangling": ambiguous,
        "superseded_active": superseded,
        "contradictions": contradictions,
        "fixed": {"dangling_removed": 0, "marked_stale": 0},
    }

    if fix:
        if dangling:
            path = _edges_file()
            with locked(path):
                current = _load_edges()
                current_keys = known_keys()
                dead = {
                    (e["from"], e["to"], e["relation"])
                    for e in current
                    if "external_nodes" in e and any(
                        node not in current_keys and node not in set(e.get("external_nodes", []))
                        for node in (e["from"], e["to"])
                    )
                }
                kept = [e for e in current if (e["from"], e["to"], e["relation"]) not in dead]
                if len(kept) != len(current):
                    _save_edges(kept)
                result["fixed"]["dangling_removed"] = len(current) - len(kept)
        with locked(learnings_path):
            current = _load_learnings_strict(learnings_path)
            current_by_key = {key: item for item in current if (key := _learning_key(item))}
            targets = {edge["to"] for edge in superseded}
            changed = 0
            for target in targets:
                item = current_by_key.get(target)
                if item is not None and not item.get("stale"):
                    item["stale"] = True
                    changed += 1
            if changed:
                atomic_write(learnings_path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in current))
            result["fixed"]["marked_stale"] = changed

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-memory graph", description="Relationship graph over knowledge nodes")
    sub = parser.add_subparsers(dest="command", required=True)

    link = sub.add_parser("link", help="Add a directed edge between two node keys")
    link.add_argument("from_key")
    link.add_argument("to_key")
    link.add_argument("--relation", "-r", required=True, choices=sorted(RELATIONS))
    link.add_argument("--note", default="")
    link.add_argument("--force", action="store_true", help="Allow keys not present in the current index")

    unlink = sub.add_parser("unlink", help="Remove edge(s) between two node keys")
    unlink.add_argument("from_key")
    unlink.add_argument("to_key")
    unlink.add_argument("--relation", "-r", default=None, choices=sorted(RELATIONS))

    nb = sub.add_parser("neighbors", help="Show nodes reachable from a key")
    nb.add_argument("key")
    nb.add_argument("--hops", type=_positive_int, default=1)
    nb.add_argument("--relation", "-r", action="append", default=[], choices=sorted(RELATIONS))
    nb.add_argument("--direction", default="both", choices=["both", "out", "in"])
    nb.add_argument("--json", action="store_true")

    ls = sub.add_parser("list", help="List edges (optionally touching a key)")
    ls.add_argument("--key", default=None)
    ls.add_argument("--json", action="store_true")

    nodes = sub.add_parser("nodes", help="List valid node keys from the index")
    nodes.add_argument("pattern", nargs="?", default="")

    doc = sub.add_parser("doctor", help="Audit memory hygiene using the relation graph")
    doc.add_argument("--fix", action="store_true",
                     help="Remove dangling edges and mark superseded learnings stale")
    doc.add_argument("--json", action="store_true")

    sub.add_parser("relations", help="Show the controlled relation vocabulary")

    args = parser.parse_args(argv)

    if args.command == "link":
        try:
            edge = add_edge(args.from_key, args.to_key, args.relation, note=args.note, force=args.force)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"✓ {edge['from']} --[{edge['relation']}]--> {edge['to']}")
        return 0

    if args.command == "unlink":
        try:
            removed = remove_edge(args.from_key, args.to_key, args.relation)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"✓ removed {removed} edge(s)" if removed else "no matching edge")
        return 0

    if args.command == "neighbors":
        try:
            results = neighbors(args.key, hops=args.hops, relations=args.relation or None, direction=args.direction)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(results, ensure_ascii=False))
            return 0
        if not results:
            print(f"No neighbors for {args.key}")
            return 0
        print(f"Neighbors of {args.key} (≤{args.hops} hop{'s' if args.hops != 1 else ''}):\n")
        arrow = {"out": "-->", "in": "<--"}
        for item in results:
            print(f"  {arrow[item['direction']]} [{item['relation']}] {item['key']}  (hop {item['distance']})")
        return 0

    if args.command == "list":
        try:
            edges = list_edges(args.key)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(edges, ensure_ascii=False))
            return 0
        if not edges:
            print("No edges yet. Add one with: graph link <from> <to> --relation relates-to")
            return 0
        for edge in edges:
            note = f"  # {edge['note']}" if edge.get("note") else ""
            print(f"  {edge['from']} --[{edge['relation']}]--> {edge['to']}{note}")
        return 0

    if args.command == "nodes":
        from . import search  # lazy

        pattern = args.pattern.lower()
        for entry in search.collect_entries():
            if pattern and pattern not in entry.key.lower() and pattern not in entry.title.lower():
                continue
            print(f"  [{entry.kind}] {entry.key}  —  {entry.title[:70]}")
        return 0

    if args.command == "doctor":
        try:
            report = doctor(fix=args.fix)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            _print_doctor(report, fixed=args.fix)
        unresolved = len(report["dangling"]) + len(report["ambiguous_dangling"]) + len(report["superseded_active"])
        if args.fix:
            unresolved -= report["fixed"]["dangling_removed"] + report["fixed"]["marked_stale"]
        return 1 if unresolved > 0 else 0

    if args.command == "relations":
        for name, description in RELATIONS.items():
            print(f"  {name:<12} {description}")
        return 0

    return 2


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _print_doctor(report: dict, *, fixed: bool) -> None:
    dangling, ambiguous, superseded, contradictions = (
        report["dangling"], report["ambiguous_dangling"], report["superseded_active"], report["contradictions"],
    )
    if not (dangling or ambiguous or superseded or contradictions):
        print("✓ graph is healthy: no dangling edges, superseded-active learnings, or contradictions")
        return
    if dangling:
        print(f"⚠ {len(dangling)} dangling edge(s) (endpoint no longer indexed):")
        for edge in dangling:
            print(f"    {edge['from']} --[{edge['relation']}]--> {edge['to']}")
    if ambiguous:
        print(f"⚠ {len(ambiguous)} ambiguous legacy dangling edge(s) (report-only):")
        for edge in ambiguous:
            print(f"    {edge['from']} --[{edge['relation']}]--> {edge['to']}")
    if superseded:
        print(f"⚠ {len(superseded)} superseded-but-active learning(s) (should be stale):")
        for edge in superseded:
            print(f"    {edge['to']}  ← superseded by {edge['from']}")
    if contradictions:
        print(f"ℹ {len(contradictions)} contradiction(s) for human review:")
        for edge in contradictions:
            print(f"    {edge['from']} ⚡ {edge['to']}")
    if fixed:
        f = report["fixed"]
        print(f"\n✓ fixed: removed {f['dangling_removed']} dangling edge(s), marked {f['marked_stale']} learning(s) stale")
    else:
        print("\nRun `graph doctor --fix` to remove dangling edges and mark superseded learnings stale.")


if __name__ == "__main__":
    raise SystemExit(main())
