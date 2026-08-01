"""Explicit lifecycle governance for project learnings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .learning_store import atomic_write, locked


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _path() -> Path:
    return _root() / "memory" / "learnings.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_strict() -> list[dict[str, object]]:
    path = _path()
    records: list[dict[str, object]] = []
    if not path.exists():
        return records
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"invalid learning on line {number}: expected object")
        records.append(value)
    return records


def _save_atomic(records: list[dict[str, object]]) -> None:
    path = _path()
    atomic_write(path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records))


def governed(record: dict[str, object]) -> dict[str, object]:
    """Return a v2 candidate while preserving the original learning fields."""
    item = dict(record)
    now = _now()
    source = str(item.get("source", "manual"))
    item.update({
        "schema_version": 2,
        "lifecycle_status": "candidate",
        "scope": "project",
        "desired_targets": [],
        "provenance": {
            "evidence": [source] if source else [], "contributors": [],
            "authoring_mode": "agent" if source.startswith("agent:") else "manual",
            "verified_by": [], "verified_at": None,
            "graduated_by": [], "graduated_at": None,
        },
        "governance_updated_at": now,
        "rejection_reason": "",
    })
    return item


def verify_repeated_pattern(pattern: str, *, evidence: list[str], targets: list[str]) -> bool:
    """Mark the canonical learning project-verified after repeated evidence."""
    with locked(_path()):
        records = _load_strict()
        matches = [item for item in records if str(item.get("pattern", "")) == pattern]
        if not matches:
            return False
        item = matches[0]
        current = item.get("lifecycle_status")
        if current == "rejected":
            return False
        if current in {"project_verified", "graduated"}:
            return True
        now = _now()
        provenance = dict(item.get("provenance", {}))
        provenance["evidence"] = list(dict.fromkeys([*provenance.get("evidence", []), *evidence]))
        provenance["verified_by"] = list(dict.fromkeys([*provenance.get("verified_by", []), "automation:repeated-pattern"]))
        provenance["verified_at"] = now
        item.update({"schema_version": 2, "lifecycle_status": "project_verified", "scope": "project",
                     "desired_targets": targets, "provenance": provenance, "governance_updated_at": now})
        _save_atomic(records)
    _event("governance_verified", item, "automation:repeated-pattern", evidence_count=len(evidence))
    return True


def ensure_pattern_candidate(pattern: str, *, source: str, tags: list[str], confidence: int) -> bool:
    """Ensure automatically captured workflow evidence has one canonical candidate."""
    with locked(_path()):
        records = _load_strict()
        matches = [item for item in records if str(item.get("pattern", "")) == pattern]
        if matches:
            return str(matches[0].get("lifecycle_status", "candidate")) != "rejected"
        now = _now()
        item = governed({
            "id": hashlib.sha256(pattern.encode()).hexdigest()[:8], "pattern": pattern,
            "confidence": confidence, "source": source or "automation:pattern",
            "tags": tags, "files": [], "context": "", "created_at": now,
            "last_referenced": now, "reference_count": 0, "stale": False,
        })
        records.append(item)
        _save_atomic(records)
    return True


def _materialize(item: dict[str, object], targets: list[str]) -> None:
    import re
    text = str(item.get("pattern", ""))
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64] or str(item.get("id", "learning"))
    provenance = json.dumps(item.get("provenance", {}), ensure_ascii=False)
    paths = {
        "rule": _root() / "memory" / "rules" / f"{slug}.md",
        "knowledge": _root() / "wiki" / "concepts" / f"{slug}.md",
        "skill": _root() / "skills" / slug / "SKILL.md",
    }
    for target in targets:
        path = paths[target]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            continue
        if target == "skill":
            content = f"---\nname: {slug}\ndescription: Verified project workflow.\n---\n\n# {text[:80]}\n\n{text}\n\nProvenance: {provenance}\n"
        else:
            content = f"# {text[:80]}\n\n{text}\n\nProvenance: {provenance}\n"
        atomic_write(path, content)


def _event(event: str, item: dict[str, object], actor: str, **extra: object) -> None:
    path = _root() / "memory" / "lifecycle.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": event, "at": _now(), "learning_id": item.get("id", ""), "by": actor, **extra}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _find(records: list[dict[str, object]], identity: str) -> dict[str, object]:
    matches = [item for item in records if str(item.get("id", "")) == identity]
    if len(matches) != 1:
        raise ValueError("learning id not found" if not matches else "duplicate learning id")
    return matches[0]


def _transition(args: argparse.Namespace) -> int:
    with locked(_path()):
        records = _load_strict()
        item = _find(records, args.id)
        if "schema_version" not in item:
            raise ValueError("legacy learning must be migrated before transition")
        current = str(item.get("lifecycle_status", "project_verified"))
        allowed = {
            "verify": {"candidate"}, "graduate": {"project_verified"},
            "reject": {"candidate", "project_verified"}, "withdraw": {"graduated"},
        }
        if current not in allowed[args.command]:
            raise ValueError(f"cannot {args.command} learning in {current} state")
        now = _now()
        provenance = dict(item.get("provenance", {}))
        if args.command == "verify":
            targets = [part.strip() for part in args.targets.split(",") if part.strip()]
            invalid = sorted(set(targets) - {"rule", "knowledge", "skill"})
            if invalid:
                raise ValueError("invalid verify target(s): " + ", ".join(invalid))
            item["lifecycle_status"], item["scope"] = "project_verified", "project"
            item["desired_targets"] = targets
            provenance["verified_by"] = list(dict.fromkeys([*provenance.get("verified_by", []), args.by]))
            provenance["verified_at"] = now
        elif args.command == "graduate":
            item["lifecycle_status"], item["scope"] = "graduated", "cross_project"
            provenance["graduated_by"] = list(dict.fromkeys([*provenance.get("graduated_by", []), args.by]))
            provenance["graduated_at"] = now
        elif args.command == "reject":
            item["lifecycle_status"] = "rejected"
            item["rejection_reason"] = args.reason
        else:
            item["lifecycle_status"], item["scope"] = "project_verified", "project"
            item["rejection_reason"] = args.reason
        item["schema_version"] = 2
        item["provenance"] = provenance
        item["governance_updated_at"] = now
        _save_atomic(records)
    if args.command == "verify":
        _materialize(item, targets)
    event = {"verify": "governance_verified", "graduate": "governance_graduated", "reject": "governance_rejected", "withdraw": "governance_withdrawn"}[args.command]
    _event(event, item, args.by, reason=getattr(args, "reason", ""))
    print(f"✓ {args.command}: {args.id} → {item['lifecycle_status']}")
    return 0


def _status(args: argparse.Namespace) -> int:
    records = _load_strict()
    output = []
    for item in records:
        status = str(item.get("lifecycle_status", "project_verified"))
        if args.status and status != args.status:
            continue
        output.append({**item, "lifecycle_status": status, "scope": item.get("scope", "project"), "legacy": "schema_version" not in item})
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif not output:
        print("No governed learnings found.")
    else:
        for item in output:
            print(f"{item.get('id', '?')} [{item['lifecycle_status']}/{item['scope']}] {item.get('pattern', '')}")
    return 0


def _migrate(args: argparse.Namespace) -> int:
    with locked(_path()):
        records = _load_strict()
        legacy = [item for item in records if "schema_version" not in item]
        if args.apply and legacy:
            for item in legacy:
                item.update(governed(item))
                item["lifecycle_status"] = "project_verified"
            _save_atomic(records)
    print(f"{len(legacy)} legacy learning(s){' migrated' if args.apply else ' found'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Govern learning lifecycle and cross-project graduation")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--status", choices=["candidate", "project_verified", "graduated", "rejected"])
    status.add_argument("--json", action="store_true")
    for command in ("verify", "graduate", "reject", "withdraw"):
        action = sub.add_parser(command)
        action.add_argument("id")
        action.add_argument("--by", required=True)
        if command == "verify":
            action.add_argument("--targets", default="")
        if command in {"reject", "withdraw"}:
            action.add_argument("--reason", required=True)
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        return _status(args) if args.command == "status" else _migrate(args) if args.command == "migrate" else _transition(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
