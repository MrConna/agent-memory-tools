"""Unified, read-mostly project knowledge hygiene audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .learning_store import atomic_write, locked

SCHEMA_VERSION = 1
VALID_STATES = {"candidate", "project_verified", "graduated", "rejected"}
VALID_SCOPES = {"session", "project", "cross_project"}


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _strict_jsonl(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    values: list[dict[str, Any]] = []
    if not path.exists():
        return values, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], str(exc)
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            return [], f"line {number}: {exc.msg}"
        if not isinstance(value, dict):
            return [], f"line {number}: expected object"
        values.append(value)
    return values, None


def _finding(code: str, severity: str, domain: str, message: str, *, subject: str = "",
             path: str = "", fixable: bool = False, details: Any = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "domain": domain, "message": message,
            "subject": subject, "path": path, "fixable": fixable, "fixed": False,
            "details": {} if details is None else details}


def _provenance_ok(item: dict[str, Any], state: str) -> bool:
    p = item.get("provenance")
    if not isinstance(p, dict):
        return False
    if state == "project_verified":
        return bool(p.get("verified_by")) and bool(p.get("verified_at"))
    return (bool(p.get("verified_by")) and bool(p.get("verified_at")) and
            bool(p.get("graduated_by")) and bool(p.get("graduated_at")))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*, fix_safe: bool = False) -> dict[str, Any]:
    root = _root()
    findings: list[dict[str, Any]] = []
    fixes = {"requested": fix_safe, "applied": 0, "skipped": 0}
    learn_path = root / "memory" / "learnings.jsonl"
    learnings, learn_error = _strict_jsonl(learn_path)
    # Complete the strict read phase before considering any fix. A corrupt
    # ledger makes the whole audit read-only, even for an unrelated domain.
    sources_path = root / "memory" / "wiki" / "sources.jsonl"
    sources, sources_error = _strict_jsonl(sources_path)
    edges_path = root / "memory" / "edges.jsonl"
    edges, edge_error = _strict_jsonl(edges_path)
    patterns_path = root / "memory" / "patterns.json"
    patterns_error: str | None = None
    if patterns_path.exists():
        try:
            raw_patterns = json.loads(patterns_path.read_text(encoding="utf-8"))
            if not isinstance(raw_patterns, dict) or not all(isinstance(value, dict) for value in raw_patterns.values()):
                raise ValueError("expected an object whose values are pattern objects")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            patterns_error = str(exc)
    active = root / "progress" / "active"
    active_record_error: str | None = None
    if active.exists():
        active_id = active.read_text(encoding="utf-8").strip()
        active_record = root / "progress" / f"{active_id}.json"
        if active_id and active_record.exists():
            try:
                value = json.loads(active_record.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("expected object")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                active_record_error = str(exc)
    reliable = not any((learn_error, sources_error, edge_error, patterns_error, active_record_error))
    if learn_error:
        findings.append(_finding("LEARNINGS_MALFORMED", "error", "governance", learn_error,
                                 path="memory/learnings.jsonl"))
    else:
        for n, item in enumerate(learnings, 1):
            identity = str(item.get("id") or f"line:{n}")
            if "schema_version" not in item:
                findings.append(_finding("GOVERNANCE_LEGACY", "warning", "governance",
                                         "Learning has not been migrated", subject=identity,
                                         path="memory/learnings.jsonl"))
                continue
            state, scope = str(item.get("lifecycle_status", "")), str(item.get("scope", ""))
            if state not in VALID_STATES or scope not in VALID_SCOPES or (
                state == "graduated" and scope != "cross_project"):
                findings.append(_finding("GOVERNANCE_INVALID", "error", "governance",
                                         "Invalid lifecycle state or scope", subject=identity,
                                         path="memory/learnings.jsonl", details={"state": state, "scope": scope}))
            if state == "candidate":
                findings.append(_finding("GOVERNANCE_CANDIDATE", "warning", "governance",
                                         "Candidate awaits review", subject=identity,
                                         path="memory/learnings.jsonl"))
            if state in {"project_verified", "graduated"} and not _provenance_ok(item, state):
                findings.append(_finding("GOVERNANCE_PROVENANCE", "error", "governance",
                                         "Verified knowledge lacks required provenance", subject=identity,
                                         path="memory/learnings.jsonl"))

    if patterns_path.exists():
        try:
            patterns_data = json.loads(patterns_path.read_text(encoding="utf-8"))
            if not isinstance(patterns_data, dict):
                raise ValueError("expected object")
            items = list(patterns_data.values())
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("pattern must be an object")
                promoted_paths = list(item.get("promoted_paths", []) or [])
                promoted_paths.extend(item.get(f"{target}_path") for target in item.get("promoted", []) or []
                                      if item.get(f"{target}_path"))
                for value in promoted_paths:
                    if not (root / str(value)).exists():
                        findings.append(_finding("PATTERN_PROMOTED_MISSING", "warning", "patterns",
                                                 "Promoted asset is missing", subject=str(value),
                                                 path="memory/patterns.json"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            findings.append(_finding("PATTERNS_MALFORMED", "error", "patterns", str(exc),
                                     path="memory/patterns.json"))

    # Only files carrying the generator's explicit marker are eligible. This
    # deliberately excludes hand-authored assets from orphan heuristics.
    if not learn_error:
        generated: list[Path] = []
        for base, glob in ((root / "memory" / "rules", "*.md"),
                           (root / "wiki" / "concepts", "*.md"),
                           (root / "skills", "*/SKILL.md")):
            generated.extend(base.glob(glob) if base.exists() else [])
        patterns = [str(item.get("pattern", "")) for item in learnings if item.get("pattern")]
        for asset in generated:
            try:
                content = asset.read_text(encoding="utf-8")
            except OSError as exc:
                findings.append(_finding("ASSET_UNREADABLE", "error", "assets", str(exc),
                                         path=str(asset.relative_to(root))))
                continue
            if "Provenance:" in content and not any(pattern in content for pattern in patterns):
                findings.append(_finding("ASSET_GENERATED_ORPHAN", "warning", "assets",
                                         "Generated asset has no canonical learning", subject=asset.stem,
                                         path=str(asset.relative_to(root))))

    active = root / "progress" / "active"
    if active.exists():
        task_id = active.read_text(encoding="utf-8").strip()
        task_path = root / "progress" / f"{task_id}.json"
        code = message = ""
        if not task_id or not task_path.exists():
            code, message = "PROGRESS_ACTIVE_DANGLING", "Active progress points to a missing record"
        else:
            try:
                record = json.loads(task_path.read_text(encoding="utf-8"))
                if record.get("status") == "completed":
                    code, message = "PROGRESS_ACTIVE_COMPLETED", "Completed progress is still active"
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(_finding("PROGRESS_MALFORMED", "error", "progress", str(exc), path=str(task_path.relative_to(root))))
        if code:
            f = _finding(code, "warning", "progress", message, subject=task_id,
                         path="progress/active", fixable=True)
            if fix_safe and reliable:
                active.unlink(missing_ok=True); f["fixed"] = True; fixes["applied"] += 1
            elif fix_safe:
                fixes["skipped"] += 1
            findings.append(f)

    if sources_error:
        findings.append(_finding("WIKI_SOURCES_MALFORMED", "error", "wiki", sources_error,
                                 path="memory/wiki/sources.jsonl"))
    else:
        from . import wiki
        for record in sources:
            rel = str(record.get("path", "")); source = root / rel
            status = "missing" if not source.is_file() else ("changed" if _sha(source) != record.get("sha256") else "")
            if not status:
                continue
            f = _finding(f"WIKI_SOURCE_{status.upper()}", "warning", "wiki",
                         f"Tracked source is {status}", subject=rel, path="memory/wiki/sources.jsonl", fixable=False,
                         details={"pages": record.get("pages", [])})
            findings.append(f)
            for slug in record.get("pages", []) or []:
                page = root / "memory" / "wiki" / "pages" / f"{wiki._slug(str(slug))}.md"
                meta, _ = wiki._read_page(page) if page.exists() else ({}, "")
                if page.exists() and str(meta.get("stale", "false")).lower() != "true":
                    propagation = _finding("WIKI_STALE_NOT_PROPAGATED", "warning", "wiki",
                                           "Changed source has a dependent page not marked stale",
                                           subject=str(slug), path=str(page.relative_to(root)), fixable=True,
                                           details={"source": rel})
                    if fix_safe and reliable:
                        wiki._set_page_stale(str(slug), True)
                        propagation["fixed"] = True; fixes["applied"] += 1
                    elif fix_safe:
                        fixes["skipped"] += 1
                    findings.append(propagation)

    if edge_error:
        findings.append(_finding("GRAPH_EDGES_MALFORMED", "error", "graph", edge_error, path="memory/edges.jsonl"))
    else:
        try:
            from .search import collect_entries
            keys = {entry.key for entry in collect_entries()}
        except Exception as exc:  # audit must describe inability instead of mutating
            keys = set(); findings.append(_finding("GRAPH_KEYS_UNAVAILABLE", "error", "graph", str(exc)))
        dangling = [e for e in edges if any(
            node not in keys and node not in set(e.get("external_nodes", []))
            for node in (e.get("from"), e.get("to"))
        )]
        for edge in dangling:
            f = _finding("GRAPH_DANGLING", "warning", "graph", "Edge has a missing endpoint",
                         subject=f"{edge.get('from')}->{edge.get('to')}", path="memory/edges.jsonl", fixable=False,
                         details=edge)
            findings.append(f)
        for edge in edges:
            if edge.get("relation") == "contradicts":
                findings.append(_finding("GRAPH_CONTRADICTION", "warning", "graph", "Contradiction requires review",
                                         subject=f"{edge.get('from')}->{edge.get('to')}", path="memory/edges.jsonl", details=edge))
        if not learn_error:
            from .graph import _learning_key

            by_key = {key: item for item in learnings if (key := _learning_key(item))}
            stale_targets = {str(e.get("to")) for e in edges if e.get("relation") == "supersedes" and e.get("to") in by_key and not by_key[str(e.get("to"))].get("stale")}
            for target in stale_targets:
                f = _finding("GRAPH_SUPERSEDED_ACTIVE", "warning", "graph", "Superseded learning remains active",
                             subject=target, path="memory/learnings.jsonl", fixable=True)
                findings.append(f)
            if fix_safe and stale_targets and reliable:
                with locked(learn_path):
                    current, current_error = _strict_jsonl(learn_path)
                    if current_error:
                        fixes["skipped"] += len(stale_targets)
                    else:
                        current_by_key = {key: item for item in current if (key := _learning_key(item))}
                        actual = {target for target in stale_targets if target in current_by_key and not current_by_key[target].get("stale")}
                        for item in current:
                            if _learning_key(item) in actual:
                                item["stale"] = True
                        if actual:
                            atomic_write(learn_path, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in current))
                        for finding in findings:
                            if finding["code"] == "GRAPH_SUPERSEDED_ACTIVE" and finding["subject"] in actual:
                                finding["fixed"] = True
                        fixes["applied"] += len(actual)
            elif fix_safe and stale_targets:
                fixes["skipped"] += len(stale_targets)

    findings.sort(key=lambda f: (f["domain"], f["code"], f["path"], f["subject"], f["message"]))
    unresolved = [f for f in findings if not f["fixed"] and f["severity"] in {"warning", "error"}]
    summary = {"total": len(findings), "unresolved": len(unresolved),
               "errors": sum(f["severity"] == "error" and not f["fixed"] for f in findings),
               "warnings": sum(f["severity"] == "warning" and not f["fixed"] for f in findings)}
    return {"schema_version": SCHEMA_VERSION, "project_root": str(root),
            "generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary,
            "findings": findings, "fix_safe": fixes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-memory audit", description="Audit project memory hygiene")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fix-safe", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(fix_safe=args.fix_safe)
    except Exception as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for finding in report["findings"]:
            marker = "fixed" if finding["fixed"] else finding["severity"]
            print(f"[{marker}] {finding['code']}: {finding['message']} ({finding['subject']})")
        print(f"Audit: {report['summary']['unresolved']} unresolved finding(s)")
    return 1 if report["summary"]["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
